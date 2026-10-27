---
name: pfd-generator
description: Generate a conceptual PFD (process flow diagram) as an editable SVG, along with the Python script that produced it. Use when the user describes a process and asks to draw, diagram, sketch, or visualize it; when they mention a P&ID, PFD, control loop drawing, or cascade control; or when they ask to edit an existing P&ID SVG. Not a substitute for an issued-for-design P&ID - does not size equipment or relief devices and does not perform hazard analysis.
---

# PFD Generator

Produce a conceptual PFD as a hand-authored SVG that a process engineer would accept: correct process flow, correct ISA instrumentation, closed control loops, and a layout with zero collisions and zero crossed process lines.

The output is judged by an engineer who will spot a backwards arrowhead, a steam coil above the liquid level, or a label sitting under a balloon. Accuracy and legibility rank above speed.

### Non-negotiable output rules

1. **No hidden text.** Every label must be fully readable. Nothing may sit under a line, balloon, valve, vessel, or another label.
2. **No crossing process lines.** Solve crossings by re-planning elevations, not by drawing over. If one is truly unavoidable, draw a proper line jump (semicircular hop).
3. **Control loops must be complete and directional.** Every loop is measurement → controller → final element, with an arrowhead on each leg. A signal line without an arrowhead is a defect.
4. **Text is real `<text>`, never glyph paths or outlines.** The user must be able to edit labels in a text editor. Never emit a matplotlib/Illustrator-style SVG where letters are `<use>` or `<path>` references.
5. **Minimum font size 8.5.** Tag text 10–11.5, line labels 11–13, title 20–22. Nothing smaller than 8.5 survives a slide deck.
6. **Elevations must be physically true.** See Rule of elevation below.

### Workflow

#### 1. Read the description and fill the gaps

A process description almost always underspecifies the drawing. Before drawing, resolve:

- What is the controlled variable, and what is the final control element?
- Are any loops cascaded? Which is master, which is slave?
- Where does each stream enter and leave the vessel (top, bottom, side; above or below liquid level)?
- What is the heating/cooling medium and its return path?
- Any redundant or voting instruments?

Ask at most 2–3 questions, and only for things that change the drawing. For anything minor, make a defensible engineering assumption and state it in the response afterward. Do not stall the drawing over detail that can be noted as an assumption.

#### 2. Plan the layout on paper before writing any SVG

Write out the coordinate plan first. This step is what prevents rework.

- Choose a canvas. Default `1400 × 940`, landscape, with a hairline border inset 20.
- Place the main vessel/equipment roughly centered, e.g. `x 560–800, y 300–640`.
- Assign each horizontal run its own **elevation band** (a y value), and each vertical run its own **corridor** (an x value). Two lines sharing a band or corridor is how crossings happen.
- List every label with its anchor point and estimated width, and check it against the bounding box of every nearby symbol. Estimate text width as `0.55 × font_size × character_count` for regular and `0.6 ×` for bold. This is approximate — the render check in step 4 is the real verification.

**Rule of elevation.** Lay out by physics first, then aesthetics:
- Gravity drains and bottoms products leave the bottom head.
- A submerged coil or sparger enters *below* normal liquid level.
- A free-fall or splash-fill inlet enters *above* level, usually through a top nozzle.
- Vents, relief, and vapor lines leave the top.
- Nozzles land on flat wall sections, never on a corner radius.
- If two supply lines both come from the left, put the one that connects lower on the vessel at a lower elevation the whole way. That alone removes most crossings.

#### 3. Generate the SVG from a parametric script

Write a Python script that emits the SVG. Never hand-type raw SVG for a full drawing.

Every drawing goes through at least three revisions. A script with named coordinates makes "shift the steam header down 40" a one-line change; hand-typed SVG makes it a rewrite.

Emit in this order: vessel bodies and fills, external pipes, vessel internals (coils, dip pipes), equipment details, then balloons and valves last with white fill. Internals drawn before the vessel fill get painted over; balloons drawn before pipes get a line through the tag.

`scripts/pid_lib.py` provides the primitives: `bubble`, `cvalve`, `pipe`, `sig`, `vessel`, `agitator`, `steam_trap`, `line_jump`, `legend`, `txt`. Read that file before writing the script and use it rather than reinventing symbols. Read `references/isa-conventions.md` for symbol and tag rules, and `references/layout-rules.md` for the collision geometry.

#### 4. Render, look at it, and fix — then repeat

**This step is mandatory and is the difference between a passable drawing and a professional one.** Do not deliver a P&ID you have not looked at.

This step needs `cairosvg` and `pillow` (see `scripts/requirements.txt`). Install them once before the first render rather than discovering the gap mid-loop.

```bash
pip install -r scripts/requirements.txt -q   # add --break-system-packages on a managed Python
python3 build_pid.py
python3 -c "import cairosvg; cairosvg.svg2png(url='out.svg', write_to='preview.png', output_width=1680)"
```

**If `cairosvg` will not install, do not skip this step and do not pretend the drawing was checked.** `cairosvg` needs native Cairo/GTK libraries that pip does not supply on Windows, so this fails routinely there. Fall back to a pure-Python renderer, which needs no native libraries:

```bash
pip install -q svglib pymupdf
```

