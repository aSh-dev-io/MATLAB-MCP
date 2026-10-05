# Dataset mapping

Every value in `matlab/gan_parameters.m` traces to one of four provenance tags.
No value is invented silently.

| Tag | Meaning |
| --- | --- |
| `DATASET-DERIVED` | Printed verbatim in the datasheet |
| `CALCULATED-FROM-DATASET` | Arithmetic on printed values only |
| `MANUFACTURER-DERIVED` | Stated by onsemi as a method or condition, not as a number |
| `ASSUMED` | Chosen to close a gap the datasheet leaves open |

Source: `GaN-HEMT Datasheet.PDF`, onsemi **NTLEF2D2N15GN1**, revision
**P1 (preliminary), July 2026**, 6 pages.

## Device identity

| Parameter | Value | Tag |
| --- | --- | --- |
| Manufacturer | onsemi | `DATASET-DERIVED` |
| Part number | NTLEF2D2N15GN1 | `DATASET-DERIVED` |
| Publication order | NTLEF2D2N15GN1/D | `DATASET-DERIVED` |
| Technology | enhancement-mode AlGaN/GaN HEMT | `DATASET-DERIVED` |
| Package | PDSO-N8, 5.0 x 6.0 x 0.87 mm | `DATASET-DERIVED` |

## DC characteristics

| Parameter | Value | Tag |
| --- | --- | --- |
| `RDS(on)` typ | 1.6 mOhm | `DATASET-DERIVED` |
| `RDS(on)` max | 2.2 mOhm | `DATASET-DERIVED` |
| `RDS(on)` test `VGS` | 5 V | `DATASET-DERIVED` |
| `RDS(on)` test `IDS` | 50 A | `DATASET-DERIVED` |
| `VDS` at the RON test point, 0.08 V | 1.6 mOhm x 50 A | `CALCULATED-FROM-DATASET` |
| `VGS(th)` range | 1.1 to 6 V | `DATASET-DERIVED` |
| `VGS(th)` test `IDS` | 10 mA | `DATASET-DERIVED` |
| `IDSS` max at 25 degC, `VDS` = 150 V | 4 uA | `DATASET-DERIVED` |
| `IDSS` max at 125 degC, `VDS` = 150 V | 60 uA | `DATASET-DERIVED` |
| Leakage ratio 125/25 degC, factor 15 | 60 uA / 4 uA | `CALCULATED-FROM-DATASET` |
| `IGSS` max at 25 degC, `VGS` = 6 V | 2 uA | `DATASET-DERIVED` |
| `IGSS` max at 125 degC, `VGS` = 6 V | 40 uA | `DATASET-DERIVED` |
| Leakage ratio 125/25 degC, factor 20 | 40 uA / 2 uA | `CALCULATED-FROM-DATASET` |
| `BV(DSS)` min | 150 V | `DATASET-DERIVED` |
| `FOM-QG` | 54.4 nC*mOhm | `DATASET-DERIVED` |
| `FOM-QG` cross-check | 34 nC x 1.6 mOhm = 54.4 | `CALCULATED-FROM-DATASET` |

The two leakage pairs have **different** temperature ratios. `IDSS` scales by
15 and `IGSS` by 20, so the twin carries two separate ratios
(`leak_temp_ratio`, `igss_temp_ratio`). Using one for both misses the printed
`IGSS` maximum by 25 %.

## Capacitance and charge

| Parameter | Value | Tag |
| --- | --- | --- |
| `Ciss` at `VGS` = 0 V, `VDS` = 75 V, 1 MHz | 4820 pF | `DATASET-DERIVED` |
| `Coss` at the same bias | 1150 pF | `DATASET-DERIVED` |
| `Crss` at the same bias | 19 pF | `DATASET-DERIVED` |
| `Ciss` = `Cgs` + `Cgd` | 4820 = 4782 + 19 pF (rounding) | `CALCULATED-FROM-DATASET` |
| `Coss` = `Cds` + `Cgd` | 1150 = 1131 + 19 pF (rounding) | `CALCULATED-FROM-DATASET` |
| `QGS` | 10.8 nC | `DATASET-DERIVED` |
| `QGD` | 4.7 nC | `DATASET-DERIVED` |
| `Qoss` | 187 nC | `DATASET-DERIVED` |
| `QG` | 34 nC | `DATASET-DERIVED` |
| `QGD` test `VDS` / `IDS` | 75 V / 50 A | `DATASET-DERIVED` |
| Charge sweep `VGS` end | 5 V | `DATASET-DERIVED` |
| `Cgs0`, `Vgsc` | 4782 pF, 1.587 V | `CALCULATED-FROM-DATASET` |
| `Cds0`, `Vjc` | 7063 pF, 14.587 V | `CALCULATED-FROM-DATASET` |
| `Cgd0`, `Vjg` | 447.0 pF, 3.330 V | `CALCULATED-FROM-DATASET` |

The three depletion pairs are solved so that each capacitance matches its
printed value at `VDS` = 75 V **and** the matching charge matches its printed
value at the same drain voltage. Two consequences are worth recording:

