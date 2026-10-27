# Layout Rules

Layout geometry and the QA checklist.

### 1. Canvas and coordinate budget

Default canvas `1400 × 940`, border inset 20.

| Zone | y range | Contents |
|---|---|---|
| Title | 40–95 | Title, subtitle, NOT FOR CONSTRUCTION stamp |
| Upper process | 110–290 | High-elevation lines, top nozzles, upper control clusters |
| Equipment | 300–640 | Main vessel |
| Lower process | 650–780 | Bottom outlets, drains, condensate |
| Notes | 800–860 | Design basis |
| Legend | 875–900 | Legend row, revision identifier |

Scale up proportionally for wider units. Keep at least 40 px of clear space around the sheet border.

### 2. Bands and corridors

Every horizontal run gets its own y (an **elevation band**). Every vertical run gets its own x (a **corridor**). Two lines that share a band or corridor either overlap or force a crossing.

Keep at least 30 px between adjacent bands so labels fit between them, and at least 25 px between adjacent corridors so parallel lines read as two.

**Collinear segments read as one line.** Two signal legs at the same y with a gap between them look like a single continuous run. Offset one by at least 20 px even when they do not touch.

### 3. Eliminating crossings

In priority order:

1. **Re-order elevations.** If line A connects lower on the vessel than line B, put A at a lower elevation for its whole run. Most crossings disappear here.
2. **Move the source.** Route a line in from the top or the opposite side.
3. **Relocate the instrument.** Placing a controller on the same side as its transmitter usually removes two crossings at once.
4. **Line jump.** Only when 1–3 all fail. Draw a semicircular hop on one line:
   ```
   M {x-14},{y} A 14 14 0 0 1 {x+14},{y}
   ```
   Break the underlying path either side of the hop.

Signal lines crossing process lines is acceptable P&ID practice and needs no jump, but avoid it when a small reroute will do. Signal lines crossing *each other* looks careless — reroute.

### 4. Collision geometry

Bounding boxes to check every label against:

| Object | Extent |
|---|---|
| Balloon r=22 | `cx±22, cy±22` |
| Shared-display balloon r=24 | `cx±24, cy±24` (square, not circle) |
| Control valve | `cx±18, cy±12`; actuator adds `cx±14` × 12 on the signal side |
| Pipe | `y±(stroke/2)`, plus ~10 for the arrowhead at the end |
| Text | width ≈ `0.55 × font_size × chars` regular, `0.6 ×` bold; height ≈ font_size; baseline is the *bottom* |

**Label placement rules:**
- A line label sits above its pipe with the baseline at least `bubble_radius + 10` above the pipe centerline. A label at `y_pipe − 22` will collide with the first balloon; `y_pipe − 32` clears it.
- Equipment tags go in dead space, checked against any line dropping from the equipment.
- Destination labels at a sheet edge are right-anchored at the border and must clear the last valve or balloon on that line. This is the single most frequent late-stage collision.
- Annotations next to a controller go on the side with no signal legs.

**Font size changes break layouts.** Text width scales linearly, so bumping a 13-character label from 11 to 13 adds ~15 px. After any font change, re-check every right-anchored and centered label.

### 5. Symbol construction

Draw multi-part symbols as separate closed paths, not one path with shared edges. Two triangles that share an edge merge into one filled blob when rendered. Impeller blades, valve bowties, and arrowheads all fail this way.

**Draw order is load-bearing.** Emit in this sequence:

1. Vessel bodies and liquid fills
2. External process pipes
3. Vessel internals — coils, dip pipes, spargers, baffles
4. Agitators and other equipment details
5. Instrument balloons and valves, all with white fill

Internals must come after the vessel fill or the fill paints over them. Balloons and valves must come last so their white fill hides the pipe behind the tag, which is what lets an inline flow element sit on its line without a stroke running through the text.

Nozzles must land on flat wall sections. For a rounded rectangle with radius `r`, the flat spans are `x: left+r … right−r` and `y: top+r … bottom−r`. A nozzle at `y = bottom − r + 2` will float off the shell.

### 6. QA checklist

Run this against the rendered PNG, not the code. Zoom into every dense cluster at 3200 px.

**Text**
- [ ] Every label fully readable, nothing under a line, balloon, valve, or vessel
- [ ] No label overlaps another label
- [ ] Nothing smaller than 8.5
- [ ] Text inside the vessel does not collide with the agitator shaft, coil, or level line
- [ ] Destination labels clear the last symbol on their line
- [ ] All text is `<text>`, not paths

**Process lines**
- [ ] Zero process-to-process crossings, or a proper jump where unavoidable
- [ ] Every line terminates at a nozzle or a labeled arrow, never in space
- [ ] Arrowheads land at the vessel wall, not inside it
- [ ] No stray arrowheads mid-run
- [ ] Nozzles on flat wall sections
- [ ] Nozzle elevations physically correct against the liquid level

**Instruments and loops**
- [ ] Every loop closed: measurement, controller, final element
- [ ] Every signal leg has exactly one arrowhead, pointing correctly
- [ ] Cascade legs labeled as remote setpoint
- [ ] Controllers drawn as shared-display, field instruments as plain circles
- [ ] Loop numbers consistent across each loop
- [ ] Tag letters match the function drawn: anything with a signal line leaving it is a
      transmitter (FT/LT/PT/TT), not an indicator (FI/LI/PI/TI)
- [ ] No two valve tags share an x corridor across different loops
- [ ] Every instrument drawn is connected to something
- [ ] Multiple legs into one controller land on different ports
- [ ] Failure position shown on control valves
- [ ] No signal-to-signal crossings

**Sheet**
- [ ] Legend matches the line types actually used, and only those
- [ ] NOT FOR CONSTRUCTION present
- [ ] Design basis present
- [ ] Equipment tags centered on their equipment
- [ ] Nothing outside the border

### 7. Revision discipline

Keep the generator script. When the user asks for a change, edit the script and re-render rather than patching the SVG, unless the user has hand-edited the SVG themselves — in that case patch the SVG with exact string replacements and assert each one matched, so a silent no-op cannot slip through.

Bump the revision identifier on each delivered version.

After any change, re-run the full checklist. Moving one element commonly breaks a label two zones away.
