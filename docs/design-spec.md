# Synthetic Plant Data Simulator: Design Spec

A working specification for building a simulator that generates realistic continuous chemical process data, suitable as a substrate for agentic diagnostic systems.

Hand this to Claude Code as a design reference. It is not itself the skill. The skill gets extracted later, after a reference implementation exists.

---

## 0. Premise, and one correction

The instinct is to ask an LLM to generate plant data directly. Do not do this. LLMs are bad at emitting realistic numeric series. Ask for 5,000 rows of boiler data and you get something plausible for twenty rows that then fails every test a process engineer would run: wrong autocorrelation structure, no meaningful spectral content, variables that correlate at zero lag, and noise that is suspiciously white.

What LLMs are excellent at is writing the simulator. So the hard rule is:

> **The model never emits numeric data. The model writes code that generates numeric data.**

This makes the output reproducible, auditable, and parameterizable, all of which matter if any of this gets published.

---

## 1. What makes real plant data hard to fake

These are the properties that give synthetic data away. Each one maps to a layer in the architecture below.

**Control loops.** Most measured variables are held at setpoint by a PID. Naive simulation lets the process variable wander. In reality the controlled variable sits flat with characteristic small cycling, and the information lives in the manipulated variable. Fouling shows up as the valve slowly opening while the temperature stays perfect. Get this wrong and nothing else matters, because the correlation structure of the entire dataset is wrong.

**Historian compression.** PI and PHD use swinging door compression with a per-tag deadband. Data is not on a regular grid, timestamps are irregular, values are held between stored points, and resampling produces staircases. Almost nobody simulates this, and it is one of the fastest tells. It also directly shapes any agent built on the data, since the tools must handle it.

**Transport lag.** Change a feed rate and the downstream analyzer moves eight minutes later. Synthetic data usually correlates instantaneously.

**Per-instrument noise signatures.** Flow is noisy and fast. Temperature is smooth and slow because thermal mass acts as a low-pass filter. Level integrates and drifts. Analyzers are slow, discretized, and sampled every few minutes. One noise model across all tags is wrong.

**Sensor pathology.** Quantization from a 12-bit transmitter, calibration drift, spikes, dropouts, and frozen values where a stuck transmitter repeats the last reading for hours. Frozen values are everywhere in real historians and almost never in synthetic data.

**Correlated missingness.** Instruments do not fail independently. A DCS node drops and forty tags go bad quality at the same instant. An analyzer is out for a scheduled maintenance window.

**Mass and energy balance.** Real data nearly closes but not quite, off by instrument error plus a small persistent bias. Synthetic data usually either closes exactly, which is fake, or not at all, which is worse.

**Nonstationarity.** Ambient temperature and cooling water temperature drive diurnal and seasonal swings that hit many tags at once, creating correlation that is common-cause rather than causal. Slow degradation sits on top, with step resets at cleanings and turnarounds.

**Cross-system inconsistency.** Historian, alarm, and LIMS timestamps come from different clocks. Lab data is sparse and delayed, with sample time and analysis time as separate fields. Operator logs are free text written at shift end. An agent has to reconcile these, so the data should make that genuinely hard.

**Alarm realism.** Real ISA-18.2 alarm logs are mostly noise: chattering alarms, standing stale alarms, shelved and suppressed points, and floods during upsets where the causal alarm is buried among two hundred consequential ones. Clean alarm data makes root cause analysis artificially easy.

---

## 2. Layer architecture

Ten layers. Data passes through them in order.

| # | Layer | Contents |
|---|-------|----------|
| 1 | Plant config | YAML: units, streams, tags, engineering units, ranges, instrument classes, loop pairings |
| 2 | Process dynamics | ODE or state-space core, deadtime, operating-point-dependent gains, enforced mass and energy balance |
| 3 | Control | PID with realistic tuning, cascades, saturation, anti-windup, some loops in manual or detuned |
| 4 | Disturbances | Colored noise, ambient and seasonal drivers, feed composition variability, upstream unit swings |
| 5 | Degradation | Fouling, catalyst decay, with reset events at cleanings |
| 6 | Fault injection | Faults enter the process layer and propagate through causal structure with lag, partially masked by controllers |
| 7 | Measurement | Per-instrument dynamics, noise, quantization, drift, spikes, freezes, dropouts |
| 8 | Historian | Compression, irregular timestamps, quality codes, tag naming conventions |
| 9 | Context generation | Alarms, lab samples, operator logs, work orders |
| 10 | Validation | Ground truth manifest and acceptance tests |

