"""Quality-report and dataset-assembly tests."""

from __future__ import annotations

import re

import numpy as np
import pytest

from ganstage2.config import Stage2Config


def test_csv_defect_is_reported_as_a_failure(artifacts):
    by_id = {c.check_id: c for c in artifacts.quality.checks}
    assert by_id["Q04"].status == "FAIL"
    assert by_id["Q04"].severity == "HIGH"
    assert "trailing delimiter" in by_id["Q04"].detail


def test_repaired_csv_agrees_with_mat(artifacts):
    by_id = {c.check_id: c for c in artifacts.quality.checks}
    assert by_id["Q05"].status == "PASS"


def test_csv_cross_check_covers_every_numeric_signal(artifacts, cfg: Stage2Config):
    """Guards against the cross-check silently narrowing to a few columns.

    The CSV uses MATLAB identifiers while the pipeline uses canonical names, so
    a name mismatch once made this check compare only `t_s` and still pass.
    """
    by_id = {c.check_id: c for c in artifacts.quality.checks}
    expected = len([1 for _, unit in cfg.schema if unit != "categorical"])
    assert f"across {expected} numeric signals" in by_id["Q05"].detail


def test_no_aging_axis_is_recorded_as_a_blocker(artifacts):
    by_id = {c.check_id: c for c in artifacts.quality.checks}
    assert by_id["Q15"].status == "BLOCKED"
    assert by_id["Q15"].severity == "BLOCKER"


def test_no_infinite_values(artifacts):
    import numpy as np

    numeric = [c for c, u in Stage2Config().schema if u != "categorical"]
    for column in numeric:
        assert not np.isinf(artifacts.dataset[column].to_numpy(float)).any()


def test_time_is_monotonic_within_each_profile(artifacts):
    df = artifacts.dataset
    for _, block in df.groupby("profile"):
        t = block["t_s"].to_numpy(float)
        assert (np.diff(t) > 0).all()


def test_sampling_interval_matches_solver(artifacts, bundle):
    declared = float(bundle.mat_params["solver.sample_time_s"])
    df = artifacts.dataset
    for _, block in df.groupby("profile"):
        dt = np.diff(block["t_s"].to_numpy(float))
        assert np.allclose(dt, declared, rtol=1e-9, atol=0)


def test_json_summary_agrees_with_mat(artifacts):
    by_id = {c.check_id: c for c in artifacts.quality.checks}
    assert by_id["Q11"].status == "PASS"
    assert by_id["Q12"].status == "PASS"


def test_stage1_dataset_defects_are_carried_forward(artifacts):
    """Guards a bug that reported zero defects for a file that records four.

    MATLAB stores a logical as a tagged uint8, so decoding by dtype turned
    ``true`` into the string ``"\\x01"`` and every bool test failed.
    """
    by_id = {c.check_id: c for c in artifacts.quality.checks}
    q13 = by_id["Q13"]
    assert q13.affected == 4
    for defect in ("curves_absent", "qg_not_sum_of_parts", "qgd_test_condition", "thermal_absent"):
        assert defect in q13.detail


def test_manifest_carries_the_defects_as_structured_data(artifacts):
    """A flattened-key lookup returns {}, which reads as 'no defects recorded'."""
    defects = artifacts.manifest["evidence"]["dataset_defects"]
    assert defects, "dataset_defects must be re-nested, not left as an empty dict"
    assert defects["curves_absent"] is True
    assert "QG" in defects["qg_detail"]


def test_every_row_carries_provenance(artifacts):
    df = artifacts.dataset
    assert (df["evidence_class"] == "calculated_from_stage1_simulation").all()
    assert df["has_experimental_validation"].eq(False).all()
    assert df["is_aging_measurement"].eq(False).all()


def test_operating_point_keys_are_populated(artifacts):
    df = artifacts.dataset
    assert df["operating_point_key"].notna().all()
    assert (df["operating_point_key"].str.count(r"\|") == 2).all()
    # Thermal profile is the only one sweeping two temperatures.
    thermal = df[df["profile"] == "thermal"]
    assert thermal["operating_point_key"].nunique() == 2 * thermal["vgs_V"].nunique() * len(
        sorted(thermal["vds_V"].unique())
    )


def test_operating_points_group_repeated_bias_conditions(artifacts):
    """Requirement 1: like-for-like comparison needs a stable grouping key."""
    df = artifacts.dataset
    counts = df.groupby("operating_point_key").size()
    assert counts.max() > 1, "expected repeated samples at identical conditions"
    key = counts.idxmax()
    block = df[df["operating_point_key"] == key]
    assert block["vgs_V"].nunique() == 1
    assert block["tcase_C"].nunique() == 1


def test_manifest_declares_scope_and_blockers(artifacts):
    m = artifacts.manifest
    assert m["stage"] == "2A"
    for excluded in ("degradation modelling", "remaining useful life", "dashboard"):
        assert excluded in m["not_in_scope"]
    assert m["blockers"], "Phase 2A must surface the dataset limitations it hit"
    assert m["evidence"]["has_experimental_validation"] is False
    assert m["evidence"]["is_aging_measurement"] is False


