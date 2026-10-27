# Validation: `cstr-rca`, seed 7

This report covers the first dataset built on a plant other than the original
heated tank: R-201, a jacketed CSTR making propylene glycol, under cascade and
ratio control. The plant was designed, implemented and validated with the
`simulate-process` workflow in this repo.

```bash
historiansim generate cstr-rca --seed 7      # reproduces this dataset exactly (about 22 min)
```

## The dataset

| | |
|---|---|
| Record | 2024-03-01 to 2024-05-30, 90 days at a 10 s scan, plus a 60 s grid |
| Tags | 100 (40 R-201, 60 neighbouring-unit ballast) |
| Clean baseline | first 14 days |
| Fault episodes | 9: each root cause, mechanism and failed component unique; at least 2 days of normal operation either side |
| Benign events | 2: reactor temperature setpoint step, production-rate increase |
| Classes covered | all 4 symptom classes; process, utility, upstream, control and instrument layers |
| Reproducibility | `historian_10s.parquet` is byte-identical across every regeneration |

| ID | Root cause | Class | Severity | Grade |
|---|---|---|---|---|
| EP-001 | Jacket heat-transfer fouling | S1 | moderate | Medium |
| EP-002 | TV-202 cooling-water valve stiction | S2 | subtle | Hard |
| EP-003 | Catalyst deactivation | S4 | moderate | Medium |
| EP-004 | Cooling tower degraded (supply temperature rise) | S1 | moderate | Medium |
| EP-005 | Temperature element TE-201 drifting low | S4 | subtle | Hard |
| EP-006 | TIC-201 left in manual | S3 | obvious | Easy |
| EP-007 | Agitator impeller damage | S1 | moderate | Medium |
| EP-008 | Process water flowmeter FT-202 reading high | S4 | moderate | Medium |
| EP-009 | PO feed pump P-201 surging | S2 | obvious | Easy |

## 1. Plant acceptance gates (`historiansim check-plant exothermic_cstr`)

| Stage | Result |
|---|---|
| 1 steady state | pass: design point is an equilibrium to 1e-14; all valves at 50 %; every loop holds for a day with nothing moving |
| 2 setpoint steps | pass: TIC-201, FIC-201 and LIC-201 settle with no residual cycling |
| 3 each cause alone | pass: all 15 catalog causes move every documented evidence tag the documented way, and every "flat" tag stays flat |
| 4 catalog integrity | pass: every symptom class separable; every tag and cause reference resolves |
| 5 quick dataset | pass |

## 2. Validation battery on the 90-day dataset: 17/17

Checks that passed:

- not trivially detectable
- solvable
- physical bounds
- no range clamping
- mass balance
- control variance ratio
- coloured noise (correlation times: flow 30 s, pressure 20 s, temperature 190 s, slow thermowell 415 s)
- transport lag
- PCA dimensionality
- historian irregularity
- frozen values present and unflagged
- correlated dropouts (5 nodes, all as groups)
- no-fault twin integrity
- baseline settled
- recipe
- dataset layout
- no answer leak

Difficulty, comparing first observability with a naive 3-sigma detector on
the baseline:

| | EP-001 | EP-002 | EP-003 | EP-004 | EP-005 | EP-006 | EP-007 | EP-008 | EP-009 |
|---|---|---|---|---|---|---|---|---|---|
| observable | 0.1 h | 15.4 h | 0.1 h | 0.1 h | 0.2 h | 0.0 h | 0.1 h | 0.5 h | 0.0 h |
| naive 3-sigma | 43 h | 42 h | 23 h | 63 h | 25 h | 11 h | 8 h | 13 h | 0.2 h |

The masked faults stay invisible to a threshold for one to three days, while
the evidence is in the data within the first hour.

## 3. Physics review

Every episode was plotted (`historiansim plot --episode`) and read against its
answer-key evidence. Highlights:

- **EP-001 / EP-007.** `CALC-UA` falls with reactor temperature on setpoint
  and the cooling valve opening. Agitator power separates the two cleanly:
  15.0 to 12.3 kW only in EP-007.
