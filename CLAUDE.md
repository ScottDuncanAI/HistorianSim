# HistorianSim

This repo generates realistic chemical-plant historian datasets: a dynamic
simulation of one process unit, its control loops and its instruments, with
the data corrupted the way a real DCS and historian corrupt it.

Each dataset is 90 days of data with these properties:

- a clean 14-day baseline, then 9 different fault events, each diagnosable
  from the data and the process description;
- 2 deliberate operator moves;
- a fault answer key;
- a conceptual PFD of the unit (`PFD.svg`, `PFD.png`), drawn with the copy of
  the PFD generator skill in `.claude/skills/simulate/pfd-generator/`.

The people using this repo are mostly process and chemical engineers, not
software developers. Talk to them in engineering terms, run every command
yourself, and never ask them to edit code.

## When the user asks for a dataset

Any request to simulate a process, build a dataset or recommend a process
goes through the **`/simulate` skill** (`.claude/skills/simulate/`). Follow it
step by step. If the user just wants a shipped process, run it:

```bash
historiansim list                                      # processes, scenarios, recipes
historiansim generate cstr-rca --seed 7 --out output   # R-201 reactor, 90 days, about 20 min
historiansim generate tank-rca --seed 42               # TK-101 tank, 90 days
historiansim generate cstr-rca --profile quick         # 7-day version, about 2 min
```

## First-run setup (do this yourself if it is missing)

1. Python 3.11 or newer is required: check with `python --version`. If it is
   missing, ask the user to install it from python.org, ticking "Add
   python.exe to PATH" on Windows.
2. Create a virtual environment in the repo and install the package:
   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -e ".[dev]"   # Windows
   .venv/bin/python -m pip install -e ".[dev]"       # macOS / Linux
   ```
3. Run the `historiansim` command through the venv:
   `.venv/Scripts/historiansim` (Windows) or `.venv/bin/historiansim`.
4. Smoke test: `historiansim check-plant exothermic_cstr --stage 1`.

## Hard rules

- **Never emit numeric data yourself.** Write or change the simulator, then
  run it.
- **Process faults are parameter modifiers inside the integration loop**
  (`ProcessFault`, `DisturbanceFault`, `ControlFault`). Only instrument faults
  (`InstrumentFault`) act on a reading. Never add a fault to a finished signal.
- **The controller sees the transmitter, not the truth.** Transmitter faults
  on a controlled tag are applied inside the loop automatically.
- **Coloured noise only**, and **never global `np.random`**: every random draw
  comes from a named `SeedBank` stream.
- **`PROCESS_DESCRIPTION.md`, `tags.csv` and the PFD describe the plant,
  never its faults.** Only `FAULT_ANSWER_KEY.md` and `metadata/` may name a cause.
  `historiansim audit` checks this.
- **Text the user reads is for process engineers.** Plain sentences, no em
  dashes, no rhetorical "it's not X, it's Y" phrasing.
- **Don't change shared engine code to make one plant work** unless the change
  is generic. Plants live entirely in `src/historiansim/plants/<name>/`.

## Layout

```
src/historiansim/
  plants/<name>/       one folder per process: model, tags, loops, faults, description
  plants/_template/    scaffold copied by `historiansim new-plant`
  core/                integration loop, PID, valves, deadtime, RNG
  measurement/         instrument classes, noise, drift, freezes, dropouts
  historian/           swinging-door compression, exports
  faults/              fault primitives, catalog types, episode scheduler
  truth/               ground truth and labels
  validation/          checks, catalog sweep, plant gates
  layout.py            file names of a written dataset
  scenarios.py         profiles and recipes (rca-benchmark)
```

The reference plants are `heated_stirred_tank` (TK-101, the HistorianRCA
unit) and `exothermic_cstr` (R-201). When writing a new plant, read both.

## Tests

```bash
python -m pytest tests -q -m "not slow"   # about 8 minutes
python -m pytest tests -q                 # adds the per-cause sweep for every plant
```
