"""Tests for the Phase 2B stress model.

These cover the properties that, if they broke, would make the report quietly
wrong rather than loudly fail: trajectory and window structure, index integrity,
the reversibility verdict, the displacement attribution, and the promise that
switching loss stays unavailable instead of being estimated from a path that
cannot support it.
"""

from __future__ import annotations

import json
import re

import numpy as np
import pytest

from ganstage2.stress import (
    StressResult,
    build_stress_model,
    coverage_summary,
    segment_switching,
    stress_report,
)
from ganstage2.stress_report import STRESS_COLUMNS
from ganstage2.stress_report import render as render_stress


@pytest.fixture(scope="session")
def stress(artifacts, bundle):
    return build_stress_model(artifacts.dataset, bundle.mat_params)


# --------------------------------------------------------------------------
# Structure: trajectories, windows, index integrity
# --------------------------------------------------------------------------

def test_trajectory_id_is_profile_and_bias_key(stress: StressResult):
    expect = stress.frame["profile"] + "::" + stress.frame["operating_point_key"]
    assert (stress.frame["trajectory_id"].to_numpy() == expect.to_numpy()).all()


def test_trajectory_table_covers_every_row_exactly_once(stress: StressResult):
    traj = stress.trajectories
    assert traj["trajectory_id"].is_unique
    assert traj["samples"].sum() == len(stress.frame)
    counts = stress.frame.groupby("trajectory_id").size()
    assert traj.set_index("trajectory_id")["samples"].sort_index().equals(
        counts.sort_index()
    )


def test_trajectory_numerics_come_only_from_its_own_rows(stress: StressResult):
    """Integration must be per trajectory, not over a shared clock.

    Stage 1 put several trajectories on one monotonic time axis, so a profile-wide
    integral would add concurrent trajectories together.
    """
    traj = stress.trajectories
    one = traj[traj["samples"] > 3].iloc[0]
    sub = stress.frame[stress.frame["trajectory_id"] == one["trajectory_id"]]
    assert sub["t_s"].iloc[0] == pytest.approx(one["start_s"])
    assert sub["t_s"].iloc[-1] == pytest.approx(one["end_s"])
    assert len(sub) == one["samples"]


def test_load_line_rows_are_the_small_trajectories(stress: StressResult):
    """The slew spans bias points, so a single trajectory cannot hold it.

    Conversely the DC holds own thousands of samples each, so trajectory size is
    what separates a load line from a hold.
    """
    traj = stress.trajectories
    switch = traj[traj["profile"] == "switching"]
    load_line = switch[switch["trajectory_id"].isin(
        stress.frame.loc[stress.frame["transition_window"].notna(), "trajectory_id"].unique()
    )]
    holds = switch[~switch["trajectory_id"].isin(load_line["trajectory_id"])]

    assert len(load_line) == stress.switching["load_line_bias_points"]
    assert len(holds) == stress.switching["dc_hold_bias_points"]
    # Every load-line trajectory is short, and every hold is long by orders of
    # magnitude. If this ever inverted, the classification would be arbitrary.
    assert load_line["samples"].max() < holds["samples"].min()


def test_windows_recover_every_load_line_row(stress: StressResult):
    sw = stress.switching
    assert sw["available"] is True
    labelled = stress.frame[stress.frame["transition_window"].notna()]
    rows_per_bias = _rows_per_bias_point(sw)
    assert len(labelled) == sw["n_windows"] * sw["load_line_bias_points"] * rows_per_bias
    assert labelled["transition_window"].nunique() == sw["n_windows"]
    # Turn-on and turn-off must both be present. Labelling direction from a
    # single global endpoint comparison mislabels every window but one.
    counts = labelled["transition_kind"].value_counts().to_dict()
    assert counts == {
        "turn_on": sw["n_turn_on"] * sw["load_line_bias_points"] * rows_per_bias,
        "turn_off": sw["n_turn_off"] * sw["load_line_bias_points"] * rows_per_bias,
    }


def _rows_per_bias_point(sw: dict) -> int:
    return sw["samples_per_transition"] // sw["load_line_bias_points"]


def test_switching_classifies_by_structure_not_profile_label(stress: StressResult):
    """DC holds are told from load-line rows by trajectory size alone."""
    sw = stress.switching
    assert sw["n_windows"] == 6
    assert sw["n_turn_on"] == sw["n_turn_off"] == 3
    assert sw["dc_hold_bias_points"] == 2
    assert sw["load_line_bias_points"] == 18
    for window in sw["windows"]:
        assert window["samples"] == sw["load_line_bias_points"]
        # A transition must actually change the bias; a mislabelled window would
        # show no span.
        assert window["vds_end_V"] != pytest.approx(window["vds_start_V"]) or \
               window["vgs_end_V"] != pytest.approx(window["vgs_start_V"])