### The hard rule about layers

**Faults are injected at layer 6, never at layer 7.**

If you add a fault to the final signal, you have created a step change in a CSV, not a process upset. Faults must be parameter modifiers that alter how state evolves, so that the controller responds, the effect propagates with correct lag, and the observable is partially masked. This is the single most important structural decision in the simulator.

### The split that makes it tractable

Layers 2 through 6 live inside the integration loop because they change how state evolves. Layers 7 through 9 are pure post-processing on the finished array. Nothing in the measurement or historian layer can affect the physics.

So: simulate on a clean fine fixed grid, then corrupt it.

---

## 3. Implementation

### 3.1 Core loop

```python
dt_sim = 0.1      # integration step, seconds
dt_scan = 1.0     # DCS scan rate, seconds
n_sub = int(dt_scan / dt_sim)

x = x0.copy()
log = []

for k in range(n_steps):
    t = k * dt_scan

    # layer 4: disturbances resolved at this instant
    d = disturbances(t)

    # layers 5 and 6: degradation and faults are parameter modifiers
    p = base_params.copy()
    for f in faults:
        f.apply(p, t)

    # layer 3: controllers execute once per scan, zero-order hold on output
    u = {}
    for loop in loops:
        pv = sensor_reading(x, loop.pv_tag)   # what the controller actually sees
        u[loop.mv_tag] = loop.step(pv, dt_scan)

    # layer 2: integrate with u held constant across the scan
    for _ in range(n_sub):
        x = rk4(derivatives, x, u, d, p, dt_sim)

    log.append((t, x.copy(), u.copy(), d.copy(), p.copy()))
```

Two things matter here:

1. The controller runs at its own scan rate with a zero-order hold on the output. This is what a real DCS does and it produces the characteristic sawtooth in manipulated variables.
2. The controller sees `sensor_reading`, not the true state. Sensor lag and noise belong inside the feedback loop.

### 3.2 Process layer

Reference example, heated stirred tank with level and temperature under control:

```python
def derivatives(x, u, d, p):
    h, T = x
    V = p['area'] * h

    F_in = d['feed_flow']
    T_in = d['feed_temp']

    # valve characteristic: nonlinear, gives operating-point-dependent gain
    F_out = p['Cv_out'] * u['LV-101'] * np.sqrt(max(h, 1e-6))
    Q = p['UA_coil'] * u['TV-101'] * (p['T_steam'] - T)

    dh = (F_in - F_out) / p['area']
    dT = (F_in * (T_in - T) / V
          + Q / (p['rho'] * p['cp'] * V)
          - p['UA_loss'] * (T - d['T_amb']) / (p['rho'] * p['cp'] * V))
    return np.array([dh, dT])
```

The nonlinearity is free here and it is real. The square root on the valve means process gain changes with level, so a loop tuned at 60 percent level cycles at 30 percent. Ambient enters the heat loss term, so every temperature in the plant picks up a diurnal component without scripting one.

### 3.3 Faults as parameter modifiers

```python
@dataclass
class CoilFouling:
    onset: float        # seconds
    tau: float          # seconds, time constant of degradation
    severity: float     # asymptotic fractional loss of UA

    def apply(self, p, t):
        if t < self.onset:
            return
        frac = self.severity * (1 - np.exp(-(t - self.onset) / self.tau))
        p['UA_coil'] *= (1 - frac)
```

Nothing is added to any signal. UA degrades, temperature sags, the controller opens TV-101 to compensate, and temperature returns to setpoint within a couple of time constants. The observable is the valve position drifting up over days while the temperature looks perfect. That masking behavior falls out of the physics rather than being scripted.

Instrument faults (a fouled orifice plate, a drifting transmitter) go in the measurement layer instead. Deciding which layer a fault belongs to is the main design judgment in the whole simulator.

### 3.4 Controller

```python
class PID:
    def step(self, pv, dt):
        e = self.sp - pv if not self.reverse else pv - self.sp
        p_term = self.kc * e
        d_term = -self.kc * self.td * (pv - self.pv_prev) / dt   # derivative on PV
        out_unsat = p_term + self.integral + d_term
        out = np.clip(out_unsat, 0.0, 1.0)
        if out == out_unsat:                      # conditional integration
            self.integral += self.kc * dt / self.ti * e
        self.pv_prev = pv
        return out
```

Derivative on PV rather than error, so setpoint changes do not kick. Integral accumulates only when the output is off the stops, which is the simplest correct anti-windup. When a fault drives a valve to 100 percent, the loop should sit saturated without winding up, because the recovery behavior after the fault clears is a signature an agent can learn from.

