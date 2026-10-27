# -*- coding: utf-8 -*-
"""
pid_lib - primitives for hand-authored P&ID SVGs.

Usage:
    from pid_lib import PID
    d = PID(1400, 940)
    d.title("TK-101 HEATED STIRRED TANK", "Hold stage | Cascade temperature control")
    d.vessel(560, 300, 800, 640, level=385)
    d.pipe("M 60,500 L 560,500", d.RUST)
    d.bubble(140, 500, "PI", "201")
    d.cvalve(300, 500, "TV-101", fail="FC")
    d.sig("M 390,478 L 390,360 L 350,360 L 350,316")
    d.legend([("Process liquid", d.BLUE, False), ("Steam", d.RUST, False),
              ("DCS signal", d.SIG, True)])
    d.save("out.svg")

All coordinates are absolute in viewBox units. Draw order:
vessel bodies+fills -> external pipes -> vessel internals (coils) -> equipment
details -> balloons and valves last (white fill hides pipes behind tags).
Internals drawn before the vessel fill will be painted over.
"""

BLUE = "#1d4e89"   # process liquid
RUST = "#a34a28"   # steam / condensate
CYAN = "#2a7f8f"   # cooling water
GREEN = "#3f7a4d"  # gas / nitrogen
SIG = "#50565f"    # instrument signal
EQ = "#343a46"     # equipment outline
INK = "#111418"
SUB = "#5a6472"
HAIR = "#b8bec7"
LIQ = "#dce8f5"
SHELL = "#f7f8fa"
RED = "#b02418"
FONTS = "'Helvetica Neue', Helvetica, Arial, sans-serif"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def text_width(s, size, bold=False):
    """Rough width estimate. Verify by rendering; this only catches gross errors."""
    return len(s) * size * (0.60 if bold else 0.55)


