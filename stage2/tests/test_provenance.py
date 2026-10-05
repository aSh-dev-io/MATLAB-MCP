"""Provenance tests.

The project rule is that no model value is invented silently. These tests hold
the provenance ledger to that rule: every Stage 1 parameter must carry one of
the four declared tags, and the tag ledger in ``DATASET_MAPPING.md`` must use
the same vocabulary.
"""

from __future__ import annotations

from pathlib import Path

from ganstage2.provenance import (
    PROVENANCE_TAGS,
    build_provenance_record,
    ledger_from_mapping,
    parameters_from_mat,
    split_tag,
)


def test_four_declared_tags():
    assert PROVENANCE_TAGS == (
        "DATASET-DERIVED",
        "CALCULATED-FROM-DATASET",
        "MANUFACTURER-DERIVED",
        "ASSUMED",
    )


def test_split_tag_separates_tag_from_basis():
    assert split_tag("ASSUMED: no output-conductance data exist") == (
        "ASSUMED",
        "no output-conductance data exist",
    )


def test_split_tag_rejects_an_undeclared_tag():
    """An out-of-vocabulary tag must not be silently accepted as provenance."""
    tag, basis = split_tag("MADE-UP: something invented")
    assert tag == ""
    assert basis == "MADE-UP: something invented"


def test_every_mat_parameter_carries_a_declared_tag(bundle):
    parameters = parameters_from_mat(bundle.mat_params)
    assert parameters, "expected provenance entries in the Stage 1 MAT"
    untagged = [name for name, entry in parameters.items() if not entry["tag"]]
    assert untagged == [], f"parameters arrived without a provenance tag: {untagged}"
    for name, entry in parameters.items():
        assert entry["tag"] in PROVENANCE_TAGS
        assert entry["basis"].strip(), f"{name} has a tag but no stated basis"


def test_provenance_counts_match_the_grouping(bundle):
    record = build_provenance_record(bundle.mat_params, Path("does-not-exist.md"))
    total = sum(record["counts_by_tag"].values())
    assert total == len(record["parameters"])
    assert record["counts_by_tag"]["ASSUMED"] > 0, "the assumed set is the audit surface"


def test_assumed_parameters_are_named(artifacts):
    """Assumptions must be enumerable, not just counted."""
    record = artifacts.manifest["provenance"]
    assumed = record["by_tag"]["ASSUMED"]
    assert "va_V" in assumed, "the assumed output conductance should be listed"
    assert "thermal_model" in assumed
    for name in assumed:
        assert record["parameters"][name]["basis"].strip()


def test_ledger_parses_every_tagged_row(cfg):
    ledger = ledger_from_mapping(cfg.mapping_path)
    assert ledger["present"]
    assert ledger["tagged_rows"] == sum(ledger["tag_occurrences_in_tables"].values())
    assert ledger["tagged_rows"] > 0


def test_ledger_finds_no_undeclared_tags(cfg):
    """A tag outside the four declared ones is the failure the rule prevents."""
    ledger = ledger_from_mapping(cfg.mapping_path)
    assert ledger["unknown_tags"] == {}


def test_ledger_leaves_no_row_untagged(cfg):
    ledger = ledger_from_mapping(cfg.mapping_path)
    assert ledger["untagged_rows"] == []


def test_ledger_locates_the_tag_column_in_both_table_layouts(cfg):
    """Three-column tables put Tag last; four-column ones put it third.

    Guessing a fixed position silently miscounts, and the parameter column of
    the "values the datasheet leaves open" table holds single-token names such
    as `` `PTOT` `` that are syntactically identical to a tag.
    """
    ledger = ledger_from_mapping(cfg.mapping_path)
    counts = ledger["tag_occurrences_in_tables"]
    for tag in PROVENANCE_TAGS:
        assert counts[tag] > 0, f"tag {tag} was never counted, so a column was missed"


def test_ledger_handles_a_missing_file(tmp_path):
    """A missing ledger must degrade to zeros, not remove the keys."""
    ledger = ledger_from_mapping(tmp_path / "absent.md")
    assert ledger["present"] is False
    assert ledger["tagged_rows"] == 0
    assert set(ledger["tag_occurrences_in_tables"]) == set(PROVENANCE_TAGS)
    assert set(ledger["tag_occurrences_in_tables"].values()) == {0}
    assert ledger["unknown_tags"] == {}


def test_manifest_carries_the_provenance_block(artifacts):
    provenance = artifacts.manifest["provenance"]
    assert provenance["tags"] == list(PROVENANCE_TAGS)
    assert provenance["stage2_evidence_class"] == "calculated_from_stage1_simulation"
    assert provenance["mapping_ledger"]["present"] is True
    assert provenance["untagged_parameters"] == []


def test_device_identity_is_not_reported_as_none(artifacts):
    """Manufacturer lives under p/meta, not the top-level meta group."""
    device = artifacts.manifest["device"]
    assert device["manufacturer"] == "onsemi"
    assert device["part_number"] == "NTLEF2D2N15GN1"
    assert "P1" in device["datasheet_revision"]
    for key, value in device.items():
        assert value not in (None, ""), f"device.{key} is empty"