Deliberately detune two or three loops and put one in manual. Every real plant has them, and a dataset where all loops are perfectly tuned is its own kind of tell.

### 3.5 Deadtime

```python
class DeadTime:
    def __init__(self, delay_s, dt_scan, init):
        n = max(1, int(delay_s / dt_scan))
        self.buf = deque([init] * n, maxlen=n)

    def __call__(self, v):
        self.buf.append(v)
        return self.buf[0]
```

Apply wherever a measurement is downstream of where the action happens. This is what puts the cross-correlation peak at the declared lag instead of at zero.

### 3.6 Measurement layer

Vectorized after the loop finishes, driven by instrument class from the YAML:

```python
def apply_instrument(true, cls, rng):
    v = true.copy()
    if cls.tau > 0:                                   # sensor lag, e.g. thermowell
        v = first_order_filter(v, cls.tau, dt_scan)
    v += ou_noise(len(v), cls.noise_sigma, cls.noise_tau, rng)
    v += cls.drift_rate * np.arange(len(v)) * dt_scan
    v = np.round(v / cls.lsb) * cls.lsb                # transmitter quantization
    return v
```

Colored noise, not white. Ornstein-Uhlenbeck with a short correlation time for flow and a long one for temperature. White noise across every tag is the fastest way to fail an autocorrelation check.

Spikes, freezes, and dropouts go on top as event schedules. A freeze is just `v[i0:i1] = v[i0]`. Correlated missingness operates on a tag group rather than a single tag, so one DCS node event marks forty tags bad quality over the same index range.

### 3.7 Historian compression

Swinging door per tag, with per-tag deadband as a percentage of range:

```python
def swinging_door(t, v, dev):
    keep, anchor = [0], 0
    smax, smin = -np.inf, np.inf
    for i in range(1, len(t)):
        dti = t[i] - t[anchor]
        s_up = (v[i] + dev - v[anchor]) / dti
        s_lo = (v[i] - dev - v[anchor]) / dti
        if s_lo > smin or s_up < smax:      # cone closed
            keep.append(i - 1)
            anchor = i - 1
            smax, smin = -np.inf, np.inf
            dti = t[i] - t[anchor]
            s_up = (v[i] + dev - v[anchor]) / dti
            s_lo = (v[i] - dev - v[anchor]) / dti
        smax = max(smax, s_lo)
        smin = min(smin, s_up)
    keep.append(len(t) - 1)
    return keep
```

Because the deadband differs per tag, every tag ends up with a different set of timestamps. That single fact is what makes the dataset genuinely hard to work with, forces tools to resample explicitly, and reproduces what real historian data actually does.

Store the compressed result long-format: `tag, timestamp, value, quality`. That matches a PHD or PI export and drops straight into DuckDB.

---

## 4. Ground truth manifest

Emit this during simulation, not reconstructed afterward. Things are known inside the loop that are hard to recover later.

```json
{
  "fault_id": "F-003",
  "type": "coil_fouling",
  "true_onset_s": 432000,
  "root_cause_tag": "E-101",
  "first_observable_tag": "TV-101",
  "first_observable_s": 448200,
  "propagation": [["TV-101", 0], ["TI-101", 1800], ["FI-102", 5400]],
  "causal_alarms": ["TV-101.HI"],
  "consequential_alarms": ["TI-101.LO", "FI-102.LO"],
  "masked_by_control": true
}
```

The gap between `true_onset_s` and `first_observable_s` is the difficulty dial. Widen it and the fault becomes genuinely hard.

That number is also the honest headline for any benchmark published from this. Not "the agent found the fault" but "the agent found it 4.1 hours after first observability, where a variance threshold took 19 hours and a human took 3 days."

---

## 5. Validation battery

This is the anti-hallucination mechanism and the part most simulators omit. Write these as runnable pytest cases.

### 5.1 Run this one first

```python
def test_fault_not_trivially_detectable(dataset, truth):
    for f in truth.faults:
        for tag in dataset.tags:
            v = dataset.resample(tag, "5min")
            z = (v - v[:baseline_end].mean()) / v[:baseline_end].std()
            first = np.argmax(np.abs(z) > 3)
            assert first * 300 > f.first_observable_s + MIN_LEAD, \
                f"{tag} trips a 3-sigma detector before the intended window"
```

Most synthetic fault data is trivially detectable, which makes any agent built on it look brilliant and tells you nothing. If a moving-window variance one-liner finds the fault instantly, the dataset is too easy and every downstream result is worthless.

