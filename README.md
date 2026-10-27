# HistorianSim

**Describe a chemical process to Claude, and HistorianSim simulates it: the process physics, the
control loops, the instruments and the plant historian.** You get 90 days of
time-series data with faults injected, plus an answer key that says what
went wrong, when, and how to tell from the data.

Use it to practice root cause analysis, test a fault detection or machine
learning method, train an AI agent, or teach. Nothing in the data comes from
a real plant, so you can share it freely.

---

## How to make a dataset

You need two things installed once: **Python** and **Claude Code**. Then it
is six steps.

### One-time setup

1. **Install Python 3.11 or newer** from [python.org/downloads](https://www.python.org/downloads/).
   On Windows, tick **"Add python.exe to PATH"** on the first screen of the
   installer.
2. **Install Claude Code.** It needs a Claude Pro, Max, Team or Enterprise
   plan. Open a terminal (on Windows, *PowerShell*; on a Mac, *Terminal*) and
   paste the line for your computer:

   Windows (PowerShell):
   ```
   irm https://claude.ai/install.ps1 | iex
   ```
   Mac or Linux (Terminal):
   ```
   curl -fsSL https://claude.ai/install.sh | bash
   ```
   The first time you run `claude`, it asks you to log in to your Claude
   account. The [Claude Code documentation](https://code.claude.com/docs) has
   more detail if you need it.

### Every time you want a dataset

1. **Download HistorianSim.** On this page, click the green **Code** button,
   then **Download ZIP**. Unzip it somewhere convenient, for example your
   Documents folder. You get a folder called `HistorianSim-main`.
2. **Open a terminal in that folder.**
   - Windows: open the folder in File Explorer, right-click an empty space
     and choose **Open in Terminal**.
   - Mac: right-click the folder in Finder and choose **New Terminal at
     Folder**.
3. **Start Claude** by typing:
   ```
   claude
   ```
4. **Type `/simulate`, then describe the process in as much detail as you
   can.** For example:

   > /simulate A continuous jacketed reactor making ethylene glycol from
   > ethylene oxide and water, about 15 m3/h of feed. Reactor temperature is
   > controlled by cooling water through the jacket, cascaded to jacket
   > outlet temperature. Level is controlled on the outlet. There is an
   > on-line analyzer for unreacted ethylene oxide.

   Useful things to include:
   - the equipment;
   - the chemistry or service;
   - rough flows and temperatures;
   - how each loop is controlled;
   - any faults you particularly want.

   If you are not sure what to simulate, type `/simulate` on its own, or
   `/simulate recommend a process`, and Claude will suggest some.
5. **Approve the design.** Claude asks a question or two if it needs to. It
   then shows you a short design:
   - the process;
   - its control scheme;
   - the 9 faults it plans to hide in the data.

   Reply `approved`, or tell it what to change.
6. **Wait for the dataset.** Claude builds the simulation, checks the physics
   at each stage, generates the data and validates it. That takes roughly one
   to two hours for a new process. When it finishes, it tells you where the
   dataset is and summarises the faults.

The first time, Claude also sets up the Python packages HistorianSim needs.
You don't have to do anything for that.

**Want a dataset right away?** Two processes are already built. Type
`/simulate` and ask for one of these; each takes about 20 minutes to
generate.

| Process | What it is |
|---|---|
| **R-201 reactor** (`cstr-rca`) | Jacketed CSTR making propylene glycol. Reactor temperature cascaded onto jacket temperature, water feed ratioed to PO feed, on-line residual PO analyzer. |
| **TK-101 hold tank** (`tank-rca`) | Steam-heated agitated tank. Temperature cascaded onto steam flow, plus level control. The unit behind the [HistorianRCA](https://github.com/ScottDuncanAI/HistorianRCA) dataset. |

---

## What you get

Each dataset is a folder inside `output/`:

```
output/cstr-rca-standard-s7/
  historian_10s.parquet    the full record at the 10 s DCS scan
  historian_60s.parquet    the same data on a regular 1-minute grid
  tags.csv                 tag dictionary: description, units, range, instrument type
  PROCESS_DESCRIPTION.md   the plant: equipment, physics, control strategy, every tag
  FAULT_ANSWER_KEY.md      every event: start, end, root cause, and the evidence
  metadata/                per-minute fault labels, plus the settings that reproduce the dataset
```

What is in the data:

- **90 days at a 10 s scan.** About 40 tags on the unit itself, plus about 60
  tags from neighbouring equipment that shares only the weather. You have to
  work out which tags matter.
- **14 days of normal operation first.** Use them to learn what normal looks
  like.
- **9 faults.** Each has a different root cause and a different failed
  item, and each has at least 2 days of normal operation either side. They
  include:
  - equipment problems such as fouling, a sticking valve or a damaged
    impeller;
  - utility and upstream problems;
  - control problems;
  - instrument problems.
- **2 deliberate operator actions,** such as a setpoint change. They look
  abnormal but are not faults.

The answer key gives, for every fault:

- start and end times;
- the root cause and the failed item;
- a plain-language explanation of how to diagnose it from the data;
- the other causes with the same first symptom, and the tags that rule
  each one out.

**Opening the data.** `historian_60s.parquet` is the easiest place to start:
one column per tag and one row per minute. It opens in Python (pandas), Power
BI, Spotfire, Seeq and most analytics tools. If you would rather use Excel,
ask Claude to "export the 60 second data to CSV".

```python
import pandas as pd

grid = pd.read_parquet("historian_60s.parquet")   # timestamp + one column per tag
tags = pd.read_csv("tags.csv")
```

`historian_10s.parquet` is stored the way a real historian stores data. It
has one row per stored value, with columns `tag`, `timestamp`, `value` and
`quality`. Each tag only keeps a value when it changes by more than its
deadband, so every tag has its own timestamps.

**Using it as a blind test.** Give someone everything except
`FAULT_ANSWER_KEY.md` and the `metadata` folder. Or ask Claude to "make a
challenge from this dataset". That produces a separate folder with a task
statement and an answer template, and Claude can score the answers when they
come back.

---

## Why the data behaves like plant data

HistorianSim never makes up numbers. It solves the material and energy
balances of the process, runs real PI controllers against them, and then
passes the result through models of the instruments and the historian. The
faults are changes to the process itself, such as a lower heat-transfer
coefficient or a valve that sticks. So:

- **Control loops hide faults the way they do on a real plant.** A fouling
  jacket does not show up in reactor temperature, because the controller
  holds it on setpoint. It shows up in the cooling valve slowly opening.
- **Several faults share the same first symptom.** Telling them apart means
  checking the right other tag, as in a real investigation.
- **The instruments behave like instruments:**
  - noise that is smooth on a thermowell and fast on a flowmeter;
  - slow calibration drift;
  - spikes;
  - stuck transmitters that keep reporting good quality;
  - whole groups of tags going bad when a DCS node drops out.
- **The historian compresses the data.** Every tag has its own irregular
  timestamps, as in a PI or PHD export.
- **The weather reaches everything.** Daily and seasonal ambient swings
  move cooling water, feed temperatures and heat losses, so many tags move
  together for no process reason.

### How we know it works

Every dataset is checked automatically before it is handed over:

- **Controlled variables:** they stay on setpoint while valves do the moving.
- **Balances:** they nearly close but not exactly.
- **Noise:** it has the right character for each instrument type.
- **Transmitter ranges:** no transmitter sits pinned at its range limit.
- **No giveaways:** the process description and tag list give nothing away.
- **Difficulty:** no subtle fault is caught instantly by a simple alarm
  limit.
- **Solvability:** every fault leaves evidence in the data.

Each new process also has every fault in its catalog injected one at a time,
to confirm the evidence moves the way the answer key says.

The shipped R-201 reactor dataset was also given **blind** to an AI agent.
The agent had only the data, the tag list and the process description, with
no answer key. In the final round it found all 9 faults with the correct
root cause and raised no false alarms. The full report is in
[`docs/validation/cstr-rca-s7.md`](docs/validation/cstr-rca-s7.md).

### Limits

Simulated data shows whether a method works and whether your tools give
sensible answers. It cannot show that a method will diagnose a real plant,
because real plants fail in ways nobody thought to simulate. Keep that in
mind in anything you publish from these datasets.

The simulations cover continuous operation near one operating point.
Startups, shutdowns, trips and batch operation are not modelled.

---

## Other ways to get HistorianSim

**With git.** If you use git, clone the repository instead of downloading
the ZIP. The steps are otherwise the same.

```
git clone https://github.com/ScottDuncanAI/HistorianSim.git
cd HistorianSim
claude
```

**Without Claude.** The simulator is a Python package and runs on its own.
In the HistorianSim folder:

```
python -m venv .venv
.venv\Scriptsctivate                        (Windows)
source .venv/bin/activate                     (Mac or Linux)
python -m pip install -e .

historiansim list                              list the processes and scenarios
historiansim generate cstr-rca --seed 7        make the R-201 dataset
historiansim plot output/cstr-rca-standard-s7 --episode EP-003
```

New processes need Python code, which is what Claude writes for you with
`/simulate`. If you want to write one yourself, start from the two built-in
processes in `src/historiansim/plants/`.

---

## About

Made by Scott Duncan ([LinkedIn](https://www.linkedin.com/in/scottduncanai/)),
built with [Claude Code](https://claude.com/claude-code). Released under the
MIT license.