* The printed `QGD` / `Cgd` ratio at 75 V is 247 V, far above the 75 V sweep
  voltage, so `Cgd` must be strongly voltage dependent with a large zero-bias
  value. `Cgd0` = 447 pF is the honest result of that fit, not a typo.
* `Cds0` = 7063 pF is likewise a fit consequence of pairing `Coss(75 V)` with
  `Qoss = 187 nC` at 150 V.

Both reproduce the printed values exactly at the datasheet bias, which is the
only behaviour the dataset constrains.

## Absolute maximum ratings

| Parameter | Value | Tag |
| --- | --- | --- |
| `VDSS` | 150 V | `DATASET-DERIVED` |
| `VGS` min / max | -4 V / 6 V | `DATASET-DERIVED` |
| `VGS` pulse max | 6.5 V | `DATASET-DERIVED` |
| `ID` continuous at 25 degC | 115 A | `DATASET-DERIVED` |
| `ID` pulse at 25 degC | 840 A | `DATASET-DERIVED` |
| `ID` pulse at 150 degC | 640 A | `DATASET-DERIVED` |
| `PTOT` | **TBD** | `DATASET-DERIVED` |
| `TJ` min / max | -55 degC / 150 degC | `DATASET-DERIVED` |
| `TSTG` min / max | -55 degC / 150 degC | `DATASET-DERIVED` |
| `TSLD` max | 260 degC | `DATASET-DERIVED` |

`ID` continuous is a package and thermal limit, not an I-V point. With every
thermal resistance `TBD` it cannot be reproduced by any device model, so
`verify_gan_hemt_twin` reports it as `NOT_COMPARABLE` rather than as a pass or
a failure.

## Values the datasheet leaves open

| Parameter | Value used | Tag | Why |
| --- | --- | --- | --- |
| `VTH` | 1.1 V | `DATASET-DERIVED` | Taken as the minimum of the printed `VGS(th)` range |
| `VDSAT` | 1.66303 V | `CALCULATED-FROM-DATASET` | Solved so `ID,sat` at `VGS` = 5 V equals the 840 A pulsed rating |
| `K` | 161.917 A/V^2 | `CALCULATED-FROM-DATASET` | Solved from `VDSAT` and the 1.6 mOhm RON point |
| `VA` (output conductance) | 100 V | `ASSUMED` | No `GDS` or off-state curve is printed |
| `VSMOOTH` | 0.05 V | `ASSUMED` | Smooths the gate-to-drain coupling |
| `VIGS` isolation | 0.5 V | `ASSUMED` | Shapes gate-leakage dependence on `VGS` |
| Leakage temperature span | 100 degC | `ASSUMED` | Anchors 25 degC, reaches the printed 125 degC value |
| `RON` ITH threshold | 0.1 A | `ASSUMED` | Fraction of `ID,sat` defining the knee |
| `Tnom` | 25 degC | `MANUFACTURER-DERIVED` | Datasheet characterises at `Tcase` = 25 degC |
| `Tj` | `Tj = Tcase` | `ASSUMED` | No thermal resistance available |
| Switching bus / load | 100 V / 0.12 Ohm | `ASSUMED` | No application circuit is specified |

The datasheet prints `VGS(th)` as a **range** (1.1 V to 6 V) together with a
test current of 10 mA, not as a single model value. The twin uses the range
minimum as `VTH`; the twin therefore predicts no appreciable drain conduction
at 1.1 V, which is consistent with the printed test current but is not a
calibration of the threshold itself.

## Defects in the supplied dataset

These are recorded rather than silently patched.

### 1. Gate charge is internally inconsistent

The datasheet prints `QG` = 34 nC, but also `QGS` = 10.8 nC and
`QGD` = 4.7 nC, which sum to 15.5 nC. No model can satisfy both.

`FOM-QG` = 54.4 nC*mOhm equals `QG` x `RDS(on)` = 34 nC x 1.6 mOhm exactly, so
the printed `QG` is self-consistent with the RON figure. The **charge
components** are therefore the values treated as suspect, and the twin is built
from them. `verify_gan_hemt_twin` returns `DATASET_INCONSISTENCY` for the `QG`
row rather than `FAIL`, because no model could pass it.

### 2. No characteristic curves

The datasheet contains no `ID`-`VDS`, `ID`-`VGS`, `C`-`V`, switching or
temperature curves. Every curve in `plots/` is a model prediction and is
labelled `MODEL PREDICTION - NOT VALIDATED`.

### 3. Thermal data is absent

`Rth(j-c)`, `Rth(j-a)` and `PTOT` are all `TBD`, and no thermal impedance curve
is printed. The twin therefore sets `Tj = Tcase` and no thermal behaviour can be
validated. The exact statement used everywhere in this project is:

> Thermal validation not supported by the provided dataset.

### 4. Leakage pairs use different temperature ratios

Covered above under DC characteristics. Handled, not a defect in the data, but
worth recording because a single-ratio shortcut is wrong by 25 % on `IGSS`.

## Not in Stage 1

Degradation modelling, health-state assessment, remaining-useful-life
prediction, converter or application-level models, and parameter ageing. The
dataset contains no ageing data to support any of them.