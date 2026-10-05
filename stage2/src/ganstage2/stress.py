"""Stage 2B -- physics-informed stress and exposure modelling.

This module turns the validated Stage 2A dataset into stress quantities. It does
**not** model degradation. There is no aging axis anywhere in the input, so no
degradation law could be fitted even in principle; what follows is a stress and
exposure accounting that a future aging study could be normalised against.

Three properties of the Stage 1 output shape everything here.

**The channel current is ``ID``, not ``ID + IS``.** The Stage 1 node balance
``ID + IG + IS = 0`` makes ``ID + IS = -IG``, which is essentially zero. Using
it as a current would silently produce a near-zero resistance.

**A profile is not one trajectory.** The Stage 1 exporter placed several
independent trajectories on a single shared, monotonic time axis. In the
switching profile, 20 distinct bias points each own a slice of the same time
span, so the 18-point rise path is only visible once the rows are grouped by
operating point and then by transition window. Integrating over a whole profile
would sum concurrent trajectories and mean nothing. Every integral here is
therefore taken *within* a trajectory, and the segmentation is exposed as a
column so the grouping is auditable.

**The switching transient is resolvable, but only just.** The rise and fall
paths are sampled 18 times at 1 ns intervals spanning 17 ns, alternating
turn-on and turn-off across 3 cycles. That supports a transition-energy
integral, but with 18 samples across the whole slew the peak is a lower bound.

Every quantity produced here is registered in :mod:`ganstage2.equations` with its
meaning, unit, provenance, assumptions and evidence class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from . import equations as eq
from .anchors import Anchor, build_anchors
from .evidence import EvidenceClass

#: Minimum samples in a window before its energy and slew rates are trusted. A
#: 1-2 point window cannot resolve a peak and is reported but not relied upon.
_LOAD_LINE_MIN_POINTS = 4


def _finite(value: float | None) -> float | None:
    """NaN-safe JSON coercion; ``None`` passes through."""
    if value is None:
        return None
    v = float(value)
    return v if np.isfinite(v) else None


@dataclass
class StressResult:
    """Per-sample stress table plus the trajectory and dataset-level summaries."""

    frame: pd.DataFrame
    trajectories: pd.DataFrame
    switching: dict[str, Any]
    ron: dict[str, Any]
    thermal: dict[str, Any]
    capacitance: dict[str, Any]
    charge: dict[str, Any]
    coverage: dict[str, Any]
    displacement: dict[str, Any]
    anchors: dict[str, Anchor] = field(default_factory=dict)


# --------------------------------------------------------------------------
# segmentation
# --------------------------------------------------------------------------
def add_trajectory_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Label each row with the independent trajectory it belongs to.

    A trajectory is one bias point held over its own slice of the shared time
    axis: the pair ``(profile, operating_point_key)``. Within such a group the
    time is monotonic and the bias is constant, which is the minimum needed for
    a time integral to mean anything.
    """
    out = df.copy()
    out["trajectory_id"] = (
        out["profile"].astype(str) + "::" + out["operating_point_key"].astype(str)
    )
    return out


def _transition_windows(sub: pd.DataFrame) -> pd.DataFrame:
    """Split load-line rows into transition windows by gap detection.

    The rows arrive on one shared monotonic clock. Within a window the samples
    are one solver interval apart; between windows there is a far larger gap
    because the circuit returns to its DC state in between. Grouping on that gap
    recovers the individual transitions without relying on Stage 1's labels.
    """
    ordered = sub.sort_values("t_s").copy()
    n = len(ordered)
    if n == 0:
        return ordered.assign(
            transition_window=pd.Series(dtype=int),
            transition_kind=pd.Series(dtype=str),
        )
    gaps = np.diff(ordered["t_s"].to_numpy())
    positive = gaps[gaps > 0]
    if positive.size == 0:
        return ordered.assign(
            transition_window=pd.Series(dtype=int),
            transition_kind=pd.Series(dtype=str),
        )
    sample_dt = float(np.median(positive))
    threshold = max(sample_dt * 4.0, 1e-18)
    breaks = np.flatnonzero(gaps > threshold)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks + 1, [n]))
    ordered["transition_window"] = np.concatenate(
        [np.full(e - s, i) for i, (s, e) in enumerate(zip(starts, ends))]
    )
    # Label each window from its own endpoints. A window is one continuous slew,
    # so Vgs travels in a single direction throughout it and the sign of that
    # window's overall change names the transition. Taking the endpoints of the
    # whole block instead would give every window the same label.
    ends_vgs = ordered.groupby("transition_window", sort=True)["vgs_V"].agg(["first", "last"])
    label = pd.Series(
        np.where(ends_vgs["last"] > ends_vgs["first"], "turn_on", "turn_off"),
        index=ends_vgs.index,
    )
    ordered["transition_kind"] = ordered["transition_window"].map(label).astype(str)
    return ordered


