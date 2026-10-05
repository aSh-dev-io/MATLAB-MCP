# Phase 2C - Exposure indicators

## What this is not

This is an exposure indicator derived from the simulated stimulus and the printed ratings.
It is not a health state and carries no information about degradation, because no aging
axis, repeated measurement or health label exists in the dataset.

### Why no health indicator is produced

A health indicator requires an aging axis, repeated measurement of the same device, and a
ground-truth label to validate against. The dataset has none: aging_time_h is NaN in all
15,904 rows, every profile is a single forward sweep with no repeats, and Stage 1 sets
meta.health_state_modelled and meta.degradation_modelled to false. Any health score computed
here would be a relabelling of the stimulus, not a measurement of the device.

This framework currently provides physics-informed stress/degradation assessment based on the available device and Digital-Twin data. Experimental aging data is required to validate a true degradation-prediction model.

## The indicator set

10 of 12 indicators are computable from this dataset. Each answers a question about the *stimulus* relative to the printed ratings. None answers a question about the device's condition.

| Indicator | Value | Margin to limit | Limit it is measured against | Evidence |
|---|---|---|---|---|
| On-resistance at the 99th percentile of conduction samples, against the printed maximum | 0.00267087 ohm | -0.21403 | printed RDS(on) max = 0.0022 ohm | CALCULATED |
| On-resistance at the printed test condition, relative to typical | 0.998765 ratio | 0.00123495 | printed RDS(on) typical = 0.0016 ohm | CALCULATED |
| Worst drain-source voltage against its absolute maximum | 1 ratio | 0 | printed vds abs max = 150.0 | CALCULATED |
| Worst drain current against the continuous rating | 17.9676 ratio | -16.9676 | printed continuous ID = 115.0 A at 25 degC | CALCULATED |
| Worst drain current against the pulse rating | 2.45985 ratio | -1.45985 | printed pulsed ID = 840.0 A at 25 degC | CALCULATED |
| Worst gate voltage against its sign-selected window | 1 ratio | 0 | printed vgs abs max = 6.0 | CALCULATED |
| Worst junction temperature against the printed maximum | 0.833333 ratio | 0.166667 | printed tj max = 150.0 | CALCULATED |
| Dissipated power against the printed package rating | UNAVAILABLE | n/a | n/a | UNAVAILABLE |
| Leakage temperature coefficient at matched bias | 0.14 1/degC | n/a | n/a | DATASET_DERIVED |
| Median share of dissipated power that is channel conduction | 1 fraction | n/a | n/a | CALCULATED |
| Fraction of samples driven outside the printed ratings | 0.46089 fraction | 0.53911 | printed absolute-maximum and continuous ratings | CALCULATED |
| Switching energy per cycle | UNAVAILABLE | n/a | n/a | UNAVAILABLE |

Every row above carries `is_health_state = false` in the JSON and CSV. A utilisation above 1 means the simulated stimulus drove a terminal past its printed limit; it is a property of the excitation, not evidence of damage.

## Margins are to printed limits, never to fitted thresholds

A degradation model would introduce a threshold fitted to observed drift and call everything beyond it degraded. No such threshold exists here, and inventing one is exactly the failure this project rules forbid. Every margin above is therefore referenced to a number printed on the datasheet, which can be checked independently.

### On-resistance needs care

RDS(on) is specified at a single bias, so it is the one indicator where a swept statistic can mislead. The full conduction set gives these values:

| Statistic | Value | Against the printed maximum |
|---|---|---|
| median | 0.001964 ohm | 0.893 x |
| 99th percentile | 0.002671 ohm | 1.214 x |
| maximum | 0.124 ohm | 56.4 x |

The maximum sits in the **transfer** profile at VDS = 0.08 V, where the device is not fully enhanced. The ratio VDS/ID there is a triode-region quantity, not the datasheet RDS(on), and using it as a worst-case resistance margin would overstate the margin loss by more than an order of magnitude. The headroom indicator therefore uses the 99th percentile and the maximum is reported only as a diagnostic.

## The one usable temperature indicator

| Quantity | Value |
|---|---|
| case temperatures | 25, 125 degC |
| matched bias points | 160 |
| leakage ratio high/low | 15 |
| ratio spread across bias | 15.0000 to 15.0000 |
| fitted coefficient | 1.400e-01 /degC |
| Stage 1 declared ratio | 15 |
| relative error | 0 |

Method: median |i_leak_A| compared at matched (Vgs, Vds) between the lowest and highest case
temperature present.

The measured ratio reproduces the Stage 1 leakage temperature law, so this confirms the
simulation is internally consistent. It is not a characterisation of a device. A real GaN
HEMT leakage coefficient is strongly temperature dependent, which makes this the only usable
temperature indicator in the dataset; the on-resistance has none, so thermal normalisation
of RON stays unavailable.


## Indicators that are refused

These are returned as blocked rather than omitted, so the absence is on the record instead of looking like an oversight.

**power_rating_utilisation**

  PTOT is not specified in the source dataset, so there is no power rating to compare
  against. The switching profile reaches 20.8 kW instantaneously, but no limit exists to
  call that an exceedance.

**switching_loss_per_cycle**

  Stage 1's loss budget is exactly Ploss = Pcond + Psw (residual 0.0 W over all 15904 rows).
  Psw is the Miller channel only, contributing 0.07 % of the path integral. There is no
  output-capacitance charge/discharge channel and no gate-drive dissipation channel, so Coss
  is never charged during a transition. The consequence is measurable: the simulated load
  line is exactly reversible, with turn-off the bit-level reverse of turn-on. A hard-
  switched device cannot behave this way, because turn-on charges Coss and clamps the
  inductor current into the low-side device while turn-off does not. The energies below are
  therefore reported as reversible channel-conduction path integrals and are explicitly NOT
  switching losses.

## Per-trajectory exposure

`exposure_by_trajectory.csv` holds one row per bias point (1804 trajectories) with its peak current, peak loss, integrated conduction and Miller energy, thermal exposure and cumulative utilisation, so a consumer can rank trajectories by exposure without re-deriving the integrals.

No exposure class, band or label is assigned. Ranking trajectories by exposure is one short step from ranking them by health, and that step is not supported by this data.

## Column provenance

| File | Contents |
|---|---|
| `exposure_indicators.csv` | one row per indicator, with value, unit, evidence, margin and blocked reason |
| `exposure_indicators.json` | the same set with full interpretations and the leakage diagnostic |
| `exposure_by_trajectory.csv` | one row per trajectory with its exposure integrals |
