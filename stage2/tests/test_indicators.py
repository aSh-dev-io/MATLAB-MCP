"""Tests for the Phase 2C exposure indicators.

The point of this phase is what it refuses to claim, so the tests are weighted
towards that: that no indicator is a health state, that blocked ones stay
blocked, and that every margin is referenced to a printed limit rather than to a
fitted threshold.
"""

from __future__ import annotations

import json
import math
import re

import numpy as np
import pytest

from ganstage2.evidence import EvidenceClass
from ganstage2.indicators import (
    _INDICATOR_KEYS,
    build_indicators,
    indicator_report,
    indicator_table,
    leakage_temperature_coefficient,
    trajectory_indicators,
)
from ganstage2.indicators_report import render as render_indicators
from ganstage2.stress import build_stress_model


@pytest.fixture(scope="session")
def stress(artifacts, bundle):
    return build_stress_model(artifacts.dataset, bundle.mat_params)


@pytest.fixture(scope="session")
def indicators(stress):
    return build_indicators(stress)


# --------------------------------------------------------------------------
# The central claim: these are exposure indicators, not health indicators
# --------------------------------------------------------------------------

def test_no_indicator_is_a_health_state(indicators):
    for key in _INDICATOR_KEYS:
        rec = indicators[key]
        assert rec["is_health_state"] is False, key
        assert "not a health state" in rec["disclaimer"].lower(), key


def test_report_states_why_no_health_indicator_exists(stress, indicators):
    rep = indicator_report(stress, indicators)
    why = rep["why_no_health_indicators"].lower()
    # The three things a health indicator needs, each explicitly absent.
    assert "aging axis" in why
    assert "repeated measurement" in why
    assert "ground-truth label" in why
    assert rep["required_limitation_statement"].startswith(
        "This framework currently provides"
    )


def test_no_degradation_quantity_is_computed(stress, indicators):
    """Nothing here may be a degradation rate, drift, RUL or health score."""
    payload = json.dumps(indicator_report(stress, indicators))

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                # is_health_state is the guard asserting False, not a claim.
                if k != "is_health_state":
                    assert not re.search(
                        r"degradation|drift|\brul\b|health_score|failure_time|end_of_life",
                        k, re.I,
                    ), f"degradation-shaped key at {path}/{k}"
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(json.loads(payload))


def test_health_related_quantities_are_blocked_not_omitted(stress, indicators):
    """The absence must be on the record, not invisible."""
    rep = indicator_report(stress, indicators)
    blocked = {b["indicator"] for b in rep["blocked_indicators"]}
    # Switching loss cannot be attributed to the device.
    assert "switching_loss_per_cycle" in blocked
    # There is no printed power rating to normalise against.
    assert "power_rating_utilisation" in blocked
    for entry in rep["blocked_indicators"]:
        assert entry["reason"].strip(), entry["indicator"]


def test_switching_loss_indicator_reuses_the_stress_verdict(stress, indicators):
    assert indicators["switching_loss_per_cycle"]["unavailable_reason"] == \
        stress.switching["switching_loss_unavailable_reason"]


# --------------------------------------------------------------------------
# Margins reference printed limits only
# --------------------------------------------------------------------------

def test_every_available_margin_names_a_printed_limit(indicators):
    for key in _INDICATOR_KEYS:
        rec = indicators[key]
        if not rec["available"] or rec["margin_to_limit"] is None:
            continue
        assert rec["threshold_basis"], key
        assert "printed" in rec["threshold_basis"].lower(), key


def test_margins_are_consistent_with_their_values(indicators):
    """margin = 1 - utilisation, so a ratio above 1 must give a negative margin."""
    for key, util in (
        ("vds_rating_utilisation_max", "vds_rating_utilisation_max"),
        ("junction_temperature_utilisation_max", "junction_temperature_utilisation_max"),
        ("outside_rated_envelope_fraction", "outside_rated_envelope_fraction"),
    ):
        rec = indicators[key]
        if not rec["available"]:
            continue
        assert rec["margin_to_limit"] == pytest.approx(1.0 - rec["value"]), key


def test_ron_headroom_uses_percentile_not_the_triode_maximum(stress, indicators):
    """The worst-case RON is a triode artefact and must not be the indicator."""
    rec = indicators["ron_p99_to_printed_max"]
    rds_max = stress.anchors["RDS_ON_MAX"].value
    values = stress.frame.loc[stress.frame["ron_valid"], "ron_stage1_ohm"].to_numpy(float)

    assert rec["value"] == pytest.approx(np.nanpercentile(values, 99))
    assert rec["margin_to_limit"] == pytest.approx(1.0 - rec["value"] / rds_max)
    assert str(rds_max) in rec["threshold_basis"]

    # The raw maximum is larger still, and is reported as a diagnostic instead.
    ron = indicators["_diagnostics"]["ron"]
    assert ron["max_ohm"] > rec["value"]
    assert ron["max_profile"] == "transfer"
    assert ron["max_vds_V"] == pytest.approx(0.08)
    assert ron["max_to_printed_max"] == pytest.approx(ron["max_ohm"] / rds_max)
    assert "triode" in ron["note"]


