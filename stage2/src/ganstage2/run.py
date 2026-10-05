"""Entry point: ``python -m ganstage2.run``.

Runs the Phase 2A pipeline, the Phase 2B stress model and the Phase 2C exposure
indicators, writing every artefact under ``stage2/output/``. Exits non-zero if a
structural check fails outright, so it can gate a later phase.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import Stage2Config
from .dataset import build_dataset, write_artifacts
from .indicators import build_indicators, indicator_report
from .indicators_report import render as render_indicators
from .indicators_report import write_artifacts as write_indicator_artifacts
from .ingestion import load_stage1
from .report import render
from .stress import build_stress_model
from .stress_report import render as render_stress
from .stress_report import write_artifacts as write_stress_artifacts

#: Output files, in the order they are written, for lock diagnostics.
_ARTEFACTS = ("dataset", "manifest", "quality report", "report")


def _write(path: Path, label: str, action) -> Path:
    """Run *action*, turning a file lock into an actionable message.

    A permission error here is almost never a pipeline fault; it is a viewer
    holding the previous artefact open, and the raw ``PermissionError`` says
    nothing useful about that.
    """
    try:
        action()
    except PermissionError as exc:
        raise SystemExit(
            f"error: cannot write the {label} at {path}\n"
            f"         {LOCKED}"
        ) from exc
    return path


def main(argv: list[str] | None = None) -> int:
    del argv
    cfg = Stage2Config()

    print("Stage 2")
    print(f"  Stage 1 root : {cfg.stage1_root}")
    print(f"  Output dir   : {cfg.output_dir}")
    print()
    print("Phase 2A - dataset, provenance and physics validation")

    bundle = load_stage1(cfg)
    print(f"  ingested {len(bundle.frame)} samples from {bundle.sources['mat']}")

    parse = bundle.csv_parse
    if parse is not None and parse.is_defective:
        print(
            f"  CSV DEFECT  : {parse.rows_repaired_trailing_delimiter} rows carry a "
            f"surplus trailing field ({parse.header_field_count}-column header). "
            "Repaired in memory; Stage 1 files untouched."
        )
        print("               A default pandas read would mislabel every signal and null Crss.")
    print()

    artifacts = build_dataset(bundle, cfg)

    locked = _locked_output(cfg)
    if locked is not None:
        raise SystemExit(
            f"error: {locked.name} is locked for writing\n"
            f"         at {locked}\n"
            f"         {LOCKED}"
        )

    print("Data quality")
    for check in artifacts.quality.checks:
        print(f"  {check.check_id}  {check.status:<8} {check.name}")
    print()

    print("Physics consistency")
    for check in artifacts.physics_checks:
        print(f"  {check.check_id}  {check.status:<8} {check.name}")
    print()

    report_text = render(artifacts, cfg)

    written = write_artifacts(artifacts, cfg)
    _write(cfg.report_path, "report", lambda: cfg.report_path.write_text(report_text, encoding="utf-8"))

    print("Wrote")
    for label, path in written.items():
        print(f"  {label:<14} {path}")
    print(f"  {'report':<14} {cfg.report_path}")
    print()

    print("Stage 2 Phase 2B")
    print("-" * 70)
    stress = build_stress_model(artifacts.dataset, bundle.mat_params)
    sw = stress.switching
    rv = sw.get("reversibility", {})
    print(f"  trajectories           : {len(stress.trajectories)}")
    print(f"  outside rated envelope : {stress.coverage['outside_rated_envelope_total']} samples "
          f"({100.0 * stress.coverage['outside_rated_envelope_share']:.1f} %)")
    if sw.get("available"):
        print(f"  transitions recovered  : {sw['n_windows']} "
              f"({sw['n_turn_on']} turn-on, {sw['n_turn_off']} turn-off), "
              f"{sw['samples_per_transition']} samples each")
        print(f"  load line reversible   : {rv.get('load_line_is_reversible')} "
              f"(max relative asymmetry {rv.get('max_relative_asymmetry')})")
        print(f"  switching loss         : NOT AVAILABLE - "
              f"{'reversible path, no Coss channel' if rv.get('load_line_is_reversible') else 'see report'}")
    ll = stress.displacement.get("load_line", {})
    if ll:
        print(f"  displacement check     : Coss*|dv/dt| / (ID - Pcond/Vds) median "
              f"{ll.get('median_ratio')}, range {ll.get('min_ratio')} to {ll.get('max_ratio')}")
    spec = stress.ron["at_spec_point"]
    print(f"  RON at datasheet point : {spec['ron_ohm']} ohm "
          f"(ratio to printed typical {spec['ratio_to_typ']:.4f})")
    print(f"  temperature-normalised : "
          f"{'unavailable (model RON has no T dependence)' if stress.ron['temperature_normalisation_is_identity'] else 'available'}")
    print()

    stress_text = render_stress(stress, cfg)
    stress_written = write_stress_artifacts(stress, cfg)
    _write(cfg.stress_report_path, "stress report",
           lambda: cfg.stress_report_path.write_text(stress_text, encoding="utf-8"))

    print("Wrote")
    for label, path in stress_written.items():
        print(f"  {label:<18} {path}")
    print(f"  {'stress report':<18} {cfg.stress_report_path}")
    print()

    print("Stage 2 Phase 2C - exposure indicators")
    print("-" * 70)
    indicators = build_indicators(stress)
    rep = indicator_report(stress, indicators)
    print(f"  indicators available  : {rep['available_count']} of {rep['indicator_count']}")
    print(f"  indicators blocked    : {rep['blocked_count']}")
    print(f"  health states claimed : 0 (no aging axis, repeats or labels exist)")
    leak = rep["leakage_diagnostic"]
    if leak.get("available"):
        print(f"  leakage temp. coeff.  : {leak['coefficient_per_C']:.3e} /degC "
              f"(ratio {leak['leakage_ratio_high_over_low']:.4f} over "
              f"{leak['span_C']:.0f} degC)")
    print()

    indicator_text = render_indicators(stress, indicators)
    indicator_written = write_indicator_artifacts(stress, indicators, cfg)
    _write(cfg.indicators_report_path, "indicators report",
           lambda: cfg.indicators_report_path.write_text(indicator_text, encoding="utf-8"))

    print("Wrote")
    for label, path in indicator_written.items():
        print(f"  {label:<18} {path}")
    print(f"  {'indicators report':<18} {cfg.indicators_report_path}")
    print()

    counts = artifacts.quality.counts
    print(f"Quality   : {counts}")
    blockers = sorted(set(artifacts.manifest["blockers"]))
    if blockers:
        print(f"Blockers  : {', '.join(blockers)}")
        print("           These are dataset limitations, not pipeline errors. They bound")
        print("           what Phases 2B and 2C can legitimately claim.")
    return 0


LOCKED = (
    "another program holds it open, commonly a spreadsheet viewing the dataset.\n"
    "         Close the file and re-run; nothing else needs to change."
)


def _locked_output(cfg: Stage2Config) -> Path | None:
    """The first output file that cannot be written, if any.

    Checked before any write so a lock cannot leave the run half-applied with
    some artefacts refreshed and others stale. A permission error here is almost
    never a pipeline fault; the raw ``PermissionError`` just says nothing useful.
    """
    for path in (cfg.dataset_path, cfg.manifest_path, cfg.quality_path, cfg.report_path,
                 cfg.stress_dataset_path, cfg.stress_trajectories_path,
                 cfg.stress_json_path, cfg.stress_report_path,
                 cfg.indicators_path, cfg.indicators_json_path,
                 cfg.trajectory_indicators_path, cfg.indicators_report_path):
        if not path.exists():
            continue
        try:
            handle = os.open(path, os.O_WRONLY)
        except PermissionError:
            return path
        else:
            os.close(handle)
    return None


if __name__ == "__main__":
    sys.exit(main())
