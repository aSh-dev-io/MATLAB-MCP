"""Rendering and writing of the Phase 2B stress artefacts.

The JSON report is the machine-readable record and the Markdown report is the
human-readable one. They are generated from the same
:func:`~ganstage2.stress.stress_report` payload, so they cannot disagree.

The Markdown renderer escapes pipes in every cell. A table row containing an
unescaped ``|`` shifts every column to its right, which silently corrupts a
report while leaving the file syntactically valid, so escaping is centralised
here rather than left to each call site.
"""

from __future__ import annotations

from typing import Any

from .config import Stage2Config
from .dataset import _atomic_write_csv, _atomic_write_json
from .stress import StressResult, stress_report

#: Stress columns appended in Phase 2B, with the unit or meaning of each.
STRESS_COLUMNS: tuple[tuple[str, str], ...] = (
    ("trajectory_id", "profile::operating_point_key; one independent bias point"),
    ("transition_window", "int; reconstructed switching transition, NA for DC rows"),
    ("transition_kind", "turn_on | turn_off; NA for DC rows"),
    ("vgs_gate_window_utilisation", "ratio; |Vgs| against the sign-selected gate limit"),
    ("id_pulse_rating_utilisation", "ratio; |ID| / 840 A pulse rating"),
    ("case_rise_above_ambient_C", "degC; Tcase - 25 degC"),
    ("junction_rating_utilisation", "ratio; Tj / 150 degC, equals the case ratio"),
    ("conduction_power_rating_product_ratio", "ratio; |Pcond| / (115 A * 150 V)"),
    ("conduction_loss_share", "fraction; Pcond / Ploss"),
    ("dvdt_path_V_per_s", "V/s; along the transition path, else the trajectory"),
    ("didt_path_A_per_s", "A/s; along the transition path, else the trajectory"),
    ("rating_exceedance_count", "int; printed limits exceeded by this sample"),
)


def _cell(value: Any) -> str:
    """Render one table cell, escaping pipes and normalising empty values."""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value != value:  # NaN
            return "n/a"
        if value == 0.0:
            return "0"
        if abs(value) < 1e-3 or abs(value) >= 1e5:
            return f"{value:.4e}"
        return f"{value:.6g}"
    text = str(value)
    return text.replace("|", r"\|") if "|" in text else text


def _sentence(text: str) -> str:
    """Capitalise a status fragment so it reads as a sentence in prose."""
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    """A GitHub-flavoured Markdown table with every cell escaped."""
    out = ["| " + " | ".join(_cell(h) for h in headers) + " |"]
    out.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        out.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return out


def _wrap(text: str, indent: str = "", width: int = 92) -> list[str]:
    """Wrap prose to a fixed width so the raw file stays readable."""
    import textwrap

    return textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=indent) or [indent]


