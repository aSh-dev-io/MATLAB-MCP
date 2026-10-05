# Phase 2B - Physics-informed stress and exposure model

## Scope and what this report is not

This report is a stress and exposure accounting of a Digital-Twin simulation. It is not a degradation assessment, because the dataset contains no aging axis, no repeated measurement and no experimental health label. No degradation law, aging coefficient, failure threshold or remaining-useful-life figure appears anywhere in Phase 2, and none could be supported by these inputs. None of the numbers below is a measurement of a real device.

This framework currently provides physics-informed stress/degradation assessment based on the available device and Digital-Twin data. Experimental aging data is required to validate a true degradation-prediction model.

## Two definitional corrections that affect every number below

### The channel current is not `ID + IS`

ID + IS is NOT the channel current: the Stage 1 node balance ID + IG + IS = 0 makes ID + IS
= -IG, which is essentially zero. The conduction-only channel current Ich is not exported,
but it is recoverable as Pcond / Vds. It coincides with ID on quiescent rows and falls below
ID by the displacement current wherever Vds moves.

### `Pcond` is not `Vds * ID`

Pcond is Vds times a conduction-only channel current, not Vds times the exported ID. The two
coincide where the drain node is quiescent and separate by exactly the output-capacitance
displacement current where it is moving. Pcond and Vds*ID are therefore distinct quantities:
they must not be summed, and their difference is not a model error and not a degradation
signal.

| Where | Rows | Separation `abs(ID - Ich)` (A) | `Coss*abs(dv/dt)` predicts (A) | Ratio |
|---|---|---|---|---|
| quiescent rows | 7510 | 4.1444e-07 | n/a, the drain node is not moving | 5.0547e-10 |
| switching load line | 84 | 14.4468 | 14.4545 | 1.00069 |

Verdict: the separation between ID and the conduction-only current is explained by output-capacitance displacement charging. On the load line the ratio stays between 0.999996 and 1.004837 across every row tested, so the displacement attribution is tight rather than merely plausible.

The load line is excluded where the rate is zero: the segment with Vgs still below threshold has Vds pinned at 100 V, so there is no displacement current and the residual gap there is pure leakage.

## Data structure: trajectories and paths

A trajectory is one bias point (profile, operating_point_key) held over its own slice of a
shared time axis. All DC time integrals are taken within a trajectory, because integrating
across the shared axis would sum concurrent trajectories.

The switching load line is not a trajectory. Its 18 bias points each own a handful of rows
on the shared clock, so the slew only exists when the samples of one transition window are
read across bias points. Load-line rows are told from DC holds by trajectory size, and
windows are recovered by gap detection, so no Stage 1 profile label is trusted.

The dataset resolves into 1804 trajectories. Because Stage 1 placed several independent trajectories on one shared monotonic clock, integrating over a whole profile would add concurrent trajectories together and produce a number with no physical meaning.

## Coverage and rated-envelope exceedance

| Profile | Samples | Share | RON-valid | Outside rated envelope |
|---|---|---|---|---|
| capacitance | 453 | 2.85 % | 2 | 300 |
| charge | 481 | 3.02 % | 0 | 320 |
| output | 405 | 2.55 % | 27 | 318 |
| switching | 14120 | 88.78 % | 6006 | 6072 |
| thermal | 324 | 2.04 % | 12 | 320 |
| transfer | 121 | 0.76 % | 97 | 0 |
| **total** | 15904 | 100.00 % | 6144 | 7330 (46.1 %) |

Exceedance is dominated by the characterisation profiles rather than by operation: the thermal sweep exceeds its rating on almost every sample and the C-V and gate-charge sweeps drive the drain and gate terminals hard purely to bias a measurement. The transfer profile, which stays inside the envelope throughout, is the sweep that actually characterises on-resistance. A pooled exceedance count therefore says little about stress in service.

## Switching transitions