def test_utilisation_indicators_can_exceed_one(indicators):
    """A utilisation above 1 is the point: the stimulus overdrives the ratings."""
    assert indicators["id_continuous_rating_utilisation_max"]["value"] > 1.0
    assert indicators["id_pulse_rating_utilisation_max"]["value"] > 1.0
    # The interpretation must attribute the exceedance to the excitation and
    # explicitly deny that it says anything about the device's condition.
    text = indicators["id_continuous_rating_utilisation_max"]["interpretation"].lower()
    assert "excitation" in text
    assert "says nothing about whether the device degraded" in text


def test_current_rating_basis_names_the_printed_ratings(stress, indicators):
    """The pulse indicator must not claim the continuous rating as its basis."""
    assert str(stress.anchors["ID_CONTINUOUS_25C"].value) in \
        indicators["id_continuous_rating_utilisation_max"]["threshold_basis"]
    assert str(stress.anchors["ID_PULSE_25C"].value) in \
        indicators["id_pulse_rating_utilisation_max"]["threshold_basis"]


# --------------------------------------------------------------------------
# The leakage temperature indicator
# --------------------------------------------------------------------------

def test_leakage_coefficient_is_measured_from_the_dataset(stress, indicators):
    rec = indicators["leakage_temperature_coefficient_per_C"]
    assert rec["available"] is True
    assert rec["evidence"] == EvidenceClass.DATASET_DERIVED.value

    leak = indicators["_diagnostics"]["leakage"]
    assert leak["matched_bias_points"] > 0
    assert leak["span_C"] == 100.0
    # coefficient = (ratio - 1) / span
    assert leak["coefficient_per_C"] == pytest.approx(
        (leak["leakage_ratio_high_over_low"] - 1.0) / leak["span_C"]
    )


def test_leakage_measurement_reproduces_the_declared_law(stress, indicators):
    leak = indicators["_diagnostics"]["leakage"]
    declared = stress.anchors["LEAK_TEMP_RATIO"].value
    assert leak["model_declared_ratio"] == pytest.approx(declared)
    # The whole point of measuring rather than restating: the two agree.
    assert leak["ratio_relative_error"] < 1e-9
    # And it is uniform across bias, which a fitted artefact would not be.
    assert leak["leakage_ratio_min"] == pytest.approx(leak["leakage_ratio_max"])


def test_leakage_indicator_refuses_when_bias_is_not_repeated(artifacts, stress):
    """Dropping the elevated-temperature rows must block it, not crash it."""
    single_temp = artifacts.dataset[artifacts.dataset["tcase_C"] == 25.0]
    out = leakage_temperature_coefficient(single_temp, stress.anchors)
    assert out["available"] is False
    assert "temperature" in out["reason"]


# --------------------------------------------------------------------------
# Table and artefact shape
# --------------------------------------------------------------------------

def test_indicator_table_covers_every_indicator(indicators):
    table = indicator_table(indicators)
    assert list(table["indicator"]) == list(_INDICATOR_KEYS)
    assert table["is_health_state"].eq(False).all()
    # A blocked indicator must still carry its reason.
    for _, row in table[~table["available"]].iterrows():
        assert str(row["unavailable_reason"]).strip(), row["indicator"]


def test_trajectory_indicators_match_the_stress_trajectories(stress):
    traj = trajectory_indicators(stress)
    assert len(traj) == len(stress.trajectories)
    assert traj["trajectory_id"].is_unique
    assert traj["samples"].sum() == len(stress.frame)


def test_trajectory_indicators_carry_no_class_or_label(stress):
    """Labelling trajectories by exposure is one step from labelling by health."""
    traj = trajectory_indicators(stress)
    for col in traj.columns:
        assert not re.search(r"class|label|band|grade|state|health|status", col, re.I), col


def test_indicator_report_is_json_serialisable(stress, indicators):
    payload = indicator_report(stress, indicators)
    # allow_nan=False is the real check: it rejects any NaN or infinity *value*.
    text = json.dumps(payload, allow_nan=False)
    assert json.loads(text)["phase"] == "2C"

    def numbers(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from numbers(v)
        elif isinstance(node, list):
            for v in node:
                yield from numbers(v)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            yield node

    for value in numbers(payload):
        assert math.isfinite(value), value


def test_render_leads_with_what_the_indicators_are_not(stress, indicators):
    text = render_indicators(stress, indicators)
    assert text.startswith("# Phase 2C")
    # The disclaimer must appear before any indicator table.
    assert text.index("not a health state") < text.index("| Indicator |")
    assert "UNAVAILABLE" in text


def test_render_tables_are_aligned(stress, indicators):
    text = render_indicators(stress, indicators)
    lines = text.split("\n")
    checked = 0
    for i, line in enumerate(lines):
        if line.startswith("|") and i + 1 < len(lines) and re.fullmatch(
            r"\|(\s*---\s*\|)+", lines[i + 1].strip()
        ):
            width = len(re.split(r"(?<!\\)\|", line.strip())) - 2
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                checked += 1
                assert len(re.split(r"(?<!\\)\|", lines[j].strip())) - 2 == width, \
                    f"line {j + 1} has the wrong cell count"
                j += 1
    assert checked > 0


def test_render_has_no_python_repr_sentinels(stress, indicators):
    text = render_indicators(stress, indicators)
    cells = [c.strip() for line in text.split("\n") if line.startswith("|")
             for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
    for cell in cells:
        assert cell not in {"None", "nan", "NaN", "NoneType"}, repr(cell)
        assert not cell.startswith("[") and not cell.startswith("{"), repr(cell)
    assert not re.search(r"\d\.\d{10,}", text)
