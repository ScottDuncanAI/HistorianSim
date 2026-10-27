# ISA Conventions

ISA-5.1 conventions, simplified to what a conceptual drawing needs.

Simplified to what a conceptual drawing needs. Where full ISA-5.1 offers many variants, this file picks one and stays consistent.

### Contents
1. Instrument balloons
2. Tag construction
3. Signal line types
4. Control valves and failure position
5. Control loop patterns
6. Equipment symbols
7. Line and stream identification
8. Common errors reviewers catch

---

### 1. Instrument balloons

| Symbol | Meaning | How to draw |
|---|---|---|
| Plain circle, r=22 | Field mounted, locally accessible | `circle` white fill, stroke 1.4 |
| Circle inscribed in a square | DCS / shared display, shared control | `rect` 2r × 2r behind the circle |
| Circle with a single horizontal line | Central panel mounted, behind panel | add a chord line at cy |
| Circle with a double line | Auxiliary panel | two chord lines |
| Hexagon | Computer function | rarely needed conceptually |
| Diamond in a square | Logic / interlock (PLC) | use for trips and permissives |

Tag text sits in two lines: function letters on top (bold, 11.5), loop number below (10). Center both.

Balloons are drawn *after* the pipe so their white fill hides the line behind them. This is what keeps an inline flow element from having a line running through the tag.

Field elements attached to a vessel get a short solid lead line from the vessel wall to the balloon. That lead is a process/impulse connection, drawn thin (1.2) and solid, not dashed.

### 2. Tag construction

`[First letter][Succeeding letters]-[Loop number]`

**First letter — measured or initiating variable**

| Letter | Variable |
|---|---|
| A | Analysis |
| F | Flow |
| L | Level |
| P | Pressure |
| T | Temperature |
| W | Weight / force |
| S | Speed |
| H | Hand (manual) |

**Succeeding letters — function**

| Letter | Function |
|---|---|
| I | Indicator |
| C | Controller |
| T | Transmitter |
| R | Recorder |
| V | Valve, damper, louver |
| S | Switch |
| A | Alarm |
| Y | Compute / convert / relay |
| E | Primary element (sensor) |

**Modifiers**: `H` high, `L` low, `HH` high-high, `LL` low-low, appended as a subscript-style suffix (`LAH-101`).

**Indicator versus transmitter.** `I` means the instrument displays a reading and nothing
leaves it. `T` means it transmits a signal. So the tag has to match what is drawn: if a signal
line runs from a balloon to a controller, that balloon is a transmitter and must be tagged
`FT`, `LT`, `PT`, `TT` — never `FI`, `LI`, `PI`, `TI`. Tagging a transmitting element as an
indicator is a contradiction visible on the face of the drawing and is one of the first things
a reviewer flags.

Use the plain transmitter form (`FT-203`) rather than the combined form (`FIT-203`) unless the
instrument genuinely has a local display. When the element already reports through a paired
controller balloon on the DCS, the combined form claims field hardware that has not been
specified. Only tag an element `FI`/`LI`/`PI`/`TI` when it is terminal — a local gauge or a
DCS indication with no downstream control action.

Strictly, flow and temperature loops also carry a primary element separate from the
transmitter: `FE-203` (orifice) feeding `FT-203`, `TE-205` (thermowell) feeding `TT-205`.
Collapsing the pair into one balloon is normal on a conceptual sheet; draw both once the
drawing moves toward issued-for-design.

**Loop numbering.** Every element of one control loop shares one number. A temperature loop numbered 101 gives `TE-101`, `TI-101`, `TIC-101`, `TV-101`. Do not renumber the valve. Reviewers read loop numbers to trace the loop, so a mismatch reads as a real error.

Use a distinct series per system so numbers stay readable: 100 series for feed, 200 for steam, 300 for product, and so on.

### 3. Signal line types

| Type | Representation | Use |
|---|---|---|
| Electrical / DCS | Dashed, `7,5.5`, weight 1.35 | Default for all signals in a modern plant |
| Pneumatic | Line with double cross-hatches | Only if the user specifies pneumatic |
| Software / data link | Dotted with small circles | Internal DCS links, e.g. cascade between two blocks in the same controller |
| Capillary | Line with arcs | Filled thermal systems |

For most conceptual drawings, use one dashed style for everything and label it "DCS / instrument signal" in the legend. Introducing three signal styles on a conceptual sheet adds noise without adding information.