- **EP-002.** The valve position-to-demand gap has a standard deviation 3.5x
  its normal level in EP-002 and nowhere else.
- **EP-005.** `TI-204` and `TI-203` climb about 0.9 degC while the controlled
  `TIC-201.PV` stays on setpoint; residual PO falls as the hotter reactor
  converts more.
- **EP-008.** The liquid balance opens steadily while the outlet valve closes
  with level held: less liquid is really arriving than the meters say.
- **Seasonal envelope.** The cooling valve rises with the warming season but
  peaks around 83 %, so it never saturates.

## 4. Blind diagnosis

A fresh agent was given **only the challenge folder** made by
`historiansim make-challenge`: the two historian files, `tags.csv`,
`PROCESS_DESCRIPTION.md`, `CHALLENGE.md` and the template. It had no catalog,
design doc, code or answer key. It was asked to find and diagnose every fault
from first principles. Root causes were judged right only if both the failed
item and the mechanism matched.

| Round | Detected | Correct cause | False positives | Missed | Points | Median start error |
|---|---|---|---|---|---|---|
| 1 | 8 / 9 | 8 / 8 | 0 | EP-006 | 24 / 27 | 2.8 h |
| 2 (fresh agent, final dataset) | 9 / 9 | 9 / 9 | 0 | none | **27 / 27** | 1.8 h |

**Round 1's miss was the dataset's fault.** The agent found EP-006 (TIC-201
in MAN) but filed it as an operator action, which the challenge wording
allowed. `CHALLENGE.md` now states two boundary cases:

- a loop left out of its normal mode is a control-system fault;
- drift many times the documented rate is an instrument fault.

## 5. Issues found and fixed

| Found by | Issue | Fix |
|---|---|---|
| Per-cause sweep | Jacket UA of 18 kW/K left the cooling valve near its stop under S1 faults; "flat" evidence then moved | UA raised to 30 kW/K; cooling water now rises 20 K across the jacket |
| Per-cause sweep | Cooling-water supply loss raised the header pressure (scale-sign convention) | negative magnitude |
| Per-cause sweep | "Flat" judged on single-sample noise and on changes below the instrument's own noise | judged on the 1-hour sustained change, with an instrument noise floor |
| Battery | Control-variance and dropout checks were tank-specific | flow loops and held unloaded loops handled; dropouts only required once enough node-months have passed |
| Battery | Naive 3-sigma credited with a "detection" that was the analyzer's background drift crossing its band at onset | alarms the no-fault twin raises as early are not credited |
| Physics review | `AI-201` (0–10 wt%) and `FI-301` (0–150 m3/h) ranged far above duty, inflating drift and noise | ranged to duty |
| Blind round 1 | Manual-mode loop classed as an operator action | boundary cases stated in `CHALLENGE.md` |
| Blind round 1 | "Jacket-side" fouling implied a side of the wall the data cannot show | relabelled jacket heat-transfer fouling |
| Blind round 2 | `FI-301` clipped at its range top on one hot afternoon | range 0–60 m3/h, plus a new battery check: no plant transmitter may sit at a range limit |
| Blind round 2 | `CALC-UA` creeps about 6 % over the record, unexplained | description now explains the drift amplification |
| Blind round 2 | Stuck readings look like ramps, not flat lines, in the 60 s grid | description now says so |
| Slow tests | Separability check called a sustained rise and an oscillation on the same tag identical | signatures distinguish oscillation from sustained shift |

## 6. Known limits, kept on purpose

These are the open points the blind agents raised. Each is realistic and
none prevents a correct diagnosis.

- **EP-009.** There is no PO supply pressure tag, so the pump is inferred
  from the cycling pattern rather than read off a gauge.
- **EP-003.** Low acid dosing and catalyst poisoning look the same: only
  the activity is observable. The answer key judges "loss of catalyst
  activity" correct.
- **All faults.** They ramp in and are repaired in a step, so end times are
  sharp and start times are uncertain by hours.
- **Calibration drift.** Slow drift accumulates over 90 days. The reference
  period represents late May less well than early March, as on a real plant.