def test_switch_profile_rows_are_either_window_or_hold(stress: StressResult):
    switch = stress.frame[stress.frame["profile"] == "switching"]
    in_window = switch["transition_window"].notna()
    holds = switch[~in_window]
    assert len(holds) > 0
    # Everything not in a window is a DC hold: one operating point held constant.
    assert holds["trajectory_id"].nunique() == stress.switching["dc_hold_bias_points"]
    assert holds.groupby("trajectory_id")["vds_V"].nunique().max() == 1


def test_segmentation_preserves_original_index(artifacts):
    """Regression: a reset_index() inside the windowing dropped the row index."""
    df = artifacts.dataset.copy()
    original = df.index.copy()
    out, _sw = segment_switching(df, 1e-9)
    assert out.index.equals(original)
    assert out.index.is_unique
    assert len(out) == len(df)


def test_transition_rows_are_monotonic_in_time(artifacts):
    df = artifacts.dataset
    out, sw = segment_switching(df, 1e-9)
    labelled = out[out["transition_window"].notna()]
    assert sw["available"] is True
    for _window, grp in labelled.groupby("transition_window"):
        assert grp["t_s"].is_monotonic_increasing


def test_segmentation_returns_the_same_summary_as_the_model(stress: StressResult):
    """The standalone function and the model must not drift apart."""
    _out, sw = segment_switching(stress.frame, 1e-9)
    assert sw["n_windows"] == stress.switching["n_windows"]
    assert sw["n_turn_on"] == stress.switching["n_turn_on"]
    assert sw["reversibility"]["load_line_is_reversible"] == \
        stress.switching["reversibility"]["load_line_is_reversible"]


# --------------------------------------------------------------------------
# Switching loss must stay unavailable
# --------------------------------------------------------------------------

def test_switching_loss_is_unavailable(stress: StressResult):
    sw = stress.switching
    assert sw["switching_loss_available"] is False
    reason = sw["switching_loss_unavailable_reason"].lower()
    assert "reversible" in reason
    assert "coss" in reason


def test_load_line_is_reversible(stress: StressResult):
    rv = stress.switching["reversibility"]
    assert rv["load_line_is_reversible"] is True
    # Bit-level reversal, so the asymmetry sits at machine epsilon, not merely
    # small. A loose bound would pass for a merely plausible model.
    assert rv["max_relative_asymmetry"] < 1e-12
    assert rv["cycles_bit_identical"] is True
    assert rv["max_cycle_difference_W"] == 0.0


def test_path_integrals_are_not_labelled_as_switching_loss(stress: StressResult):
    sw = stress_report(stress)["switching"]
    assert "not" in sw["path_integral_note"].lower()
    # The report must never expose Eon/Eoff keys, only path-integral names.
    flat = json.dumps(sw).lower()
    assert '"eon_j"' not in flat
    assert '"e_off_j"' not in flat
    assert '"eoff_j"' not in flat


# --------------------------------------------------------------------------
# Displacement attribution
# --------------------------------------------------------------------------

def test_displacement_attribution_is_tight(stress: StressResult):
    ll = stress.displacement["load_line"]
    assert ll["rows_with_a_nonzero_rate"] > 0
    assert 0.99 < ll["median_ratio"] < 1.01
    assert ll["min_ratio"] > 0.99
    assert ll["max_ratio"] < 1.01


def test_quiescent_rows_show_no_displacement(stress: StressResult):
    q = stress.displacement["quiescent"]
    assert q["rows"] > 0
    # With a static drain node the conduction current and ID coincide, so any
    # residual is leakage and must be negligible.
    assert q["relative_separation"] < 1e-6


def test_displacement_check_is_actually_run(stress: StressResult):
    assert stress.displacement["checked"] is True
    assert "displacement" in stress.displacement["conclusion"].lower()


def test_displacement_matches_the_frame_definition(stress: StressResult):
    """ID - Pcond/Vds must be what the load line says it is.

    The model reports the median over the samples where dv/dt is non-zero. The
    remaining load-line samples sit at Vds = 100 V with the drain node pinned, so
    their residual is leakage rather than displacement charging and they are
    excluded on purpose.
    """
    frame = stress.frame
    ll = frame[frame["transition_kind"].notna()]
    moving = ll[ll["dvdt_path_V_per_s"].fillna(0.0) != 0.0]
    assert len(moving) == stress.displacement["load_line"]["rows_with_a_nonzero_rate"]
    assert len(ll) - len(moving) == stress.displacement["load_line"]["rows_excluded_rate_zero"]

    gap = (moving["id_A"] - moving["pcond_W"] / moving["vds_V"]).abs()
    assert stress.displacement["load_line"]["median_gap_A"] == pytest.approx(
        float(np.median(gap.to_numpy())), rel=1e-6
    )


