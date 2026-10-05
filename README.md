# Stage 1 GaN HEMT device digital twin

Device-level digital twin of the onsemi **NTLEF2D2N15GN1** 650 V enhancement-mode
GaN HEMT, together with a standardized continuous output layer.

Built from `GaN-HEMT Datasheet.PDF`, onsemi revision **P1 (preliminary),
July 2026**.

## Scope

**In scope.** A calibrated device model that reproduces every printed
datasheet value, six standard excitation profiles, verification against the
dataset, and exported data with plots.

**Out of scope.** Degradation modelling, health-state assessment,
remaining-useful-life prediction, converter or application-level models, and
parameter ageing. The dataset contains no ageing data to support any of them.

## Layout

```
gan_digital_twin/
  matlab/
    gan_parameters.m          all values, each with a provenance tag
    gan_init.m                bootstrap: paths, parameters, Simulink check
    create_gan_hemt_twin.m    builds simulink/gan_hemt_digital_twin.slx
    run_gan_hemt_twin.m       six excitation profiles
    verify_gan_hemt_twin.m    dataset verification report
    export_twin_output.m      writes results/ and plots/
  simulink/
    gan_hemt_digital_twin.slx generated model
  results/                    stage1_output.mat / .csv / stage1_summary.json
  plots/                      six characteristic plots
  README.md
  DATASET_MAPPING.md          every value traced to the datasheet
```

## Running it

Add the folder to the path and call the entry points in order:

```matlab
addpath('D:\MATLAB-MCP\gan_digital_twin\matlab')

info   = gan_init();                       % paths, parameters, Simulink check
create_gan_hemt_twin();                    % write the .slx from scratch
out    = run_gan_hemt_twin('output');      % one profile
report = verify_gan_hemt_twin();           % print the verification table
export_twin_output();                      % all profiles, data files, plots
```

`run_gan_hemt_twin` accepts:

| Call | Result |
| --- | --- |
| `run_gan_hemt_twin('dc', [Vgs Vds Tcase])` | one constant-bias point |
| `run_gan_hemt_twin('output')` | `ID`-`VDS` families |
| `run_gan_hemt_twin('transfer')` | `ID`-`VGS` at the RON drain voltage |
| `run_gan_hemt_twin('capacitance')` | `Ciss`/`Coss`/`Crss` vs `VDS` |
| `run_gan_hemt_twin('charge')` | gate-charge sweep at `VDS` = 75 V |
| `run_gan_hemt_twin('switching')` | hard-switched double pulse |
| `run_gan_hemt_twin('thermal')` | `ID`-`VDS` at 25 degC and 125 degC |

`export_twin_output` takes `'profiles'`, `'write'`, `'verify'`, `'p'` and
`'root'` for partial or dry runs.

## Model interface

Three excitation inputs, in this order:

| Port | Meaning |
| --- | --- |
| `Vgs_cmd` | gate-source voltage (V) |
| `Vds_cmd` | drain-source voltage (V) |
| `Tcase_cmd` | case temperature (degC) |

Sixteen outputs, in this order:

| # | Signal | Unit | # | Signal | Unit |
| --- | --- | --- | --- | --- | --- |
| 1 | `Vgs` | V | 9 | `Ploss` | W |
| 2 | `Vds` | V | 10 | `Tj` | degC |
| 3 | `ID` | A | 11 | `Tcase` | degC |
| 4 | `IG` | A | 12 | `Qg` | C |
| 5 | `IS` | A | 13 | `Qgd` | C |
| 6 | `RON` | Ohm | 14 | `Ciss` | F |
| 7 | `Pcond` | W | 15 | `Coss` | F |
| 8 | `Psw` | W | 16 | `Crss` | F |

The model is built from three MATLAB Function subsystems fed by one Constant
parameter vector, so rebuilding from `gan_parameters.m` is deterministic.

## Model structure

* **Channel.** Smoothed gate-to-drain coupling into a saturation voltage, a
  quadratic drain law with an output-conductance factor, and a knee threshold.
  `K` and `VDSAT` are solved so that `RDS(on)` = 1.6 mOhm at the printed test
  point and `ID,sat` at `VGS` = 5 V equals the printed 840 A pulsed rating.
* **Capacitance.** Three depletion-capacitance branches, each solving for its
  zero-bias value and junction potential so that the capacitance **and** the
  matching charge both match the datasheet at `VDS` = 75 V.
* **Charge.** `Qg` and `Qgd` are integrated from the gate and gate-drain
  currents rather than imposed, so they respond correctly to any waveform.
* **Leakage.** Separate drain and gate leakage with separate temperature ratios,
  because the printed pairs scale differently (15 for `IDSS`, 20 for `IGSS`).
* **Thermal.** `Tj = Tcase`. No thermal network, because no thermal resistance
  is available.

## Verification

`verify_gan_hemt_twin` compares the twin against every printed value and prints
a table. Current result:

```
TOTAL 15   PASS 12   FAIL 0   DATASET_INCONSISTENCY 1   NOT_COMPARABLE 2
```

The three non-pass rows are not twin errors:

* **`DATASET_INCONSISTENCY` for `QG`.** The datasheet prints `QG` = 34 nC but
  also `QGS` + `QGD` = 15.5 nC. No model can satisfy both. `FOM-QG` =
  `QG` x `RDS(on)` = 54.4 nC*mOhm corroborates `QG` exactly, so the twin is
  built from the two charge components.
* **`NOT_COMPARABLE` for `Qoss`.** Measured over a discharge to a different
  drain voltage than the twin's charge sweep reaches.
* **`NOT_COMPARABLE` for the continuous `ID` rating.** A package and thermal
  limit, not an I-V point, with every thermal resistance `TBD`.

Headline agreements:

| Check | Datasheet | Twin |
| --- | --- | --- |
| `RDS(on)` at 50 A, `VDS` = 0.08 V | 1.6 mOhm | 1.5987 mOhm |
| `Ciss` / `Coss` / `Crss` at 0 V, 75 V | 4820 / 1150 / 19 pF | 4820 / 1150 / 19 pF |
| `Qgd` at 75 V | 4.7 nC | 4.7 nC |
| `IGSS` at 6 V, 125 degC | 40 uA max | 40 uA |
| `IDSS` at 0 V, 150 V, 125 degC | 60 uA max | 60 uA |
| `ID,sat` at `VGS` = 5 V | 840 A pulsed rating | 840 A |

## What cannot be validated

The datasheet contains **no characteristic curves**. Every curve in `plots/` is
a model prediction and carries the label:

> MODEL PREDICTION - NOT VALIDATED

Not validatable from this dataset: `ID`-`VDS` output curves, `ID`-`VGS` transfer
curves, `C`-`V` curves, switching waveforms, turn-on and turn-off energies, and
temperature behaviour.

For temperature specifically:

> Thermal validation not supported by the provided dataset.

`PTOT`, `Rth(j-c)` and `Rth(j-a)` are all `TBD` in the source document.

The switching profile is a simplified excitation: a resistive load line with no
freewheeling path, parasitics or stray inductance, because the dataset contains
none. It is a device-level waveform, not a datasheet double-pulse test.

## Provenance

Every parameter carries one of four tags: `DATASET-DERIVED`,
`CALCULATED-FROM-DATASET`, `MANUFACTURER-DERIVED`, `ASSUMED`. See
`DATASET_MAPPING.md` for the full table, the assumed values and their
justification, and the recorded dataset defects.

## Requirements

MATLAB R2026a with Simulink. Developed and verified on R2026a.