def test_manifest_documents_every_threshold(artifacts):
    m = artifacts.manifest
    assert m["analysis_conventions"]
    assert m["tolerances"]
    for group in (m["analysis_conventions"], m["tolerances"]):
        for entry in group.values():
            assert entry["justification"].strip(), "every threshold needs a justification"


def test_no_degradation_or_health_columns_exist(artifacts):
    """Guards against scope creep into Phase 2B."""
    forbidden = ("health", "degradation", "rul", "remaining_life", "wear", "age_h")
    for column in artifacts.dataset.columns:
        assert not any(token in column.lower() for token in forbidden), column


def test_artifact_writes_land_only_under_output(cfg: Stage2Config, artifacts):
    import tempfile
    from pathlib import Path

    from ganstage2.dataset import write_artifacts
    from ganstage2.report import render

    with tempfile.TemporaryDirectory() as tmp:
        local = Stage2Config(output_dir=Path(tmp))
        written = write_artifacts(artifacts, local)
        local.report_path.write_text(render(artifacts, local), encoding="utf-8")
        for path in [*written.values(), str(local.report_path)]:
            assert Path(path).exists()
            assert Path(path).parent == Path(tmp)


def _is_row(line: str) -> bool:
    return line.startswith("| ") and line.endswith(" |")


def _is_separator(line: str) -> bool:
    return bool(line) and set(line) <= set("| -")


def _bars(line: str) -> int:
    """Unescaped pipe count, which is the rendered column count plus one."""
    return len(re.findall(r"(?<!\\)\|", line))


def test_report_renders_with_real_numbers(artifacts, cfg: Stage2Config):
    from ganstage2.report import render

    text = render(artifacts, cfg)
    assert "# Stage 2 Phase 2A Report" in text
    assert "15904" in text
    assert "MODEL PREDICTION - NOT VALIDATED" in text
    assert "Crss_F" in text
    for section in ("Available signals", "Operating conditions", "Data quality",
                    "Physics consistency", "Gaps and limitations", "Provenance"):
        assert section in text


def test_report_names_the_device_without_printing_none(artifacts, cfg: Stage2Config):
    """Manufacturer lives under p/meta, not the top-level meta group."""
    from ganstage2.report import render

    text = render(artifacts, cfg)
    device_line = next(line for line in text.splitlines() if line.startswith("- Device:"))
    assert "onsemi" in device_line
    assert "NTLEF2D2N15GN1" in device_line
    assert "None" not in device_line


def test_report_tables_are_not_broken_by_raw_pipes(artifacts, cfg: Stage2Config):
    """Units and justifications carry absolute-value bars that end a Markdown cell.

    A raw ``|ID|`` in a unit column silently shifts every column to its right, so
    the schema and threshold tables are checked too, not just the detail tables.
    """
    from ganstage2.report import render

    text = render(artifacts, cfg)
    lines = text.splitlines()

    # A table is a header, a separator, then rows. Escaped pipes must not count
    # toward a row's width, otherwise the check cannot see a real break.
    for i, line in enumerate(lines):
        if not _is_row(line) or not _is_separator(lines[i + 1] if i + 1 < len(lines) else ""):
            continue
        width = _bars(line)
        for row in lines[i + 2 :]:
            if not _is_row(row):
                break
            assert _bars(row) == width, (
                f"table starting {line!r}: row has {_bars(row)} bars, header {width}: {row!r}"
            )

    for expected in (
        "bool; \\|ID\\| >= conduction threshold",
        "vgs\\|vds\\|tcase",
        "ratio; \\|VDS\\| / 150 V",
        "\\|ID\\| >= 100 x I_leak",
        "`vgs`\\|`vds`\\|`tcase`",
    ):
        assert expected in text, f"expected escaped form {expected!r} in the report"


def test_report_lists_the_stage1_dataset_defects(artifacts, cfg: Stage2Config):
    from ganstage2.report import render

    text = render(artifacts, cfg)
    for defect in ("curves_absent", "qg_not_sum_of_parts", "thermal_absent"):
        assert defect in text, f"{defect} should be surfaced in the report"


def test_report_lists_the_assumed_values(artifacts, cfg: Stage2Config):
    """The ASSUMED set is the audit surface and must be enumerable in prose."""
    from ganstage2.report import render

    text = render(artifacts, cfg)
    assert "ASSUMED" in text
    for name in artifacts.manifest["provenance"]["by_tag"]["ASSUMED"]:
        assert f"`{name}`" in text


def test_report_vds_range_is_not_padded_with_float_noise(artifacts, cfg: Stage2Config):
    """Sweep endpoints are exact; only float noise like 149.99999999 needs rounding."""
    from ganstage2.report import render

    seen = 0
    for line in render(artifacts, cfg).splitlines():
        if not line.startswith("| `") or ".." not in line:
            continue
        seen += 1
        cells = [c.strip() for c in line.split("|")]
        for bound in cells[5].split(".."):
            assert re.fullmatch(r"-?\d+(\.\d{1,3})?", bound), f"unrounded Vds bound {bound!r}"
    assert seen == len(artifacts.manifest["profiles"])