# --------------------------------------------------------------------------
# RON
# --------------------------------------------------------------------------

def test_ron_at_spec_point_matches_printed_typical(stress: StressResult):
    ron = stress.ron["at_spec_point"]
    assert ron["ratio_to_typ"] < 1.0
    assert ron["margin_ratio_to_max"] > 1.0
    assert "reproduces the printed typical" in ron["verdict"]


def test_ron_is_evaluated_at_the_printed_bias(stress: StressResult):
    spec = stress.ron["spec_point"]
    at = stress.ron["at_spec_point"]
    assert at["vgs_V"] == pytest.approx(spec["vgs_V"])
    assert at["vds_V"] == pytest.approx(spec["vds_V"])


def test_ron_temperature_is_not_mistaken_for_a_coefficient(stress: StressResult):
    ron = stress.ron
    assert ron["temperature_normalisation_is_identity"] is True
    tc = ron["temperature_coefficient"]
    # A usable coefficient needs a real T dependence. The identity means there is
    # none, so no normalising coefficient may be published as if there were.
    assert abs(tc["coefficient_per_C"]) < 1e-6
    assert tc["normalisation_status"]


# --------------------------------------------------------------------------
# Coverage must not be inverted
# --------------------------------------------------------------------------

def test_coverage_counts_samples_outside_not_inside(artifacts):
    """Regression: a negated flag counted the samples *inside* the envelope.

    It made the transfer profile look 121/121 out of rating when none are, and
    reported 53.9 % exceedance instead of the true 46.1 %.
    """
    df = artifacts.dataset
    cov = coverage_summary(df)
    expected = int(df["is_rating_exceeded"].astype(bool).sum())
    assert cov["outside_rated_envelope_total"] == expected
    assert cov["outside_rated_envelope_total"] < len(df)
    per_profile = {p: v["outside_rated_envelope"] for p, v in cov.items() if isinstance(v, dict)}
    for prof, count in per_profile.items():
        sub = df[df["profile"] == prof]
        assert count == int(sub["is_rating_exceeded"].sum()), prof
        assert count <= len(sub), prof
    # The low-current transfer sweep is inside the envelope everywhere.
    assert cov["transfer"]["outside_rated_envelope"] == 0


def test_coverage_uses_phase2a_exceedance_flag(artifacts, stress: StressResult):
    assert stress.coverage["outside_rated_envelope_total"] == int(
        artifacts.dataset["is_rating_exceeded"].sum()
    )


def test_trajectory_exceedance_sums_to_the_coverage_total(stress: StressResult):
    assert int(stress.trajectories["samples_outside_rated_envelope"].sum()) == \
        stress.coverage["outside_rated_envelope_total"]


# --------------------------------------------------------------------------
# Column discipline and serialisation
# --------------------------------------------------------------------------

def test_stress_columns_are_all_present(stress: StressResult):
    for col, _unit in STRESS_COLUMNS:
        assert col in stress.frame.columns


def test_phase2a_columns_are_not_overwritten(artifacts, stress: StressResult):
    """Phase 2B must not silently redefine a Phase 2A column."""
    for col in ("vds_rating_utilisation", "vgs_rating_utilisation",
                "id_continuous_rating_utilisation", "is_rating_exceeded"):
        assert np.array_equal(
            artifacts.dataset[col].to_numpy(),
            stress.frame[col].to_numpy(),
        ), f"{col} was changed by Phase 2B"


def test_stress_frame_preserves_phase2a_row_count_and_order(artifacts, stress: StressResult):
    assert len(stress.frame) == len(artifacts.dataset)
    assert artifacts.dataset["t_s"].tolist() == stress.frame["t_s"].tolist()
    assert artifacts.dataset["profile"].tolist() == stress.frame["profile"].tolist()


def test_stress_report_has_no_floating_nan(artifacts, stress: StressResult):
    """Strict JSON: a bare NaN literal breaks every non-Python consumer."""
    payload = stress_report(stress)
    text = json.dumps(payload, allow_nan=False)
    assert json.loads(text)["trajectory_count"] == len(stress.trajectories)

    def walk(node, path=""):
        if isinstance(node, float):
            assert node == node, f"NaN at {path}"
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(payload)