| Quantity | Value |
|---|---|
| transition windows recovered | 6 |
| turn-on / turn-off | 3 / 3 |
| load-line bias points | 18 |
| DC hold bias points | 2 |
| samples per transition | 18 in each of the 6 windows |
| solver sample interval | 1.00 ns |
| mean turn-on path integral | 170.848 uJ |
| mean turn-off path integral | 170.855 uJ |
| spread across windows | 3.47e-03 uJ |
| **switching loss available** | **no** |

### Why switching loss is not available

Stage 1's loss budget is exactly Ploss = Pcond + Psw (residual 0.0 W over all 15904 rows).
Psw is the Miller channel only, contributing 0.07 % of the path integral. There is no
output-capacitance charge/discharge channel and no gate-drive dissipation channel, so Coss
is never charged during a transition. The consequence is measurable: the simulated load line
is exactly reversible, with turn-off the bit-level reverse of turn-on. A hard-switched
device cannot behave this way, because turn-on charges Coss and clamps the inductor current
into the low-side device while turn-off does not. The energies below are therefore reported
as reversible channel-conduction path integrals and are explicitly NOT switching losses.

### Reversibility test

| Test | Result |
|---|---|
| turn-off is the reverse of turn-on | yes |
| max relative asymmetry | 6.5532e-16 |
| all cycles bit-identical | yes |
| max cycle-to-cycle difference | 0.0 W |

Reversibility is a property of the Stage 1 loss model, not of a GaN HEMT. It means the
exported trajectory has no capacitive state, so turn-on and turn-off are the same integral
traversed in opposite directions.

All cycles are bit-identical, which confirms the excitation is a deterministic scripted
waveform rather than a stochastic simulation.

### How these transitions must be read

A path integral of channel power along a reversible trajectory is a property of the path,
not a device loss. It cannot be compared to a datasheet switching-loss figure, and it must
not be multiplied by a switching frequency.

A transition is sampled at the solver output interval, which is the finest resolution the
dataset offers. Peaks within one sample interval are invisible, so every energy and rate
here is a lower bound.

The sampled load line spans Vgs 0.263 V to 4.737 V. The 0 V to 0.263 V gate segment appears
only in the off-state DC hold, and the final Vds = 1.61 V endpoint only in the on-state
hold. Those are separate trajectories on the same clock, so the sampled path is not one
continuous waveform and the transition energy omits both end segments.

Peak |ID| is 809.8 A, which is 7.04x the 115 A continuous rating and 0.96x the 840 A pulse
rating, with 20.8 kW peak instantaneous dissipation and 10.05 kW mean over the 17 ns slew.
The Stage 1 excitation has no external loop inductance, so nothing limits di/dt and the
drain node cannot sag; that is why 380 A and 52 V coexist. These transitions are an
excitation artefact, not a representative operating condition.

### Per-transition detail

| # | Kind | Samples | Vgs start->end (V) | Vds start->end (V) | Peak `\|ID\|` (A) | Peak loss (W) | Path integral (uJ) | Peak `\|dv/dt\|` (V/s) |
|---|---|---|---|---|---|---|---|---|
| 0 | turn_on | 18 | 0.263 -> 4.737 | 100.00 -> 4.91 | 766.6 | 20794.2 | 170.848 | 1.022e+10 |
| 1 | turn_off | 18 | 4.737 -> 0.263 | 4.91 -> 100.00 | 809.8 | 20792.8 | 170.855 | 1.022e+10 |
| 2 | turn_on | 18 | 0.263 -> 4.737 | 100.00 -> 4.91 | 766.6 | 20794.2 | 170.848 | 1.022e+10 |
| 3 | turn_off | 18 | 4.737 -> 0.263 | 4.91 -> 100.00 | 809.8 | 20792.8 | 170.855 | 1.022e+10 |
| 4 | turn_on | 18 | 0.263 -> 4.737 | 100.00 -> 4.91 | 766.6 | 20794.2 | 170.848 | 1.022e+10 |
| 5 | turn_off | 18 | 4.737 -> 0.263 | 4.91 -> 100.00 | 809.8 | 20792.8 | 170.855 | 1.022e+10 |

The path-integral column is **not** a switching loss and must not be compared with a datasheet switching-energy figure or multiplied by a switching frequency.

