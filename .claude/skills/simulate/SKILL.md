---
name: simulate
description: Build a realistic chemical-plant historian dataset for a process the user describes, or recommend a process to simulate. The dataset is months of time series with control loops, instrument noise, historian compression and fault episodes, plus a fault answer key. Use when the user types /simulate, describes a process to simulate, asks for a synthetic process / manufacturing / plant / historian / time-series dataset, asks for a fault detection or root cause analysis dataset, or asks what process they could simulate.
---

# /simulate: build a process dataset

The user is usually a process or chemical engineer, not a software developer.
Keep every message to them in plain engineering language:

- explain what you are doing and what you need from them;
- never paste code or stack traces at them;
- never ask them to run commands themselves. You run everything.

You are turning their process description into a validated dataset with this
shape (the `rca-benchmark` recipe):

- 90 days of historian data at a 10 s scan, plus the same data on a 60 s grid;
- 14 days of clean normal operation first;
- 9 fault events, all different. No root cause, mechanism or failed component
  repeats, and each event has at least 2 days of normal operation either side;
- 2 deliberate operator moves (a setpoint change, a rate change) that are not
  faults;
- every root cause deducible from the data, the tag list and the process
  description.

The dataset folder the user gets:

```
output/<scenario>-standard-s<seed>/
  historian_10s.parquet    full record, 10 s scan, compressed like a real historian
  historian_60s.parquet    same data on a regular 1-minute grid
  tags.csv                 tag dictionary
  PROCESS_DESCRIPTION.md   the plant, for a process engineer
  FAULT_ANSWER_KEY.md      every event: start, end, root cause, evidence
  metadata/                per-minute labels, ground truth JSON, config and seed
```

Quality comes from three places, in order of importance:

1. **The fault catalog.** Causes grouped by shared first symptom, each with
   evidence that confirms it and rules out its competitors.
2. **The physics.** Faults masked by control loops the way they are on a
   real plant.
3. **The process description.** It must give every relationship needed to
   reason from first principles, and never list failure modes.

Read the two reference plants before writing anything:

- `src/historiansim/plants/heated_stirred_tank/`, the unit behind HistorianRCA;
- `src/historiansim/plants/exothermic_cstr/`, built from a `DESIGN.md` exactly
  as this skill describes.

Never write numbers into a dataset yourself. You write the plant; the
simulator writes the data.

## Step 0: environment (silent unless something is missing)

Check that the `historiansim` command runs. If it doesn't, follow the
first-run setup in `CLAUDE.md`:

1. Check for Python 3.11+.
2. Create `.venv`.
3. `pip install -e ".[dev]"`.

Use the venv's `historiansim` for every command below. If Python itself is
missing, tell the user in one sentence to install Python 3.11 or newer from
python.org, ticking "Add python.exe to PATH" on Windows. Then wait.

**In the Claude app** (no HistorianSim repository open, skill installed from
`simulate-skill.zip`), the simulator source ships inside this skill folder at
`historiansim-src/`:

1. Copy `historiansim-src/` to a writable working folder, for example
   `~/historiansim`, and run `pip install -e ~/historiansim` there.
2. Read `~/historiansim/CLAUDE.md` for the hard rules. Paths in this skill
   such as `src/historiansim/plants/` are relative to that folder.
3. Start long commands (`generate`, `check-plant --stage 3` and `--stage 5`)
   in the background with output to a log file, then check the log until
   they finish. A single command can time out.
4. Write datasets to the working folder, then zip the dataset folder into
   the outputs folder so the user can download it.

## Step 1: understand the request (at most 2 questions)

- **They described a process.** Restate it as one unit operation with its
  controls, in one or two sentences.
- **They asked for a recommendation, or typed `/simulate` with nothing
  else.** Offer three or four options from
  `references/recommended_processes.md`, each with its one-line pitch. Say
  that the two shipped processes can be generated straight away. Let them
  pick.
- **They picked a shipped process** (`cstr-rca` or `tank-rca`).
  Skip to Step 5.

Ask only what changes the design, typically:

- which unit, if they described a whole plant (simulate **one** unit, with
  its utilities and feeds as disturbances);
- anything about the control scheme or faults they care about.

Don't ask about duration, scan rate or fault count. The recipe fixes them.

If the description is a whole flowsheet, pick the unit with the richest
diagnostic story, usually a reactor or a column, and say why.

## Step 2: write `DESIGN.md` and stop for approval

Run `historiansim new-plant <snake_case_name> --equipment <TAG>`. Then fill in
`src/historiansim/plants/<name>/DESIGN.md` following the template's sections
and the R-201 example. It must contain:

1. **Service.** What the unit does, its chemistry and the product spec.
2. **Equipment and flow.** An ASCII sketch with every tag.
3. **Design point.** Flows, temperatures, duties and valve positions.
   - Check the numbers with a short Python calculation, not by eye.
   - Every control valve should sit at 30–70 % at design.
   - Every transmitter range should put its normal reading at roughly
     20–60 % of span.
4. **States and physics.** The ODEs and algebraic relations, with
   nonlinearity that is real: valve characteristics, Arrhenius kinetics,
   `sqrt(h)` outflow. Keep it to 2–6 states. Treat anything faster than the
   scan as quasi-steady.
5. **Control.** Loops, pairings, cascades and ratio stations, with tuning
   intent. Deliberately leave one loop loose.
6. **Disturbances.** Weather coupling, utility headers, feed variability.
7. **Fault catalog.** 12–20 causes in 3–5 symptom classes. See
   `references/fault_design.md`. This is the most important section.