def test_report_renders_without_sentinels(stress: StressResult, cfg):
    """No Python repr may leak into the rendered tables.

    Checked against table cells and value positions rather than the whole file,
    because the prose legitimately contains the word "None".
    """
    text = render_stress(stress, cfg)
    assert text.startswith("# Phase 2B")

    cells = [c.strip() for line in text.split("\n") if line.startswith("|")
             for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
    assert cells
    for cell in cells:
        assert cell not in {"None", "nan", "NaN", "NoneType"}, repr(cell)
        # A raw list or dict repr in a cell means a value skipped _cell().
        assert not cell.startswith("[") and not cell.startswith("{"), repr(cell)
    # An unformatted float means a value bypassed _cell() via an f-string.
    assert not re.search(r"\d\.\d{10,}", text)
    assert not re.search(r"\bNone[,)]", text)
    # A sentence fragment must not start lowercase after a blank line.
    for block in text.split("\n\n"):
        first = block.strip().split("\n")[0]
        if first and not first.startswith(("#", "|", "-", "1", "2", "3", "4", "5", "6")):
            assert first[0].isupper() or first[0] in "`*", repr(first[:60])


def test_markdown_tables_are_aligned(stress: StressResult, cfg):
    """An unescaped pipe shifts columns silently; the file still renders."""
    text = render_stress(stress, cfg)
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


def test_report_contains_the_required_limitation_sentence(stress: StressResult, cfg):
    text = render_stress(stress, cfg)
    assert (
        "This framework currently provides physics-informed stress/degradation "
        "assessment based on the available device and Digital-Twin data. "
        "Experimental aging data is required to validate a true degradation-"
        "prediction model."
    ) in " ".join(text.split())


# --------------------------------------------------------------------------
# Evidence discipline
# --------------------------------------------------------------------------

def test_blocked_quantities_stay_blocked(stress: StressResult):
    blocked = stress_report(stress)["equations"]["blocked_quantities"]
    quantities = {b["quantity"] for b in blocked}
    assert any("aging" in q.lower() or "degradation" in q.lower() for q in quantities)
    assert any("switching" in q.lower() for q in quantities)
    assert all(b["reason"].strip() for b in blocked)


def test_no_rul_value_is_computed(stress: StressResult):
    """RUL may be named as blocked, but no RUL number may appear.

    The blocked-quantity reasons legitimately say "remaining useful life (rul)"
    in order to explain why it is refused, so this checks for a computed value
    rather than for the word itself.
    """
    payload = stress_report(stress)

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not re.search(r"\brul\b|health[_ ]?(score|index)", k, re.I), \
                    f"computed RUL/health key at {path}/{k}"
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(payload)
    assert payload["phase"] == "2B"


def test_printed_capacitance_is_in_a_plausible_range(stress: StressResult):
    """Regression: a 1e12/1e15 mix-up made Coss print as 1.15e6 pF.

    A GaN HEMT output capacitance is order 1 nF. Printing 1.15e6 pF is a units
    bug, not a device, so the rendered figure is pinned rather than trusted.
    """
    text = render_stress(stress, cfg_of(stress))
    # Coss and Crss must appear as order-nF and order-tens-of-pF figures.
    assert re.search(r"\|\s*1150 pF / 19\.0 pF\s*\|", text), "printed Coss/Crss mis-scaled"
    assert "7063 pF" in text, "Coss at 0 V mis-scaled"
    assert "1150000" not in text and "7062941" not in text


def test_charge_anchors_are_labelled_in_coulombs(bundle):
    """The Stage 1 keys say ``_nC`` but store coulombs.

    Declaring the unit as nC would understate every charge figure by 1e9.
    """
    from ganstage2.anchors import build_anchors

    anchors = build_anchors(bundle.mat_params)
    for key in ("QG_PRINTED", "QGS_PRINTED", "QGD_PRINTED", "QOSS_PRINTED"):
        anchor = anchors[key]
        assert anchor.unit == "C", key
        assert "value is in C" in anchor.note, key
        # The stored value must be a plausible charge, i.e. order 1e-8 C.
        assert 1e-9 < anchor.value < 1e-6, (key, anchor.value)


def cfg_of(_stress):
    from ganstage2.config import Stage2Config

    return Stage2Config()


def test_gate_charge_figures_are_consistent_with_the_datasheet(stress: StressResult):
    ch = stress.charge
    assert ch["available"] is True
    # 34 nC printed gate charge must render as 34 nC, not 3.4e-8 nC.
    assert 1e-9 * 30 < ch["printed_qg_C"] * 1e9 < 40
    assert ch["integrated_ratio_to_printed_qg"] < 1.0


def test_disclaimer_denies_degradation_claims(stress: StressResult):
    from ganstage2.evidence import EvidenceClass

    rep = stress_report(stress)
    # Every Phase 2B number is derived from the simulation, never measured on a
    # device, so the report must be labelled as calculated rather than validated.
    assert rep["evidence"] == EvidenceClass.CALCULATED.value
    assert "degradation" in rep["disclaimer"].lower()
    assert "no aging axis" in rep["disclaimer"].lower()