## On-resistance against the datasheet

| Quantity | Value |
|---|---|
| printed test condition | Vgs = 5.0 V, IDS = 50.0 A, VDS = 0.08 V |
| printed RDS(on) typical / max | 0.0016 / 0.0022 ohm |
| nearest simulated sample | transfer profile, Vgs = 5.0 V, Vds = 0.08 V, ID = 50.06 A |
| RON there | 1.5980 mohm |
| ratio to printed typical | 0.998765 |
| margin to printed maximum | 1.3767 |
| verdict | model reproduces the printed typical on-resistance |
| RON-valid samples | 6144 of 15904 (38.63 %) |

This is the single point in the whole project where the Digital Twin is compared with a measured datasheet number, so it is evaluated exactly at the printed test condition rather than at a convenient nearby bias.

### Temperature dependence

| Quantity | Value |
|---|---|
| matched bias points | 6 |
| RON(125 degC)/RON(25 degC), min / median / max | 0.999999977 / 0.999999985 / 0.999999993 |
| fitted coefficient | -1.480e-10 /degC |
| temperature normalisation is the identity | yes |

The Stage 1 model's on-resistance has no temperature dependence: the ratio is exactly 1 at
every matched bias. A real GaN HEMT has a strongly positive coefficient. This is a model
limitation, not a device property.

Unavailable: the model coefficient is zero to within 1e-6 /K, so temperature normalisation
of RON would divide by one and add no information. Reported as unavailable rather than as a
normalisation factor of exactly 1.0, which would misleadingly imply a validated RON(T)
model.

## Thermal exposure

| Quantity | Value |
|---|---|
| Tj equals Tcase | yes |
| case temperatures present | 25, 125 degC |
| junction rise above case available | no |
| package thermal resistance available | no |
| margin to printed Tj max | 25.0 degC |
| max case rise above nominal | 100.0 degC |

Every thermal resistance in the source dataset is printed as TBD and the Stage 1 model has
no thermal network, so Tj is identically Tcase and no junction temperature above case can be
computed.

An apparent thermal resistance of 1.83e-19 K/W can be fitted to the thermal profile, but it is reported only to document the absence of a thermal model.
A property of how the Stage 1 script drove Tcase, not of the package. Reported to document
the absence of a thermal model, never as a device parameter.

## Capacitance-derived energy

| Quantity | Value | Note |
|---|---|---|
| printed Coss / Crss | 1150 pF / 19.0 pF | datasheet |
| CV test Vds | 75.0 V | datasheet |
| Coss at 0 V / at the test point | 7063 pF / 1150 pF | simulated |
| integrated Qoss | 249.70 nC | printed Qoss is 187.00 nC |
| Eoss | 11.811 uJ | Eoss = integral \|Vds * Coss(Vds)\| dVds over the measured CV sweep, the hard-switching output-capacitance loss at the datasheet CV frequency. |

Integrating the simulated Coss(Vds) gives more charge than the printed Qoss because the
depletion model places a large Coss at low Vds. The capacitance is calibrated at the 75 V
test point, where it matches the printed value exactly, so the disagreement is a shape
difference at low drain voltage rather than a calibration error.

This Eoss is the direct evidence that the switching integrals are incomplete: a hard-switched turn-on must charge Coss, and none of this energy appears in the transition path integrals.

## Gate charge

| Quantity | Value |
|---|---|
| printed QG / QGS / QGD | 34.00 / 10.80 / 4.70 nC |
| gate ramp | 0.0 V to 6.0 V over 480.00 ns |
| integrated gate charge | 12.647 nC |
| Stage 1 logged Qg | 16.666 nC |
| integrated / printed QG | 0.371975 |
| logged / integrated | 1.31773 |
| peak gate current | 1.4 A |

The Stage 1 logged Qg does not equal the integral of the logged gate current. The logged
value comes from the model's own capacitance integral, so the two disagree. Both are
reported; neither is silently preferred.

The simulated total gate charge is a fraction of the printed figure, and the Stage 1
parameter block itself records qg_is_consistent = False. Gate charge is therefore not a
validated quantity and no switching-loss figure is derived from it.

