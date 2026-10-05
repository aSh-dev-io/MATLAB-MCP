# Stage 2 Phase 2A Report

**Scope:** ingestion, data-quality validation and physics-consistency screening of the
Stage 1 output, producing a structured dataset for Phase 2B.

**Not in this phase:** degradation modelling, health-indicator weighting,
health-state classification, remaining useful life, predictive accuracy, dashboard.

- Authoritative source: `stage1_output.mat`
- Device: onsemi NTLEF2D2N15GN1, P1 (preliminary), July 2026, enhancement-mode AlGaN/GaN HEMT
- Dataset: **15904 rows x 51 columns** across 6 profiles
- Evidence class: `calculated_from_stage1_simulation`
- Stage 1 label: `MODEL PREDICTION - NOT VALIDATED`

## Headline findings

1. **The Stage 1 CSV is silently corrupt.** Every data row carries a trailing
   delimiter, giving one more field than the header declares. A default
   `pandas.read_csv` accepts this, promotes field 0 to the index and shifts every
   signal one column left: `profile` becomes numeric, every signal is mislabelled,
   and `Crss_F` becomes all-NaN. Nothing in the file signals it. Phase 2A parses
   field-count-explicitly, repairs in memory, and verifies the repair against the MAT.
   The MAT is unaffected and is used as the authoritative source.
2. **The exported RON column is not a resistance over most of its range.** Stage 1
   masks RON only on `ID > 0.1 A`, then evaluates `Vds/ID` across the whole sweep,
   including deep saturation and the off state.
   Only **6144 of 15904 rows (38.6%)** are both
   conducting and in the triode region. Stage 2 adds `ron_valid` plus a reason code
   and does not consume the raw column.
3. **The dataset cannot support temperature-aware resistance comparison.** The Stage 1
   channel equation has no temperature term; only leakage scales. Drain current at
   125 degC equals drain current at 25 degC to within numerical noise. There is no
   printed RON(T) coefficient either, so `ron_temp_normalised_ohm` is present but
   explicitly empty rather than filled with an invented coefficient.
4. **There is no aging data and no thermal model.** Every profile is a single
   operating-condition sweep on one simulated device at one instant, so permanent
   degradation cannot be separated from an operating change. `Tj` equals `Tcase`
   exactly because all thermal resistances and PTOT are TBD in the datasheet.
5. Open blockers carried into Phase 2B: `P09, P10, P12, Q15`.

## Available signals

| Signal | Unit | Provenance | Phase 2A notes |
| --- | --- | --- | --- |
| `t_s` | s | model prediction | simulation time within one sweep; **not** an aging axis |
| `vgs_V` | V | model prediction | gate drive; conditioning variable |
| `vds_V` | V | model prediction | drain bias; conditioning variable |
| `tcase_C` | degC | model prediction | case temperature; conditioning variable, the only temperature available |
| `id_A` | A | model prediction | drain current incl. displacement + leakage |
| `ig_A` | A | model prediction | gate current incl. Miller + gate leakage |
| `is_A` | A | model prediction | source current, defined as -(ID+IG) so KCL closes exactly |
| `ron_stage1_ohm` | Ohm | model prediction | **raw, ungated** Vds/ID; use `ron_valid` before reading it |
| `pcond_W` | W | model prediction | channel power Vds*Ich, not Vds*ID |
| `psw_W` | W | model prediction | Miller-capacitance power (Vds x abs(iCgd)); **not** switching loss |
| `ploss_W` | W | model prediction | total dissipated power, Pcond + Psw |
| `tj_C` | degC | model prediction | junction temperature; equals tcase_C (no thermal model) |
| `qg_C` | C | model prediction | Qg = Qgs + Qgd incl. Cgd depletion charge; use delta-Qg |
| `qgd_C` | C | model prediction | Miller charge |
| `ciss_F` | F | model prediction | input capacitance |
| `coss_F` | F | model prediction | output capacitance |
| `crss_F` | F | model prediction | Miller capacitance; **lost by a naive CSV read**, intact in the MAT |

- Profiles: capacitance, charge, output, switching, thermal, transfer

## Operating conditions

