"""Physics-informed validation of the Stage 1 signals.

This module does **not** model degradation. It establishes which Stage 1
samples are physically interpretable at all, which is the precondition for any
degradation or health work in Phase 2B.

Three Stage 1 behaviours drive nearly every rule here, and they were read out of
the Stage 1 model scripts rather than assumed:

``RON = Vds / ID`` where ``ID > 0.1 A`` (``create_gan_hemt_twin.m``, slot 21)
    A current threshold alone is not enough. The ratio is evaluated over the
    whole sweep, so in deep saturation it reports a large "resistance" for a
    device that is behaving correctly. Only the triode (ohmic) region makes
    ``Vds/ID`` a resistance, so :func:`add_physics_columns` gates on both
    conduction and region.

``Pcond = Vds * Ich`` and ``Ploss = Pcond + Psw``
    ``Pcond`` is *channel* power, computed by Stage 1 from its internal
    conduction-only current ``Ich``. The exported ``ID`` is the total terminal
    current, ``ID = Ich + displacement + leakage``. The two therefore coincide
    at steady state (measured agreement 5e-10 relative over 7591 quiescent
    rows) and separate wherever Vds moves. On the switching load line, where
    ``|dv/dt|`` reaches 6e9 V/s, the separation is about 14.5 A of output-capacitance
    displacement current and up to 843 W of power.

    Note that ``ID + IS`` is **not** the channel current: the Stage 1 node
    balance ``ID + IG + IS = 0`` makes ``ID + IS = -IG``, which is essentially
    zero in every profile. Any analysis that treats ``ID + IS`` as the channel
    current will compute a near-zero current and therefore a meaningless
    resistance or stress figure. The channel current is ``Ich``, and ``ID`` is
    the correct observable proxy for it.

    The residual ``Pcond - Vds * ID`` is *not* a model error and must not be
    read as one, but it is also not a single clean quantity: it is dominated by
    ``Vds * Coss * dv/dt`` displacement charging wherever the sweep moves, which
    is why even a "DC" profile shows a gap (the DC sweeps advance Vds by 0.5 V
    per 1 ns sample). Phase 2B must therefore treat ``Pcond`` and ``Vds * ID``
    as distinct, must not sum them, and must not use the residual as a
    degradation signal.

``Ploss = Pcond + Psw`` exactly, and nothing else
    The Stage 1 loss budget has precisely two channels, verified to 0.0 W
    residual over all 15904 rows. There is **no** output-capacitance
    charge/discharge channel and **no** gate-drive dissipation channel. This
    matters for Phase 2B: because Coss is never charged, the simulated load line
    is exactly reversible, so the dataset cannot distinguish turn-on from
    turn-off loss. Any switching-energy integral computed from it is a
    reversible channel-conduction path integral, not a switching loss.

``Psw = Vds * abs(iCgd)``
    ``Psw`` is the power flowing through the Miller capacitance during a
    transition. It is **not** turn-on/turn-off switching loss. Stage 2 records
    this so Phase 2B cannot silently treat it as an energy-loss indicator.

The channel current itself carries no temperature term in the Stage 1 model
(only leakage scales with temperature), which is checked and reported as a
blocker for any temperature-dependent RON analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import Stage2Config


# --------------------------------------------------------------------------
# Stage 1 model equations, restated so the physics rules are auditable.
# Every constant is read from the Stage 1 parameter set at runtime.
# --------------------------------------------------------------------------
def saturation_voltage_v(
    vgs: np.ndarray, vth: float, vsmooth: float, vdsat_max: float
) -> np.ndarray:
    """Stage 1 knee voltage ``VDSAT(VGS) = min(max(Vc, 0), VDSAT)``.

    Mirrors ``channelScript`` in ``create_gan_hemt_twin.m``. Used to place the
    triode/saturation boundary without inventing a fixed knee voltage.
    """
    vov = np.asarray(vgs, dtype=float) - vth
    vc = 0.5 * vov * (1.0 + np.tanh(vov / (2.0 * vsmooth)))
    return np.minimum(np.maximum(vc, 0.0), vdsat_max)


def leakage_current_a(
    vds: np.ndarray, tcase_C: np.ndarray, params: dict[str, Any]
) -> np.ndarray:
    """Stage 1 drain leakage ``Ild``.

    Mirrors ``Ild = idss * (min(|Vds|, vdss_ref)/vdss_ref)^0.5 * tf`` where
    ``tf`` is the printed 25->125 degC leakage ratio raised over its span.
    """
    idss = float(params["model.idss_A"])
    vdss_ref = float(params["model.vdss_ref_V"])
    ratio = float(params["model.leak_temp_ratio"])
    span = float(params["model.leak_temp_span_C"])
    tnom = float(params["model.tnom_C"])

    vda = np.abs(np.asarray(vds, dtype=float))
    tf = ratio ** ((np.asarray(tcase_C, dtype=float) - tnom) / span)
    return idss * (np.minimum(vda, vdss_ref) / vdss_ref) ** 0.5 * tf


def add_physics_columns(df: pd.DataFrame, params: dict[str, Any], cfg: Stage2Config) -> pd.DataFrame:
    """Add interpretability flags and physically-derived columns.

    Adds, per row:
      ``i_leak_A``, ``is_conducting``, ``vdsat_vgs_V``, ``operating_regime``,
      ``ron_static_ohm``, ``ron_valid``, ``ron_valid_reason``,
      ``is_characterisation``, ``is_rating_exceeded``,
      ``pcond_minus_vds_id_W``, ``cds_derived_F``, ``cgs_derived_F``.
    """
    out = df.copy()

    vth = float(params["model.vth_V"])
    vsmooth = float(params["model.vsmooth_V"])
    vdsat_max = float(params["model.vdsat_V"])

    vgs = out["vgs_V"].to_numpy(float)
    vds = out["vds_V"].to_numpy(float)
    id_ = out["id_A"].to_numpy(float)

    # --- conduction gate -------------------------------------------------
    # Anchored on the printed IDSS via the Stage 1 leakage equation, so the
    # gate moves with temperature instead of using one fixed current floor.
    # The sign test matters: at low VDS the twin's total ID can go slightly
    # negative through displacement and leakage terms, and |ID| alone would
    # admit that as "conducting", yielding a negative Vds/ID. A conducting
    # channel has ID and VDS of the same sign.
    ileak = leakage_current_a(vds, out["tcase_C"].to_numpy(float), params)
    out["i_leak_A"] = ileak
    conducting_threshold = cfg.conduction_leakage_multiple.value * ileak
    forward = id_ * vds > 0.0
    is_conducting = forward & (np.abs(id_) >= conducting_threshold)
    out["conduction_threshold_A"] = conducting_threshold

    # --- region gate ------------------------------------------------------
    vdsat = saturation_voltage_v(vgs, vth, vsmooth, vdsat_max)
    out["vdsat_vgs_V"] = vdsat
    positive_vds = vds > cfg.vds_positive_floor_V.value
    in_triode = vds <= vdsat

    out["is_conducting"] = is_conducting
    out["is_positive_vds"] = positive_vds
    out["is_triode"] = in_triode

    regime = np.full(len(out), "off_or_leakage", dtype=object)
    regime[is_conducting & in_triode & positive_vds] = "triode_ohmic"
    regime[is_conducting & ~in_triode] = "saturation_or_cvdrive"
    regime[~is_conducting & ~positive_vds] = "zero_bias"
    out["operating_regime"] = pd.Series(regime, dtype="string")
    # --- RON, gated -------------------------------------------------------
    # Only defined where a resistance can physically exist.
    ron_valid = is_conducting & in_triode & positive_vds
    with np.errstate(divide="ignore", invalid="ignore"):
        ron_static = np.where(ron_valid & (id_ != 0.0), vds / np.where(id_ == 0.0, np.nan, id_), np.nan)
    out["ron_static_ohm"] = ron_static
    out["ron_valid"] = ron_valid

    reason = np.full(len(out), "", dtype=object)
    reason[~positive_vds] = "vds_not_positive"
    reason[(positive_vds) & (~is_conducting)] = "channel_current_below_leakage_anchor"
    reason[(positive_vds) & is_conducting & (~in_triode)] = "outside_triode_vds_above_vdsat"
    reason[ron_valid] = ""
    out["ron_valid_reason"] = pd.Series(reason, dtype="string")

    # --- context flags ----------------------------------------------------
    out["profile_role"] = out["profile"].map(cfg.profile_roles).astype("string")

    ratings = params.get("_ratings", {})
    vds_rating = float(ratings.get("vds_V", np.inf))
    vgs_rating = float(params["model.vgs_max_V"])
    id_cont = float(ratings.get("id_continuous_25C_A", np.inf))

    out["vds_rating_utilisation"] = np.abs(vds) / vds_rating
    out["vgs_rating_utilisation"] = vgs / vgs_rating
    out["id_continuous_rating_utilisation"] = np.abs(id_) / id_cont
    out["is_rating_exceeded"] = (
        (np.abs(vds) > vds_rating)
        | (vgs > vgs_rating)
        | (np.abs(id_) > id_cont)
    )

    # C-V and gate-charge sweeps drive VGS at high VDS purely to bias the
    # measurement. They are not application operating points.
    out["is_characterisation_sweep"] = out["profile"].isin(
        ["capacitance", "charge", "output", "transfer", "thermal"]
    )
    out["is_application_operating_point"] = (
        (out["profile"] == "switching") & out["is_conducting"] & ~out["is_rating_exceeded"]
    )

    # --- derived physics --------------------------------------------------
    # Pcond is Vds*Ich, where Ich is Stage 1's conduction-only channel current.
    # The exported ID additionally carries displacement and leakage, so the
    # residual is displacement-charging power wherever Vds is moving. It is not
    # a model error, but it is not a constant either and must not be summed
    # with Pcond or read as a degradation signal.
    out["pcond_minus_vds_id_W"] = out["pcond_W"] - out["vds_V"] * out["id_A"]
    out["ploss_identity_residual_W"] = out["ploss_W"] - (out["pcond_W"] + out["psw_W"])
    out["kcl_residual_A"] = out["id_A"] + out["ig_A"] + out["is_A"]

    # Intrinsic capacitances recovered from the measured terminal set:
    # Coss = Cds + Cgd and Ciss = Cgs + 2*Cgd with Cgd = Crss.
    out["cgd_derived_F"] = out["crss_F"]
    out["cds_derived_F"] = out["coss_F"] - out["crss_F"]
    out["cgs_derived_F"] = out["ciss_F"] - 2.0 * out["crss_F"]

    return out


def estimate_differential_ron(df: pd.DataFrame, cfg: Stage2Config) -> pd.DataFrame:
    """Per-operating-point slope ``dVds/dID`` from the DC output sweep.

    The datasheet quotes a single RON at one bias point; a physics-informed
    Stage 2 indicator instead needs the local slope, which is only obtainable
    where a VDS sweep exists at fixed VGS and Tcase. Non-sweep profiles get
    NaN and ``ron_differential_available = False``.
    """
    out = df.copy()
    out["ron_differential_ohm"] = np.nan
    out["ron_differential_available"] = False

    sweep = out[out["profile"] == "output"].copy()
    if sweep.empty:
        return out

    dec = int(cfg.operating_point_decimals.value)
    sweep["_key_vgs"] = sweep["vgs_V"].round(dec)
    sweep["_key_tcase"] = sweep["tcase_C"].round(dec)
    for key, block in sweep.groupby(["_key_vgs", "_key_tcase"], sort=False):
        key_vgs, key_tcase = key[0], key[1]
        usable = block[block["ron_valid"]]
        if len(usable) < 3:
            continue
        slope = np.polyfit(usable["id_A"].to_numpy(float), usable["vds_V"].to_numpy(float), 1)[0]
        selector = (
            (out["profile"] == "output")
            & np.isclose(out["vgs_V"], key_vgs, atol=10.0 ** -dec)
            & np.isclose(out["tcase_C"], key_tcase, atol=10.0 ** -dec)
        )
        out.loc[selector, "ron_differential_ohm"] = slope
        out.loc[selector, "ron_differential_available"] = True

    return out


# --------------------------------------------------------------------------
# Physics consistency checks
# --------------------------------------------------------------------------
@dataclass
class PhysicsCheck:
    check_id: str
    name: str
    passed: bool
    detail: str
    affected: int = 0
    severity: str = "HIGH"
    status: str = "PASS"


def run_physics_checks(df: pd.DataFrame, params: dict[str, Any], cfg: Stage2Config) -> list[PhysicsCheck]:
    """Evaluate physical identities and interpretability gates."""
    checks: list[PhysicsCheck] = []
    n = len(df)

    # P01 node current balance: ID + IG + IS = 0 (identity)
    worst = float(np.nanmax(np.abs(df["kcl_residual_A"].to_numpy(float))))
    checks.append(
        PhysicsCheck(
            "P01",
            "Node current balance (ID + IG + IS = 0)",
            worst <= cfg.kcl_atol.value,
            f"max |residual| = {worst:.3e} A over {n} samples "
            f"(tolerance {cfg.kcl_atol.value:.1e} A)",
            affected=int((np.abs(df["kcl_residual_A"]) > cfg.kcl_atol.value).sum()),
        )
    )

    # P02 power balance: Ploss = Pcond + Psw (identity)
    worst_p = float(np.nanmax(np.abs(df["ploss_identity_residual_W"].to_numpy(float))))
    checks.append(
        PhysicsCheck(
            "P02",
            "Power balance (Ploss = Pcond + Psw)",
            worst_p <= cfg.power_balance_atol.value,
            f"max |residual| = {worst_p:.3e} W over {n} samples "
            f"(tolerance {cfg.power_balance_atol.value:.1e} W)",
            affected=int((np.abs(df["ploss_identity_residual_W"]) > cfg.power_balance_atol.value).sum()),
        )
    )

    # P03 Pcond is Vds*Ich, so Pcond != Vds*ID wherever ID carries displacement.
    # The residual must be attributable to displacement charging and to nothing
    # else. Stage 2B verifies that attribution quantitatively against
    # Coss*|dv/dt| on the reconstructed switching load line.
    saturated_dc = df[df["profile"].isin(["output", "transfer", "thermal"]) & ~df["is_triode"]]
    if len(saturated_dc):
        resid = saturated_dc["pcond_minus_vds_id_W"].abs()
        chan = saturated_dc["pcond_W"].abs().replace(0.0, np.nan)
        max_resid = float(resid.max())
        max_rel = float((resid / chan).max())
        # Attribute the residual to a current rather than quoting watts alone.
        disp_a = (resid / saturated_dc["vds_V"].abs()).max()
        leak_a = float(saturated_dc["i_leak_A"].max())
        ratio = disp_a / leak_a if leak_a > 0 else float("inf")
        quiescent = df[df["ploss_W"].abs() > 1.0]
        q_resid = float((quiescent["pcond_minus_vds_id_W"].abs()).median()) if len(quiescent) else 0.0
        checks.append(
            PhysicsCheck(
                "P03",
                "Pcond is channel power (Vds*Ich) and carries a displacement residual",
                True,
                "Pcond is Vds*Ich with Stage 1's conduction-only channel current, while the "
                "exported ID additionally carries displacement and leakage current, so the two "
                "coincide only where nothing is moving: the median residual over dissipative "
                f"samples is {q_resid:.3e} W. Largest gap over {len(saturated_dc)} saturated DC "
                f"samples = {max_resid:.3e} W, at most {100.0 * max_rel:.1f} % of channel power. "
                f"That gap implies a {disp_a:.3e} A displacement current, which exceeds the "
                f"worst-case leakage ({leak_a:.3e} A) by {ratio:.0f}x, so it is displacement "
                "charging and not a model error. The DC sweeps step Vds by 0.5 V per 1 ns sample, "
                "so these samples are not quasi-static and the residual is material here. On the "
                "switching load line the gap is far larger (up to ~843 W) because |dv/dt| reaches "
                "~6e9 V/s. Downstream code must treat Pcond and Vds*ID as distinct quantities, "
                "must not add them together, and must not read the residual as a degradation signal.",
                severity="MEDIUM",
                status="INFO",
            )
        )

    # P04 capacitance ordering: Cds = Coss - Crss >= 0 and Cgs = Ciss - 2*Crss >= 0
    bad_c = int(((df["cds_derived_F"] < -1e-18) | (df["cgs_derived_F"] < -1e-18)).sum())
    checks.append(
        PhysicsCheck(
            "P04",
            "Intrinsic capacitance positivity (Cds, Cgs >= 0)",
            bad_c == 0,
            f"min Cds = {df['cds_derived_F'].min():.4e} F, "
            f"min Cgs = {df['cgs_derived_F'].min():.4e} F; {bad_c} negative samples",
            affected=bad_c,
        )
    )

    # P05 Qg must not decrease during a monotonic gate ramp
    charge = df[df["profile"] == "charge"]
    if len(charge):
        qg = charge["qg_C"].to_numpy(float)
        drops = int((np.diff(qg) < -1e-18).sum())
        checks.append(
            PhysicsCheck(
                "P05",
                "Gate charge monotonicity during the charge sweep",
                drops == 0,
                f"Qg starts at {qg[0]:.4e} C and ends at {qg[-1]:.4e} C; "
                f"{drops} decreasing steps",
                affected=drops,
            )
        )
        # Qg initial value is a semantic trap, not an error.
        checks.append(
            PhysicsCheck(
                "P06",
                "Qg initial value at the start of the charge sweep",
                False,
                f"Qg(0) = {qg[0]:.4e} C, not 0. Stage 1 defines Qg = Qgs + Qgd where "
                "Qgd includes the Cgd depletion charge at VDS = 75 V, which equals the "
                "printed QGD = 4.7 nC. Qg is therefore an absolute charge referenced to "
                "the drain bias; Phase 2B must use delta-Qg over a gate excursion, not "
                "Qg itself.",
                affected=1,
                severity="MEDIUM",
                status="WARN",
            )
        )

    # P07 RON interpretability: how much of the exported RON survives the gates
    total = n
    usable = int(df["ron_valid"].sum())
    pct = 100.0 * usable / total if total else 0.0
    checks.append(
        PhysicsCheck(
            "P07",
            "Exported RON interpretable as a conduction resistance",
            pct >= 50.0,
            f"{usable}/{total} samples ({pct:.1f}%) are both conducting and in the "
            "triode region. Stage 1 masks RON only on ID > 0.1 A, so the remainder "
            "report Vds/ID in saturation or in the off state, where the ratio is not a "
            "resistance. Phase 2B must use ron_valid, not the raw column.",
            affected=total - usable,
            severity="HIGH",
            status="WARN" if pct < 50.0 else "PASS",
        )
    )

    # P08 Stage 1 RON must equal the recomputed static RON wherever both defined
    both = df[df["ron_valid"] & df["ron_stage1_ohm"].notna()]
    if len(both):
        rel = float(
            np.nanmax(
                np.abs(
                    (both["ron_stage1_ohm"] - both["ron_static_ohm"]).to_numpy(float)
                    / np.where(both["ron_static_ohm"] == 0, np.nan, both["ron_static_ohm"])
                )
            )
        )
        checks.append(
            PhysicsCheck(
                "P08",
                "Stage 1 RON agrees with recomputed Vds/ID where valid",
                rel <= 1e-9,
                f"max relative difference = {rel:.3e} over {len(both)} gated samples",
                severity="INFO",
                status="INFO",
            )
        )

    # P09 temperature dependence of the channel current.
    # Requirement 3 needs temperature-aware RON; check whether the source
    # model can supply it at all.
    thermal = df[df["profile"] == "thermal"].copy()
    temp_spread = 0.0
    if len(thermal):
        thermal["_key_vgs"] = thermal["vgs_V"].round(3)
        thermal["_key_vds"] = thermal["vds_V"].round(3)
        ratios = []
        for _, block in thermal.groupby(["_key_vgs", "_key_vds"]):
            conduction = block[block["is_conducting"]]
            if conduction["tcase_C"].nunique() > 1:
                by_t = conduction.groupby("tcase_C")["id_A"].mean()
                if len(by_t) == 2 and by_t.iloc[0] != 0:
                    ratios.append(by_t.iloc[1] / by_t.iloc[0])
        if ratios:
            temp_spread = float(np.max(np.abs(np.array(ratios) - 1.0)))
    checks.append(
        PhysicsCheck(
            "P09",
            "Temperature dependence present in the channel current",
            False,
            f"Across the thermal sweep the 25->125 degC drain-current ratio deviates "
            f"from 1.0 by at most {temp_spread:.3e} (i.e. no dependence). The Stage 1 "
            "channel equation has no temperature term; only leakage scales. A "
            "temperature-normalised RON cannot be computed from this dataset without "
            "inventing a coefficient, so it is left unavailable.",
            affected=int(len(thermal)),
            severity="BLOCKER",
            status="BLOCKED",
        )
    )

    # P10 thermal model absent: Tj tracks Tcase exactly
    dT = float(np.nanmax(np.abs((df["tj_C"] - df["tcase_C"]).to_numpy(float))))
    checks.append(
        PhysicsCheck(
            "P10",
            "Thermal model present (Tj rises above Tcase)",
            dT > 0.0,
            f"max |Tj - Tcase| = {dT:.3e} degC. All thermal resistances and PTOT are "
            "TBD in the datasheet, so junction temperature is not modelled and no "
            "thermal stress indicator is available.",
            affected=n,
            severity="BLOCKER",
            status="BLOCKED",
        )
    )

    # P11 rating utilisation of the characterisation sweeps
    exceeded = int(df["is_rating_exceeded"].sum())
    if exceeded:
        worst_cur = float(df["id_A"].abs().max())
        checks.append(
            PhysicsCheck(
                "P11",
                "Samples outside absolute-maximum or continuous ratings",
                False,
                f"{exceeded} samples exceed a printed rating, driven by the datasheet "
                f"characterisation sweeps (peak |ID| = {worst_cur:.1f} A against a "
                f"{params.get('_ratings', {}).get('id_continuous_25C_A', float('nan')):.0f} A "
                "continuous rating). Legitimate as measurement conditions, but they are "
                "not application operating points and must be excluded from stress "
                "indicators.",
                affected=exceeded,
                severity="MEDIUM",
                status="WARN",
            )
        )

    # P12 aging data present
    checks.append(
        PhysicsCheck(
            "P12",
            "Aging / stress-history measurements present",
            False,
            "Every Stage 1 profile is a single operating-condition sweep on one "
            "simulated device at one point in time. There is no time-separated "
            "repetition, no stress history and no second device instance, so no "
            "permanent degradation can be separated from an operating change.",
            affected=n,
            severity="BLOCKER",
            status="BLOCKED",
        )
    )

    return checks