## Quantities this phase refuses to compute

**degradation rate / drift coefficient**

  No aging axis exists. aging_time_h is NaN in every one of the 15,904 rows because the
  source dataset contains no stress-hours, no bias-hour and no pulse-count history.

**activation energy for thermal acceleration**

  No temperature-acceleration data. Choosing an Ea would be inventing an aging coefficient,
  which the project rules forbid.

**remaining useful life (RUL)**

  RUL requires a validated degradation trajectory. None exists, so no RUL is computed,
  estimated or reported anywhere in Stage 2.

**switching loss per cycle (Eon, Eoff)**

  Blocked by the Stage 1 loss model itself, not by resolution. The budget is exactly Ploss =
  Pcond + Psw (residual 0.0 W over all 15904 rows), so there is no output-capacitance
  charge/discharge channel and no gate-drive dissipation channel: Coss is never charged
  during a transition. The simulated load line is therefore exactly reversible, turn-off
  being the bit-level reverse of turn-on (max relative asymmetry 6.6e-16), and all three
  cycles are bit-identical. A hard-switched device cannot behave this way, since turn-on
  charges Coss and clamps the inductor current into the low-side device while turn-off does
  not. The independent CV sweep gives Eoss = 11.81 uJ and none of it appears in the
  transition integrals. The load line is in fact sampled finely enough to resolve (18 points
  at 1 ns across the whole slew), so the obstruction is the missing physics, not the sample
  rate. The resulting path integrals are reported as reversible path diagnostics and are
  never called switching losses. Separately, the gate-charge profile integrates QG = 16.67
  nC against the printed 34 nC, so gate charge cannot substitute for the missing channel
  either.

**junction temperature above case**

  Every thermal resistance in the dataset is printed as TBD and the Stage 1 model has no
  thermal network, so Tj is identically Tcase.

**package power rating normalisation**

  PTOT is printed as TBD, so no dissipated-power limit exists to normalise against.

**temperature coefficient of RON**

  The Stage 1 model's RON has no temperature dependence, giving a measured coefficient of
  exactly 0 /degC against a real GaN HEMT value that is strongly positive.

**experimental health labels**

  No measured device, no aging experiment and no ground-truth health state exists in the
  inputs.

## Column provenance for Phase 2B additions

| Column | Unit / meaning |
|---|---|
| trajectory_id | profile::operating_point_key; one independent bias point |
| transition_window | int; reconstructed switching transition, NA for DC rows |
| transition_kind | turn_on \| turn_off; NA for DC rows |
| vgs_gate_window_utilisation | ratio; \|Vgs\| against the sign-selected gate limit |
| id_pulse_rating_utilisation | ratio; \|ID\| / 840 A pulse rating |
| case_rise_above_ambient_C | degC; Tcase - 25 degC |
| junction_rating_utilisation | ratio; Tj / 150 degC, equals the case ratio |
| conduction_power_rating_product_ratio | ratio; \|Pcond\| / (115 A * 150 V) |
| conduction_loss_share | fraction; Pcond / Ploss |
| dvdt_path_V_per_s | V/s; along the transition path, else the trajectory |
| didt_path_A_per_s | A/s; along the transition path, else the trajectory |
| rating_exceedance_count | int; printed limits exceeded by this sample |

The Phase 2A columns `vds_rating_utilisation`, `vgs_rating_utilisation`, `id_continuous_rating_utilisation` and `is_rating_exceeded` are reused unchanged. The gate-drive ratio here is a separate column because the printed gate window is asymmetric (+6 V / -4 V) and the Stage 2A ratio uses the positive limit for both signs.

## Reference anchors

