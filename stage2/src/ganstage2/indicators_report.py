"""Rendering and writing of the Phase 2C exposure-indicator artefacts.

Reuses the Phase 2B table helpers so both reports escape and format values
identically. The renderer leads with what these indicators are *not*, because the
single most likely misuse of this file is to read a utilisation ratio as a
health score.
"""

from __future__ import annotations

from typing import Any

from .config import Stage2Config
from .dataset import _atomic_write_csv, _atomic_write_json
from .indicators import (
    build_indicators,
    indicator_report,
    indicator_table,
    trajectory_indicators,
)
from .stress import StressResult
from .stress_report import _cell, _sentence, _table, _wrap

_INDICATOR_ORDER = (
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


def _value_cell(rec: dict[str, Any]) -> str:
    """Render an indicator value with its unit, or the blocked marker."""
    if not rec["available"]:
        return "UNAVAILABLE"
    value = rec["value"]
    if isinstance(value, (int, float)):
        return f"{_cell(value)} {rec['unit']}".strip()
    return str(value)


def render(result: StressResult, indicators: dict[str, Any]) -> str:
    """Render the Phase 2C Markdown report."""
    rep = indicator_report(result, indicators)
    L: list[str] = []
    add = L.append

    add("# Phase 2C - Exposure indicators")
    add("")
    add("## What this is not")
    add("")
    for line in _wrap(rep["not_a_health_assessment"]):
        add(line)
    add("")
    add("### Why no health indicator is produced")
    add("")
    for line in _wrap(rep["why_no_health_indicators"]):
        add(line)
    add("")
    add(rep["required_limitation_statement"])
    add("")

    add("## The indicator set")
    add("")
    add(
        f"{rep['available_count']} of {rep['indicator_count']} indicators are computable "
        "from this dataset. Each answers a question about the *stimulus* relative to "
        "the printed ratings. None answers a question about the device's condition."
    )
    add("")
    L.extend(_table(
        ["Indicator", "Value", "Margin to limit", "Limit it is measured against", "Evidence"],
        [
            [
                rec["label"],
                _value_cell(rec),
                _cell(rec["margin_to_limit"]) if rec["available"] else "n/a",
                rec["threshold_basis"] or "n/a",
                rec["evidence"],
            ]
            for rec in (indicators[k] for k in _INDICATOR_ORDER)
        ],
    ))
    add("")
    add(
        "Every row above carries `is_health_state = false` in the JSON and CSV. A "
        "utilisation above 1 means the simulated stimulus drove a terminal past its "
        "printed limit; it is a property of the excitation, not evidence of damage."
    )
    add("")

    add("## Margins are to printed limits, never to fitted thresholds")
    add("")
    add(
        "A degradation model would introduce a threshold fitted to observed drift and "
        "call everything beyond it degraded. No such threshold exists here, and "
        "inventing one is exactly the failure this project rules forbid. Every margin "
        "above is therefore referenced to a number printed on the datasheet, which can "
        "be checked independently."
    )
    add("")

    add("### On-resistance needs care")
    add("")
    ron = rep["ron_diagnostic"]
    if ron.get("available"):
        add(
            "RDS(on) is specified at a single bias, so it is the one indicator where a "
            "swept statistic can mislead. The full conduction set gives these values:"
        )
        add("")
        L.extend(_table(
            ["Statistic", "Value", "Against the printed maximum"],
            [
                ["median", f"{ron['median_ohm']:.4g} ohm", f"{ron['median_ohm'] / result.anchors['RDS_ON_MAX'].value:.3f} x"],
                ["99th percentile", f"{ron['p99_ohm']:.4g} ohm", f"{ron['p99_ohm'] / result.anchors['RDS_ON_MAX'].value:.3f} x"],
                ["maximum", f"{ron['max_ohm']:.4g} ohm", f"{ron['max_to_printed_max']:.1f} x"],
            ],
        ))
        add("")
        add(
            f"The maximum sits in the **{ron['max_profile']}** profile at "
            f"VDS = {ron['max_vds_V']:g} V, where the device is not fully enhanced. "
            "The ratio VDS/ID there is a triode-region quantity, not the datasheet "
            "RDS(on), and using it as a worst-case resistance margin would overstate "
            "the margin loss by more than an order of magnitude. The headroom "
            "indicator therefore uses the 99th percentile and the maximum is reported "
            "only as a diagnostic."
        )
    else:
        add(f"Unavailable: {ron.get('reason')}")
    add("")

    add("## The one usable temperature indicator")
    add("")
    leak = rep["leakage_diagnostic"]
    if leak.get("available"):
        L.extend(_table(
            ["Quantity", "Value"],
            [
                ["case temperatures", ", ".join(f"{t:g}" for t in leak["case_temperatures_C"]) + " degC"],
                ["matched bias points", leak["matched_bias_points"]],
                ["leakage ratio high/low", _cell(leak["leakage_ratio_high_over_low"])],
                ["ratio spread across bias", f"{leak['leakage_ratio_min']:.4f} to {leak['leakage_ratio_max']:.4f}"],
                ["fitted coefficient", f"{leak['coefficient_per_C']:.3e} /degC"],
                ["Stage 1 declared ratio", _cell(leak["model_declared_ratio"])],
                ["relative error", _cell(leak["ratio_relative_error"])],
            ],
        ))
        add("")
        for line in _wrap(f"Method: {leak['method']}."):
            add(line)
        add("")
        for line in _wrap(leak["note"]):
            add(line)
        add("")
    else:
        add(f"Unavailable: {leak.get('reason')}")
    add("")

    add("## Indicators that are refused")
    add("")
    add(
        "These are returned as blocked rather than omitted, so the absence is on the "
        "record instead of looking like an oversight."
    )
    add("")
    for entry in rep["blocked_indicators"]:
        add(f"**{entry['indicator']}**")
        add("")
        for line in _wrap(_sentence(entry["reason"] or ""), indent="  "):
            add(line)
        add("")

    add("## Per-trajectory exposure")
    add("")
    add(
        f"`exposure_by_trajectory.csv` holds one row per bias point "
        f"({rep['trajectory_count']} trajectories) with its peak current, peak loss, "
        "integrated conduction and Miller energy, thermal exposure and cumulative "
        "utilisation, so a consumer can rank trajectories by exposure without "
        "re-deriving the integrals."
    )
    add("")
    add(
        "No exposure class, band or label is assigned. Ranking trajectories by "
        "exposure is one short step from ranking them by health, and that step is not "
        "supported by this data."
    )
    add("")

    add("## Column provenance")
    add("")
    L.extend(_table(
        ["File", "Contents"],
        [
            ["`exposure_indicators.csv`", "one row per indicator, with value, unit, evidence, margin and blocked reason"],
            ["`exposure_indicators.json`", "the same set with full interpretations and the leakage diagnostic"],
            ["`exposure_by_trajectory.csv`", "one row per trajectory with its exposure integrals"],
        ],
    ))
    add("")
    return "\n".join(L)


def write_artifacts(
    result: StressResult, indicators: dict[str, Any], cfg: Stage2Config
) -> dict[str, str]:
    """Write the Phase 2C artefacts. Returns label -> path."""
    _atomic_write_csv(indicator_table(indicators), cfg.indicators_path)
    _atomic_write_csv(trajectory_indicators(result), cfg.trajectory_indicators_path)
    _atomic_write_json(indicator_report(result, indicators), cfg.indicators_json_path)
    return {
        "indicators": str(cfg.indicators_path),
        "indicators json": str(cfg.indicators_json_path),
        "trajectory exposure": str(cfg.trajectory_indicators_path),
    }


__all__ = [
    "build_indicators",
    "indicator_report",
    "indicator_table",
    "render",
    "trajectory_indicators",
    "write_artifacts",
]
