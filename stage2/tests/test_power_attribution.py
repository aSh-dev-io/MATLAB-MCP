"""Attribution test for the Pcond vs Vds*ID gap.

The gap is Vds * (ID - Ich), i.e. displacement plus leakage current. If it were
anything else it would be a model error, so the test attributes the current
rather than just quoting the watts.
"""

from __future__ import annotations

import numpy as np

from ganstage2.config import Stage2Config


def test_pcond_gap_is_displacement_not_leakage(artifacts):
    df = artifacts.dataset
    saturated_dc = df[df["profile"].isin(["output", "transfer", "thermal"]) & ~df["is_triode"]]
    assert len(saturated_dc) > 0

    resid = saturated_dc["pcond_minus_vds_id_W"].abs()
    implied_a = (resid / saturated_dc["vds_V"].abs()).max()

    # Displacement must dominate leakage by orders of magnitude, otherwise the
    # gap would be leakage and the P03 attribution would be wrong.
    assert implied_a > 100.0 * saturated_dc["i_leak_A"].max()


def test_pcond_gap_is_bounded_but_not_negligible(artifacts):
    """Pins both directions: not a model error, but not ignorable either.

    An earlier version of P03 described this residual as "near zero
    quasi-statically" while reporting 37.7 W, which is 20 % of channel power.
    """
    df = artifacts.dataset
    saturated_dc = df[df["profile"].isin(["output", "transfer", "thermal"]) & ~df["is_triode"]]

    resid = saturated_dc["pcond_minus_vds_id_W"].abs()
    rel = (resid / saturated_dc["pcond_W"].abs().replace(0.0, np.nan)).max()

    assert rel < 0.5, "gap too large to attribute to displacement charging alone"
    assert rel > 0.01, "gap should not be described as negligible"


def test_pcond_gap_never_exceeds_channel_power_by_orders_of_magnitude(artifacts):
    """A sanity bound against a gross model error rather than a fine detail."""
    df = artifacts.dataset
    ratio = (
        df["pcond_minus_vds_id_W"].abs() / df["pcond_W"].abs().replace(0.0, np.nan)
    ).max()
    assert ratio < 1.0


def test_p03_reports_the_relative_size(artifacts):
    p03 = next(c for c in artifacts.physics_checks if c.check_id == "P03")
    assert p03.status == "INFO"
    assert "% of channel" in p03.detail
    assert "displacement" in p03.detail
    assert "not quasi-static" in p03.detail