**Arrowheads carry meaning.** Draw them at 7 px with `orient="auto-start-reverse"`.

- Measurement: transmitter → controller. Arrow points *into* the controller.
- Output: controller → final element. Arrow points *into* the valve actuator.
- Remote setpoint (cascade): master controller → slave controller. Arrow points *into* the slave. Label the leg "cascade SP" or "remote SP" so it is not mistaken for a measurement.

A signal line with no arrowhead is ambiguous and counts as a defect.

### 4. Control valves and failure position

Body: two triangles meeting at a point (bowtie), white fill, stroke 1.6, miter joins.

Actuator, drawn on the side the signal arrives from:
- Diaphragm: rounded rectangle on a short stem
- Piston: plain rectangle
- Motor: circle containing `M`
- Solenoid: rectangle containing `S`

Drawing the actuator below the valve is acceptable and often necessary when the controller sits below the pipe. Do not route a signal up and across a process line just to reach an actuator on top.

**Failure position** goes next to the valve tag: `FC` fail closed, `FO` fail open, `FL` fail last/locked. Choose from the process consequence:
- Steam or fuel to a heater: **FC** (loss of air stops heat input)
- Cooling medium: **FO**
- Level letdown from a vessel that must not overflow: depends on which is safer; state the reasoning

### 5. Control loop patterns

**Simple feedback.** `XT/XI-n → XIC-n → XV-n`. Three legs, three arrowheads.

**Cascade.** Master controls the slow variable, slave the fast one.
```
TI-101  →  TIC-101  →(remote SP)→  FIC-201  →  TV-101
                                      ↑
                                   FI-201
```
Draw the master to one side of the slave and the remote-SP leg as a short horizontal between them. The slave has three connections (measurement in, remote SP in, output out) — assign them to three different ports on the balloon (bottom, one side, the other side or top) so no two legs overlap.

**Ratio, override, split range.** Add a `FY`/`TY` computing block between the controllers rather than implying the math in a line.

**Redundant transmitters.** Two transmitters feeding one controller need two separate signal legs into two different ports. If the arrangement is voting or selection, draw a `LY` selector block; otherwise annotate the intent.

**Interlocks and trips** are drawn as a diamond-in-square logic symbol with dashed lines to the initiating instrument and the final element. Keep them visually distinct from regulatory control.

### 6. Equipment symbols

| Equipment | Symbol |
|---|---|
| Vertical vessel / tank | Rounded rectangle, corner radius ~10% of width |
| Horizontal drum | Rounded rectangle, landscape |
| Column | Tall rectangle with internal tray lines |
| Shell and tube exchanger | Rectangle with tube-side U-path through it |
| Submerged coil | Serpentine inside the vessel, in the heating-medium color |
| Agitator | Motor box on top, shaft down the centerline, blades as two angled parallelograms |
| Centrifugal pump | Circle with a tangential discharge |
| Steam trap | Small square with a diagonal |

Show normal liquid level as a dashed line in the process-liquid color, with liquid fill below it. It gives the reader an instant check that every nozzle is on the right side of the surface.

Equipment tag goes in dead space near the equipment: tag, service description, and key dimensions. Below the vessel is usually the clearest place. Center it on the equipment centerline, and check it against any line dropping from the bottom head.

### 7. Line and stream identification

Terminate every line at a sheet boundary with an arrowhead and a destination label: `TO DOWNSTREAM RECOVERY`, `FROM UPSTREAM STORAGE`, `TO CONDENSATE RETURN`. An unlabeled line stub is a defect.

Add stream conditions under the origin label where known: `15.0 m³/h nominal | 25 °C`. On a conceptual sheet this is more useful than a full line number.

Off-page connectors (a pentagon with the destination sheet number) are optional conceptually; a labeled arrow is sufficient.

### 8. Common errors reviewers catch

- Measurement arrow pointing at the transmitter instead of the controller
- Controller drawn as a plain circle, implying a local gauge controls the plant
- Cascade leg with no arrowhead, so master and slave are ambiguous
- Valve tagged with a different loop number from its controller
- Coil, sparger, or dip pipe drawn above the liquid level
- Nozzle drawn on a corner radius
- Level transmitter tapped in the vapor space
- Redundant instrument drawn but wired to nothing
- Legend listing a line type that does not appear on the sheet
- No failure position on control valves
- Conceptual drawing with no `NOT FOR CONSTRUCTION` stamp