### 5.2 The rest

- Mass balance closes within stated instrument error, with residual bias in a plausible range
- Autocorrelation decay time per tag is within an expected band for its instrument class
- Controlled variables show low variance at setpoint while manipulated variables carry the movement
- Cross-correlation peaks at the declared transport lag, not at zero
- PCA on normal operation yields the expected effective dimensionality
- No tag violates physical bounds; compositions sum to one; nothing goes negative

### 5.3 Calibration against something real

The strongest version of this work is running the same validation battery against real data. Use TEP, or any de-identified historian export you can obtain, and tune the simulator until the statistical fingerprints match.

Then the claim becomes "synthetic data passes the same tests real data does," which is defensible, rather than an assertion.

---

## 6. Scenarios

Ordered so each adds exactly one new capability to the simulator and one new demand on the agent. Build in this order.

### 6.1 Heated stirred tank, coil fouling

Two states, two loops. The reference implementation. Fault is slow UA degradation fully masked by the temperature controller.

**Tests:** whether the agent looks at the manipulated variable instead of the controlled variable. The single most important habit in process diagnosis, and most agents fail it because the temperature trend looks perfect the entire time.

### 6.2 Exchanger fouling with competing explanations

Same unit, three separate scenarios producing an identical first symptom (steam valve slowly opening): coil fouling, gradual feed rate increase, and slow decline in steam header pressure.

**Tests:** discrimination, not detection. The agent must query other tags to rule things in and out. Feed rate is visible in FI-101. Header pressure is a different tag entirely. Fouling leaves both flat.

This is where the knowledge graph earns its place, since disambiguation is a structural question about what feeds what. **Build the demo around this one.**

### 6.3 Distillation column, feed composition upset

Four to six states, dual composition control, analyzer with eight minutes deadtime, sparse delayed LIMS samples that disagree slightly with the online analyzer.

**Tests:** multivariate coupling and cross-source reconciliation. Reflux and reboiler duty interact, so moving one degrades the other. The lab result arrives four hours after the sample was pulled, with sample time and analysis time as separate fields, and the agent must align them correctly to reason about when composition actually shifted.

### 6.4 Pump, seal degradation with intermittent cavitation

Adds a fast-sampled vibration tag at a different rate from the process tags, plus genuinely spiky data.

**Tests:** the hard regime. Cavitation is event-driven and bursty, exactly where forecasting and anomaly methods struggle. Also forces tools to handle mixed sample rates in one query.

Worth building specifically because it is where the agent should look worse. Publishing that honestly is more credible than five scenarios where it wins.

### 6.5 Fired heater or boiler, cascading trip with alarm flood

Drum level with shrink and swell, so level moves the wrong way first. A fuel gas pressure disturbance propagates to combustion air, firing rate, steam temperature, and drum level, generating a couple hundred alarms in ten minutes with the causal one buried early in the sequence.

**Tests:** alarm triage under ISA-18.2, plus inverse response. Shrink and swell makes a feedwater increase drop indicated level before raising it. An agent reasoning naively about direction gets causality backwards, which sharply tests whether it understands the process or is pattern matching on trends.

### 6.6 No-fault variants (not optional)

Run every scenario again with identical disturbances, ambient cycling, and degradation, but no injected fault.

Nothing else measures the false positive rate. An agent that confidently finds a root cause in clean data is worse than useless in a control room. Cheapest scenario to build, and the one that most affects how results are received by anyone who has run a plant.

### 6.7 Sequencing note

6.1 and 6.2 share a simulator, so the highest-value demo costs barely more than the reference case. 6.3 is a real jump in effort because of the column model, so do not start there. 6.4 and 6.5 each add a data type rather than physics complexity, making them good candidates for later content since the visual is a vibration trace or an alarm flood rather than another line chart.

---

## 7. Tag counts

A control loop is not one tag. It is PV, SP, OP, and MODE at minimum, sometimes plus alarm limits and a bad-quality flag. Forty loops is 160 tags before counting a single indicator.

| Scenario | Loops | Process tags | Total |
|---|---|---|---|
| Stirred tank | 2 | ~10 | ~18 |
| Tank, competing causes | 2 | ~16 | ~25 |
| Column | 6 | ~45 | ~70 |
| Pump | 1 | ~20 + vib channels | ~30 |
| Fired heater | 7 | ~90 | ~120 |

For the pump, vibration is separate from the process tag count because it runs at a different rate. Three or four channels at 1 kHz, or precomputed band energies at 1 Hz if waveform storage is unwanted.