```python
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF
import pymupdf
renderPDF.drawToFile(svg2rlg('out.svg'), '_tmp.pdf')
pymupdf.open('_tmp.pdf')[0].get_pixmap(dpi=120).save('preview.png')
```

**The fallback does not draw arrowheads.** Arrowheads are SVG `<marker>` elements, and neither `svglib` nor `pymupdf` supports markers — they render dashes, fonts, colors, and geometry faithfully, but every arrowhead silently disappears. So when you are on the fallback:

- Use the preview for what it is good at: collisions, overlaps, hidden text, elevations, crossed lines.
- **A missing arrowhead in a fallback preview is a rendering artifact, not a defect.** Do not "fix" it. Chasing it will make you add duplicate arrows to a drawing that was already correct.
- Verify directionality from the SVG source instead, which is more reliable than reading it off an image anyway: every `sig()` call and every `pipe(..., arrow=True)` should emit a `marker-end`. Count them and check each control loop leg has one.
- Say in your final response that the preview was rendered without arrowheads and that directionality was confirmed from the source.

If neither renderer is available, deliver the SVG and state plainly that you could not view it and it has not been visually checked. An unchecked drawing presented as a checked one is the worst outcome this skill can produce.

Then open `preview.png` as an image (the Read tool in Claude Code, the `view` tool on claude.ai) and inspect it as an engineer would. Also crop and zoom the dense areas (control clusters, the vessel interior, instrument stacks) at 3200 px wide — collisions of a few pixels are invisible at full-sheet scale:

```python
from PIL import Image
im = Image.open('z.png'); sx = 3200/1400
im.crop((int(x0*sx), int(y0*sx), int(x1*sx), int(y1*sx))).save('zoom.png')
```

Run the checklist in `references/layout-rules.md` against what you see. Fix and re-render until it passes. Expect 2–4 rounds. Common defects caught only by looking:
- A symbol drawn from bad coordinates (two triangles merging into one blob)
- A label overlapping the first balloon on its line
- An arrowhead landing on the wrong side of a symbol
- Two collinear signal segments reading as one continuous line
- A label that fits at font 11 but collides after the user bumps it to 13

#### 5. Deliver

Save the SVG where the user can reach it and present it: use the path they asked for, otherwise the current working directory — or `/mnt/user-data/outputs/` when that directory exists (claude.ai). Keep the generator script alongside it, and mention it exists — the user will want revisions.

In the response, state briefly:
- Engineering assumptions made
- Anything in the description that could not be drawn and why
- Any design concern noticed while drawing (e.g. free-fall entry will entrain air; a bottom outlet with no isolation valve). Flagging these is a large part of the value.

### Instrumentation, condensed

Full detail in `references/isa-conventions.md`. The rules that matter most:

- **Balloon type encodes location.** Plain circle = field mounted. Circle inside a square = DCS / shared display. Getting this wrong makes controllers look like local gauges.
- **Tag = function letters + loop number.** First letter is the measured variable (F, L, P, T, A), following letters the function (I indicator, C controller, T transmitter, V valve). Every element of one loop shares a loop number: `TIC-101`, `TI-101`, `TV-101`.
- **Signal lines are dashed, process lines are solid and heavier.** Distinguish by weight and dash, and put both in the legend.
- **Arrow direction is semantic.** Into the controller = measurement. Out of the controller = output. A cascade master's output arrows into the slave controller and is labeled as a remote setpoint.
- **Show valve failure position** (FC, FO, FL) next to each control valve tag. It is one of the first things a reviewer looks for.
- Controllers can carry one short tuning or action note (e.g. "direct acting"), placed in dead space, never on a line.

### Sheet furniture

Include unless the user says otherwise:

- Title and one-line subtitle naming the service and the control scheme
- `NOT FOR CONSTRUCTION` stamp in red outline, top right — mandatory on any conceptual drawing
- Legend covering exactly the line types used, and no others
- Design basis note (duty, flows, residence time, valve position at design) — this is what makes the drawing defensible in a review
- Revision identifier

Also state, in the drawing or the response, what a conceptual P&ID deliberately omits: relief devices, isolation and drain valves, vents, line numbers, insulation and tracing, and equipment sizing. Without that note a reader may assume the scope is complete.

### Style

Restrained engineering palette, not a marketing graphic. Working defaults:

| Element | Color | Weight |
|---|---|---|
| Process liquid | `#1d4e89` | 2.4 |
| Steam / condensate | `#a34a28` | 2.4 |
| Instrument signal | `#50565f` | 1.35, dash `7,5.5` |
| Equipment outline | `#343a46` | 1.6–2.2 |
| Body text | `#111418` | — |
| Secondary text | `#5a6472` | — |
| Vessel shell / liquid | `#f7f8fa` / `#dce8f5` | — |
| NOT FOR CONSTRUCTION | `#b02418` | 1.4 |

Add one color per additional service (cooling water, nitrogen, product) and put each in the legend. Balloons and valves get white fill so process lines do not show through them.

### What this skill does not do

It draws conceptual P&IDs. It is not a substitute for an issued-for-design P&ID, does not size equipment or relief devices, and does not perform hazard analysis. Say so if the user's framing suggests they expect otherwise.