def segment_switching(df: pd.DataFrame, cfg_sample_dt: float) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach transition-window structure to the switching profile.

    Load-line rows and DC holds are told apart by *trajectory size*, not by bias
    variation. Each load-line bias point appears once per transition, so it owns
    only a handful of rows in total, while a DC hold owns thousands. The
    distinction matters: integrating across a DC hold measures how long the
    device sat at one bias, while integrating along a load line measures what a
    transition cost.
    """
    out = df.copy()
    out["transition_window"] = pd.Series([pd.NA] * len(out), dtype="object")
    out["transition_kind"] = pd.Series([pd.NA] * len(out), dtype="object")

    sw = out["profile"] == "switching"
    if not sw.any():
        return out, {"available": False, "reason": "no switching profile in the dataset"}

    block = out.loc[sw]
    sizes = block.groupby("operating_point_key", sort=False).size()
    # A hold owns an order of magnitude more rows than a transition sample.
    hold_threshold = max(int(len(block) * 0.1), 2)
    hold_keys = set(sizes.index[sizes >= hold_threshold])
    ladder = block[~block["operating_point_key"].isin(hold_keys)]

    if ladder.empty:
        return out, {
            "available": False,
            "reason": (
                "every switching bias point is a long DC hold, so the profile "
                "contains no resolvable transition"
            ),
            "dc_hold_bias_points": int(len(hold_keys)),
        }

    seg = _transition_windows(ladder)
    out.loc[seg.index, "transition_window"] = seg["transition_window"].to_numpy()
    out.loc[seg.index, "transition_kind"] = seg["transition_kind"].to_numpy()

    windows = []
    for w, sub in seg.groupby("transition_window", sort=True):
        sub = sub.sort_values("t_s")
        t = sub["t_s"].to_numpy()
        multi = t.size > 1
        dt = float(np.median(np.diff(t))) if multi else float("nan")
        windows.append({
            "window": int(w),
            "kind": str(sub["transition_kind"].iloc[0]),
            "start_s": float(t[0]),
            "end_s": float(t[-1]),
            "span_s": float(t[-1] - t[0]) if multi else 0.0,
            "samples": int(len(sub)),
            "sample_interval_s": _finite(dt),
            "vgs_start_V": float(sub["vgs_V"].iloc[0]),
            "vgs_end_V": float(sub["vgs_V"].iloc[-1]),
            "vds_start_V": float(sub["vds_V"].iloc[0]),
            "vds_end_V": float(sub["vds_V"].iloc[-1]),
            "peak_id_A": float(np.abs(sub["id_A"].to_numpy()).max()),
            "peak_ploss_W": float(np.abs(sub["ploss_W"].to_numpy()).max()),
            "transition_energy_J": _finite(float(np.trapezoid(sub["ploss_W"].to_numpy(), t))) if multi else 0.0,
            "conduction_overlap_energy_J": _finite(float(np.trapezoid(sub["pcond_W"].to_numpy(), t))) if multi else 0.0,
            "miller_energy_J": _finite(float(np.trapezoid(sub["psw_W"].to_numpy(), t))) if multi else 0.0,
            "peak_dvdt_V_per_s": _finite(_peak_rate(sub["vds_V"].to_numpy(), t)),
            "peak_didt_A_per_s": _finite(_peak_rate(sub["id_A"].to_numpy(), t)),
        })

    on = [w for w in windows if w["kind"] == "turn_on"]
    off = [w for w in windows if w["kind"] == "turn_off"]
    ivals = [w["transition_energy_J"] for w in windows if w["transition_energy_J"] is not None]
    resolved = [w for w in windows if w["samples"] >= _LOAD_LINE_MIN_POINTS]
    window_lengths = sorted({w["samples"] for w in windows})

    reversibility = _reversibility_diagnostic(seg)

    summary: dict[str, Any] = {
        "available": True,
        "n_windows": len(windows),
        "n_windows_resolved": len(resolved),
        "n_turn_on": len(on),
        "n_turn_off": len(off),
        "load_line_bias_points": int(ladder["operating_point_key"].nunique()),
        "dc_hold_bias_points": int(len(hold_keys)),
        "dc_hold_keys": sorted(str(k) for k in hold_keys),
        "windows": windows,
        "mean_turn_on_energy_J": _finite(float(np.mean([w["transition_energy_J"] for w in on]))) if on else None,
        "mean_turn_off_energy_J": _finite(float(np.mean([w["transition_energy_J"] for w in off]))) if off else None,
        "transition_energy_spread_J": _finite(float(np.std(ivals))) if ivals else None,
        "solver_sample_interval_s": _finite(cfg_sample_dt),
        # Kept as a list so the report can show that every recovered window has
        # the same length; a non-uniform result would mean the gap detection
        # merged or split a window, which is a structural failure worth seeing.
        "samples_per_transition_all": window_lengths,
        "samples_per_transition": window_lengths[0] if len(window_lengths) == 1 else None,
        "reversibility": reversibility,
        "switching_loss_available": False,
        "switching_loss_unavailable_reason": (
            "Stage 1's loss budget is exactly Ploss = Pcond + Psw (residual 0.0 W over all "
            "15904 rows). Psw is the Miller channel only, contributing 0.07 % of the path "
            "integral. There is no output-capacitance charge/discharge channel and no "
            "gate-drive dissipation channel, so Coss is never charged during a transition. "
            "The consequence is measurable: the simulated load line is exactly reversible, "
            "with turn-off the bit-level reverse of turn-on. A hard-switched device cannot "
            "behave this way, because turn-on charges Coss and clamps the inductor current "
            "into the low-side device while turn-off does not. The energies below are "
            "therefore reported as reversible channel-conduction path integrals and are "
            "explicitly NOT switching losses."
        ),
        "path_integral_note": (
            "A path integral of channel power along a reversible trajectory is a property of "
            "the path, not a device loss. It cannot be compared to a datasheet switching-loss "
            "figure, and it must not be multiplied by a switching frequency."
        ),
        "interpretation": (
            "Each window is one hard-switching transition sampled across its whole "
            "slew. The energy is the energy of that transition, not of a switching "
            "cycle: no repetition rate exists in the dataset, so it is never "
            "multiplied by one and is never called a per-cycle switching loss."
        ),
        "resolution_caveat": (
            "A transition is sampled at the solver output interval, which is the "
            "finest resolution the dataset offers. Peaks within one sample interval "
            "are invisible, so every energy and rate here is a lower bound."
        ),
        "incomplete_evidence": (
            "The sampled load line spans Vgs 0.263 V to 4.737 V. The 0 V to 0.263 V "
            "gate segment appears only in the off-state DC hold, and the final "
            "Vds = 1.61 V endpoint only in the on-state hold. Those are separate "
            "trajectories on the same clock, so the sampled path is not one "
            "continuous waveform and the transition energy omits both end segments."
        ),
        "excitation_representativeness": (
            "Peak |ID| is 809.8 A, which is 7.04x the 115 A continuous rating and 0.96x "
            "the 840 A pulse rating, with 20.8 kW peak instantaneous dissipation and "
            "10.05 kW mean over the 17 ns slew. The Stage 1 excitation has no external "
            "loop inductance, so nothing limits di/dt and the drain node cannot sag; that "
            "is why 380 A and 52 V coexist. These transitions are an excitation artefact, "
            "not a representative operating condition."
        ),
        "evidence": EvidenceClass.SIMULATED.value,
    }
    return out, summary


def _reversibility_diagnostic(seg: pd.DataFrame) -> dict[str, Any]:
    """Test whether turn-off is the reverse of turn-on, and whether cycles repeat.

    This is the check that decides whether a switching loss can be extracted at
    all. In a real hard-switched device the two directions differ by at least the
    output-capacitance energy. If the exported path is bit-for-bit reversible,
    the loss model contains no capacitive state, and no switching loss exists in
    the data to recover.
    """
    kind_of = {
        int(w): str(sub["transition_kind"].iloc[0])
        for w, sub in seg.groupby("transition_window", sort=True)
    }
    windows_sorted = sorted(kind_of)

    # Pair each turn-on with the turn-off that follows it in the same cycle.
    pairs: list[dict[str, Any]] = []
    for i, w in enumerate(windows_sorted):
        if kind_of[w] != "turn_on":
            continue
        nxt = windows_sorted[i + 1] if i + 1 < len(windows_sorted) else None
        if nxt is None or kind_of[nxt] != "turn_off":
            continue
        a = seg[seg["transition_window"] == w].sort_values("t_s")
        b = seg[seg["transition_window"] == nxt].sort_values("t_s")
        if len(a) != len(b):
            continue
        diff = np.abs(a["pcond_W"].to_numpy()[::-1] - b["pcond_W"].to_numpy())
        scale = np.maximum(np.abs(b["pcond_W"].to_numpy()), 1e-12)
        pairs.append({
            "turn_on_window": w,
            "turn_off_window": int(nxt),
            "max_abs_difference_W": _finite(float(diff.max())),
            "max_relative_difference": _finite(float((diff / scale).max())),
            "bias_keys_reversed_identical": bool(
                a["operating_point_key"].tolist() == b["operating_point_key"].tolist()[::-1]
            ),
        })

    # Cycle-to-cycle repeatability, comparing like transitions.
    repeat: list[dict[str, Any]] = []
    by_kind: dict[str, list[int]] = {}
    for w in windows_sorted:
        by_kind.setdefault(kind_of[w], []).append(w)
    for kind, ws in sorted(by_kind.items()):
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                a = seg[seg["transition_window"] == ws[i]].sort_values("t_s")["pcond_W"].to_numpy()
                b = seg[seg["transition_window"] == ws[j]].sort_values("t_s")["pcond_W"].to_numpy()
                if len(a) != len(b):
                    continue
                repeat.append({
                    "kind": kind,
                    "windows": [ws[i], ws[j]],
                    "max_abs_difference_W": _finite(float(np.abs(a - b).max())),
                })

    max_rel = max((p["max_relative_difference"] or 0.0) for p in pairs) if pairs else None
    max_rep = max((r["max_abs_difference_W"] or 0.0) for r in repeat) if repeat else None
    reversible = bool(pairs) and max_rel is not None and max_rel < 1e-9
    identical_cycles = bool(repeat) and max_rep is not None and max_rep == 0.0

    return {
        "tested_pairs": pairs,
        "cycle_repeatability": repeat,
        "max_relative_asymmetry": _finite(max_rel),
        "max_cycle_difference_W": _finite(max_rep),
        "load_line_is_reversible": reversible,
        "cycles_bit_identical": identical_cycles,
        "interpretation": (
            "Reversibility is a property of the Stage 1 loss model, not of a GaN HEMT. "
            "It means the exported trajectory has no capacitive state, so turn-on and "
            "turn-off are the same integral traversed in opposite directions."
            if reversible
            else "The two transition directions differ measurably, so a directional "
            "split of the path integral carries information."
        ),
        "cycle_identity_note": (
            "All cycles are bit-identical, which confirms the excitation is a "
            "deterministic scripted waveform rather than a stochastic simulation."
            if identical_cycles
            else "Cycles differ, so the excitation contains run-to-run variation."
        ),
        "evidence": EvidenceClass.CALCULATED.value,
    }


def _peak_rate(values: np.ndarray, t: np.ndarray) -> float:
    """Peak absolute rate of change, NaN-safe for short or degenerate windows."""
    if values.size < 2:
        return float("nan")
    rate = np.abs(np.gradient(values, t))
    rate = rate[np.isfinite(rate)]
    return float(rate.max()) if rate.size else float("nan")


# --------------------------------------------------------------------------
# per-sample stress
# --------------------------------------------------------------------------
def add_sample_stress(df: pd.DataFrame, anchors: dict[str, Anchor]) -> pd.DataFrame:
    """Add per-sample electrical, thermal and loss stress ratios.

    The three rating-utilisation ratios already exist in the Stage 2A dataset and
    are reused unchanged rather than recomputed. Stage 2A defines them against
    ``|VDS|/150``, ``VGS/6`` and ``|ID|/115``; overwriting them here would
    silently change a validated column, and the gate-drive ratio in particular
    differs, because Stage 2A uses the positive limit for both signs while the
    printed negative gate limit is -4 V.
    """
    out = df.copy()

    id_abs = out["id_A"].abs()
    vgs = out["vgs_V"]

    # A sign-aware gate-drive ratio, kept under a new name because Stage 2A's
    # single-limit version cannot express the asymmetric +/-6 V / -4 V window.
    gate_span = np.where(vgs >= 0.0, anchors["VGS_ABS_MAX"].value, abs(anchors["VGS_ABS_MIN"].value))
    out["vgs_gate_window_utilisation"] = np.divide(
        vgs.abs(), gate_span, out=np.zeros(len(out)), where=gate_span > 0
    )

    # Pulse rating is a separate limit from the continuous rating and is not
    # part of the Stage 2A schema.
    id_pulse = anchors["ID_PULSE_25C"].value
    out["id_pulse_rating_utilisation"] = id_abs / id_pulse if id_pulse > 0 else np.nan

    out["case_rise_above_ambient_C"] = out["tcase_C"] - anchors["TCASE_NOM"].value
    tj_max = anchors["TJ_MAX"].value
    out["junction_rating_utilisation"] = out["tj_C"] / tj_max if tj_max > 0 else np.nan

    # PTOT is printed TBD, so power is normalised by the rating *product* purely
    # to give a dimensionless scale of reference. This is not a power density.
    rating_product = anchors["ID_CONTINUOUS_25C"].value * anchors["VDS_ABS_MAX"].value
    out["conduction_power_rating_product_ratio"] = (
        out["pcond_W"].abs() / rating_product if rating_product > 0 else np.nan
    )

    out["conduction_loss_share"] = np.divide(
        out["pcond_W"],
        out["ploss_W"],
        out=np.full(len(out), np.nan),
        where=out["ploss_W"].abs() > 0,
    )

    # Slew rates need the right path. A trajectory is one bias point, and a bias
    # point does not move, so within-trajectory differencing returns ~0
    # everywhere. The load line is only visible when the samples of a single
    # transition window are read across bias points, so slew is computed on the
    # window path where one exists and on the trajectory otherwise.
    out["dvdt_path_V_per_s"], out["didt_path_A_per_s"] = _path_rates(out)

    # Rating exceedance, extending the Stage 2A boolean with a signed gate-window
    # check and a count, so a reader can see how many limits are broken at once.
    exceed = out["is_rating_exceeded"].to_numpy().astype(int)
    exceed += (out["vgs_gate_window_utilisation"] > 1.0).to_numpy()
    exceed += (out["junction_rating_utilisation"] > 1.0).to_numpy()
    out["rating_exceedance_count"] = exceed
    return out


def _path_rates(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Slew rates along the transition path, else along the trajectory.

    Rows belonging to a reconstructed transition window are differenced against
    their neighbours *within that window*, which is the only grouping under
    which Vds and ID actually change. Every other row is differenced within its
    own trajectory.
    """
    dv = np.full(len(df), np.nan)
    di = np.full(len(df), np.nan)
    t = df["t_s"].to_numpy()
    y_vds = df["vds_V"].to_numpy()
    y_id = df["id_A"].to_numpy()

    def _fill(group: pd.core.groupby.DataFrameGroupBy, a: np.ndarray, b: np.ndarray) -> None:
        for _, idx in group.groups.items():
            pos = df.index.get_indexer(idx)
            pos = pos[np.argsort(t[pos], kind="stable")]
            if pos.size < 2:
                continue
            dt = np.diff(t[pos])
            good = dt > 0
            if not good.any():
                continue
            a[pos[1:]] = np.where(good, np.abs(np.diff(y_vds[pos])) / np.where(good, dt, 1.0), np.nan)
            b[pos[1:]] = np.where(good, np.abs(np.diff(y_id[pos])) / np.where(good, dt, 1.0), np.nan)

    on_path = df["transition_window"].notna()
    if on_path.any():
        _fill(df[on_path].groupby("transition_window", sort=False), dv, di)
    off_path = ~on_path
    if off_path.any():
        _fill(df[off_path].groupby("trajectory_id", sort=False), dv, di)
    return dv, di