| Profile | Role | Rows | Vgs (V) | Vds range (V) | Tcase (C) | Op. points | RON-valid | App. op. |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `capacitance` | cv_characterisation | 453 | 0.0, 4.0, 5.0 | 0.000..150.000 | 25.0 | 453 | 2 | 0 |
| `charge` | gate_charge_characterisation | 481 | 0.0..6.0 (481 distinct) | 75.000..75.000 | 25.0 | 481 | 0 | 0 |
| `output` | dc_output_sweep | 405 | 2.0..5.5 (5 distinct) | 0.000..20.000 | 25.0 | 405 | 27 | 0 |
| `switching` | switching_transient | 14120 | 0.0..5.0 (20 distinct) | 1.610..100.000 | 25.0 | 20 | 6006 | 22 |
| `thermal` | dc_thermal_sweep | 324 | 3.0, 5.0 | 0.000..40.000 | 25.0, 125.0 | 324 | 12 | 0 |
| `transfer` | dc_transfer_sweep | 121 | 0.0..6.0 (121 distinct) | 0.080..0.080 | 25.0 | 121 | 97 | 0 |

Every row carries an `operating_point_key` (`vgs`\|`vds`\|`tcase`), so Phase 2B can
group like-for-like conditions instead of correlating across a sweep.

## Data quality

Summary: **1 BLOCKED**, **1 FAIL**, **1 INFO**, **11 PASS**, **1 WARN**.

| ID | Check | Status | Severity | Detail |
| --- | --- | --- | --- | --- |
| Q01 | Stage 1 artefacts present | PASS | HIGH | mat=yes, csv=yes, json=yes, mapping=yes |
| Q02 | Canonical schema complete | PASS | HIGH | 18/18 columns present |
| Q03 | Profile set matches the declared inventory | PASS | HIGH | found ['capacitance', 'charge', 'output', 'switching', 'thermal', 'transfer']; expected ['capacitance', 'charge', 'output', 'switching', 'thermal', 'transfer'] |
| Q04 | Stage 1 CSV is well formed | FAIL | HIGH | Every data row carries a trailing delimiter, so each record has 19 fields against a 18-column header. A default pandas read_csv silently promotes field 0 to the index and shifts all signals one column left, mislabelling every signal and nulling Crss_F. Repaired in memory by dropping the surplus empty trailing field; the Stage 1 file is left unmodified. |
| Q05 | Repaired CSV matches the MAT sample for sample | PASS | HIGH | 15904 samples compared across 17 numeric signals, joined on (profile, sample ordinal); max relative difference 4.943e-10 (column id_A). Confirms the in-memory repair is exact and the MAT is usable as the authoritative source. |
| Q06 | No infinite values | PASS | HIGH | 0 samples contain +/-inf |
| Q07 | Missing-value inventory | WARN | MEDIUM | ron_stage1_ohm: 8141. All are confined to ron_stage1_ohm, where Stage 1 itself writes NaN for ID <= 0.1 A. No other signal has gaps. |
| Q08 | Simulation time strictly increasing within each profile | PASS | MEDIUM | 6 profiles checked |
| Q09 | Sampling interval uniform and equal to the solver step | PASS | LOW | median dt = 1.000000e-09 s, spread = 1.694e-21 s; solver declares 1e-09 s |
| Q10 | No duplicate (profile, time) samples | PASS | LOW | 0 duplicate keys |
| Q11 | Summary JSON profile inventory matches the MAT | PASS | MEDIUM | json=['capacitance', 'charge', 'output', 'switching', 'thermal', 'transfer'], mat=['capacitance', 'charge', 'output', 'switching', 'thermal', 'transfer'] |
| Q12 | Summary JSON sample counts match the MAT | PASS | MEDIUM | all profile counts agree |
| Q13 | Stage 1 dataset defects propagated into Stage 2 | INFO | INFO | Stage 1 recorded 4 dataset defects: ['curves_absent', 'qg_not_sum_of_parts', 'qgd_test_condition', 'thermal_absent']. These are dataset properties, not ingestion failures, and remain open in Stage 2. |
| Q14 | Evidence class recorded as unvalidated model output | PASS | INFO | Stage 1 label: 'MODEL PREDICTION - NOT VALIDATED'. No experimental validation data exists anywhere in the inputs, so no Stage 2 output may be described as measured or experimentally validated. |
| Q15 | Aging axis present in the source data | BLOCKED | BLOCKER | There is no aging time, no repeated measurement of the same device and no second device instance. t_s is simulation time within a single sweep. Permanent degradation cannot be separated from operating-condition changes. |

### CSV ingestion defect