For the fired heater, the alarm log is rows, not tags. Budget two to three hundred alarm records in the ten minutes around the trip, against a baseline of roughly forty per day.

### Ballast tags

The number driving agent difficulty is not total tags, it is the ratio of relevant to irrelevant. If all 18 tags in the tank dataset bear on the fault, retrieval is trivial and the agent looks smart for no reason. Real plants have thousands of tags of which six matter.

Add ballast: unrelated loops from neighboring units running normally, with their own disturbances and noise, sharing only the ambient driver. They cost almost nothing to generate since they need no coupled physics, and they turn tag selection into a real problem.

Suggested: tank at 18 real plus 60 ballast, fired heater at 120 plus 300. Then the knowledge graph is doing actual work narrowing the search rather than decorating an answer reachable by reading every tag.

---

## 8. Skill structure

One skill, not five. Five would duplicate 90 percent of their content, because the layer architecture, validation battery, ground truth schema, and historian corruption are identical across every unit. Only the derivatives function and config vary. Duplicated methodology also drifts: improve the swinging door in one and forget the others.

```
process-data-sim/
  SKILL.md              methodology, build order, hard rules
  reference/
    architecture.md     the 10 layers, what belongs in each
    validation.md       the battery, with rationale per test
    ground_truth.md     manifest schema
    unit_library.md     physics templates per unit type
  templates/
    plant_config.yaml
    derivatives_template.py
    test_validation.py
  reference_impl/
    stirred_tank/       working code that passes everything
```

SKILL.md stays short and always loads. Claude Code reads `unit_library.md` only when it needs the column equations. Adding a sixth unit type becomes a section in one reference file rather than a new skill.

### Rules that belong in SKILL.md itself

State these as prohibitions, because they are what gets violated when left implicit:

- Never emit numeric data directly. Write the simulator.
- Never inject a process fault in the measurement layer.
- Never use white noise for instrument noise.
- Never skip the trivial-detectability test.
- Never use global `np.random`. Thread one seeded Generator explicitly.

---

## 9. Workflow

The intuitive order is skill, then simulator, then dataset. Do not do that. Writing the skill first means encoding guesses about what is hard, and those guesses will be wrong about which parts Claude Code actually fumbles.

**1. Implement.** Build the reference implementation by hand with Claude Code, no skill. Just scenario 6.1. Get the tank passing the full validation battery. This surfaces things no amount of upfront design does, like where the deadtime buffer must sit relative to the controller, or that the first swinging door implementation drops the wrong endpoint.

**2. Extract.** Write the skill from the working code. The skill documents what was actually done, and `reference_impl/stirred_tank/` becomes the artifact it points at. Pattern matching against real code beats following prose instructions, which is why the reference implementation is the most valuable file in the folder.

**3. Validate cheaply.** Scenario 6.2 reuses the same simulator with new fault definitions, so it mostly checks that the config schema and ground truth manifest generalize.

**4. Stress.** Scenario 6.3 is the real test, because the column is new physics and new unit operations. Wherever Claude Code struggles is a gap in `unit_library.md` or an underspecified rule in SKILL.md.

**5. Revise, then build 6.4 and 6.5.**

### Build order within a single scenario

Get one loop working with pure physics and no corruption. Confirm it responds sensibly to a setpoint step. Add the second loop and check the interaction. Then disturbances, then one fault, and verify from the plot that the controller masks it as expected. Only then add the measurement and historian layers.

Debugging physics through quantization noise and irregular timestamps is miserable. Do not do it.

Expect roughly 1,200 lines for a two-loop unit. The CFB boiler version is more states and more loops but not a different architecture.

---

## 10. Reproducibility and repo hygiene

Keep the simulator and configs in git. Do not commit generated parquet. Put the RNG seed in the config so that a given config plus seed reproduces the dataset exactly, then attach one generated dataset per scenario to a GitHub release. This keeps the repo small, makes results reproducible, and lets someone regenerate at a different length or difficulty without downloading anything.

Determinism needs care. Use one seeded `np.random.Generator` threaded through explicitly, never the global `np.random`. Otherwise adding a fault shifts every downstream draw, and the no-fault variant stops being the same run minus the fault, which quietly breaks the comparison that scenario 6.6 exists to make.

---

## 11. Honest limits

Simulated data validates that the architecture works and that tools return sensible things. It cannot validate that an agent will diagnose a real plant, because the failure modes not thought to simulate are exactly the ones that will bite in production.

Keep that distinction explicit in anything published. The credibility of the whole position rests on not overclaiming.
