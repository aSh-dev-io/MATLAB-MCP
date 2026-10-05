"""Physics-consistency tests."""

from __future__ import annotations

import numpy as np

from ganstage2.physics import leakage_current_a, saturation_voltage_v


def test_node_current_balance_is_exact(artifacts, cfg):
    residual = artifacts.dataset["kcl_residual_A"].abs().max()
    assert residual <= cfg.kcl_atol.value


def test_power_balance_is_exact(artifacts, cfg):
    residual = artifacts.dataset["ploss_identity_residual_W"].abs().max()
    assert residual <= cfg.power_balance_atol.value


def test_pcond_is_not_vds_times_id(artifacts):
    """Confirms Pcond is channel power, so the gap is physical, not an error."""
    gap = artifacts.dataset["pcond_minus_vds_id_W"]
    assert gap.abs().max() > 0.0


def test_intrinsic_capacitances_are_positive(artifacts):
    df = artifacts.dataset
    assert (df["cds_derived_F"] >= -1e-18).all()
    assert (df["cgs_derived_F"] >= -1e-18).all()


def test_ron_valid_requires_conduction_and_triode(artifacts):
    df = artifacts.dataset
    valid = df[df["ron_valid"]]
    assert valid["is_conducting"].all()
    assert valid["is_triode"].all()
    assert (valid["vds_V"] > 0).all()
    assert valid["ron_static_ohm"].notna().all()


def test_ron_invalid_rows_have_a_reason(artifacts):
    df = artifacts.dataset
    invalid = df[~df["ron_valid"]]
    assert (invalid["ron_valid_reason"].str.len() > 0).all()


def test_raw_stage1_ron_is_mostly_uninterpretable(artifacts):
    """The central Phase 2A finding, pinned as a regression test."""
    df = artifacts.dataset
    fraction_valid = df["ron_valid"].mean()
    assert fraction_valid < 0.5, (
        "expected most exported RON values to be uninterpretable as a "
        f"resistance, got {fraction_valid:.1%} valid"
    )
    # And the raw column really does contain absurd resistances.
    raw = df["ron_stage1_ohm"].dropna()
    assert raw.max() > 1.0, "raw RON should contain physically meaningless values > 1 ohm"


def test_ron_gating_recovers_the_datasheet_point(artifacts):
    """At the datasheet RON test point the gated RON must match 1.6 mOhm.

    This is the payoff of gating: Stage 1's own summary quotes ~11 mOhm for the
    output profile at VGS = 5 V because it evaluates Vds/ID in saturation.
    """
    df = artifacts.dataset
    point = df[
        (df["profile"] == "output")
        & (df["vgs_V"].round(6) == 5.0)
        & (df["is_triode"])
        & (df["is_conducting"])
    ]
    assert len(point) > 5
    # Differential slope over the triode segment is the physical RON.
    slope = np.polyfit(point["id_A"].to_numpy(float), point["vds_V"].to_numpy(float), 1)[0]
    assert 1.0e-3 < slope < 3.0e-3, f"differential RON {slope:.4g} ohm is not near 1.6 mOhm"


def test_differential_ron_available_only_for_sweeps(artifacts):
    df = artifacts.dataset
    assert df[df["profile"] == "output"]["ron_differential_available"].any()
    assert not df[df["profile"] != "output"]["ron_differential_available"].any()


def test_no_temperature_normalisation_is_fabricated(artifacts):
    df = artifacts.dataset
    assert df["ron_temp_normalised_ohm"].isna().all()
    assert df["ron_tempnorm_status"].str.contains("unavailable").all()


def test_channel_current_has_no_temperature_dependence(artifacts):
    """Requirement 3 needs temperature-aware RON; the source cannot supply it."""
    thermal = artifacts.dataset[artifacts.dataset["profile"] == "thermal"]
    conduction = thermal[thermal["is_conducting"]]
    by_point = conduction.groupby(["vgs_V", "vds_V", "tcase_C"])["id_A"].mean().unstack()
    assert by_point.shape[1] == 2
    ratio = (by_point[125.0] / by_point[25.0]).to_numpy(float)
    assert np.allclose(ratio, 1.0, rtol=1e-6), f"unexpected temperature dependence: {ratio}"


def test_tj_tracks_tcase_exactly(artifacts):
    df = artifacts.dataset
    assert (df["tj_C"] - df["tcase_C"]).abs().max() == 0.0


def test_no_row_is_flagged_as_aging(artifacts):
    df = artifacts.dataset
    assert not df["is_aging_measurement"].any()
    assert df["aging_time_h"].isna().all()
    assert not df["has_experimental_validation"].any()


def test_saturation_voltage_matches_stage1_behaviour():
    """VDSAT(VGS) must reproduce the 1.66303 V ceiling at high gate drive."""
    vth, vsmooth, vdsat_max = 1.1, 0.05, 1.6630271007940307
    assert saturation_voltage_v(np.array([5.0]), vth, vsmooth, vdsat_max)[0] == vdsat_max
    assert saturation_voltage_v(np.array([0.0]), vth, vsmooth, vdsat_max)[0] == 0.0
    # Below threshold the channel is off, so the knee is zero.
    assert saturation_voltage_v(np.array([0.5]), vth, vsmooth, vdsat_max)[0] == 0.0


def test_leakage_matches_printed_idss(artifacts, bundle):
    params = bundle.mat_params
    at_25 = leakage_current_a(np.array([150.0]), np.array([25.0]), params)[0]
    at_125 = leakage_current_a(np.array([150.0]), np.array([125.0]), params)[0]
    assert np.isclose(at_25, 4e-6, rtol=1e-9)
    assert np.isclose(at_125, 6e-5, rtol=1e-9)
    assert np.isclose(at_125 / at_25, 15.0, rtol=1e-9)


def test_rating_exceedances_are_confined_to_characterisation(artifacts):
    df = artifacts.dataset
    exceeded = df[df["is_rating_exceeded"]]
    assert len(exceeded) > 0
    assert not exceeded["is_application_operating_point"].any()