15904 of 15904 rows carried a surplus trailing empty field against a 18-column header (`profile, t_s, Vgs_V, Vds_V, Tcase_C, ID_A, IG_A, IS_A, RON_ohm, Pcond_W, Psw_W, Ploss_W, Tj_C, Qg_C, Qgd_C, Ciss_F, Coss_F, Crss_F`).

## Physics consistency

| ID | Check | Status | Severity | Detail |
| --- | --- | --- | --- | --- |
| P01 | Node current balance (ID + IG + IS = 0) | PASS | HIGH | max \|residual\| = 0.000e+00 A over 15904 samples (tolerance 1.0e-09 A) |
| P02 | Power balance (Ploss = Pcond + Psw) | PASS | HIGH | max \|residual\| = 0.000e+00 W over 15904 samples (tolerance 1.0e-09 W) |
| P03 | Pcond is channel power (Vds*Ich) and carries a displacement residual | INFO | MEDIUM | Pcond is Vds*Ich with Stage 1's conduction-only channel current, while the exported ID additionally carries displacement and leakage current, so the two coincide only where nothing is moving: the median residual over dissipative samples is 6.674e-07 W. Largest gap over 705 saturated DC samples = 3.775e+01 W, at most 20.2 % of channel power. That gap implies a 3.106e+00 A displacement current, which exceeds the worst-case leakage (3.098e-05 A) by 100235x, so it is displacement charging and not a model error. The DC sweeps step Vds by 0.5 V per 1 ns sample, so these samples are not quasi-static and the residual is material here. On the switching load line the gap is far larger (up to ~843 W) because \|dv/dt\| reaches ~6e9 V/s. Downstream code must treat Pcond and Vds*ID as distinct quantities, must not add them together, and must not read the residual as a degradation signal. |
| P04 | Intrinsic capacitance positivity (Cds, Cgs >= 0) | PASS | HIGH | min Cds = 6.1625e-10 F, min Cgs = 1.0001e-09 F; 0 negative samples |
| P05 | Gate charge monotonicity during the charge sweep | PASS | HIGH | Qg starts at 4.7000e-09 C and ends at 1.6666e-08 C; 0 decreasing steps |
| P06 | Qg initial value at the start of the charge sweep | WARN | MEDIUM | Qg(0) = 4.7000e-09 C, not 0. Stage 1 defines Qg = Qgs + Qgd where Qgd includes the Cgd depletion charge at VDS = 75 V, which equals the printed QGD = 4.7 nC. Qg is therefore an absolute charge referenced to the drain bias; Phase 2B must use delta-Qg over a gate excursion, not Qg itself. |
| P07 | Exported RON interpretable as a conduction resistance | WARN | HIGH | 6144/15904 samples (38.6%) are both conducting and in the triode region. Stage 1 masks RON only on ID > 0.1 A, so the remainder report Vds/ID in saturation or in the off state, where the ratio is not a resistance. Phase 2B must use ron_valid, not the raw column. |
| P08 | Stage 1 RON agrees with recomputed Vds/ID where valid | INFO | INFO | max relative difference = 0.000e+00 over 6144 gated samples |
| P09 | Temperature dependence present in the channel current | BLOCKED | BLOCKER | Across the thermal sweep the 25->125 degC drain-current ratio deviates from 1.0 by at most 7.163e-08 (i.e. no dependence). The Stage 1 channel equation has no temperature term; only leakage scales. A temperature-normalised RON cannot be computed from this dataset without inventing a coefficient, so it is left unavailable. |
| P10 | Thermal model present (Tj rises above Tcase) | BLOCKED | BLOCKER | max \|Tj - Tcase\| = 0.000e+00 degC. All thermal resistances and PTOT are TBD in the datasheet, so junction temperature is not modelled and no thermal stress indicator is available. |
| P11 | Samples outside absolute-maximum or continuous ratings | WARN | MEDIUM | 7330 samples exceed a printed rating, driven by the datasheet characterisation sweeps (peak \|ID\| = 2066.3 A against a 115 A continuous rating). Legitimate as measurement conditions, but they are not application operating points and must be excluded from stress indicators. |
| P12 | Aging / stress-history measurements present | BLOCKED | BLOCKER | Every Stage 1 profile is a single operating-condition sweep on one simulated device at one point in time. There is no time-separated repetition, no stress history and no second device instance, so no permanent degradation can be separated from an operating change. |

## Structured dataset schema

`stage2_dataset.csv` - one row per Stage 1 sample, 51 columns.