| Anchor | Value | Unit | Provenance | Usable |
|---|---|---|---|---|
| VDS_ABS_MAX | 150 | V | DATASET_DERIVED | yes |
| VGS_ABS_MAX | 6 | V | DATASET_DERIVED | yes |
| VGS_ABS_MIN | -4 | V | DATASET_DERIVED | yes |
| VGS_PULSE_MAX | 6.5 | V | DATASET_DERIVED | yes |
| ID_CONTINUOUS_25C | 115 | A | DATASET_DERIVED | yes |
| ID_PULSE_25C | 840 | A | DATASET_DERIVED | yes |
| ID_PULSE_150C | 640 | A | DATASET_DERIVED | yes |
| TJ_MAX | 150 | degC | DATASET_DERIVED | yes |
| TSTG_MAX | 150 | degC | DATASET_DERIVED | yes |
| PD_TOTAL | n/a | W | UNAVAILABLE | no |
| RDS_ON_TYP | 0.0016 | Ohm | DATASET_DERIVED | yes |
| RDS_ON_MAX | 0.0022 | Ohm | DATASET_DERIVED | yes |
| RDS_ON_VGS | 5 | V | DATASET_DERIVED | yes |
| RDS_ON_IDS | 50 | A | DATASET_DERIVED | yes |
| RDS_ON_VDS_SPEC | 0.08 | V | CALCULATED | yes |
| VTH_MIN | 1.1 | V | DATASET_DERIVED | yes |
| IDSS_MAX_25C | 4.0000e-06 | A | DATASET_DERIVED | yes |
| IDSS_MAX_125C | 6.0000e-05 | A | DATASET_DERIVED | yes |
| BR_DSS_MIN | 150 | V | DATASET_DERIVED | yes |
| FOM_QG_RON | 54.4 | nC*mohm | DATASET_DERIVED | yes |
| QG_PRINTED | 3.4000e-08 | C | DATASET_DERIVED | yes |
| QGS_PRINTED | 1.0800e-08 | C | DATASET_DERIVED | yes |
| QGD_PRINTED | 4.7000e-09 | C | DATASET_DERIVED | yes |
| QOSS_PRINTED | 1.8700e-07 | C | DATASET_DERIVED | yes |
| QGD_TEST_VDS | 75 | V | DATASET_DERIVED | yes |
| QGD_TEST_IDS | 50 | A | DATASET_DERIVED | yes |
| CISS_REF | 4.8200e-09 | F | DATASET_DERIVED | yes |
| COSS_REF | 1.1500e-09 | F | DATASET_DERIVED | yes |
| CRSS_REF | 1.9000e-11 | F | DATASET_DERIVED | yes |
| CAPS_TEST_VDS | 75 | V | DATASET_DERIVED | yes |
| CAPS_TEST_F | 1.0000e+06 | Hz | DATASET_DERIVED | yes |
| TCASE_NOM | 25 | degC | DATASET_DERIVED | yes |
| SAMPLE_TIME | 1.0000e-09 | s | DATASET_DERIVED | yes |
| SWITCH_T_ON | 2.0000e-06 | s | DATASET_DERIVED | yes |
| SWITCH_T_OFF | 2.0000e-06 | s | DATASET_DERIVED | yes |
| SWITCH_N_CYCLES | 3 | count | DATASET_DERIVED | yes |
| SWITCH_N_RISE | 20 | count | DATASET_DERIVED | yes |
| SWITCH_VBUS | 100 | V | DATASET_DERIVED | yes |
| SWITCH_RLOAD | 0.12 | Ohm | DATASET_DERIVED | yes |
| SWITCH_VGS_ON | 5 | V | DATASET_DERIVED | yes |
| SWITCH_VGS_OFF | 0 | V | DATASET_DERIVED | yes |
| VDSAT | 1.66303 | V | CALCULATED | yes |
| K_AMP_PER_V2 | 161.917 | A/V^2 | CALCULATED | yes |
| LEAK_TEMP_RATIO | 15 | dimensionless | CALCULATED | yes |
| IGSS_TEMP_RATIO | 20 | dimensionless | CALCULATED | yes |

Unusable anchors: PD_TOTAL. Every value above is carried with its source, so a reader can tell a printed datasheet rating from a value solved out of the dataset or from an assumption.

Generated by `ganstage2.stress` from stage1_output.mat; see `equations.py` for all 33 registered equations.
