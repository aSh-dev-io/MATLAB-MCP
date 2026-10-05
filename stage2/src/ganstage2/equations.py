"""Registry of every physics equation Stage 2B/2C/2D evaluates.

The project rule is that no equation may enter the pipeline without a recorded
physical meaning, unit, provenance, assumption list and evidence class. Keeping
that in a single declarative table rather than in scattered code comments means
the reports, the dashboard and the tests all read the *same* source of truth, so
a quantity cannot be documented one way in the README and computed another way
in the module.

Nothing in this registry is a degradation law. There is no Arrhenius activation
energy, no Coffin-Manson term, no cycle-to-failure coefficient, because the
available evidence contains no aging data to fit any of them. See
:data:`BLOCKED_QUANTITIES` for what that rules out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .evidence import EvidenceClass


@dataclass(frozen=True)
class Equation:
    """One physical relation, with everything needed to audit it."""

    key: str
    expression: str
    meaning: str
    unit: str
    #: Where the inputs come from: datasheet, Stage 1 model, or this pipeline.
    inputs: str
    #: Ordered list of assumptions. Empty means the relation is exact given inputs.
    assumptions: tuple[str, ...] = ()
    #: Strongest class any input supports; the equation cannot be stronger.
    evidence: EvidenceClass = EvidenceClass.SIMULATED
    #: Set when the equation exists in the code but cannot be evaluated on this data.
    unavailable_reason: str | None = None

    @property
    def is_available(self) -> bool:
        return self.unavailable_reason is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "expression": self.expression,
            "meaning": self.meaning,
            "unit": self.unit,
            "inputs": self.inputs,
            "assumptions": list(self.assumptions),
            "evidence": self.evidence.value,
            "available": self.is_available,
            "unavailable_reason": self.unavailable_reason,
        }


# --------------------------------------------------------------------------
# 2B -- stress and exposure
# --------------------------------------------------------------------------

_ELECTRICAL_STRESS = (
    Equation(
        key="vds_rating_utilisation",
        expression="|Vds| / Vds_drain_source_max",
        meaning=(
            "Fraction of the printed absolute-maximum drain-source voltage the "
            "device is instantaneously blocking."
        ),
        unit="dimensionless (0-1 within rating)",
        inputs="Stage 1 Vds; ratings.vds_drain_source_V = 150 V (datasheet)",
        assumptions=(
            "The printed absolute maximum is treated as a hard bound that must "
            "not be exceeded in any application.",
        ),
        evidence=EvidenceClass.DATASET_DERIVED,
    ),
    Equation(
        key="vgs_rating_utilisation",
        expression="|Vgs| / Vgs_max",
        meaning=(
            "Fraction of the printed maximum gate-source voltage. Negative Vgs "
            "is measured against Vgs_min so reverse drive is bounded too."
        ),
        unit="dimensionless",
        inputs="Stage 1 Vgs; ratings.vgs_max_V = 6 V, ratings.vgs_min_V = -4 V",
        assumptions=(
            "The DC gate rating applies. The printed 6.5 V pulse rating is a "
            "pulsed-condition limit and is not used against a DC waveform.",
        ),
        evidence=EvidenceClass.DATASET_DERIVED,
    ),
    Equation(
        key="id_continuous_rating_utilisation",
        expression="|ID| / Id_continuous_25C",
        meaning=(
            "Fraction of the printed 25 degC continuous drain-current rating "
            "carried by the channel."
        ),
        unit="dimensionless",
        inputs="Stage 1 ID; ratings.id_continuous_25C_A = 115 A",
        assumptions=(
            "The continuous rating is quoted at 25 degC case. Comparing a 125 "
            "degC sample against the 25 degC rating is conservative, which is "
            "recorded rather than corrected, because no derating curve exists.",
            "The channel current is taken as ID, the exported drain current. It is "
            "NOT taken as ID + IS: the Stage 1 node balance ID + IG + IS = 0 makes "
            "ID + IS = -IG, which is essentially zero, so using it would report a "
            "near-zero current and a correspondingly meaningless rating ratio.",
            "Stage 1's internal conduction-only current Ich is not exported. ID "
            "exceeds Ich by the displacement current wherever Vds moves, up to "
            "about 14.5 A on the switching load line, so this ratio is an upper "
            "bound on the true channel loading during transitions and is exact "
            "only on quiescent rows.",
        ),
        evidence=EvidenceClass.DATASET_DERIVED,
    ),
    Equation(
        key="id_pulse_rating_utilisation",
        expression="|ID| / Id_pulse_25C",
        meaning=(
            "Fraction of the printed 25 degC pulsed drain-current rating. The "
            "pulsed rating bounds a transient, not a steady state."
        ),
        unit="dimensionless",
        inputs="Stage 1 ID; ratings.id_pulse_25C_A = 840 A",
        assumptions=(
            "Whether a sample counts as pulsed requires the datasheet pulse "
            "width, which is not printed. This ratio is therefore reported as "
            "context only and never used to raise or clear a finding.",
        ),
        evidence=EvidenceClass.DATASET_DERIVED,
    ),
    Equation(
        key="channel_current_definition",
        expression="Ich = Pcond / Vds   (Stage 1 internal),   ID = Ich + iCds + iCgd + Ileak",
        meaning=(
            "Why the exported drain current ID and the current Stage 1 uses for "
            "conduction power are different quantities, and how to recover the "
            "conduction-only current from the exported signals."
        ),
        unit="A",
        inputs="Stage 1 Pcond, Vds, ID; Coss, Cgd; dv/dt within the trajectory path",
        assumptions=(
            "Pcond = Vds * Ich, so Ich is recoverable wherever Vds is non-zero. At "
            "Vds = 0 the ratio is undefined and no channel current can be inferred.",
            "The separation ID - Ich is displacement plus leakage. This was verified "
            "quantitatively: on quiescent rows ID and Ich agree to 5e-10 relative, "
            "while on the reconstructed switching load line the gap reaches 12.63 A "
            "at the median of all 108 load-line samples. Restricting to the 84 samples "
            "where dv/dt is non-zero (the remaining 24 sit at Vds = 100 V with the "
            "drain node pinned, so their residual is pure leakage) gives 14.45 A "
            "against 14.45 A predicted by Coss * |dv/dt|, a ratio of 1.00069.",
            "Consequence: Pcond and Vds * ID must never be added together or treated "
            "as interchangeable, and their difference must not be read as a model "
            "error or as a degradation signal.",
        ),
        evidence=EvidenceClass.CALCULATED,
    ),
    Equation(
        key="conduction_power_rating_product_ratio",
        expression="|Pcond| / (Id_continuous_25C * Vds_rating_max)",
        meaning=(
            "Conduction loss normalised by the product of the printed continuous "
            "current and printed maximum voltage, giving a dimensionless figure of "
            "how hard the device is being worked in the conduction mode."
        ),
        unit="dimensionless",
        inputs="Stage 1 Pcond; printed ratings",
        assumptions=(
            "PTOT is printed as TBD in the dataset, so dissipated power cannot "
            "be normalised by a real power rating. The rating product is used "
            "as a scale of reference only, and is not a power dissipation limit.",
        ),
        evidence=EvidenceClass.CONVENTION,
    ),
)

_LOSS_STRESS = (
    Equation(
        key="total_loss_energy_J",
        expression="integral Ploss dt  (trapezoid, within one trajectory)",
        meaning=(
            "Energy dissipated in the device over the simulated observation "
            "window of one trajectory."
        ),
        unit="J",
        inputs="Stage 1 Ploss and t within a single trajectory",
        assumptions=(
            "Integrates only within a trajectory. The Stage 1 profiles place "
            "several trajectories on one shared time axis, so a single integral "
            "over a whole profile would sum concurrent trajectories and is "
            "meaningless.",
            "This is the energy of the observation window, NOT a lifetime or "
            "per-cycle energy. No duty cycle, repetition rate or field history "
            "exists, so it cannot be scaled to a duty.",
        ),
        evidence=EvidenceClass.SIMULATED,
    ),
    Equation(
        key="conduction_energy_J",
        expression="integral Pcond dt  (trapezoid, within one trajectory)",
        meaning="Joule-heating energy dissipated in the channel over the window.",
        unit="J",
        inputs="Stage 1 Pcond and t within a single trajectory",
        assumptions=("Same trajectory restriction and same observation-window caveat as total_loss_energy_J.",),
        evidence=EvidenceClass.SIMULATED,
    ),
    Equation(
        key="switching_energy_miller_J",
        expression="integral Psw dt  (trapezoid, within one reconstructed transition window)",
        meaning=(
            "Energy dissipated through the gate-drain capacitance during one gate "
            "transition, i.e. the Miller-plateau component."
        ),
        unit="J",
        inputs="Stage 1 Psw and t along the transition path",
        assumptions=(
            "Psw is the Stage 1 gate-drive power term. It is NOT the total "
            "switching loss: total Eon+Eoff also contains the drain-side Vds*Id "
            "overlap and the output-capacitance charge, neither of which is "
            "present in the Stage 1 signals.",
            "The Miller term contributes only 0.07 % of the load-line path "
            "integral, which is itself evidence that the loss model is missing "
            "the dominant capacitive channel.",
            "Each transition is sampled 18 times at 1 ns across the whole slew, "
            "so this is a lower bound: peaks within one sample interval are "
            "invisible. It must not be multiplied by a switching frequency, "
            "because no repetition rate exists in the dataset.",
        ),
        evidence=EvidenceClass.SIMULATED,
    ),
    Equation(
        key="transition_path_integral_J",
        expression="integral Ploss dt  (trapezoid, within one reconstructed transition window)",
        meaning=(
            "Energy of one hard-switching transition, integrated along the "
            "reconstructed load-line path."
        ),
        unit="J",
        inputs="Stage 1 Ploss and t along the transition path",
        assumptions=(
            "THIS IS NOT A SWITCHING LOSS. Stage 1's loss budget is exactly "
            "Ploss = Pcond + Psw with no output-capacitance charge/discharge "
            "channel and no gate-drive dissipation channel, so Coss is never "
            "charged during a transition. The consequence is measurable: the "
            "simulated load line is exactly reversible, with turn-off the "
            "bit-level reverse of turn-on (max relative asymmetry 6.6e-16), and "
            "all three cycles are bit-identical.",
            "A hard-switched device cannot behave this way. Turn-on charges Coss "
            "and clamps the inductor current into the low-side device; turn-off "
            "does neither. The independent CV sweep gives Eoss = 11.81 uJ, and "
            "none of it appears in these integrals, which is the direct "
            "confirmation that the capacitive channel is absent.",
            "An integral of channel power along a reversible trajectory is a "
            "property of the path, not a device loss. It cannot be compared with "
            "a datasheet switching-loss figure.",
        ),
        evidence=EvidenceClass.SIMULATED,
    ),
    Equation(
        key="output_capacitance_loss_energy_J",
        expression="integral |Vds * Coss(Vds)| dVds   over the measured CV sweep",
        meaning=(
            "Eoss: the energy charged into the output capacitance during a "
            "hard-switched voltage transition. Computed from the measured "
            "Coss(Vds) characteristic."
        ),
        unit="J",
        inputs="Stage 1 capacitance profile: Vds and Coss(F)",
        assumptions=(
            "Hard-switching reference Eoss, defined at the datasheet CV test "
            "frequency. Requires Coss to be bias dependent only, so it is "
            "evaluated on the VGS = 0 V trace where the printed Coss is quoted.",
            "Excludes the VGS-dependent component of Coss, which is real for a "
            "gate-reduced Cgs device but cannot be separated without a "
            "temperature-dependent CV model.",
        ),
        evidence=EvidenceClass.PHYSICS_MODELLED,
    ),
    Equation(
        key="drain_slew_rate_V_per_s",
        expression="|dVds/dt| along the reconstructed transition path, else within one trajectory",
        meaning=(
            "Rate of change of drain voltage. A primary dv/dt stress driver for "
            "drain-gate capacitance charging and parasitic turn-on."
        ),
        unit="V/s",
        inputs="Stage 1 Vds and t",
        assumptions=(
            "The grouping matters and is not obvious. A trajectory is one bias "
            "point, and a bias point does not move, so differencing within a "
            "trajectory returns ~0 everywhere. The switching load line only "
            "becomes visible when the samples of a single transition window are "
            "read across bias points, so slew is computed on the window path "
            "where one exists and on the trajectory elsewhere.",
            "A backward difference between samples, so it understates the true "
            "peak when the transition is unresolved. The load line is sampled at "
            "1 ns, giving a median |dv/dt| of 5.9e9 V/s.",
        ),
        evidence=EvidenceClass.SIMULATED,
    ),
    Equation(
        key="channel_slew_rate_A_per_s",
        expression="|dID/dt| along the reconstructed transition path, else within one trajectory",
        meaning="Rate of change of channel current; an di/dt stress driver.",
        unit="A/s",
        inputs="Stage 1 ID and t",
        assumptions=("Same path-grouping and resolution caveat as drain_slew_rate_V_per_s.",),
        evidence=EvidenceClass.SIMULATED,
    ),
)

_THERMAL_STRESS = (
    Equation(
        key="case_rise_above_ambient_C",
        expression="Tcase - 25 degC",
        meaning=(
            "Case temperature rise above the 25 degC nominal condition used for "
            "the printed ratings."
        ),
        unit="degC",
        inputs="Stage 1 Tcase; solver.tcase_nom_C = 25 degC",
        assumptions=("25 degC is the nominal case temperature of the ratings, not a measured ambient.",),
        evidence=EvidenceClass.DATASET_DERIVED,
    ),
    Equation(
        key="junction_rating_utilisation",
        expression="Tj / Tj_max",
        meaning="Fraction of the printed maximum junction temperature.",
        unit="dimensionless",
        inputs="Stage 1 Tj; ratings.tj_max_C = 150 degC",
        assumptions=(
            "Tj equals Tcase in the Stage 1 model because every thermal "
            "resistance is printed as TBD. This ratio is therefore a case "
            "temperature ratio and must not be read as a junction temperature.",
        ),
        evidence=EvidenceClass.SIMULATED,
    ),
    Equation(
        key="thermal_exposure_Ks",
        expression="integral max(Tcase - 25 degC, 0) dt  (within one trajectory)",
        meaning=(
            "Time-temperature product: the integral of case temperature rise "
            "above the rating nominal condition. A parameter-free measure of "
            "how much thermal load the device saw."
        ),
        unit="K*s",
        inputs="Stage 1 Tcase and t within a single trajectory",
        assumptions=(
            "Deliberately linear in temperature. An Arrhenius weighting "
            "exp(-Ea/kT) would be the physically standard form, but the "
            "activation energy Ea is not present in the dataset and inventing "
            "one is exactly what this project forbids. The linear product is "
            "reported instead and is explicitly NOT convertible to a lifetime.",
        ),
        evidence=EvidenceClass.PHYSICS_MODELLED,
    ),
    Equation(
        key="thermal_resistance_K_per_W",
        expression="dTcase / dPcond",
        meaning=(
            "Apparent thermal resistance of the simulated device, obtained from "
            "the slope of case temperature against dissipated power."
        ),
        unit="K/W",
        inputs="Stage 1 Tcase and Pcond",
        assumptions=(
            "The Stage 1 model contains no thermal network, so this slope is a "
            "property of how the script drove Tcase, not of the package. It is "
            "reported only to document the absence, never as a package "
            "parameter.",
        ),
        evidence=EvidenceClass.SIMULATED,
    ),
)

_RON_STRESS = (
    Equation(
        key="on_resistance_ohm",
        expression="Vds / ID",
        meaning="Static on-resistance from drain voltage over channel current.",
        unit="Ohm",
        inputs="Stage 1 Vds, ID, IS",
        assumptions=(
            "Evaluated only inside a validated conduction window: Vds above the "
            "numerical floor, |ID| above the conduction threshold, and the "
            "sample in the triode regime. Saturation samples are excluded "
            "because Vds/ID there is an output conductance, not a resistance.",
        ),
        evidence=EvidenceClass.CALCULATED,
    ),
    Equation(
        key="specific_on_resistance_ohm_cm2",
        expression="Ron * A_active",
        meaning=(
            "Specific on-resistance, the figure-of-merit that normalises RON by "
            "die area so devices can be compared."
        ),
        unit="ohm*cm^2",
        inputs="Stage 1 Ron and the active die area",
        assumptions=(
            "The active area is not printed in the source dataset. It is "
            "solved from the printed figure of merit FOM = QG * RDS(on) = 54.4 "
            "nC*mohm together with the modelled QG, and that solution is "
            "labelled ASSUMED rather than presented as a datasheet dimension.",
        ),
        evidence=EvidenceClass.PHYSICS_MODELLED,
    ),
    Equation(
        key="ron_at_datasheet_spec_ohm",
        expression="Ron evaluated at Vgs = Rds_on_vgs, Vds = Rds_on*Ids, ID = Ids",
        meaning=(
            "The model's on-resistance at the exact printed RON test condition, "
            "which is the one point in the dataset where the Digital Twin can "
            "be compared against a measured datasheet number."
        ),
        unit="Ohm",
        inputs="Stage 1 transfer profile; dc.rds_on_* parameters",
        assumptions=(
            "Valid only if the simulated bias grid lands on the datasheet test "
            "condition. The transfer profile does: Vgs = 5.00 V, "
            "Vds = 0.08 V, ID = 50.06 A against a specified 50 A.",
        ),
        evidence=EvidenceClass.VALIDATED_AGAINST_DATASHEET,
    ),
    Equation(
        key="ron_temperature_coefficient_per_C",
        expression="d ln(Ron) / dTcase",
        meaning=(
            "Fractional change of on-resistance per degree of case temperature, "
            "measured from the dataset's only temperature contrast."
        ),
        unit="1/degC",
        inputs="Stage 1 thermal profile, matched bias, 25 degC vs 125 degC",
        assumptions=(
            "Requires the model to carry a temperature dependence. It does not: "
            "RON is exactly identical at 25 degC and 125 degC at all six "
            "matched bias points, because RON is evaluated from the DC model's "
            "bias-dependent terms which carry no explicit T dependence.",
            "The measured coefficient is therefore exactly zero. This is a "
            "model limitation, not a device property: a real GaN HEMT has a "
            "strongly temperature-dependent RON.",
        ),
        evidence=EvidenceClass.CALCULATED,
    ),
    Equation(
        key="ron_temperature_normalised_ohm",
        expression="Ron(T) / Ron(T_nom) * Ron(T_nom)",
        meaning=(
            "RON referred to the 25 degC rating condition so that on-resistance "
            "can be compared across temperatures."
        ),
        unit="Ohm",
        inputs="Stage 1 Ron, ron_temperature_coefficient_per_C",
        assumptions=(
            "Applies the measured coefficient of 0 /degC. Because that "
            "coefficient is zero the normalisation is the identity, so this "
            "quantity currently carries no information. It is retained so the "
            "comparison is explicit rather than silently assumed, and it will "
            "become meaningful only if the Stage 1 model gains a thermal "
            "dependence.",
        ),
        evidence=EvidenceClass.PHYSICS_MODELLED,
    ),
    Equation(
        key="gate_charge_C",
        expression="integral Ig dt  (trapezoid over the charge profile)",
        meaning="Total gate charge delivered over the measured gate ramp.",
        unit="C",
        inputs="Stage 1 Ig and t on the charge profile",
        assumptions=(
            "Ig includes any gate leakage, which at these biases is five to six "
            "decades below the capacitive component, so the integral is "
            "dominated by displacement current.",
        ),
        evidence=EvidenceClass.PHYSICS_MODELLED,
    ),
    Equation(
        key="ciss_gated_dvdt_V_per_s",
        expression="max |dVgs/dt| on the charge profile",
        meaning=(
            "Maximum gate slew rate driven in the simulated gate-charge ramp, "
            "the dv/dt the Ciss network actually imposes."
        ),
        unit="V/s",
        inputs="Stage 1 Vgs and t on the charge profile",
        assumptions=(
            "This is the ramp the Stage 1 script chose (0 to 6 V in 480 ns), "
            "not a datasheet condition. It is a property of the stimulus, not "
            "of the device.",
        ),
        evidence=EvidenceClass.SIMULATED,
    ),
)

# --------------------------------------------------------------------------
# 2C -- health indicators
# --------------------------------------------------------------------------

_HEALTH_INDICATORS = (
    Equation(
        key="ron_ratio_to_datasheet_typ",
        expression="Ron(T,Vgs) / RDS(on)_typ",
        meaning=(
            "On-resistance at the current bias relative to the printed typical "
            "on-resistance. 1.0 means the model matches the typical figure."
        ),
        unit="dimensionless",
        inputs="Stage 1 Ron; dc.rds_on_typ_ohm = 1.6 mohm",
        assumptions=(
            "RDS(on) is specified at one bias point (Vgs = 5 V, ID = 50 A). "
            "RON is strongly bias dependent, so this ratio is meaningful only "
            "at that point. Elsewhere it is a bias-dependent number divided by "
            "a fixed reference and is reported as such.",
        ),
        evidence=EvidenceClass.CALCULATED,
    ),
    Equation(
        key="ron_datasheet_margin_ratio",
        expression="RDS(on)_max / Ron(T,Vgs)",
        meaning=(
            "Margin of the simulated on-resistance against the printed maximum "
            "on-resistance. Below 1.0 means the datasheet maximum specification "
            "would not be met at that bias."
        ),
        unit="dimensionless",
        inputs="Stage 1 Ron; dc.rds_on_max_ohm = 2.2 mohm",
        assumptions=(
            "Same single-bias-point caveat as ron_ratio_to_datasheet_typ. The "
            "printed max is a 25 degC figure and the model has no temperature "
            "dependence, so no temperature derating is applied.",
        ),
        evidence=EvidenceClass.DATASET_DERIVED,
    ),
    Equation(
        key="drain_voltage_margin_ratio",
        expression="Vds_max_rating / max(|Vds| observed)",
        meaning=(
            "Voltage headroom remaining between the printed absolute maximum "
            "and the highest drain voltage the model was driven to."
        ),
        unit="dimensionless",
        inputs="Stage 1 Vds; ratings.vds_drain_source_V",
        assumptions=("Aggregate over the dataset, not a per-sample quantity.",),
        evidence=EvidenceClass.CALCULATED,
    ),
    Equation(
        key="leakage_ratio_to_idss",
        expression="|ID| off-state / IDSS_max",
        meaning=(
            "Off-state drain current as a fraction of the printed maximum "
            "off-state leakage, the dataset-anchored leakage budget."
        ),
        unit="dimensionless",
        inputs="Stage 1 ID, IS; dc.idss_max_25C_A = 4 uA, dc.idss_max_125C_A = 60 uA",
        assumptions=(
            "Compared against the 125 degC figure at 125 degC and the 25 degC "
            "figure at 25 degC, since IDSS is specified as temperature "
            "dependent. The Stage 1 leakage model reproduces the printed 15x "
            "ratio across 25-125 degC.",
        ),
        evidence=EvidenceClass.CALCULATED,
    ),
    Equation(
        key="conduction_loss_share",
        expression="Pcond / Ploss",
        meaning=(
            "Fraction of dissipated power flowing through the channel rather "
            "than the gate-drive path."
        ),
        unit="dimensionless",
        inputs="Stage 1 Pcond and Ploss",
        assumptions=(
            "Defined wherever Ploss is non-zero. During on-state conduction the "
            "share approaches 1; during gate transitions the Miller component "
            "dominates.",
        ),
        evidence=EvidenceClass.CALCULATED,
    ),
    Equation(
        key="cumulative_electrical_stress_J",
        expression="integral (Vds_rating_utilisation^2) dt  (within one trajectory)",
        meaning=(
            "Time-integrated squared voltage utilisation. The square matches the "
            "field-squared form of capacitive and oxide stress, so this is a "
            "proxy for accumulated dielectric/field stress rather than a linear "
            "time tally."
        ),
        unit="dimensionless (utilisation^2 * s)",
        inputs="Stage 1 Vds and t within a single trajectory",
        assumptions=(
            "The squared utilisation is a proxy for field stress. It carries no "
            "calibration to any known failure mechanism and cannot be "
            "converted to a lifetime.",
        ),
        evidence=EvidenceClass.PHYSICS_MODELLED,
    ),
    Equation(
        key="cumulative_conduction_stress_A2s",
        expression="integral (ID_rating_utilisation^2) dt  (within one trajectory)",
        meaning=(
            "Time-integrated squared current utilisation, the Joule-heating "
            "analogue of the electrical stress integral. Current density scales "
            "as the square of utilisation, so this tracks the thermomechanical "
            "load on the channel."
        ),
        unit="dimensionless (utilisation^2 * s)",
        inputs="Stage 1 ID, IS and t within a single trajectory",
        assumptions=(
            "Actual damage depends on current density, which needs die area. "
            "The squared-utilisation form is a stand-in that carries the same "
            "bias dependence without asserting an area.",
            "No calibration to a known electromigration law; not convertible to "
            "a lifetime.",
        ),
        evidence=EvidenceClass.PHYSICS_MODELLED,
    ),
)

# --------------------------------------------------------------------------
# 2D -- health-state assessment
# --------------------------------------------------------------------------

_HEALTH_STATE = (
    Equation(
        key="rating_exceedance_count",
        expression="count of rating utilisations > 1.0",
        meaning=(
            "How many printed datasheet limits the evaluated sample is outside "
            "of. This is the primary input to the health-state classification."
        ),
        unit="count",
        inputs="Stage 1 signals; printed absolute-maximum ratings",
        assumptions=(
            "The printed absolute maxima are treated as the pass/fail boundary. "
            "This is the only threshold in 2D that comes from measured data "
            "rather than from this pipeline.",
        ),
        evidence=EvidenceClass.DATASET_DERIVED,
    ),
    Equation(
        key="health_state",
        expression="f(rating_exceedance_count, utilisation margin)",
        meaning=(
            "Engineering assessment state describing how far outside its printed "
            "operating envelope the simulated device is being driven."
        ),
        unit="categorical",
        inputs="Stage 2B utilisations; printed ratings",
        assumptions=(
            "This is a STRESS-EXPOSURE state, not a measurement of degradation. "
            "With no aging data there is no observed degradation to classify, so "
            "the state describes operating severity only.",
            "Thresholds are ratios to printed ratings, not fitted values.",
            "NOT a maintenance decision and NOT a remaining-useful-life estimate.",
        ),
        evidence=EvidenceClass.CONVENTION,
    ),
)

#: Quantities a degradation study would need that this dataset cannot supply.
#: Each carries the reason it is absent, so a reader never has to guess whether
#: an omission is an oversight or a consequence of the evidence.
BLOCKED_QUANTITIES: tuple[dict[str, str], ...] = (
    {
        "quantity": "degradation rate / drift coefficient",
        "reason": (
            "No aging axis exists. aging_time_h is NaN in every one of the "
            "15,904 rows because the source dataset contains no stress-hours, "
            "no bias-hour and no pulse-count history."
        ),
    },
    {
        "quantity": "activation energy for thermal acceleration",
        "reason": (
            "No temperature-acceleration data. Choosing an Ea would be "
            "inventing an aging coefficient, which the project rules forbid."
        ),
    },
    {
        "quantity": "remaining useful life (RUL)",
        "reason": (
            "RUL requires a validated degradation trajectory. None exists, so "
            "no RUL is computed, estimated or reported anywhere in Stage 2."
        ),
    },
    {
        "quantity": "switching loss per cycle (Eon, Eoff)",
        "reason": (
            "Blocked by the Stage 1 loss model itself, not by resolution. The "
            "budget is exactly Ploss = Pcond + Psw (residual 0.0 W over all "
            "15904 rows), so there is no output-capacitance charge/discharge "
            "channel and no gate-drive dissipation channel: Coss is never "
            "charged during a transition. The simulated load line is therefore "
            "exactly reversible, turn-off being the bit-level reverse of turn-on "
            "(max relative asymmetry 6.6e-16), and all three cycles are "
            "bit-identical. A hard-switched device cannot behave this way, since "
            "turn-on charges Coss and clamps the inductor current into the "
            "low-side device while turn-off does not. The independent CV sweep "
            "gives Eoss = 11.81 uJ and none of it appears in the transition "
            "integrals. The load line is in fact sampled finely enough to "
            "resolve (18 points at 1 ns across the whole slew), so the "
            "obstruction is the missing physics, not the sample rate. The "
            "resulting path integrals are reported as reversible path "
            "diagnostics and are never called switching losses. Separately, the "
            "gate-charge profile integrates QG = 16.67 nC against the printed "
            "34 nC, so gate charge cannot substitute for the missing channel "
            "either."
        ),
    },
    {
        "quantity": "junction temperature above case",
        "reason": (
            "Every thermal resistance in the dataset is printed as TBD and the "
            "Stage 1 model has no thermal network, so Tj is identically Tcase."
        ),
    },
    {
        "quantity": "package power rating normalisation",
        "reason": "PTOT is printed as TBD, so no dissipated-power limit exists to normalise against.",
    },
    {
        "quantity": "temperature coefficient of RON",
        "reason": (
            "The Stage 1 model's RON has no temperature dependence, giving a "
            "measured coefficient of exactly 0 /degC against a real GaN HEMT "
            "value that is strongly positive."
        ),
    },
    {
        "quantity": "experimental health labels",
        "reason": "No measured device, no aging experiment and no ground-truth health state exists in the inputs.",
    },
)


ALL_EQUATIONS: tuple[Equation, ...] = (
    _ELECTRICAL_STRESS + _LOSS_STRESS + _THERMAL_STRESS + _RON_STRESS
    + _HEALTH_INDICATORS + _HEALTH_STATE
)

EQUATIONS_BY_KEY: dict[str, Equation] = {e.key: e for e in ALL_EQUATIONS}


def equation(key: str) -> Equation:
    """Look up a registered equation, failing loudly on a typo."""
    try:
        return EQUATIONS_BY_KEY[key]
    except KeyError as exc:  # pragma: no cover - programming error
        raise KeyError(
            f"no registered equation {key!r}; registered keys are "
            f"{sorted(EQUATIONS_BY_KEY)}"
        ) from exc


def registry() -> dict[str, Any]:
    """The whole registry plus the blocked list, for embedding in reports."""
    return {
        "equations": [e.to_dict() for e in ALL_EQUATIONS],
        "counts": {
            "total": len(ALL_EQUATIONS),
            "by_evidence": {
                cls.value: sum(1 for e in ALL_EQUATIONS if e.evidence is cls)
                for cls in EvidenceClass
            },
        },
        "blocked_quantities": [dict(b) for b in BLOCKED_QUANTITIES],
        "policy": (
            "No equation in this registry contains a degradation law, an aging "
            "coefficient or a failure threshold, because no aging evidence "
            "exists to support one."
        ),
    }