| Column | Unit / meaning | Origin |
| --- | --- | --- |
| `profile` | categorical | stage1 |
| `t_s` | s | stage1 |
| `vgs_V` | V | stage1 |
| `vds_V` | V | stage1 |
| `tcase_C` | degC | stage1 |
| `id_A` | A | stage1 |
| `ig_A` | A | stage1 |
| `is_A` | A | stage1 |
| `ron_stage1_ohm` | Ohm | stage1 |
| `pcond_W` | W | stage1 |
| `psw_W` | W | stage1 |
| `ploss_W` | W | stage1 |
| `tj_C` | degC | stage1 |
| `qg_C` | C | stage1 |
| `qgd_C` | C | stage1 |
| `ciss_F` | F | stage1 |
| `coss_F` | F | stage1 |
| `crss_F` | F | stage1 |
| `sample_index` | index within profile | stage2_derived |
| `operating_point_key` | vgs\|vds\|tcase snapped to the configured rounding | stage2_derived |
| `i_leak_A` | A; Stage 1 leakage equation | stage2_derived |
| `conduction_threshold_A` | A; conduction_leakage_multiple x i_leak_A | stage2_derived |
| `is_conducting` | bool; \|ID\| >= conduction threshold | stage2_derived |
| `is_positive_vds` | bool | stage2_derived |
| `is_triode` | bool; VDS <= VDSAT(VGS) | stage2_derived |
| `vdsat_vgs_V` | V; Stage 1 knee voltage at this VGS | stage2_derived |
| `operating_regime` | zero_bias \| off_or_leakage \| triode_ohmic \| saturation_or_cvdrive | stage2_derived |
| `ron_static_ohm` | Ohm; VDS/ID, NaN unless ron_valid | stage2_derived |
| `ron_valid` | bool; conducting AND triode AND VDS>0 | stage2_derived |
| `ron_valid_reason` | why ron_valid is False | stage2_derived |
| `ron_differential_ohm` | Ohm; dVDS/dID from the DC sweep, NaN if unavailable | stage2_derived |
| `ron_differential_available` | bool | stage2_derived |
| `ron_temp_normalised_ohm` | always NaN in Phase 2A | stage2_derived |
| `ron_tempnorm_status` | reason temperature normalisation is unavailable | stage2_derived |
| `profile_role` | what the profile is for | stage2_derived |
| `is_characterisation_sweep` | bool | stage2_derived |
| `is_application_operating_point` | bool | stage2_derived |
| `vds_rating_utilisation` | ratio; \|VDS\| / 150 V | stage2_derived |
| `vgs_rating_utilisation` | ratio; VGS / 6 V | stage2_derived |
| `id_continuous_rating_utilisation` | ratio; \|ID\| / 115 A | stage2_derived |
| `is_rating_exceeded` | bool | stage2_derived |
| `kcl_residual_A` | A; ID+IG+IS, identity residual | stage2_derived |
| `ploss_identity_residual_W` | W; Ploss-(Pcond+Psw), identity residual | stage2_derived |
| `pcond_minus_vds_id_W` | W; displacement-attributed power, not model error | stage2_derived |
| `cgd_derived_F` | F; = Crss | stage2_derived |
| `cds_derived_F` | F; = Coss - Crss | stage2_derived |
| `cgs_derived_F` | F; = Ciss - 2*Crss | stage2_derived |
| `evidence_class` | provenance class of the row | stage2_derived |
| `has_experimental_validation` | always False | stage2_derived |
| `is_aging_measurement` | always False | stage2_derived |
| `aging_time_h` | always NaN; no aging axis exists | stage2_derived |

## Provenance

Every Stage 1 parameter carries one of four tags, taken verbatim from the
Stage 1 export and cross-checked against `DATASET_MAPPING.md`. Phase 2A adds no
new parameter of its own; every derived column is tagged below as calculated.

| Tag | Meaning | Parameters carried |
| --- | --- | --- |
| `DATASET-DERIVED` | printed verbatim in the datasheet | 11 |
| `CALCULATED-FROM-DATASET` | arithmetic on printed values only | 12 |
| `MANUFACTURER-DERIVED` | stated as a method or condition, not as a number | 1 |
| `ASSUMED` | chosen to close a gap the datasheet leaves open | 5 |

The `ASSUMED` set is the audit surface: every one of these values is a modelling
choice, not data, and each constrains what Phase 2B may claim.

