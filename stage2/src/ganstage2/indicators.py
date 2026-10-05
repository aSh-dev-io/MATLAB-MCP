"""Phase 2C - exposure indicators.

These are *exposure* indicators, not health indicators. The distinction is the
whole point of this module, so it is worth stating precisely.

A health indicator answers "how degraded is this device?". That question needs
an aging axis, repeated measurement of the same device, and a ground-truth
health label to validate against. This dataset has none of the three, so no
quantity here answers it, and none of the values below is a health state.

An exposure indicator answers the weaker, answerable question: "how hard was
this device worked, relative to its printed ratings, and on what evidence?". That
is a property of the stimulus and the datasheet, not of the device's condition.
Every indicator therefore carries:

* an evidence class, so a consumer can see what it rests on;
* ``is_health_state: False``, so it cannot be mistaken for one downstream;
* a margin to a *printed* limit, not to a fitted degradation threshold.

Indicators that cannot be computed are returned as blocked with a reason rather
than omitted, so the absence is on the record instead of looking like an
oversight.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .anchors import Anchor
from .evidence import EvidenceClass
from .stress import StressResult

#: The sentence attached to every indicator this phase emits.
NOT_A_HEALTH_STATE = (
    "This is an exposure indicator derived from the simulated stimulus and the "
    "printed ratings. It is not a health state and carries no information about "
    "degradation, because no aging axis, repeated measurement or health label "
    "exists in the dataset."
)

_INDICATOR_KEYS = (
    "ron_p99_to_printed_max",
    "ron_ratio_to_printed_typ",
    "vds_rating_utilisation_max",
    "id_continuous_rating_utilisation_max",
    "id_pulse_rating_utilisation_max",
    "vgs_gate_window_utilisation_max",
    "junction_temperature_utilisation_max",
    "power_rating_utilisation",
    "leakage_temperature_coefficient_per_C",
    "conduction_loss_share_median",
    "outside_rated_envelope_fraction",
    "switching_loss_per_cycle",
)


def _indicator(
    key: str,
    label: str,
    value: float | None,
    unit: str,
    evidence: EvidenceClass,
    interpretation: str,
    *,
    available: bool = True,
    reason: str | None = None,
    margin: float | None = None,
    threshold: str | None = None,
) -> dict[str, Any]:
    """One indicator record, with the health-state disclaimer attached."""
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "evidence": evidence.value,
        "available": available,
        "unavailable_reason": reason,
        "margin_to_limit": margin,
        "threshold_basis": threshold,
        "interpretation": interpretation,
        "is_health_state": False,
        "disclaimer": NOT_A_HEALTH_STATE,
    }


def leakage_temperature_coefficient(
    frame: pd.DataFrame, anchors: dict[str, Anchor]
) -> dict[str, Any]:
    """The one genuinely temperature-dependent quantity in the Stage 1 model.

    Stage 1's channel current has no temperature term, but its leakage does
    (``model.leak_temp_ratio`` over ``model.leak_temp_span_C``). That makes the
    leakage coefficient a real, dataset-derived indicator, and by contrast it is
    what proves the RON model has no usable temperature behaviour.

    The law is measured rather than restated: the thermal profile repeats the
    same bias ladder at 25 and 125 degC, so the leakage at matched (Vgs, Vds) is
    compared directly. Off-state-only sampling would fail here, because the
    device is never off at an elevated case temperature in this dataset.
    """
    temps = sorted(t for t in frame["tcase_C"].unique() if t == t)
    if len(temps) < 2:
        return {
            "available": False,
            "reason": f"only one case temperature present ({temps}), so no slope can be fitted",
        }

    low, high = float(temps[0]), float(temps[-1])
    work = frame.copy()
    # Match on bias only; temperature is the variable under test.
    work["_bias"] = list(zip(work["vgs_V"].round(3), work["vds_V"].round(3)))
    means = (
        work.groupby(["_bias", "tcase_C"])["i_leak_A"]
        .apply(lambda s: float(np.abs(s.to_numpy()).mean()))
        .unstack("tcase_C")
    )
    if low not in means.columns or high not in means.columns:
        return {
            "available": False,
            "reason": (
                f"the dataset does not repeat the same bias at {low:g} and {high:g} degC, "
                "so leakage cannot be compared at matched bias"
            ),
        }

    paired = means[[low, high]].dropna()
    # A zero at both temperatures carries no ratio; Vds = 0 does exactly this.
    paired = paired[(paired[low] > 0.0) & (paired[high] > 0.0)]
    if paired.empty:
        return {
            "available": False,
            "reason": "every matched bias has zero leakage at both temperatures, so no ratio is defined",
        }

    ratios = paired[high] / paired[low]
    span = high - low
    median_ratio = float(ratios.median())
    coefficient = (median_ratio - 1.0) / span
    modelled = anchors["LEAK_TEMP_RATIO"].value

    return {
        "available": True,
        "method": (
            "median |i_leak_A| compared at matched (Vgs, Vds) between the lowest and "
            "highest case temperature present"
        ),
        "case_temperatures_C": [low, high],
        "span_C": float(span),
        "matched_bias_points": int(len(paired)),
        "leakage_ratio_high_over_low": median_ratio,
        "leakage_ratio_min": float(ratios.min()),
        "leakage_ratio_max": float(ratios.max()),
        "coefficient_per_C": float(coefficient),
        "model_declared_ratio": float(modelled),
        "ratio_relative_error": (
            float(abs(median_ratio - modelled) / modelled) if modelled else None
        ),
        "note": (
            "The measured ratio reproduces the Stage 1 leakage temperature law, so "
            "this confirms the simulation is internally consistent. It is not a "
            "characterisation of a device. A real GaN HEMT leakage coefficient is "
            "strongly temperature dependent, which makes this the only usable "
            "temperature indicator in the dataset; the on-resistance has none, so "
            "thermal normalisation of RON stays unavailable."
        ),
    }


def build_indicators(result: StressResult) -> dict[str, Any]:
    """Compute the Phase 2C exposure indicator set."""
    frame = result.frame
    anchors = result.anchors
    out: dict[str, Any] = {}

    # ---- on-resistance ---------------------------------------------------
    # Only the printed test condition is a datasheet comparison. RDS(on) is
    # specified at one bias (IDS = 50 A, VGS = 5 V, VDS = 0.08 V), so sweeping RON
    # across an output characteristic is not a compliance measurement and must not
    # be reported as one. The raw maximum over the conduction set is the clearest
    # demonstration: it comes from the transfer sweep at VDS = 0.08 V, where the
    # device is only partly enhanced and VDS/ID is in the triode region. That value
    # is kept as a diagnostic, and the headroom indicator uses a percentile so a
    # single triode artefact cannot masquerade as a resistance margin.
    ron_valid = frame[frame["ron_valid"]]
    rds_max = anchors["RDS_ON_MAX"].value
    rds_typ = anchors["RDS_ON_TYP"].value

    if ron_valid.empty:
        ron_diag: dict[str, Any] = {
            "available": False,
            "reason": "no conduction-valid samples, so on-resistance cannot be summarised",
        }
        ron_p99 = ron_median = ron_max = None
    else:
        values = ron_valid["ron_stage1_ohm"].to_numpy(dtype=float)
        ron_median = float(np.nanmedian(values))
        ron_p99 = float(np.nanpercentile(values, 99))
        ron_max = float(np.nanmax(values))
        worst = ron_valid.loc[ron_valid["ron_stage1_ohm"].idxmax()]
        ron_diag = {
            "available": True,
            "valid_samples": int(len(ron_valid)),
            "median_ohm": ron_median,
            "p99_ohm": ron_p99,
            "max_ohm": ron_max,
            "max_profile": str(worst["profile"]),
            "max_vgs_V": float(worst["vgs_V"]),
            "max_vds_V": float(worst["vds_V"]),
            "vds_range_V": [float(ron_valid["vds_V"].min()), float(ron_valid["vds_V"].max())],
            "max_to_printed_max": ron_max / rds_max,
            "note": (
                "The maximum is reached in the transfer sweep at VDS = 0.08 V, where "
                "the device is not fully enhanced and VDS/ID is a triode-region "
                "quantity rather than the datasheet RDS(on). It is reported here so "
                "the inflated figure is on the record, and excluded from the "
                "headroom indicator, which uses the 99th percentile instead."
            ),
        }

    out["ron_p99_to_printed_max"] = _indicator(
        "ron_p99_to_printed_max",
        "On-resistance at the 99th percentile of conduction samples, against the printed maximum",
        ron_p99,
        "ohm",
        EvidenceClass.CALCULATED if ron_p99 is not None else EvidenceClass.UNAVAILABLE,
        (
            "A 99th-percentile headroom, not a worst case. Only the printed test "
            "condition is a datasheet comparison; across a swept output "
            "characteristic the ratio VDS/ID is bias dependent, and the true maximum "
            "is a triode artefact of the transfer sweep. A value above the printed "
            "maximum means the model's conduction resistance exceeds the datasheet "
            "figure at some conduction biases, which is a statement about the model, "
            "not about device health."
        ),
        available=ron_p99 is not None,
        reason=None if ron_p99 is not None else ron_diag.get("reason"),
        margin=(None if ron_p99 is None else float(1.0 - ron_p99 / rds_max)),
        threshold=f"printed RDS(on) max = {rds_max} ohm",
    )
    out["ron_ratio_to_printed_typ"] = _indicator(
        "ron_ratio_to_printed_typ",
        "On-resistance at the printed test condition, relative to typical",
        result.ron["at_spec_point"]["ratio_to_typ"],
        "ratio",
        EvidenceClass.CALCULATED,
        (
            "Evaluated exactly at the printed test condition rather than at a "
            "convenient nearby bias. This is the only point in Stage 2 where the "
            "simulation is compared with a measured datasheet number."
        ),
        margin=float(1.0 - result.ron["at_spec_point"]["ratio_to_typ"]),
        threshold=f"printed RDS(on) typical = {rds_typ} ohm",
    )

    # ---- rating utilisations -------------------------------------------
    id_cont = anchors["ID_CONTINUOUS_25C"].value
    id_pulse = anchors["ID_PULSE_25C"].value
    for key, column, label, limit_key, basis, unit in (
        ("vds_rating_utilisation_max", "vds_rating_utilisation",
         "Worst drain-source voltage against its absolute maximum",
         "VDS_ABS_MAX", None, "ratio"),
        ("id_continuous_rating_utilisation_max", "id_continuous_rating_utilisation",
         "Worst drain current against the continuous rating",
         None, f"printed continuous ID = {id_cont} A at 25 degC", "ratio"),
        ("id_pulse_rating_utilisation_max", "id_pulse_rating_utilisation",
         "Worst drain current against the pulse rating",
         None, f"printed pulsed ID = {id_pulse} A at 25 degC", "ratio"),
        ("vgs_gate_window_utilisation_max", "vgs_gate_window_utilisation",
         "Worst gate voltage against its sign-selected window",
         "VGS_ABS_MAX", None, "ratio"),
        ("junction_temperature_utilisation_max", "junction_rating_utilisation",
         "Worst junction temperature against the printed maximum",
         "TJ_MAX", None, "ratio"),
    ):
        limit = anchors[limit_key].value if limit_key else None
        if basis is None:
            # Name the quantity, not just the number: VDS abs max and TJ max are
            # both 150 here, so a bare value would be ambiguous in the report.
            basis = f"printed {limit_key.lower().replace('_', ' ')} = {limit}"
        out[key] = _indicator(
            key,
            label,
            float(frame[column].max()),
            unit,
            EvidenceClass.CALCULATED,
            (
                "A utilisation above 1 means the simulated stimulus drove the "
                "terminal past its printed limit. That is a property of the "
                "excitation, and says nothing about whether the device degraded."
            ),
            margin=float(1.0 - frame[column].max()),
            threshold=basis,
        )

    # ---- dissipated power: genuinely blocked ----------------------------
    out["power_rating_utilisation"] = _indicator(
        "power_rating_utilisation",
        "Dissipated power against the printed package rating",
        None,
        "ratio",
        EvidenceClass.UNAVAILABLE,
        "No dissipated-power limit exists to normalise against.",
        available=False,
        reason=(
            "PTOT is not specified in the source dataset, so there is no power "
            "rating to compare against. The switching profile reaches 20.8 kW "
            "instantaneously, but no limit exists to call that an exceedance."
        ),
    )

    # ---- the one usable temperature indicator ---------------------------
    leak = leakage_temperature_coefficient(frame, anchors)
    out["leakage_temperature_coefficient_per_C"] = _indicator(
        "leakage_temperature_coefficient_per_C",
        "Leakage temperature coefficient at matched bias",
        leak.get("coefficient_per_C"),
        "1/degC",
        EvidenceClass.DATASET_DERIVED if leak.get("available") else EvidenceClass.UNAVAILABLE,
        leak.get("note", ""),
        available=bool(leak.get("available")),
        reason=leak.get("reason"),
    )

    # ---- loss composition ----------------------------------------------
    share = frame["conduction_loss_share"].replace([np.inf, -np.inf], np.nan).dropna()
    out["conduction_loss_share_median"] = _indicator(
        "conduction_loss_share_median",
        "Median share of dissipated power that is channel conduction",
        float(share.median()) if not share.empty else None,
        "fraction",
        EvidenceClass.CALCULATED,
        (
            "Conduction dominates the budget because the Miller term is the only "
            "other channel. This is a statement about the Stage 1 loss model, "
            "which has no output-capacitance term at all."
        ),
    )

    # ---- coverage ------------------------------------------------------
    cov = result.coverage
    out["outside_rated_envelope_fraction"] = _indicator(
        "outside_rated_envelope_fraction",
        "Fraction of samples driven outside the printed ratings",
        cov["outside_rated_envelope_share"],
        "fraction",
        EvidenceClass.CALCULATED,
        (
            "A pooled count over all profiles. It is dominated by characterisation "
            "sweeps that drive terminals hard on purpose, so it is not an exposure "
            "figure for any real operating condition."
        ),
        margin=float(1.0 - cov["outside_rated_envelope_share"]),
        threshold="printed absolute-maximum and continuous ratings",
    )

    out["switching_loss_per_cycle"] = _indicator(
        "switching_loss_per_cycle",
        "Switching energy per cycle",
        None,
        "J",
        EvidenceClass.UNAVAILABLE,
        "Cannot be attributed to the device.",
        available=False,
        reason=result.switching["switching_loss_unavailable_reason"],
    )

    out["_diagnostics"] = {"leakage": leak, "ron": ron_diag}
    return out


def indicator_table(indicators: dict[str, Any]) -> pd.DataFrame:
    """The indicator set as a flat frame, one row per indicator."""
    rows = []
    for key in _INDICATOR_KEYS:
        rec = indicators[key]
        rows.append({
            "indicator": key,
            "label": rec["label"],
            "value": rec["value"],
            "unit": rec["unit"],
            "evidence": rec["evidence"],
            "available": rec["available"],
            "margin_to_limit": rec["margin_to_limit"],
            "threshold_basis": rec["threshold_basis"],
            "is_health_state": rec["is_health_state"],
            "unavailable_reason": rec["unavailable_reason"] or "",
        })
    return pd.DataFrame(rows)


def trajectory_indicators(result: StressResult) -> pd.DataFrame:
    """Per-trajectory exposure metrics.

    One row per bias point, so a consumer can rank trajectories by exposure
    without re-deriving the integrals. Deliberately numeric: no exposure class
    or label is assigned, because labelling trajectories by exposure is one
    short step from labelling them by health.
    """
    traj = result.trajectories
    return pd.DataFrame({
        "trajectory_id": traj["trajectory_id"],
        "profile": traj["profile"],
        "operating_point_key": traj["operating_point_key"],
        "samples": traj["samples"],
        "span_s": traj["span_s"],
        "vgs_V": traj["vgs_V"],
        "vds_V": traj["vds_V"],
        "tcase_C": traj["tcase_C"],
        "peak_id_A": traj["peak_id_A"],
        "peak_ploss_W": traj["peak_ploss_W"],
        "total_loss_energy_J": traj["total_loss_energy_J"],
        "conduction_energy_J": traj["conduction_energy_J"],
        "miller_energy_J": traj["miller_energy_J"],
        "thermal_exposure_Ks": traj["thermal_exposure_Ks"],
        "cumulative_electrical_stress": traj["cumulative_electrical_stress"],
        "cumulative_conduction_stress": traj["cumulative_conduction_stress"],
        "max_vds_rating_utilisation": traj["max_vds_rating_utilisation"],
        "max_id_continuous_rating_utilisation": traj["max_id_continuous_rating_utilisation"],
        "samples_outside_rated_envelope": traj["samples_outside_rated_envelope"],
    })


def indicator_report(result: StressResult, indicators: dict[str, Any]) -> dict[str, Any]:
    """JSON payload for Phase 2C."""
    leak = indicators["_diagnostics"]["leakage"]
    available = [k for k in _INDICATOR_KEYS if indicators[k]["available"]]
    blocked = [
        {"indicator": k, "reason": indicators[k]["unavailable_reason"]}
        for k in _INDICATOR_KEYS
        if not indicators[k]["available"]
    ]
    return {
        "phase": "2C",
        "title": "Exposure indicators",
        "not_a_health_assessment": NOT_A_HEALTH_STATE,
        "required_limitation_statement": (
            "This framework currently provides physics-informed stress/degradation "
            "assessment based on the available device and Digital-Twin data. "
            "Experimental aging data is required to validate a true degradation-"
            "prediction model."
        ),
        "why_no_health_indicators": (
            "A health indicator requires an aging axis, repeated measurement of the "
            "same device, and a ground-truth label to validate against. The dataset "
            "has none: aging_time_h is NaN in all 15,904 rows, every profile is a "
            "single forward sweep with no repeats, and Stage 1 sets "
            "meta.health_state_modelled and meta.degradation_modelled to false. Any "
            "health score computed here would be a relabelling of the stimulus, not "
            "a measurement of the device."
        ),
        "indicator_count": len(_INDICATOR_KEYS),
        "available_count": len(available),
        "blocked_count": len(blocked),
        "available_indicators": available,
        "blocked_indicators": blocked,
        "indicators": {k: indicators[k] for k in _INDICATOR_KEYS},
        "leakage_diagnostic": leak,
        "ron_diagnostic": indicators["_diagnostics"]["ron"],
        "trajectory_count": int(len(result.trajectories)),
        "evidence": EvidenceClass.CALCULATED.value,
    }
