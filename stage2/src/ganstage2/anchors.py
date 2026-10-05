"""Datasheet-anchored reference values, extracted from the Stage 1 parameter block.

Every stress ratio in 2B divides by something. This module is where those
denominators come from, so that no ratio can quietly acquire a hard-coded magic
number. Each anchor records the Stage 1 parameter path it was read from, its
value, its unit and whether it is a measured datasheet figure or something the
Stage 1 model solved for itself.

The distinction matters. ``ID_CONTINUOUS_25C_A`` is measured and printed.
``RDS_ON_VDS_SPEC_V`` is derived by the Stage 1 script from the printed RON and
test current. Both are usable as denominators, but only the first is evidence
about a real device, and the anchors report which is which.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evidence import EvidenceClass


@dataclass(frozen=True)
class Anchor:
    """One reference value used as a denominator or comparison point."""

    key: str
    value: float
    unit: str
    #: Stage 1 MAT parameter path this was read from.
    source: str
    evidence: EvidenceClass
    note: str = ""

    @property
    def usable(self) -> bool:
        """False when the printed value is absent or explicitly TBD."""
        return self.value == self.value and self.evidence is not EvidenceClass.UNAVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": None if self.value != self.value else self.value,
            "unit": self.unit,
            "source": self.source,
            "evidence": self.evidence.value,
            "usable": self.usable,
            "note": self.note,
        }


_DD = EvidenceClass.DATASET_DERIVED
_CALC = EvidenceClass.CALCULATED
_ASSUMED = EvidenceClass.PHYSICS_MODELLED


def _get(params: dict[str, Any], path: str, default: Any = None) -> Any:
    """Read a flat ``a.b.c`` key out of the Stage 1 parameter dict."""
    return params.get(path, default)


def build_anchors(params: dict[str, Any]) -> dict[str, Anchor]:
    """Extract every reference value 2B/2C need from the Stage 1 parameters."""
    anchors: dict[str, Anchor] = {}

    def add(key: str, path: str, unit: str, evidence: EvidenceClass, note: str = "") -> None:
        raw = _get(params, path)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = float("nan")
        anchors[key] = Anchor(key, value, unit, path, evidence, note)

    # ---- absolute maximum ratings (printed) --------------------------------
    add("VDS_ABS_MAX", "ratings.vds_drain_source_V", "V", _DD,
        "Absolute maximum drain-source voltage.")
    add("VGS_ABS_MAX", "ratings.vgs_max_V", "V", _DD,
        "Absolute maximum gate-source voltage.")
    add("VGS_ABS_MIN", "ratings.vgs_min_V", "V", _DD,
        "Absolute minimum (reverse) gate-source voltage.")
    add("VGS_PULSE_MAX", "ratings.vgs_pulse_max_V", "V", _DD,
        "Pulsed gate limit. Not applied against DC waveforms.")
    add("ID_CONTINUOUS_25C", "ratings.id_continuous_25C_A", "A", _DD,
        "Continuous drain current, 25 degC.")
    add("ID_PULSE_25C", "ratings.id_pulse_25C_A", "A", _DD,
        "Pulsed drain current, 25 degC. Pulse width is not printed.")
    add("ID_PULSE_150C", "ratings.id_pulse_150C_A", "A", _DD,
        "Pulsed drain current, 150 degC.")
    add("TJ_MAX", "ratings.tj_max_C", "degC", _DD,
        "Maximum junction temperature.")
    add("TSTG_MAX", "ratings.tstg_max_C", "degC", _DD,
        "Maximum storage temperature.")
    add("PD_TOTAL", "ratings.pd_total_W", "W", EvidenceClass.UNAVAILABLE,
        "Printed as TBD in the dataset. No power normalisation is possible.")

    # ---- DC specification (printed) ----------------------------------------
    add("RDS_ON_TYP", "dc.rds_on_typ_ohm", "Ohm", _DD,
        "Typical on-resistance, printed.")
    add("RDS_ON_MAX", "dc.rds_on_max_ohm", "Ohm", _DD,
        "Maximum on-resistance, printed.")
    add("RDS_ON_VGS", "dc.rds_on_vgs_V", "V", _DD,
        "Gate voltage of the RON test point, printed.")
    add("RDS_ON_IDS", "dc.rds_on_ids_A", "A", _DD,
        "Drain current of the RON test point, printed.")
    add("RDS_ON_VDS_SPEC", "dc.vds_ron_spec_V", "V", _CALC,
        "Stage 1 derived the RON test Vds as RDS(on)*Ids rather than reading it.")
    add("VTH_MIN", "dc.vgs_th_min_V", "V", _DD, "Minimum threshold voltage.")
    add("IDSS_MAX_25C", "dc.idss_max_25C_A", "A", _DD, "Max off-state leakage, 25 degC.")
    add("IDSS_MAX_125C", "dc.idss_max_125C_A", "A", _DD, "Max off-state leakage, 125 degC.")
    add("BR_DSS_MIN", "dc.br_dss_min_V", "V", _DD, "Minimum drain-source breakdown.")
    add("FOM_QG_RON", "dc.fom_qg_nC_mohm", "nC*mohm", _DD,
        "Printed figure of merit QG*RDS(on).")

    # ---- gate charge (printed) ---------------------------------------------
    # The Stage 1 keys carry an "_nC" suffix but the stored values are coulombs:
    # charge.qg_nC is 3.4e-8, which is the printed 34 nC. The unit below is
    # therefore C, not the nC the key name suggests. Reading the suffix as the
    # unit would understate every charge figure by 1e9.
    add("QG_PRINTED", "charge.qg_nC", "C", _DD,
        "Printed total gate charge. Stage 1 key says nC but the value is in C.")
    add("QGS_PRINTED", "charge.qgs_nC", "C", _DD,
        "Printed gate-source charge. Stage 1 key says nC but the value is in C.")
    add("QGD_PRINTED", "charge.qgd_nC", "C", _DD,
        "Printed gate-drain charge. Stage 1 key says nC but the value is in C.")
    add("QOSS_PRINTED", "charge.qoss_nC", "C", _DD,
        "Printed output charge. Stage 1 key says nC but the value is in C.")
    add("QGD_TEST_VDS", "charge.qgd_vds_V", "V", _DD, "Vds of the QGD test point.")
    add("QGD_TEST_IDS", "charge.qgd_ids_A", "A", _DD, "Ids of the QGD test point.")

    # ---- capacitance (printed at 1 MHz) ------------------------------------
    add("CISS_REF", "caps.ciss_F", "F", _DD, "Printed input capacitance.")
    add("COSS_REF", "caps.coss_F", "F", _DD, "Printed output capacitance.")
    add("CRSS_REF", "caps.crss_F", "F", _DD, "Printed reverse transfer capacitance.")
    add("CAPS_TEST_VDS", "caps.vds_test_V", "V", _DD, "Vds of the CV test point.")
    add("CAPS_TEST_F", "caps.f_test_Hz", "Hz", _DD, "CV test frequency.")

    # ---- model / stimulus ---------------------------------------------------
    add("TCASE_NOM", "solver.tcase_nom_C", "degC", _DD,
        "Nominal case temperature of the ratings.")
    add("SAMPLE_TIME", "solver.sample_time_s", "s", _DD,
        "Stage 1 solver output sample time.")
    add("SWITCH_T_ON", "switching.t_on_s", "s", _DD, "Simulated turn-on duration.")
    add("SWITCH_T_OFF", "switching.t_off_s", "s", _DD, "Simulated turn-off duration.")
    add("SWITCH_N_CYCLES", "switching.n_cycles", "count", _DD,
        "Number of simulated switching cycles.")
    add("SWITCH_N_RISE", "switching.n_rise", "count", _DD,
        "Number of rise-transition samples per cycle.")
    add("SWITCH_VBUS", "switching.vbus_V", "V", _DD, "Simulated DC link voltage.")
    add("SWITCH_RLOAD", "switching.rload_ohm", "Ohm", _DD, "Simulated load resistance.")
    add("SWITCH_VGS_ON", "switching.vgs_on_V", "V", _DD, "Simulated on-state gate drive.")
    add("SWITCH_VGS_OFF", "switching.vgs_off_V", "V", _DD, "Simulated off-state gate drive.")
    add("VDSAT", "model.vdsat_V", "V", _CALC,
        "Stage 1 solved Vdsat so Id_sat matches the pulsed current rating.")
    add("K_AMP_PER_V2", "model.k_amp_per_v2", "A/V^2", _CALC,
        "Square-law coefficient solved from the RON test point.")
    add("LEAK_TEMP_RATIO", "model.leak_temp_ratio", "dimensionless", _CALC,
        "Stage 1 leakage ratio across 25-125 degC, fitted to the printed IDSS pair.")
    add("IGSS_TEMP_RATIO", "model.igss_temp_ratio", "dimensionless", _CALC,
        "Stage 1 gate-leakage ratio across 25-125 degC.")

    return anchors


def anchor_table(anchors: dict[str, Anchor]) -> list[dict[str, Any]]:
    """Serialisable anchor list for reports."""
    return [a.to_dict() for a in anchors.values()]


def usable(anchors: dict[str, Anchor], key: str) -> float:
    """Anchor value, raising if it is missing or printed TBD."""
    a = anchors[key]
    if not a.usable:
        raise ValueError(
            f"anchor {key!r} (from {a.source}) is not usable: printed as TBD"
        )
    return a.value