| Assumed value | Why |
| --- | --- |
| `solver` | numerical integration settings only |
| `thermal_model` | none; all thermal resistances are TBD so Tj tracks Tcase |
| `va_V` | no output-conductance data exist in the dataset |
| `vigs_iso_V` | gate-leakage knee width only |
| `vsmooth_V` | numerical knee smoothing only |

- Every tagged Stage 1 parameter carries one of the four declared tags; none is unlabelled and no tag outside the declared vocabulary was found.

## Gaps and limitations

### Missing information

- **No aging measurements.** No repeated measurement of the same device over time, no stress history, no second device instance. Nothing supports a degradation coefficient, a degradation rate or a remaining-useful-life figure.
- **No datasheet characteristic curves.** The datasheet contains no ID-VDS, ID-VGS, C-V, switching or temperature curves, so every curve Stage 1 produced is a prediction with nothing to validate against.
- **No RON(T) data.** No temperature coefficient is printed, and the Stage 1 channel model has no temperature term, so temperature-normalised resistance is unavailable.
- **No thermal data.** Every thermal resistance and PTOT is TBD, so Tj tracks Tcase and no thermal stress indicator exists.
- **No switching-loss data.** No turn-on/turn-off energies are printed; the exported `psw_W` is Miller-capacitance power, not switching loss.
- **QG contradicts its own components.** QGS + QGD = 15.5 nC against a printed QG = 34 nC. FOM-QG corroborates QG, so the components are treated as suspect.

### Dataset defects recorded upstream

- `curves_absent`
- `qg_not_sum_of_parts`
- `qgd_test_condition`
- `thermal_absent`

### Interpretability caveats carried forward

- `psw_W` is Miller-capacitance power, not switching loss. Using it as an
  energy-loss indicator would misstate the physics.
- `pcond_W` is channel power (`Vds*Ich`), so it does not equal `Vds*ID`. The gap is
  displacement-charging power and reaches about a fifth of channel power on the DC
  sweeps, which step Vds by 0.5 V per 1 ns sample. They are not quasi-static at sample
  resolution, so the two columns are not interchangeable.
- `qg_C` starts at 4.7 nC because it includes the Cgd depletion charge at
  VDS = 75 V. Phase 2B must use delta-Qg across a gate excursion.
- The capacitance and gate-charge profiles are measurement sweeps that hold VGS
  high while pushing VDS up to 150 V, so they contain samples far above the
  continuous current rating. They are characterisation conditions, not operating
  points, and are flagged as such.

## Analysis conventions and tolerances

Every threshold introduced in Phase 2A, with its justification. Nothing below is a
degradation coefficient or a health threshold.

| Name | Value | Justification |
| --- | --- | --- |
| `conduction_leakage_multiple` | 100.0 | A sample counts as conducting when \|ID\| >= 100 x I_leak. 100x is an analysis convention, chosen so channel current dominates the dataset-anchored leakage model (IDSS = 4 uA at 25 degC) by two decades. It is a classification choice, not a physical constant. |
| `vds_positive_floor_V` | 1e-06 | Numerical floor only. At Vds = 0 the ratio Vds/ID is identically zero regardless of the device's true resistance. |
| `operating_point_decimals` | 3 | Biases are snapped to 1e-3 V / 1e-3 degC so that repeated samples at nominally identical conditions group into one comparison bucket. Sampling noise is far below this. |
| `kcl_atol` | 1e-09 | Node current balance ID+IG+IS=0 is an algebraic identity in the Stage 1 model; the tolerance covers float64 round-off over Vgs/ID magnitudes up to ~2e3 A, not model error. |
| `power_balance_atol` | 1e-09 | Ploss is defined as Pcond+Psw in the Stage 1 terminal script, so any residual is float64 round-off only. |
| `csv_mat_rtol` | 1e-09 | The CSV and MAT hold the same arrays, but MATLAB writes CSV as text with roughly 10 significant digits, so agreement is bounded by that formatting rather than being exact. Observed worst case is ~2.7e-10 relative, on gate-ramp voltages such as 1.0526315789473684 written as 1.052631579. Anything larger would indicate a real misalignment. |
| `ron_positive_floor_ohm` | 1e-09 | A conduction resistance is strictly positive. A non-positive value is an artefact of Vds/ID with Vds=0, not a measurement of zero ohms. |

## Reproducibility

```
cd stage2
python -m ganstage2.run            # ingestion, checks, dataset, report
python -m pytest                    # verification tests
```

Stage 1 artefacts are opened read-only. This phase writes only under `stage2/output/`.