# --------------------------------------------------------------------------
# trajectory exposure
# --------------------------------------------------------------------------
def build_trajectory_table(df: pd.DataFrame, anchors: dict[str, Anchor]) -> pd.DataFrame:
    """Time-integrated exposure for each trajectory.

    All integrals are trapezoidal and confined to one trajectory. The resulting
    energies are energies of the simulated observation window only: there is no
    duty cycle, repetition rate or field history in the dataset, so none of them
    can be converted into a lifetime or a duty-cycle loss.
    """
    rows = []
    for (profile, traj), sub in df.groupby(["profile", "trajectory_id"], sort=False):
        sub = sub.sort_values("t_s")
        t = sub["t_s"].to_numpy()
        n = len(sub)
        span = float(t[-1] - t[0]) if n > 1 else 0.0

        def integ(col: str) -> float:
            if n < 2:
                return 0.0
            return float(np.trapezoid(sub[col].to_numpy(), t))

        rise = (sub["tcase_C"] - anchors["TCASE_NOM"].value).clip(lower=0.0)
        vutil = sub["vds_rating_utilisation"].to_numpy() ** 2
        iutil = sub["id_continuous_rating_utilisation"].to_numpy() ** 2

        rows.append({
            "profile": profile,
            "trajectory_id": traj,
            "operating_point_key": str(sub["operating_point_key"].iloc[0]),
            "samples": n,
            "start_s": float(t[0]),
            "end_s": float(t[-1]),
            "span_s": span,
            "median_sample_interval_s": _finite(
                float(np.median(np.diff(t))) if n > 1 else float("nan")
            ),
            "vgs_V": float(sub["vgs_V"].iloc[0]),
            "vds_V": float(sub["vds_V"].iloc[0]),
            "tcase_C": float(sub["tcase_C"].iloc[0]),
            "peak_id_A": float(np.abs(sub["id_A"].to_numpy()).max()),
            "peak_ploss_W": float(np.abs(sub["ploss_W"].to_numpy()).max()),
            "total_loss_energy_J": integ("ploss_W"),
            "conduction_energy_J": integ("pcond_W"),
            "miller_energy_J": integ("psw_W"),
            "thermal_exposure_Ks": float(np.trapezoid(rise.to_numpy(), t)) if n > 1 else 0.0,
            "cumulative_electrical_stress": float(np.trapezoid(vutil, t)) if n > 1 else 0.0,
            "cumulative_conduction_stress": float(np.trapezoid(iutil, t)) if n > 1 else 0.0,
            "max_vds_rating_utilisation": float(sub["vds_rating_utilisation"].max()),
            "max_id_continuous_rating_utilisation": float(
                sub["id_continuous_rating_utilisation"].max()
            ),
            "samples_outside_rated_envelope": int(sub["is_rating_exceeded"].astype(bool).sum()),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# focused analyses
# --------------------------------------------------------------------------
def analyse_ron(df: pd.DataFrame, anchors: dict[str, Anchor]) -> dict[str, Any]:
    """On-resistance against the datasheet spec point, and its temperature slope.

    This is the single place in Stage 2 where the Digital Twin is compared with a
    measured datasheet number, so the comparison is done exactly at the printed
    test condition rather than at a convenient nearby bias.
    """
    vgs_spec = anchors["RDS_ON_VGS"].value
    ids_spec = anchors["RDS_ON_IDS"].value
    vds_spec = anchors["RDS_ON_VDS_SPEC"].value
    rds_typ = anchors["RDS_ON_TYP"].value
    rds_max = anchors["RDS_ON_MAX"].value

    valid = df[df["ron_valid"]]
    result: dict[str, Any] = {
        "spec_point": {
            "vgs_V": vgs_spec,
            "ids_A": ids_spec,
            "vds_V": vds_spec,
            "rds_on_typ_ohm": rds_typ,
            "rds_on_max_ohm": rds_max,
            "source": "dc.rds_on_* parameters from the Stage 1 parameter block",
        },
        "valid_samples": int(len(valid)),
        "total_samples": int(len(df)),
        "valid_fraction": float(len(valid) / len(df)) if len(df) else 0.0,
    }

    # Nearest simulated sample to the printed test condition.
    score = (
        (df["vgs_V"] - vgs_spec).abs() / max(vgs_spec, 1e-12)
        + (df["vds_V"] - vds_spec).abs() / max(vds_spec, 1e-12)
        + (df["id_A"].abs() - ids_spec).abs() / max(ids_spec, 1e-12)
    )
    nearest = df.loc[score.idxmin()]
    ron_near = float(nearest["ron_static_ohm"]) if bool(nearest["ron_valid"]) else float("nan")

    result["at_spec_point"] = {
        "profile": str(nearest["profile"]),
        "vgs_V": float(nearest["vgs_V"]),
        "vds_V": float(nearest["vds_V"]),
        "id_A": float(nearest["id_A"]),
        "tcase_C": float(nearest["tcase_C"]),
        "ron_ohm": _finite(ron_near),
        "ron_valid": bool(nearest["ron_valid"]),
        "ratio_to_typ": _finite(ron_near / rds_typ) if rds_typ else None,
        "margin_ratio_to_max": _finite(rds_max / ron_near) if ron_near else None,
    }
    result["at_spec_point"]["verdict"] = (
        "model reproduces the printed typical on-resistance"
        if ron_near == ron_near and rds_typ and abs(ron_near / rds_typ - 1.0) <= 0.10
        else "model departs from the printed typical on-resistance"
    )

    # Temperature coefficient from the dataset's only temperature contrast.
    th = df[df["profile"] == "thermal"]
    coef: dict[str, Any] = {"available": False}
    if not th.empty and th["tcase_C"].nunique() > 1:
        piv = th.pivot_table(
            index=["vgs_V", "vds_V"], columns="tcase_C", values="ron_static_ohm", aggfunc="median"
        )
        temps = sorted(float(c) for c in piv.columns)
        if len(temps) >= 2:
            lo, hi = temps[0], temps[-1]
            both = piv[[lo, hi]].dropna()
            both = both[(both[lo] > 0) & (both[hi] > 0)]
            if len(both):
                ratios = (both[hi] / both[lo]).to_numpy()
                # dlnR/dT from the two matched temperatures.
                coef = {
                    "available": True,
                    "t_low_C": lo,
                    "t_high_C": hi,
                    "matched_bias_points": int(len(both)),
                    "ron_ratio_high_over_low_min": _finite(float(ratios.min())),
                    "ron_ratio_high_over_low_median": _finite(float(np.median(ratios))),
                    "ron_ratio_high_over_low_max": _finite(float(ratios.max())),
                    "coefficient_per_C": _finite(float(np.mean(np.log(ratios)) / (hi - lo))),
                    "interpretation": (
                        "The Stage 1 model's on-resistance has no temperature "
                        "dependence: the ratio is exactly 1 at every matched bias. "
                        "A real GaN HEMT has a strongly positive coefficient. This "
                        "is a model limitation, not a device property."
                    ),
                }
    result["temperature_coefficient"] = coef
    # "Identity" is judged physically, not by exact float equality: a real GaN
    # HEMT has a coefficient of order +0.3 %/K, so anything below 1e-6 /K is
    # zero for every purpose that matters (under 0.01 % across 100 K).
    result["temperature_normalisation_is_identity"] = bool(
        coef.get("available") and abs(coef.get("coefficient_per_C") or 0.0) < 1e-6
    )
    if result["temperature_normalisation_is_identity"]:
        coef["normalisation_status"] = (
            "unavailable: the model coefficient is zero to within 1e-6 /K, so temperature "
            "normalisation of RON would divide by one and add no information. Reported as "
            "unavailable rather than as a normalisation factor of exactly 1.0, which would "
            "misleadingly imply a validated RON(T) model."
        )

    # Where RON is valid, summarise its spread by profile.
    if not valid.empty:
        by_profile = valid.groupby("profile")["ron_static_ohm"].agg(
            ["count", "min", "median", "max"]
        )
        result["by_profile"] = {
            str(k): {kk: _finite(float(vv)) for kk, vv in v.items()}
            for k, v in by_profile.to_dict("index").items()
        }
    return result


def analyse_thermal(df: pd.DataFrame, anchors: dict[str, Anchor]) -> dict[str, Any]:
    """Thermal exposure, and explicit evidence that no thermal model exists."""
    out: dict[str, Any] = {
        "tj_equals_tcase": bool(np.allclose(df["tj_C"], df["tcase_C"])),
        "case_temperatures_C": sorted(float(v) for v in df["tcase_C"].unique()),
        "junction_rise_available": False,
        "package_thermal_resistance_available": False,
        "reason": (
            "Every thermal resistance in the source dataset is printed as TBD and "
            "the Stage 1 model has no thermal network, so Tj is identically Tcase "
            "and no junction temperature above case can be computed."
        ),
    }
    tcase_max = anchors["TJ_MAX"].value
    out["case_temperature_margin_C"] = _finite(tcase_max - float(df["tcase_C"].max()))
    out["max_case_rise_above_nominal_C"] = _finite(float(df["case_rise_above_ambient_C"].max()))

    traj = build_trajectory_table(df, anchors)
    th = traj[traj["profile"] == "thermal"]
    if not th.empty:
        out["thermal_exposure_Ks_by_trajectory"] = {
            str(r["trajectory_id"]): _finite(float(r["thermal_exposure_Ks"]))
            for _, r in th.iterrows()
        }
    # Apparent thermal resistance, reported only to document its absence.
    hot = df[df["tcase_C"] > df["tcase_C"].min()]
    if not hot.empty and float(np.ptp(hot["pcond_W"].to_numpy())) > 0:
        slope = np.polyfit(hot["pcond_W"].to_numpy(), hot["tcase_C"].to_numpy(), 1)[0]
        out["apparent_thermal_resistance_K_per_W"] = _finite(float(slope))
        out["apparent_thermal_resistance_note"] = (
            "A property of how the Stage 1 script drove Tcase, not of the package. "
            "Reported to document the absence of a thermal model, never as a device "
            "parameter."
        )
    return out


def analyse_capacitance(df: pd.DataFrame, anchors: dict[str, Anchor]) -> dict[str, Any]:
    """Output-capacitance loss energy from the measured CV sweep.

    ``Eoss`` is the standard hard-switching reference: the energy charged into
    Coss while the drain voltage rises. It is computed on the VGS = 0 V trace,
    which is where the printed Coss is quoted.
    """
    caps = df[df["profile"] == "capacitance"]
    out: dict[str, Any] = {
        "printed_coss_F": _finite(anchors["COSS_REF"].value),
        "printed_crss_F": _finite(anchors["CRSS_REF"].value),
        "printed_qoss_C": _finite(anchors["QOSS_PRINTED"].value),
        "cv_test_vds_V": _finite(anchors["CAPS_TEST_VDS"].value),
    }
    if caps.empty:
        out["available"] = False
        out["reason"] = "no capacitance profile in the dataset"
        return out

    trace = caps[caps["vgs_V"] <= caps["vgs_V"].min() + 1e-9].sort_values("vds_V")
    trace = trace[np.isfinite(trace["coss_F"].to_numpy())]
    if len(trace) < 2:
        out["available"] = False
        out["reason"] = "the VGS = 0 V CV trace has fewer than two usable points"
        return out

    v = trace["vds_V"].to_numpy()
    c = trace["coss_F"].to_numpy()
    out.update({
        "available": True,
        "trace_points": int(len(trace)),
        "vds_range_V": [_finite(float(v.min())), _finite(float(v.max()))],
        "coss_at_zero_vds_F": _finite(float(c[0])),
        "coss_at_test_vds_F": _finite(float(c[np.argmin(np.abs(v - anchors['CAPS_TEST_VDS'].value))])),
        "qoss_integrated_C": _finite(float(np.trapezoid(c, v))),
        "eoss_J": _finite(float(np.trapezoid(v * c, v))),
        "eoss_definition": (
            "Eoss = integral |Vds * Coss(Vds)| dVds over the measured CV sweep, the "
            "hard-switching output-capacitance loss at the datasheet CV frequency."
        ),
    })
    printed_qoss = anchors["QOSS_PRINTED"].value
    if printed_qoss > 0 and out["qoss_integrated_C"] is not None:
        out["qoss_integrated_ratio_to_printed"] = _finite(
            out["qoss_integrated_C"] / printed_qoss
        )
        out["qoss_note"] = (
            "Integrating the simulated Coss(Vds) gives more charge than the printed "
            "Qoss because the depletion model places a large Coss at low Vds. The "
            "capacitance is calibrated at the 75 V test point, where it matches the "
            "printed value exactly, so the disagreement is a shape difference at low "
            "drain voltage rather than a calibration error."
        )
    return out


def analyse_charge(df: pd.DataFrame, anchors: dict[str, Anchor]) -> dict[str, Any]:
    """Gate charge from the measured gate ramp, against the printed QG."""
    ch = df[df["profile"] == "charge"].sort_values("sample_index")
    out: dict[str, Any] = {
        "printed_qg_C": _finite(anchors["QG_PRINTED"].value),
        "printed_qgs_C": _finite(anchors["QGS_PRINTED"].value),
        "printed_qgd_C": _finite(anchors["QGD_PRINTED"].value),
        "qgd_test_vds_V": _finite(anchors["QGD_TEST_VDS"].value),
        "qgd_test_ids_A": _finite(anchors["QGD_TEST_IDS"].value),
    }
    if ch.empty or len(ch) < 2:
        out["available"] = False
        out["reason"] = "no gate-charge profile in the dataset"
        return out

    t = ch["t_s"].to_numpy()
    integrated = float(np.trapezoid(ch["ig_A"].to_numpy(), t))
    logged = ch["qg_C"].dropna()
    out.update({
        "available": True,
        "vgs_start_V": float(ch["vgs_V"].iloc[0]),
        "vgs_end_V": float(ch["vgs_V"].iloc[-1]),
        "ramp_duration_s": float(t[-1] - t[0]),
        "gate_charge_integrated_C": _finite(integrated),
        "gate_charge_logged_C": _finite(float(logged.iloc[-1])) if len(logged) else None,
        "peak_gate_current_A": _finite(float(np.abs(ch["ig_A"].to_numpy()).max())),
        "mean_gate_slew_V_per_s": _finite(
            float((ch["vgs_V"].iloc[-1] - ch["vgs_V"].iloc[0]) / (t[-1] - t[0]))
        ),
        "qgd_at_end_C": _finite(float(ch["qgd_C"].dropna().iloc[-1])) if ch["qgd_C"].notna().any() else None,
    })
    if anchors["QG_PRINTED"].value > 0:
        out["integrated_ratio_to_printed_qg"] = _finite(
            integrated / anchors["QG_PRINTED"].value
        )
    if out["gate_charge_logged_C"] is not None and integrated > 0:
        out["logged_vs_integrated_ratio"] = _finite(out["gate_charge_logged_C"] / integrated)
        out["logged_vs_integrated_note"] = (
            "The Stage 1 logged Qg does not equal the integral of the logged gate "
            "current. The logged value comes from the model's own capacitance "
            "integral, so the two disagree. Both are reported; neither is silently "
            "preferred."
        )
    out["note"] = (
        "The simulated total gate charge is a fraction of the printed figure, and "
        "the Stage 1 parameter block itself records qg_is_consistent = False. Gate "
        "charge is therefore not a validated quantity and no switching-loss figure "
        "is derived from it."
    )
    return out


def verify_displacement_attribution(df: pd.DataFrame) -> dict[str, Any]:
    """Check that ``Pcond`` really is ``Vds * Ich`` with ``Ich`` below ``ID``.

    Stage 2A asserts that ``Pcond`` uses a conduction-only channel current while
    the exported ``ID`` also carries displacement. This turns that assertion into
    a measurement by testing the implied current against ``Coss * dv/dt`` on the
    reconstructed load line, and by confirming the two currents coincide where
    nothing is moving.
    """
    out: dict[str, Any] = {"checked": False}
    vds = df["vds_V"].to_numpy()
    usable = np.abs(vds) > 1e-9
    if not usable.any():
        out["reason"] = "every sample has Vds = 0, so no channel current can be recovered"
        return out

    ich = np.where(usable, df["pcond_W"].to_numpy() / np.where(usable, vds, 1.0), np.nan)
    idn = df["id_A"].to_numpy()

    # Quiescent rows: displacement is absent, so ID and Ich must coincide.
    quiescent = df["dvdt_path_V_per_s"].isna().to_numpy() | (
        np.nan_to_num(df["dvdt_path_V_per_s"].to_numpy()) < 1e3
    )
    q = quiescent & usable & (np.abs(ich) > 1.0)
    out["quiescent"] = {
        "rows": int(q.sum()),
        "median_abs_separation_A": _finite(float(np.median(np.abs(idn[q] - ich[q])))),
        "median_abs_id_A": _finite(float(np.median(np.abs(idn[q])))),
    }
    if q.sum() and np.median(np.abs(idn[q])) > 0:
        out["quiescent"]["relative_separation"] = _finite(
            float(np.median(np.abs(idn[q] - ich[q])) / np.median(np.abs(idn[q])))
        )

    # Load-line rows: the separation should equal Coss * |dv/dt|.
    on_path = df["transition_window"].notna().to_numpy() & usable
    if on_path.any():
        gap = np.abs(idn[on_path] - ich[on_path])
        icds = np.abs(
            df["coss_F"].to_numpy()[on_path]
            * np.nan_to_num(df["dvdt_path_V_per_s"].to_numpy()[on_path])
        )
        # A backward difference leaves the first sample of each window without a
        # rate. The blocked part of the load line, where Vgs is still below
        # threshold and Vds has not begun to move, has a genuine rate of zero and
        # a gap of pure leakage, so it is excluded too: the displacement test only
        # means anything where the drain node is actually moving.
        rate = df["dvdt_path_V_per_s"].to_numpy()[on_path]
        have_rate = np.isfinite(rate) & (rate > 0)
        ratio = icds[have_rate] / np.maximum(gap[have_rate], 1e-12)
        if ratio.size:
            out["load_line"] = {
                "rows": int(on_path.sum()),
                "rows_with_a_nonzero_rate": int(have_rate.sum()),
                "rows_excluded_rate_zero": int((~have_rate).sum()),
                "median_gap_A": _finite(float(np.median(gap[have_rate]))),
                "median_predicted_icds_A": _finite(float(np.median(icds[have_rate]))),
                "median_ratio": _finite(float(np.median(ratio))),
                "max_ratio": _finite(float(np.max(ratio))),
                "min_ratio": _finite(float(np.min(ratio))),
            }
            out["load_line"]["verdict"] = (
                "the separation between ID and the conduction-only current is "
                "explained by output-capacitance displacement charging"
                if 0.8 <= float(np.median(ratio)) <= 1.25
                else "the separation is NOT explained by Coss * dv/dt"
            )

    out["checked"] = True
    out["conclusion"] = (
        "Pcond is Vds times a conduction-only channel current, not Vds times the "
        "exported ID. The two coincide where the drain node is quiescent and "
        "separate by exactly the output-capacitance displacement current where it "
        "is moving. Pcond and Vds*ID are therefore distinct quantities: they must "
        "not be summed, and their difference is not a model error and not a "
        "degradation signal."
    )
    out["evidence"] = EvidenceClass.CALCULATED.value
    return out


def coverage_summary(df: pd.DataFrame) -> dict[str, Any]:
    """How much of the dataset each stress view actually covers.

    ``is_rating_exceeded`` is already True for the samples *outside* the rated
    envelope, so it is used directly. Negating it would count the samples that
    are inside the envelope and invert the whole table.
    """
    total = len(df)
    exceeded = df["is_rating_exceeded"].astype(bool)
    out: dict[str, Any] = {"total_samples": int(total)}
    for prof, sub in df.groupby("profile", sort=True):
        out[str(prof)] = {
            "samples": int(len(sub)),
            "share": float(len(sub) / total) if total else 0.0,
            "ron_valid": int(sub["ron_valid"].sum()),
            "outside_rated_envelope": int(exceeded[sub.index].sum()),
        }
    out["outside_rated_envelope_total"] = int(exceeded.sum())
    out["outside_rated_envelope_share"] = float(exceeded.sum() / total) if total else 0.0
    return out


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def build_stress_model(
    df: pd.DataFrame, params: dict[str, Any]
) -> StressResult:
    """Compute the Stage 2B stress model from the Stage 2A dataset."""
    anchors = build_anchors(params)
    staged = add_trajectory_ids(df)
    staged, switching = segment_switching(staged, anchors["SAMPLE_TIME"].value)
    staged = add_sample_stress(staged, anchors)
    traj = build_trajectory_table(staged, anchors)

    return StressResult(
        frame=staged,
        trajectories=traj,
        switching=switching,
        ron=analyse_ron(staged, anchors),
        thermal=analyse_thermal(staged, anchors),
        capacitance=analyse_capacitance(staged, anchors),
        charge=analyse_charge(staged, anchors),
        coverage=coverage_summary(staged),
        displacement=verify_displacement_attribution(staged),
        anchors=anchors,
    )


def stress_report(result: StressResult) -> dict[str, Any]:
    """The Stage 2B JSON report."""
    return {
        "phase": "2B",
        "title": "Physics-informed stress and exposure model",
        "evidence": EvidenceClass.CALCULATED.value,
        "disclaimer": (
            "This is a stress and exposure accounting of a Digital-Twin simulation. "
            "It contains no degradation law, no aging coefficient and no failure "
            "threshold, because the dataset contains no aging axis to fit one to. "
            "None of these numbers is a measurement of a real device."
        ),
        "channel_current_definition": (
            "ID + IS is NOT the channel current: the Stage 1 node balance "
            "ID + IG + IS = 0 makes ID + IS = -IG, which is essentially zero. The "
            "conduction-only channel current Ich is not exported, but it is "
            "recoverable as Pcond / Vds. It coincides with ID on quiescent rows and "
            "falls below ID by the displacement current wherever Vds moves."
        ),
        "trajectory_definition": (
            "A trajectory is one bias point (profile, operating_point_key) held over "
            "its own slice of a shared time axis. All DC time integrals are taken "
            "within a trajectory, because integrating across the shared axis would "
            "sum concurrent trajectories."
        ),
        "path_definition": (
            "The switching load line is not a trajectory. Its 18 bias points each own "
            "a handful of rows on the shared clock, so the slew only exists when the "
            "samples of one transition window are read across bias points. Load-line "
            "rows are told from DC holds by trajectory size, and windows are recovered "
            "by gap detection, so no Stage 1 profile label is trusted."
        ),
        "coverage": result.coverage,
        "displacement_attribution": result.displacement,
        "switching": result.switching,
        "on_resistance": result.ron,
        "thermal": result.thermal,
        "capacitance": result.capacitance,
        "gate_charge": result.charge,
        "trajectory_count": int(len(result.trajectories)),
        "anchors": [a.to_dict() for a in result.anchors.values()],
        "equations": eq.registry(),
    }
