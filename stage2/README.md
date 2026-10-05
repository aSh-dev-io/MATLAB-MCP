# Stage 2 - Phase 2A and Phase 2B

Ingestion, data-quality validation and physics-consistency screening of the
Stage 1 digital twin (Phase 2A), followed by a physics-informed stress and
exposure model built on that dataset (Phase 2B).

Both phases deliberately stop before any degradation or health conclusion. The
dataset has no aging axis, no repeated measurement and no thermal model, so
nothing here can honestly produce a degradation law, a health state or a
remaining useful life.

## Run it

```bash
cd stage2
python -m pip install -e .      # once
python -m ganstage2.run        # 2A: ingestion, checks, dataset, report
                               # 2B: stress model, stress artefacts, report
python -m pytest               # verification suite
```

The runner exits non-zero only on a structural failure. Dataset limitations are
reported as blocked checks and do not fail the run, because they are properties
of the input, not errors in the pipeline.

Outputs land in `output/`:

| File | Phase | Contents |
| --- | --- | --- |
| `stage2_dataset.csv` | 2A | 15,904 rows x 51 columns, one row per Stage 1 sample |
| `stage2_manifest.json` | 2A | schema, scope, thresholds, provenance, blockers |
| `stage2_quality_report.json` | 2A | every check with its verdict and detail |
| `PHASE2A_REPORT.md` | 2A | generated narrative report |
| `stress_dataset.csv` | 2B | the Phase 2A dataset plus 12 stress columns |
| `stress_trajectories.csv` | 2B | 1,804 trajectories, one bias point each |
| `stress_analysis.json` | 2B | machine-readable stress report |
| `stress_analysis_report.md` | 2B | generated stress and exposure narrative |

Stage 1 artefacts are opened **read-only**. This phase writes only under
`stage2/output/`.

## What these phases are and are not

In scope: reading the Stage 1 output defensively, validating it against physical
identities, gating samples that are not physically interpretable, recording
provenance on every row, and then accounting for the electrical and thermal
stress each trajectory actually imposes.

Out of scope, and blocked by the data rather than by effort: degradation
modelling, health-indicator weighting, health-state classification, remaining
useful life, predictive accuracy, dashboard. See the blockers in
`stage2_manifest.json`.

Required limitation statement: This framework currently provides
physics-informed stress/degradation assessment based on the available device and
Digital-Twin data. Experimental aging data is required to validate a true
degradation-prediction model.

## Module layout

| Module | Responsibility |
| --- | --- |
| `matv73.py` | read-only MAT v7.3 (HDF5) reader; logical, char and reference decoding |
| `config.py` | every path, threshold and tolerance, each with a recorded justification |
| `ingestion.py` | defensive CSV reader and Stage 1 bundle loader |
| `evidence.py` | evidence taxonomy, from measured down to unavailable |
| `anchors.py` | printed datasheet and model values, each with provenance |
| `physics.py` | Stage 1 equations restated, RON validity gates, physical identities |
| `quality.py` | structural and completeness checks on the files themselves |
| `provenance.py` | provenance tag extraction and tag-ledger cross-check |
| `dataset.py` | dataset assembly, manifest, atomic artefact writes |
| `report.py` | Phase 2A Markdown report, rendered from the checks that ran |
| `equations.py` | auditable equation registry, including deliberately blocked quantities |
| `stress.py` | Phase 2B stress model: trajectories, switching, RON, thermal, energy |
| `stress_report.py` | Phase 2B Markdown and JSON writers |
| `run.py` | entry point |

## Two findings from Phase 2A that shape everything downstream