def render(result: StressResult, cfg: Stage2Config) -> str:
    """Render the Phase 2B Markdown report."""
    rep = stress_report(result)
    sw = rep["switching"]
    disp = rep["displacement_attribution"]
    ron = rep["on_resistance"]
    th = rep["thermal"]
    cap = rep["capacitance"]
    ch = rep["gate_charge"]
    add = rep["coverage"]

    L: list[str] = []
    add_line = L.append

    add_line("# Phase 2B - Physics-informed stress and exposure model")
    add_line("")
    add_line("## Scope and what this report is not")
    add_line("")
    add_line(
        "This report is a stress and exposure accounting of a Digital-Twin simulation. "
        "It is not a degradation assessment, because the dataset contains no aging axis, "
        "no repeated measurement and no experimental health label. No degradation law, "
        "aging coefficient, failure threshold or remaining-useful-life figure appears "
        "anywhere in Phase 2, and none could be supported by these inputs. None of the "
        "numbers below is a measurement of a real device."
    )
    add_line("")
    # Emitted as its own paragraph starting with a capital so the required
    # sentence appears verbatim and is greppable in the rendered file.
    add_line(
        "This framework currently provides physics-informed stress/degradation "
        "assessment based on the available device and Digital-Twin data. "
        "Experimental aging data is required to validate a true degradation-"
        "prediction model."
    )
    add_line("")

    add_line("## Two definitional corrections that affect every number below")
    add_line("")
    add_line("### The channel current is not `ID + IS`")
    add_line("")
    for line in _wrap(rep["channel_current_definition"]):
        add_line(line)
    add_line("")
    add_line("### `Pcond` is not `Vds * ID`")
    add_line("")
    for line in _wrap(disp["conclusion"] if disp.get("checked") else "not checked"):
        add_line(line)
    add_line("")
    if disp.get("checked") and disp.get("load_line"):
        ll = disp["load_line"]
        q = disp.get("quiescent", {})
        L.extend(_table(
            ["Where", "Rows", "Separation `abs(ID - Ich)` (A)", "`Coss*abs(dv/dt)` predicts (A)", "Ratio"],
            [
                [
                    "quiescent rows",
                    q.get("rows"),
                    # Left as numbers so _cell can shorten them; pre-formatting
                    # into an f-string here would defeat that and print 17 digits.
                    q.get("median_abs_separation_A"),
                    "n/a, the drain node is not moving",
                    q.get("relative_separation"),
                ],
                [
                    "switching load line",
                    ll.get("rows_with_a_nonzero_rate"),
                    ll.get("median_gap_A"),
                    ll.get("median_predicted_icds_A"),
                    ll.get("median_ratio"),
                ],
            ],
        ))
        add_line("")
        add_line(
            f"Verdict: {ll.get('verdict')}. On the load line the ratio stays between "
            f"{ll.get('min_ratio'):.6f} and {ll.get('max_ratio'):.6f} across every row "
            "tested, so the displacement attribution is tight rather than merely plausible."
        )
        add_line("")
        add_line(
            "The load line is excluded where the rate is zero: the segment with Vgs still "
            "below threshold has Vds pinned at 100 V, so there is no displacement current "
            "and the residual gap there is pure leakage."
        )
        add_line("")

    add_line("## Data structure: trajectories and paths")
    add_line("")
    for line in _wrap(rep["trajectory_definition"]):
        add_line(line)
    add_line("")
    for line in _wrap(rep["path_definition"]):
        add_line(line)
    add_line("")
    add_line(
        f"The dataset resolves into {rep['trajectory_count']} trajectories. Because Stage 1 "
        "placed several independent trajectories on one shared monotonic clock, integrating "
        "over a whole profile would add concurrent trajectories together and produce a number "
        "with no physical meaning."
    )
    add_line("")

    add_line("## Coverage and rated-envelope exceedance")
    add_line("")
    L.extend(_table(
        ["Profile", "Samples", "Share", "RON-valid", "Outside rated envelope"],
        [
            [
                prof,
                info["samples"],
                f"{100.0 * info['share']:.2f} %",
                info["ron_valid"],
                info["outside_rated_envelope"],
            ]
            for prof, info in add.items()
            if isinstance(info, dict)
        ]
        + [[
            "**total**",
            add["total_samples"],
            "100.00 %",
            sum(i["ron_valid"] for i in add.values() if isinstance(i, dict)),
            f"{add['outside_rated_envelope_total']} ({100.0 * add['outside_rated_envelope_share']:.1f} %)",
        ]],
    ))
    add_line("")
    add_line(
        f"Exceedance is dominated by the characterisation profiles rather than by "
        "operation: the thermal sweep exceeds its rating on almost every sample and the "
        "C-V and gate-charge sweeps drive the drain and gate terminals hard purely to bias "
        "a measurement. The transfer profile, which stays inside the envelope throughout, "
        "is the sweep that actually characterises on-resistance. A pooled exceedance count "
        "therefore says little about stress in service."
    )
    add_line("")

    add_line("## Switching transitions")
    add_line("")
    if not sw.get("available"):
        add_line(f"Unavailable: {sw.get('reason')}")
        add_line("")
    else:
        L.extend(_table(
            ["Quantity", "Value"],
            [
                ["transition windows recovered", sw["n_windows"]],
                ["turn-on / turn-off", f"{sw['n_turn_on']} / {sw['n_turn_off']}"],
                ["load-line bias points", sw["load_line_bias_points"]],
                ["DC hold bias points", sw["dc_hold_bias_points"]],
                ["samples per transition",
                 f"{sw['samples_per_transition']} in each of the {sw['n_windows']} windows"
                 + ("" if len(sw["samples_per_transition_all"]) == 1
                    else f" (lengths vary: {sw['samples_per_transition_all']})")],
                ["solver sample interval", f"{1e9 * sw['solver_sample_interval_s']:.2f} ns"],
                ["mean turn-on path integral", f"{1e6 * sw['mean_turn_on_energy_J']:.3f} uJ"],
                ["mean turn-off path integral", f"{1e6 * sw['mean_turn_off_energy_J']:.3f} uJ"],
                ["spread across windows", f"{1e6 * sw['transition_energy_spread_J']:.2e} uJ"],
                ["**switching loss available**", "**no**"],
            ],
        ))
        add_line("")
        add_line("### Why switching loss is not available")
        add_line("")
        for line in _wrap(sw["switching_loss_unavailable_reason"]):
            add_line(line)
        add_line("")
        add_line("### Reversibility test")
        add_line("")
        rv = sw.get("reversibility", {})
        if rv:
            L.extend(_table(
                ["Test", "Result"],
                [
                    ["turn-off is the reverse of turn-on", rv.get("load_line_is_reversible")],
                    ["max relative asymmetry", rv.get("max_relative_asymmetry")],
                    ["all cycles bit-identical", rv.get("cycles_bit_identical")],
                    ["max cycle-to-cycle difference", f"{rv.get('max_cycle_difference_W')} W"],                ],
            ))
            add_line("")
            for line in _wrap(rv.get("interpretation", "")):
                add_line(line)
            add_line("")
            for line in _wrap(rv.get("cycle_identity_note", "")):
                add_line(line)
            add_line("")
        add_line("### How these transitions must be read")
        add_line("")
        for key in ("path_integral_note", "resolution_caveat", "incomplete_evidence",
                    "excitation_representativeness"):
            if sw.get(key):
                for line in _wrap(sw[key]):
                    add_line(line)
                add_line("")

        add_line("### Per-transition detail")
        add_line("")
        L.extend(_table(
            ["#", "Kind", "Samples", "Vgs start->end (V)", "Vds start->end (V)",
             "Peak `|ID|` (A)", "Peak loss (W)", "Path integral (uJ)", "Peak `|dv/dt|` (V/s)"],
            [
                [
                    w["window"], w["kind"], w["samples"],
                    f"{w['vgs_start_V']:.3f} -> {w['vgs_end_V']:.3f}",
                    f"{w['vds_start_V']:.2f} -> {w['vds_end_V']:.2f}",
                    f"{w['peak_id_A']:.1f}",
                    f"{w['peak_ploss_W']:.1f}",
                    f"{1e6 * (w['transition_energy_J'] or 0.0):.3f}",
                    f"{w['peak_dvdt_V_per_s']:.3e}" if w["peak_dvdt_V_per_s"] else "n/a",
                ]
                for w in sw["windows"]
            ],
        ))
        add_line("")
        add_line(
            "The path-integral column is **not** a switching loss and must not be compared "
            "with a datasheet switching-energy figure or multiplied by a switching frequency."
        )
        add_line("")

    add_line("## On-resistance against the datasheet")
    add_line("")
    spec = ron["spec_point"]
    L.extend(_table(
        ["Quantity", "Value"],
        [
            ["printed test condition", f"Vgs = {spec['vgs_V']} V, IDS = {spec['ids_A']} A, VDS = {spec['vds_V']} V"],
            ["printed RDS(on) typical / max", f"{spec['rds_on_typ_ohm']} / {spec['rds_on_max_ohm']} ohm"],
            ["nearest simulated sample", f"{ron['at_spec_point']['profile']} profile, Vgs = {ron['at_spec_point']['vgs_V']} V, Vds = {ron['at_spec_point']['vds_V']} V, ID = {ron['at_spec_point']['id_A']:.2f} A"],
            ["RON there", f"{1e3 * ron['at_spec_point']['ron_ohm']:.4f} mohm"],
            ["ratio to printed typical", ron["at_spec_point"]["ratio_to_typ"]],
            ["margin to printed maximum", ron["at_spec_point"]["margin_ratio_to_max"]],
            ["verdict", ron["at_spec_point"]["verdict"]],
            ["RON-valid samples", f"{ron['valid_samples']} of {ron['total_samples']} ({100.0 * ron['valid_fraction']:.2f} %)"],
        ],
    ))
    add_line("")
    add_line(
        "This is the single point in the whole project where the Digital Twin is compared "
        "with a measured datasheet number, so it is evaluated exactly at the printed test "
        "condition rather than at a convenient nearby bias."
    )
    add_line("")
    add_line("### Temperature dependence")
    add_line("")
    tc = ron["temperature_coefficient"]
    if tc.get("available"):
        L.extend(_table(
            ["Quantity", "Value"],
            [
                ["matched bias points", tc["matched_bias_points"]],
                ["RON(125 degC)/RON(25 degC), min / median / max",
                 f"{tc['ron_ratio_high_over_low_min']:.9f} / "
                 f"{tc['ron_ratio_high_over_low_median']:.9f} / "
                 f"{tc['ron_ratio_high_over_low_max']:.9f}"],
                ["fitted coefficient", f"{tc['coefficient_per_C']:.3e} /degC"],
                ["temperature normalisation is the identity", ron["temperature_normalisation_is_identity"]],
            ],
        ))
        add_line("")
        for line in _wrap(tc.get("interpretation", "")):
            add_line(line)
        add_line("")
    if tc.get("normalisation_status"):
        for line in _wrap(_sentence(tc["normalisation_status"])):
            add_line(line)
        add_line("")

    add_line("## Thermal exposure")
    add_line("")
    L.extend(_table(
        ["Quantity", "Value"],
        [
            ["Tj equals Tcase", th["tj_equals_tcase"]],
            ["case temperatures present", ", ".join(
                f"{c:g}" for c in th["case_temperatures_C"]) + " degC"],
            ["junction rise above case available", th["junction_rise_available"]],
            ["package thermal resistance available", th["package_thermal_resistance_available"]],
            ["margin to printed Tj max", f"{th['case_temperature_margin_C']} degC"],
            ["max case rise above nominal", f"{th['max_case_rise_above_nominal_C']} degC"],
        ],
    ))
    add_line("")
    for line in _wrap(th["reason"]):
        add_line(line)
    add_line("")
    if th.get("apparent_thermal_resistance_K_per_W") is not None:
        add_line(
            f"An apparent thermal resistance of "
            f"{th['apparent_thermal_resistance_K_per_W']:.2e} K/W can be fitted to the "
            "thermal profile, but it is reported only to document the absence of a "
            "thermal model."
        )
        for line in _wrap(th.get("apparent_thermal_resistance_note", "")):
            add_line(line)
        add_line("")

    add_line("## Capacitance-derived energy")
    add_line("")
    if not cap.get("available"):
        add_line(f"Unavailable: {cap.get('reason')}")
    else:
        L.extend(_table(
            ["Quantity", "Value", "Note"],
            [
                # F -> pF is a factor of 1e12.
                ["printed Coss / Crss", f"{1e12 * cap['printed_coss_F']:.0f} pF / {1e12 * cap['printed_crss_F']:.1f} pF", "datasheet"],
                ["CV test Vds", f"{cap['cv_test_vds_V']} V", "datasheet"],
                ["Coss at 0 V / at the test point", f"{1e12 * cap['coss_at_zero_vds_F']:.0f} pF / {1e12 * cap['coss_at_test_vds_F']:.0f} pF", "simulated"],
                ["integrated Qoss", f"{1e9 * cap['qoss_integrated_C']:.2f} nC", f"printed Qoss is {1e9 * cap['printed_qoss_C']:.2f} nC"],
                ["Eoss", f"{1e6 * cap['eoss_J']:.3f} uJ", cap["eoss_definition"]],
            ],
        ))
        add_line("")
        if cap.get("qoss_note"):
            for line in _wrap(cap["qoss_note"]):
                add_line(line)
            add_line("")
        add_line(
            "This Eoss is the direct evidence that the switching integrals are incomplete: a "
            "hard-switched turn-on must charge Coss, and none of this energy appears in the "
            "transition path integrals."
        )
        add_line("")

    add_line("## Gate charge")
    add_line("")
    if not ch.get("available"):
        add_line(f"Unavailable: {ch.get('reason')}")
    else:
        L.extend(_table(
            ["Quantity", "Value"],
            [
                ["printed QG / QGS / QGD", f"{1e9 * ch['printed_qg_C']:.2f} / {1e9 * ch['printed_qgs_C']:.2f} / {1e9 * ch['printed_qgd_C']:.2f} nC"],
                ["gate ramp", f"{ch['vgs_start_V']} V to {ch['vgs_end_V']} V over {1e9 * ch['ramp_duration_s']:.2f} ns"],
                ["integrated gate charge", f"{1e9 * ch['gate_charge_integrated_C']:.3f} nC"],
                ["Stage 1 logged Qg", f"{1e9 * ch['gate_charge_logged_C']:.3f} nC"],
                ["integrated / printed QG", ch.get("integrated_ratio_to_printed_qg")],
                ["logged / integrated", ch.get("logged_vs_integrated_ratio")],
                ["peak gate current", f"{ch['peak_gate_current_A']:.1f} A"],
            ],
        ))
        add_line("")
        for key in ("logged_vs_integrated_note", "note"):
            if ch.get(key):
                for line in _wrap(ch[key]):
                    add_line(line)
                add_line("")

    add_line("## Quantities this phase refuses to compute")
    add_line("")
    for b in rep["equations"]["blocked_quantities"]:
        add_line(f"**{b['quantity']}**")
        add_line("")
        for line in _wrap(b["reason"], indent="  "):
            add_line(line)
        add_line("")

    add_line("## Column provenance for Phase 2B additions")
    add_line("")
    L.extend(_table(["Column", "Unit / meaning"], [[c, u] for c, u in STRESS_COLUMNS]))
    add_line("")
    add_line(
        "The Phase 2A columns `vds_rating_utilisation`, `vgs_rating_utilisation`, "
        "`id_continuous_rating_utilisation` and `is_rating_exceeded` are reused unchanged. "
        "The gate-drive ratio here is a separate column because the printed gate window is "
        "asymmetric (+6 V / -4 V) and the Stage 2A ratio uses the positive limit for both signs."
    )
    add_line("")

    add_line("## Reference anchors")
    add_line("")
    L.extend(_table(
        ["Anchor", "Value", "Unit", "Provenance", "Usable"],
        [
            [a["key"], a["value"], a["unit"], a["evidence"], a["usable"]]
            for a in rep["anchors"]
        ],
    ))
    add_line("")
    unusable = [a["key"] for a in rep["anchors"] if not a["usable"]]
    if unusable:
        add_line(
            f"Unusable anchors: {', '.join(unusable)}. Every value above is carried with its "
            "source, so a reader can tell a printed datasheet rating from a value solved out "
            "of the dataset or from an assumption."
        )
        add_line("")
    add_line(f"Generated by `ganstage2.stress` from {cfg.mat_path.name}; see `equations.py` for all {len(rep['equations']['equations'])} registered equations.")
    add_line("")
    return "\n".join(L)


def write_artifacts(result: StressResult, cfg: Stage2Config) -> dict[str, str]:
    """Write the Phase 2B CSV and JSON artefacts. Returns label -> path."""
    _atomic_write_csv(result.frame, cfg.stress_dataset_path)
    _atomic_write_csv(result.trajectories, cfg.stress_trajectories_path)
    _atomic_write_json(stress_report(result), cfg.stress_json_path)
    return {
        "stress dataset": str(cfg.stress_dataset_path),
        "trajectories": str(cfg.stress_trajectories_path),
        "stress json": str(cfg.stress_json_path),
    }
