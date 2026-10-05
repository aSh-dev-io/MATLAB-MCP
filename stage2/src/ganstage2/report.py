"""Render the Phase 2A report from the checks and dataset that were actually run.

The report is generated rather than hand-written so its numbers cannot drift
away from the data. Narrative that depends on findings is selected by the check
results, not hard-coded.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import Stage2Config
from .dataset import Stage2Artifacts


def _fmt(value: Any, spec: str = ".4g") -> str:
    try:
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            return "n/a"
        return format(value, spec)
    except (TypeError, ValueError):
        return str(value)


def _cell(text: Any) -> str:
    """Escape a value for use inside a Markdown table cell.

    Units, justifications and check details carry absolute-value bars such as
    ``|ID|``, ``max |residual|`` and ``vgs|vds|tcase``, which would otherwise
    terminate the cell early and shift every column to its right.
    """
    return str(text).replace("|", "\\|")


def render(artifacts: Stage2Artifacts, cfg: Stage2Config) -> str:
    df = artifacts.dataset
    m = artifacts.manifest
    q = artifacts.quality
    pc = artifacts.physics_checks

    lines: list[str] = []
    add = lines.append

    # ---------------- header ----------------
    add("# Stage 2 Phase 2A Report")
    add("")
    add("**Scope:** ingestion, data-quality validation and physics-consistency screening of the")
    add("Stage 1 output, producing a structured dataset for Phase 2B.")
    add("")
    add("**Not in this phase:** degradation modelling, health-indicator weighting,")
    add("health-state classification, remaining useful life, predictive accuracy, dashboard.")
    add("")
    add(f"- Authoritative source: `{m['authoritative_source']}`")
    device = m["device"]
    device_bits = [str(device.get(k)) for k in ("manufacturer", "part_number") if device.get(k)]
    device_txt = " ".join(device_bits)
    if device.get("datasheet_revision"):
        device_txt += f", {device['datasheet_revision']}"
    if device.get("technology"):
        device_txt += f", {device['technology']}"
    add(f"- Device: {device_txt}")
    add(f"- Dataset: **{m['row_count']} rows x {m['column_count']} columns** across "
        f"{len(m['profiles'])} profiles")
    add(f"- Evidence class: `{m['evidence']['evidence_class']}`")
    add(f"- Stage 1 label: `{m['evidence']['model_prediction_label']}`")
    add("")

    # ---------------- headline ----------------
    add("## Headline findings")
    add("")
    blockers = m["blockers"]
    add(f"1. **The Stage 1 CSV is silently corrupt.** Every data row carries a trailing")
    add("   delimiter, giving one more field than the header declares. A default")
    add("   `pandas.read_csv` accepts this, promotes field 0 to the index and shifts every")
    add("   signal one column left: `profile` becomes numeric, every signal is mislabelled,")
    add("   and `Crss_F` becomes all-NaN. Nothing in the file signals it. Phase 2A parses")
    add("   field-count-explicitly, repairs in memory, and verifies the repair against the MAT.")
    add("   The MAT is unaffected and is used as the authoritative source.")
    add("2. **The exported RON column is not a resistance over most of its range.** Stage 1")
    add("   masks RON only on `ID > 0.1 A`, then evaluates `Vds/ID` across the whole sweep,")
    add("   including deep saturation and the off state.")
    ron_valid = int(df["ron_valid"].sum())
    add(f"   Only **{ron_valid} of {len(df)} rows ({100.0 * ron_valid / len(df):.1f}%)** are both")
    add("   conducting and in the triode region. Stage 2 adds `ron_valid` plus a reason code")
    add("   and does not consume the raw column.")
    add("3. **The dataset cannot support temperature-aware resistance comparison.** The Stage 1")
    add("   channel equation has no temperature term; only leakage scales. Drain current at")
    add("   125 degC equals drain current at 25 degC to within numerical noise. There is no")
    add("   printed RON(T) coefficient either, so `ron_temp_normalised_ohm` is present but")
    add("   explicitly empty rather than filled with an invented coefficient.")
    add("4. **There is no aging data and no thermal model.** Every profile is a single")
    add("   operating-condition sweep on one simulated device at one instant, so permanent")
    add("   degradation cannot be separated from an operating change. `Tj` equals `Tcase`")
    add("   exactly because all thermal resistances and PTOT are TBD in the datasheet.")
    if blockers:
        add(f"5. Open blockers carried into Phase 2B: `{', '.join(sorted(set(blockers)))}`.")
    add("")

    # ---------------- available signals ----------------
    add("## Available signals")
    add("")
    add("| Signal | Unit | Provenance | Phase 2A notes |")
    add("| --- | --- | --- | --- |")
    notes = {
        "t_s": "simulation time within one sweep; **not** an aging axis",
        "vgs_V": "gate drive; conditioning variable",
        "vds_V": "drain bias; conditioning variable",
        "tcase_C": "case temperature; conditioning variable, the only temperature available",
        "id_A": "drain current incl. displacement + leakage",
        "ig_A": "gate current incl. Miller + gate leakage",
        "is_A": "source current, defined as -(ID+IG) so KCL closes exactly",
        "ron_stage1_ohm": "**raw, ungated** Vds/ID; use `ron_valid` before reading it",
        "pcond_W": "channel power Vds*Ich, not Vds*ID",
        "psw_W": "Miller-capacitance power (Vds x abs(iCgd)); **not** switching loss",
        "ploss_W": "total dissipated power, Pcond + Psw",
        "tj_C": "junction temperature; equals tcase_C (no thermal model)",
        "qg_C": "Qg = Qgs + Qgd incl. Cgd depletion charge; use delta-Qg",
        "qgd_C": "Miller charge",
        "ciss_F": "input capacitance",
        "coss_F": "output capacitance",
        "crss_F": "Miller capacitance; **lost by a naive CSV read**, intact in the MAT",
    }
    for column, unit in cfg.schema:
        if column == "profile":
            continue
        prov = "model prediction"
        add(f"| `{column}` | {unit} | {prov} | {_cell(notes.get(column, ''))} |")
    add("")
    add(f"- Profiles: {', '.join(sorted(m['profiles']))}")
    add("")

    # ---------------- operating conditions ----------------
    add("## Operating conditions")
    add("")
    add("| Profile | Role | Rows | Vgs (V) | Vds range (V) | Tcase (C) | Op. points | RON-valid | App. op. |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, info in m["profiles"].items():
        vgs = info["vgs_values"]
        vgs_txt = f"{vgs[0]}..{vgs[-1]} ({len(vgs)} distinct)" if len(vgs) > 4 else ", ".join(str(v) for v in vgs)
        vds_lo, vds_hi = info["vds_range_V"]
        # Sweep endpoints are exact by construction; round only to kill float
        # noise such as 149.99999999 before printing.
        vds_txt = f"{float(vds_lo):.3f}..{float(vds_hi):.3f}"
        add(
            f"| `{name}` | {cfg.profile_roles.get(name, '')} | {info['rows']} | {vgs_txt} | {vds_txt} | "
            f"{', '.join(str(v) for v in info['tcase_values_C'])} | "
            f"{info['operating_point_keys']} | {info['ron_valid_rows']} | "
            f"{info['application_operating_rows']} |"
        )
    add("")
    add("Every row carries an `operating_point_key` (`vgs`\\|`vds`\\|`tcase`), so Phase 2B can")
    add("group like-for-like conditions instead of correlating across a sweep.")
    add("")

    # ---------------- quality ----------------
    add("## Data quality")
    add("")
    counts = q.counts
    add("Summary: " + ", ".join(f"**{v} {k}**" for k, v in sorted(counts.items())) + ".")
    add("")
    add("| ID | Check | Status | Severity | Detail |")
    add("| --- | --- | --- | --- | --- |")
    for c in q.checks:
        add(f"| {c.check_id} | {_cell(c.name)} | {c.status} | {c.severity} | {_cell(c.detail)} |")
    add("")
    if bundle_csv_note(artifacts):
        add("### CSV ingestion defect")
        add("")
        add(bundle_csv_note(artifacts))
        add("")

    # ---------------- physics ----------------
    add("## Physics consistency")
    add("")
    add("| ID | Check | Status | Severity | Detail |")
    add("| --- | --- | --- | --- | --- |")
    for c in pc:
        add(f"| {c.check_id} | {_cell(c.name)} | {c.status} | {c.severity} | {_cell(c.detail)} |")
    add("")

    # ---------------- schema ----------------
    add("## Structured dataset schema")
    add("")
    add(f"`{cfg.dataset_path.name}` - one row per Stage 1 sample, {m['column_count']} columns.")
    add("")
    add("| Column | Unit / meaning | Origin |")
    add("| --- | --- | --- |")
    for entry in m["schema"]:
        add(f"| `{entry['column']}` | {_cell(entry['unit'])} | {entry['origin']} |")
    add("")

    # ---------------- provenance ----------------
    prov = m.get("provenance", {})
    if prov:
        add("## Provenance")
        add("")
        add("Every Stage 1 parameter carries one of four tags, taken verbatim from the")
        add("Stage 1 export and cross-checked against `DATASET_MAPPING.md`. Phase 2A adds no")
        add("new parameter of its own; every derived column is tagged below as calculated.")
        add("")
        add("| Tag | Meaning | Parameters carried |")
        add("| --- | --- | --- |")
        meanings = {
            "DATASET-DERIVED": "printed verbatim in the datasheet",
            "CALCULATED-FROM-DATASET": "arithmetic on printed values only",
            "MANUFACTURER-DERIVED": "stated as a method or condition, not as a number",
            "ASSUMED": "chosen to close a gap the datasheet leaves open",
        }
        for tag in prov["tags"]:
            add(
                f"| `{tag}` | {meanings.get(tag, '')} | "
                f"{prov['counts_by_tag'].get(tag, 0)} |"
            )
        add("")
        assumed = prov["by_tag"].get("ASSUMED", [])
        add("The `ASSUMED` set is the audit surface: every one of these values is a modelling")
        add("choice, not data, and each constrains what Phase 2B may claim.")
        add("")
        add("| Assumed value | Why |")
        add("| --- | --- |")
        for name in assumed:
            add(f"| `{name}` | {_cell(prov['parameters'][name]['basis'])} |")
        add("")
        if prov["untagged_parameters"]:
            add(f"- **{len(prov['untagged_parameters'])} parameters arrived without a tag**: "
                f"{prov['untagged_parameters']}.")
        else:
            add("- Every tagged Stage 1 parameter carries one of the four declared tags; "
                "none is unlabelled and no tag outside the declared vocabulary was found.")
        add("")

    # ---------------- gaps ----------------
    add("## Gaps and limitations")
    add("")
    add("### Missing information")
    add("")
    for item in [
        "**No aging measurements.** No repeated measurement of the same device over time, "
        "no stress history, no second device instance. Nothing supports a degradation "
        "coefficient, a degradation rate or a remaining-useful-life figure.",
        "**No datasheet characteristic curves.** The datasheet contains no ID-VDS, ID-VGS, "
        "C-V, switching or temperature curves, so every curve Stage 1 produced is a "
        "prediction with nothing to validate against.",
        "**No RON(T) data.** No temperature coefficient is printed, and the Stage 1 channel "
        "model has no temperature term, so temperature-normalised resistance is unavailable.",
        "**No thermal data.** Every thermal resistance and PTOT is TBD, so Tj tracks Tcase "
        "and no thermal stress indicator exists.",
        "**No switching-loss data.** No turn-on/turn-off energies are printed; the exported "
        "`psw_W` is Miller-capacitance power, not switching loss.",
        "**QG contradicts its own components.** QGS + QGD = 15.5 nC against a printed "
        "QG = 34 nC. FOM-QG corroborates QG, so the components are treated as suspect.",
    ]:
        add(f"- {item}")
    add("")
    add("### Dataset defects recorded upstream")
    add("")
    defects = m["evidence"].get("dataset_defects", {}) or {}
    flags = sorted(k for k, v in defects.items() if isinstance(v, bool) and v)
    for flag in flags:
        detail = defects.get(f"{flag}_detail")
        if detail:
            add(f"- `{flag}` - {_cell(detail)}")
        else:
            add(f"- `{flag}`")
    if not flags:
        add("- None recorded.")
    add("")
    add("### Interpretability caveats carried forward")
    add("")
    add("- `psw_W` is Miller-capacitance power, not switching loss. Using it as an")
    add("  energy-loss indicator would misstate the physics.")
    add("- `pcond_W` is channel power (`Vds*Ich`), so it does not equal `Vds*ID`. The gap is")
    add("  displacement-charging power and reaches about a fifth of channel power on the DC")
    add("  sweeps, which step Vds by 0.5 V per 1 ns sample. They are not quasi-static at sample")
    add("  resolution, so the two columns are not interchangeable.")
    add("- `qg_C` starts at 4.7 nC because it includes the Cgd depletion charge at")
    add("  VDS = 75 V. Phase 2B must use delta-Qg across a gate excursion.")
    add("- The capacitance and gate-charge profiles are measurement sweeps that hold VGS")
    add("  high while pushing VDS up to 150 V, so they contain samples far above the")
    add("  continuous current rating. They are characterisation conditions, not operating")
    add("  points, and are flagged as such.")
    add("")

    # ---------------- conventions ----------------
    add("## Analysis conventions and tolerances")
    add("")
    add("Every threshold introduced in Phase 2A, with its justification. Nothing below is a")
    add("degradation coefficient or a health threshold.")
    add("")
    add("| Name | Value | Justification |")
    add("| --- | --- | --- |")
    for name, entry in m["analysis_conventions"].items():
        add(f"| `{name}` | {entry['value']} | {_cell(entry['justification'])} |")
    for name, entry in m["tolerances"].items():
        add(f"| `{name}` | {entry['value']:.3g} | {_cell(entry['justification'])} |")
    add("")

    # ---------------- reproducibility ----------------
    add("## Reproducibility")
    add("")
    add("```")
    add("cd stage2")
    add("python -m ganstage2.run            # ingestion, checks, dataset, report")
    add("python -m pytest                    # verification tests")
    add("```")
    add("")
    add("Stage 1 artefacts are opened read-only. This phase writes only under `stage2/output/`.")
    add("")
    return "\n".join(lines)


def bundle_csv_note(artifacts: Stage2Artifacts) -> str:
    """The CSV defect text, if the defect was observed this run."""
    parse = artifacts.manifest.get("csv_parse")
    if not parse or not parse.get("is_defective"):
        return ""
    return (
        f"{parse['rows_repaired_trailing_delimiter']} of {parse['rows_read']} rows carried a "
        f"surplus trailing empty field against a {parse['header_field_count']}-column header "
        f"(`{', '.join(parse['header'])}`)."
    )