**The Stage 1 CSV is silently corrupt.** Every data row carries a trailing
delimiter, giving one more field than the header declares. A default
`pandas.read_csv` accepts this without warning, promotes field 0 to the index
and shifts every signal one column left, which mislabels every signal and
nulls `Crss_F`. `ingestion.py` therefore parses field-count-explicitly, repairs
in memory, and proves the repair against the MAT (check Q05, max relative
difference ~5e-10, bounded by MATLAB's CSV text precision). The MAT is the
authoritative source.

**The exported `RON` column is not a resistance over most of its range.** Stage 1
masks RON only on `ID > 0.1 A`, then evaluates `Vds/ID` across the entire sweep
including deep saturation and the off state. Only 6,144 of 15,904 rows (38.6 %)
are both conducting and in the triode region. Use `ron_valid` and
`ron_valid_reason`; do not consume `ron_stage1_ohm` directly.

## Signal semantics that are easy to get wrong

These were read out of the Stage 1 model scripts rather than inferred from the
column names:

- `pcond_W` is channel power `Vds*Ich`, **not** `Vds*ID`. The gap is
  displacement-charging power and reaches about a fifth of channel power,
  because the DC sweeps step Vds by 0.5 V per 1 ns sample. They are not
  quasi-static at sample resolution.
- `ID + IS` is **not** the channel current. The Stage 1 node balance
  `ID + IG + IS = 0` makes `ID + IS = -IG`, which is essentially zero in every
  profile, so using it yields a near-zero current and a meaningless resistance
  or rating ratio. The channel current is `Ich`, and `ID` is the correct
  observable proxy for it.
- `psw_W` is `Vds * abs(iCgd)`, the power through the Miller capacitance. It is
  **not** turn-on/turn-off switching loss.
- `qg_C` is `Qgs + Qgd` including the Cgd depletion charge at Vds = 75 V, so it
  starts at 4.7 nC rather than 0. Use delta-Qg across a gate excursion.
- `is_A` is defined as `-(ID + IG)`, so the KCL identity closes exactly.
- Channel current has **no** temperature term; only leakage scales. Hence
  `ron_temp_normalised_ohm` exists but is explicitly empty rather than filled
  with an invented coefficient.
- The Stage 1 parameter keys `charge.*_nC` store **coulombs**, despite the
  suffix: `charge.qg_nC` is 3.4e-8, which is the printed 34 nC. `anchors.py`
  labels these `C`, and reading the suffix as the unit would understate every
  charge figure by 1e9.

## Phase 2B: how the dataset is actually structured

Stage 1 wrote several independent trajectories onto one shared monotonic clock,
so the obvious aggregations are wrong:

- A **trajectory** is one bias point (`profile`, `operating_point_key`) held over
  its own slice of that clock. Every DC time integral is taken within a
  trajectory, because integrating across the shared axis would add concurrent
  trajectories together. The dataset resolves into 1,804 trajectories.
- The **switching load line is not a trajectory.** Its 18 bias points each own a
  handful of rows, so the slew only exists when the samples of one transition
  window are read across bias points. Load-line rows are told from DC holds by
  trajectory size and windows are recovered by gap detection, so no Stage 1
  profile label is trusted.

## Three Phase 2B findings that constrain what can be claimed

**The loss budget has no Coss or gate-drive channel.** Stage 1 satisfies
`Ploss = Pcond + Psw` exactly, but `Psw` is the Miller channel alone. The
consequence is measurable: the simulated load line is *exactly reversible*, with
turn-off the bit-level reverse of turn-on (max relative asymmetry 6.6e-16) and
all three cycles bit-identical. A hard-switched device cannot behave this way,
because turn-on charges Coss and clamps the inductor current into the low-side
device while turn-off does not. The load line is in fact sampled finely enough to
resolve it - 18 points at 1 ns across the whole slew - so the obstruction is
missing physics, not sample rate. The ~170.85 uJ figures are therefore reported
as reversible path integrals and are **never** called switching losses.

**The RON model has no temperature dependence.** The ratio
`RON(125 degC)/RON(25 degC)` is 1 at every matched bias point, giving a
coefficient of -1.48e-10 /degC against a real GaN HEMT value that is strongly
positive. Temperature normalisation is reported as unavailable rather than as a
factor of exactly 1.0, which would misleadingly imply a validated RON(T) model.
At the printed test condition (Vgs = 5 V, IDS = 50 A, VDS = 0.08 V) the model
gives 1.598 mOhm against a printed 1.6 mOhm typical, a ratio of 0.9988.

**The thermal profile carries no thermal model.** Every thermal resistance in the
source is printed `TBD`, so `Tj` is identically `Tcase` and no junction rise
above case can be computed. An apparent thermal resistance of ~1e-19 K/W can be
fitted, and is reported only to document that absence.

## Provenance

Every Stage 1 parameter carries one of four tags - `DATASET-DERIVED`,
`CALCULATED-FROM-DATASET`, `MANUFACTURER-DERIVED`, `ASSUMED` - and
`provenance.py` carries them into the manifest, cross-checked against
`DATASET_MAPPING.md`. A tag outside that vocabulary is reported rather than
normalised away, because a mislabelled tag is precisely what the rule exists to
prevent.

Every row additionally carries `evidence_class`,
`has_experimental_validation` and `is_aging_measurement`, so no downstream
consumer can mistake a simulation sweep for a measurement or for aging data.

`equations.py` holds every formula the project uses, each with its inputs,
assumptions and evidence class, and it also holds the quantities that are
deliberately **blocked** with the reason blocking them. Both phases render that
registry, so a reader can see not only what was computed but what was refused.

## Design notes

- **Thresholds are declared, not discovered.** Every numeric tolerance lives in
  `config.py` with a `justification`, and the report prints them. Nothing is a
  degradation coefficient or a health threshold.
- **Gaps are explicit.** Where a quantity cannot be computed from the data, the
  column exists and is explicitly empty rather than absent, so a consumer cannot
  assume the work was simply forgotten.
- **Writes are atomic.** Artefacts are staged and moved into place, so an
  interrupted run cannot leave a half-written file for the next reader to trust.
- **The reports are generated.** Their numbers cannot drift from the data, and
  finding-dependent narrative is selected by the check results.
- **Markdown tables are escaped centrally.** A row containing an unescaped pipe
  shifts every column to its right while leaving the file syntactically valid, so
  the corruption is silent; a test checks every table's cell counts.
- **Tests run against the real artefacts**, since validating those specific
  files is the point. Session-scoped loading keeps the suite fast.