class PID:
    BLUE, RUST, CYAN, GREEN, SIG, EQ = BLUE, RUST, CYAN, GREEN, SIG, EQ
    INK, SUB, LIQ, SHELL, RED = INK, SUB, LIQ, SHELL, RED

    def __init__(self, w=1400, h=940, border=True):
        self.w, self.h = w, h
        self.o = []
        self.o.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" font-family="{FONTS}">')
        self.o.append('<defs>')
        for name, col in (("aBlue", BLUE), ("aRust", RUST), ("aSig", SIG),
                          ("aCyan", CYAN), ("aGreen", GREEN)):
            self.o.append(
                f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" '
                f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                f'<path d="M 0,0 L 10,5 L 0,10 z" fill="{col}"/></marker>')
        self.o.append('</defs>')
        self.o.append(f'<rect width="{w}" height="{h}" fill="#ffffff"/>')
        if border:
            self.o.append(f'<rect x="20" y="20" width="{w-40}" height="{h-40}" '
                          f'fill="none" stroke="{HAIR}" stroke-width="1"/>')

    def add(self, s):
        self.o.append(s)

    # ---------------------------------------------------------------- text
    def txt(self, x, y, s, size=10, fill=INK, weight="normal",
            anchor="start", ls=0):
        extra = f' letter-spacing="{ls}"' if ls else ""
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
                 f'fill="{fill}" text-anchor="{anchor}"{extra}>{s}</text>')

    def title(self, main, subtitle=None, stamp=True):
        self.txt(45, 60, esc(main), size=21, weight="bold")
        if subtitle:
            self.txt(45, 82, esc(subtitle), size=11.5, fill=SUB)
        if stamp:
            x = self.w - 222
            self.add(f'<rect x="{x}" y="42" width="177" height="24" fill="none" '
                     f'stroke="{RED}" stroke-width="1.4"/>')
            self.txt(x + 88, 59, "NOT FOR CONSTRUCTION", size=11, weight="bold",
                     fill=RED, anchor="middle", ls=0.4)

    # ---------------------------------------------------------------- lines
    def pipe(self, d, color=BLUE, arrow=False, width=2.4):
        key = {BLUE: "aBlue", RUST: "aRust", CYAN: "aCyan", GREEN: "aGreen"}.get(color, "aBlue")
        m = f' marker-end="url(#{key})"' if arrow else ''
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
                 f'stroke-linejoin="round"{m}/>')

    def sig(self, d, arrow=True):
        """Instrument signal. Arrow points INTO the receiving device."""
        m = ' marker-end="url(#aSig)"' if arrow else ''
        self.add(f'<path d="{d}" fill="none" stroke="{SIG}" stroke-width="1.35" '
                 f'stroke-dasharray="7,5.5"{m}/>')

    def lead(self, x1, y1, x2, y2):
        """Thin solid process/impulse connection from a vessel wall to a balloon."""
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                 f'stroke="{EQ}" stroke-width="1.2"/>')

    def line_jump(self, x, y, color=BLUE, r=14):
        """Semicircular hop. Break the underlying pipe path either side of x."""
        self.add(f'<path d="M {x-r},{y} A {r} {r} 0 0 1 {x+r},{y}" fill="none" '
                 f'stroke="{color}" stroke-width="2.4"/>')

    # ---------------------------------------------------------------- instruments
    def bubble(self, cx, cy, top, bot, shared=False, panel=False, r=22):
        """shared=True -> DCS/shared display (circle in square).
           panel=True  -> panel mounted (chord line)."""
        if shared:
            self.add(f'<rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" '
                     f'fill="#ffffff" stroke="{EQ}" stroke-width="1.4"/>')
        self.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#ffffff" '
                 f'stroke="{EQ}" stroke-width="1.4"/>')
        if panel:
            self.add(f'<line x1="{cx-r}" y1="{cy}" x2="{cx+r}" y2="{cy}" '
                     f'stroke="{EQ}" stroke-width="1.1"/>')
        self.txt(cx, cy - 2, top, size=11.5, weight="bold", anchor="middle")
        self.txt(cx, cy + 12, bot, size=10, anchor="middle")

    def cvalve(self, cx, cy, tag, fail=None, actuator="below", tag_dy=45):
        """Control valve. actuator='above' or 'below' - put it on the side the
        signal arrives from, so the signal never crosses the process line."""
        for sx in (-18, 18):
            self.add(f'<path d="M {cx+sx},{cy-12} L {cx+sx},{cy+12} L {cx},{cy} Z" '
                     f'fill="#ffffff" stroke="{EQ}" stroke-width="1.6" '
                     f'stroke-linejoin="miter"/>')
        s = -1 if actuator == "above" else 1
        self.add(f'<line x1="{cx}" y1="{cy}" x2="{cx}" y2="{cy+s*20}" '
                 f'stroke="{EQ}" stroke-width="1.4"/>')
        ry = cy + s * 32 - (6 if s > 0 else 6)
        self.add(f'<rect x="{cx-14}" y="{ry}" width="28" height="12" rx="6" '
                 f'fill="#ffffff" stroke="{EQ}" stroke-width="1.4"/>')
        label = f"{tag}  ({fail})" if fail else tag
        self.txt(cx, cy + tag_dy, label, size=10.5, weight="bold", anchor="middle")

    def manual_valve(self, cx, cy, tag=None):
        for sx in (-14, 14):
            self.add(f'<path d="M {cx+sx},{cy-10} L {cx+sx},{cy+10} L {cx},{cy} Z" '
                     f'fill="#ffffff" stroke="{EQ}" stroke-width="1.5"/>')
        if tag:
            self.txt(cx, cy + 32, tag, size=10, weight="bold", anchor="middle")

    # ---------------------------------------------------------------- equipment
    def vessel(self, x0, y0, x1, y1, r=26, level=None, level_label=None):
        """Rounded-rectangle vessel. Flat wall spans are x0+r..x1-r and y0+r..y1-r;
        put every nozzle inside those ranges."""
        self.add(f'<path d="M {x0+r},{y0} L {x1-r},{y0} Q {x1},{y0} {x1},{y0+r} '
                 f'L {x1},{y1-r} Q {x1},{y1} {x1-r},{y1} L {x0+r},{y1} '
                 f'Q {x0},{y1} {x0},{y1-r} L {x0},{y0+r} Q {x0},{y0} {x0+r},{y0} Z" '
                 f'fill="{SHELL}" stroke="{EQ}" stroke-width="2.2" stroke-linejoin="miter"/>')
        if level is not None:
            self.add(f'<path d="M {x0},{level} L {x1},{level} L {x1},{y1-r} '
                     f'Q {x1},{y1} {x1-r},{y1} L {x0+r},{y1} Q {x0},{y1} {x0},{y1-r} Z" '
                     f'fill="{LIQ}"/>')
            self.add(f'<line x1="{x0+6}" y1="{level}" x2="{x1-6}" y2="{level}" '
                     f'stroke="{BLUE}" stroke-width="1.2" stroke-dasharray="7,5"/>')
            if level_label:
                self.txt(x1 - 10, level - 8, level_label, size=8.5, fill=SUB,
                         anchor="end", ls=0.3)

    def agitator(self, cx, top, shaft_bottom, tag="AG-101"):
        self.add(f'<rect x="{cx-28}" y="{top-44}" width="56" height="44" '
                 f'fill="#ffffff" stroke="{EQ}" stroke-width="1.6"/>')
        self.txt(cx, top - 15, "M", size=15, weight="bold", anchor="middle")
        self.add(f'<line x1="{cx}" y1="{top}" x2="{cx}" y2="{shaft_bottom}" '
                 f'stroke="{EQ}" stroke-width="2"/>')
        b = shaft_bottom
        self.add(f'<path d="M {cx-32},{b+4} L {cx-4},{b-14} L {cx-4},{b-5} '
                 f'L {cx-32},{b+13} Z" fill="{EQ}"/>')
        self.add(f'<path d="M {cx+32},{b+4} L {cx+4},{b-14} L {cx+4},{b-5} '
                 f'L {cx+32},{b+13} Z" fill="{EQ}"/>')
        self.txt(cx + 42, top - 18, tag, size=10.5, weight="bold")

    def steam_trap(self, cx, cy, tag="ST-101", size=28):
        h = size / 2
        self.add(f'<rect x="{cx-h}" y="{cy-h}" width="{size}" height="{size}" '
                 f'fill="#ffffff" stroke="{EQ}" stroke-width="1.5"/>')
        self.add(f'<line x1="{cx-h}" y1="{cy+h}" x2="{cx+h}" y2="{cy-h}" '
                 f'stroke="{EQ}" stroke-width="1.5"/>')
        self.txt(cx, cy + h + 22, tag, size=10, weight="bold", anchor="middle")

    def equip_tag(self, cx, y, tag, service=None, detail=None):
        """Equipment identification. Place in dead space; check against any line
        dropping from the equipment bottom."""
        self.txt(cx, y, tag, size=14, weight="bold", anchor="middle")
        if service:
            self.txt(cx, y + 18, service, size=10, fill=SUB, anchor="middle", ls=0.4)
        if detail:
            self.txt(cx, y + 35, detail, size=9, fill=SUB, anchor="middle")

    # ---------------------------------------------------------------- sheet furniture
    def notes(self, x, y, heading, bullets, size=9.5):
        self.txt(x, y, heading, size=11, weight="bold", ls=0.4)
        for i, b in enumerate(bullets):
            self.txt(x, y + 24 + i * 18, "&#8226;  " + esc(b), size=size, fill=SUB)

    def design_basis(self, cx, y, text, size=9.5):
        self.txt(cx, y, esc(text), size=size, fill=SUB, anchor="middle")

    def legend(self, entries, y=886, x=60, gap=210, size=12):
        """entries: list of (label, color, dashed)."""
        cx = x
        for label, color, dashed in entries:
            dash = ' stroke-dasharray="7,5.5"' if dashed else ''
            wgt = 1.6 if dashed else 2.8
            self.add(f'<line x1="{cx}" y1="{y}" x2="{cx+45}" y2="{y}" '
                     f'stroke="{color}" stroke-width="{wgt}"{dash}/>')
            self.txt(cx + 55, y + 5, esc(label), size=size, fill=SUB)
            cx += max(gap, 55 + text_width(label, size) + 40)

    def revision(self, text, y=890):
        self.txt(self.w - 55, y, esc(text), size=9, fill=SUB, anchor="end")

    # ---------------------------------------------------------------- output
    def save(self, path):
        out = "\n".join(self.o + ["</svg>"])
        with open(path, "w") as f:
            f.write(out)
        return path


def render(svg_path, png_path, width=1680):
    import cairosvg
    cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=width)
    return png_path


def zoom(png_path, out_path, box, src_width=3200, canvas_width=1400):
    """box = (x0, y0, x1, y1) in viewBox units. Render at src_width first."""
    from PIL import Image
    im = Image.open(png_path)
    s = src_width / float(canvas_width)
    im.crop(tuple(int(v * s) for v in box)).save(out_path)
    return out_path