8. **The dataset scenario.** The 9 pinned causes and severities, plus 2
   benign events.

Show the user a short summary in plain language:

- the process and its control scheme in two or three sentences;
- a table of the 9 faults with severity;
- for each fault, one line on what makes it hard to tell apart from its
  look-alikes;
- the two operator moves.

Ask them to reply "approved" or say what to change. **Wait for approval
before writing code.**

## Step 3: implement the plant

Fill in the scaffolded files, copying patterns from the reference plants:

| File | Contains | Reference |
|---|---|---|
| `model.py` | `UnitModel` subclass: `default_params`, `derivatives`, `signals`, `steady_inputs`, `steady_state` | `exothermic_cstr/model.py` |
| `loops.py` | design point, `LoopConfig` list, `ChannelConfig` disturbances | `exothermic_cstr/loops.py` |
| `tags.py` | `TagSpec` list and `recompute_dcs_calculations` | `exothermic_cstr/tags.py` |
| `faults.py` | `SymptomClass`es and `RootCause`s with `Evidence` | both plants |
| `description.py` | the plant sections of the process description | both plants |
| `__init__.py` | `BenignEvent`s, scenarios, the `PLANT` object | `exothermic_cstr/__init__.py` |

Rules that matter:

- Fault handles are **parameters**: a surviving fraction faulted with `scale`,
  or a zero-based quantity faulted with `offset`.
  - A `DisturbanceFault` in scale mode multiplies by `1 + severity x magnitude`,
    so a drop needs a negative magnitude.
  - Instrument faults target a **historian tag name**, for example
    `FIC-201.PV`.
- Every evidence tag must exist in `tags()`. Every `rules_in` and `rules_out`
  ID must exist in the catalog.
- A cascade slave or ratio station is `mode="CAS"`, and its configured `sp`
  must equal the design equilibrium. Compute it from the model.
- CALC tags are recomputed from **measured** tags in
  `recompute_dcs_calculations`, never from truth.
- Give every `RootCause` a `component`. Give the 9 pinned causes a `grade`
  (Easy/Medium/Hard), a `walkthrough` and `competitors`.
- **Writing for the user.** All text that reaches the user's files is read by
  process engineers:
  - mechanisms, walkthroughs, evidence notes, benign-event explanations, and
    the process description;
  - plain sentences, engineering terms, no em dashes or `--` used as a dash;
  - no rhetorical "it's not X, it's Y" constructions.

## Step 4: pass the gates, in order

```bash
historiansim check-plant <name> --stage 1   # equilibrium; loops hold still
historiansim check-plant <name> --stage 2   # setpoint steps settle
historiansim check-plant <name> --stage 3   # each cause alone moves its evidence as documented
historiansim check-plant <name> --stage 4   # candidates separable; references resolve
historiansim check-plant <name> --stage 5   # quick dataset passes every check
```

Fix each stage before moving on. When stage 3 reports that evidence did not
move or moved the wrong way, decide which is wrong, the physics or the claim.
Then fix that one and say which you changed. Never loosen a check to make it
pass. Give the user a one-line progress update after each stage.

## Step 5: generate

```bash
historiansim generate <scenario> --seed <n> --out output     # about 20-30 min for 90 days
```

It must end with every check passing, including:

- `recipe`;
- `no_range_clamping`;
- `dataset_layout`;
- `no_answer_leak`.

Then look at it:

```bash
historiansim report output/<dataset>
historiansim plot output/<dataset> --episode EP-001   # for each event; the plot is saved beside the dataset
```

## Step 6: validate like a reviewer

Follow `references/validation_checklist.md`. At minimum:

1. **Physics review.** Plot each event and check two things:
   - the evidence moves as the answer key says;
   - the tags that rule out other causes really stay flat.
2. **Blind diagnosis.** Run `historiansim make-challenge output/<dataset>` to
   make a copy without the answer key. Spawn a fresh subagent and give it
   **only that challenge folder**. Ask it to work `CHALLENGE.md` and write a
   submission CSV.

   Score the submission with `historiansim score output/<dataset> <submission.csv>`,
   judging each root cause yourself against `FAULT_ANSWER_KEY.md`. For every
   miss, decide whose fault it is:
   - **the data's:** the evidence is absent, ambiguous or misdescribed. Fix
     and regenerate;
   - **the agent's:** the evidence is there. Fine; note it.

   If you cannot spawn a subagent (for example in the Claude app), skip the
   blind diagnosis and say so in `VALIDATION.md` and the hand-over.
3. Write a short `VALIDATION.md` next to the dataset folder, not inside it:
   - the checks;
   - the blind score;
   - the fixes made.

## Step 7: hand over

Tell the user, in plain language:

- **Where the dataset is,** and what each file is. Use the layout above. In
  the Claude app, give them the zip to download, and include the new plant
  folder in it so the process can be regenerated later.
- **How to open it.** `historian_60s.parquet` opens in pandas, Power BI,
  Spotfire or Seeq. Offer to export a CSV copy if they want Excel.
- **The events table** from `FAULT_ANSWER_KEY.md`.
- **The blind-test result.**
- **Blind use.** To hand the dataset to someone as a blind test, run
  `historiansim make-challenge` or give them everything except
  `FAULT_ANSWER_KEY.md` and `metadata/`.

Offer to draw the PFD if the `pfd-generator` skill is available.

## References

- `references/fault_design.md`: designing symptom classes and evidence. Read before Step 2.
- `references/unit_library.md`: physics templates for common unit operations.
- `references/recommended_processes.md`: processes to offer when asked to recommend.
- `references/validation_checklist.md`: what to check before calling a dataset done.
