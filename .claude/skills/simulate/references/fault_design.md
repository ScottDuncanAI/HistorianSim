# Designing a fault catalog

The catalog decides whether a dataset tests **discrimination** or merely
**detection**. Detection is easy: something moved. Discrimination is the
real job: several causes produce the same first symptom, and telling them
apart takes querying the right *other* tag. A good catalog makes that the
whole problem.

## Organise by symptom, not by cause

A **symptom class** is a first observable shared by several root causes, for
example "cooling valve slowly opening while reactor temperature sits on
setpoint". Aim for 3–5 classes with 2–6 causes each. Each class gets a
`tempo`:

- `slow`: degradations that run for days;
- `cycling`: oscillations that get noticed in a few days;
- `acute`: excursions somebody responds to within hours.

Within a class, causes should differ in **one or two tags only**. That is
what makes a diagnosis earn its answer. The reference plants' best pairs:

| Pair | Same symptom | The one tag that separates them |
|---|---|---|
| TK-101 coil fouling vs condensate backup | valve opens, temperature held | condensate temperature `TI-202` falls only for backup |
| R-201 jacket fouling vs impeller damage | valve opens, UA falls | agitator power `JI-201` falls only for the impeller |
| R-201 catalyst deactivation vs analyzer drift | residual PO rises | jacket duty falls only when the reaction really slowed |
| R-201 element drift vs real temperature change | conversion and cooling move | the second element `TI-204` disagrees with the controlled one |
| TK-101 product meter offset vs vessel leak | balance opens | the outlet valve moves only for a real loss |

## Use every injection layer

| Layer | Class | Example | What it changes |
|---|---|---|---|
| 2 / 6 process | `ProcessFault` | fouling, stiction, leak, catalyst activity | a model parameter, inside the integration loop |
| 4 disturbance | `DisturbanceFault` | utility header sag, feed temperature, pump surging | a disturbance channel |
| 3 control | `ControlFault` | loop left in manual, setpoint moved | the control system |
| 7 instrument | `InstrumentFault` | transmitter drift or zero shift, analyzer drift | one tag's reading; inside the loop too if the tag is controlled |

The benchmark's 9 causes should span at least 3 classes and at least 3
layers.

**Choosing the layer is the main design judgment.** A fouled orifice
plate or a drifting transmitter changes what one transmitter *reports*, not
the process, so it is an `InstrumentFault`. A balance built from it stops
closing while every real quantity is unchanged. Real degradation changes a
parameter, so the controller responds and the effect propagates with lag.

## The control loop is your friend

Faults that the control system masks are the interesting ones. A
temperature fault that shows up in the temperature is easy. One that shows
up only in the valve position, with temperature perfect, tests whether the
analyst looks at the manipulated variable. Design at least half the catalog
to be masked (`masked_by_control=True`).

A transmitter fault on a **controlled** tag is especially rich. The loop
faithfully holds the false reading, so the *real* process moves away from
where everyone thinks it is. You need an independent measurement (a
redundant element, a downstream indicator, a balance) to catch it.

## Evidence: what to declare

For each cause, list 3–7 `Evidence` items:

- **`rules_in`** on the tag that confirms it;
- **`rules_out`** on tags that eliminate each competitor. Elimination does
  most of the work: a flat feed flow does not prove fouling, it eliminates
  feed creep;
- **expectations** `rises` / `falls` / `steps` / `erratic` / `frozen` / `flat`.
  `frozen` (a tag stops responding) is a positive observation, different from
  `flat` (not affected).

Every competitor in the class must be ruled out by at least one item on
every cause. Stage 3 of `check-plant` measures each claim. A `flat` that
moves, or a `rises` that falls, is a bug in the physics or in the claim.

## Severity sizing

Each builder takes `subtle`, `moderate` or `obvious`:

- **subtle:** the first days move the evidence less than the weather does.
  It must still be separable from its no-fault twin within the episode,
  and must not be caught instantly by a 3-sigma threshold. The battery checks
  both.
- **moderate:** clear in daily averages within a day or two.
- **obvious:** clear in the raw trend within hours.

Size from the steady-state equations, not by eye. For example, compute where
the valve saturates and keep `obvious` short of it unless saturation is the
point (an acute class).

## The benchmark's 9

- No two may share a `component`, a mechanism (`name`) or an `id`. For
  example, header pressure decline and header supply loss are the same
  component, so pick one.
- Interleave the classes in onset order.
- Choose so each pinned cause has at least two competitors in its class that
  are **not** pinned. Those are what the diagnosis must rule out.
- Mix severities: about 2 subtle, 5 moderate, 2 obvious.
- Give the 9 pinned causes a `grade`, a qualitative `walkthrough` and the
  `competitors` it eliminates.

## Benign events

Two `BenignEvent`s: operator moves the unit responds to normally (a
temperature setpoint step, a rate change). They must resemble a fault's
first symptom. The tell that they are benign is a setpoint tag moving.
