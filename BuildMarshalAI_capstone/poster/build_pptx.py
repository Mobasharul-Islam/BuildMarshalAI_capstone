"""Build an editable 18x24in PowerPoint of the poster.

The PDF is what gets printed; this is what gets nudged. Every word is a real
text box, so names, figures and wording can be changed without coming back
here. Only the three artworks are images, because PowerPoint cannot be handed
the vector originals through this file format — `rasterise.py` renders them at
print resolution first.

One effect is an approximation rather than a reproduction: in the PDF the lit
page CLIPS the headline, so the slice through the word PAGE falls wherever the
page's edge happens to cross the letterforms. PowerPoint has no such clip, so
the line is split into two boxes — "ITS P" in light, "AGE." in ink — which
lands in the same place but cannot follow the diagonal. Check that join after
any change of font or size.

    python poster/build_pptx.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_poster as bp  # noqa: E402

ASSETS = HERE / "assets"
OUT = HERE / "BuildMarshalAI-poster-18x24.pptx"

W, H, M = 18.0, 24.0, bp.MARGIN


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value.lstrip("#").upper())


GROUND = rgb(bp.art.INK)
EMBER = rgb(bp.art.EMBER)
SIGNAL = rgb(bp.art.VERMIL)
ORANGE = rgb(bp.art.SAFFRON)
AMBER = rgb(bp.art.AMBER)
PAPER = rgb(bp.art.GOLD)
CORE = rgb(bp.art.CREAM)
PAGEINK = rgb(bp.art.PAGE_INK)
DIM = rgb(bp.art.DIM)
BODYTEXT = rgb("#F0C79B")
STAKESBG = rgb("#1B0604")

SANS, DISPLAY, MONO = "Inter", "Bodoni Moda", "IBM Plex Mono"

# Band tops, following the measured HTML layout.
Y_HERO, Y_STAKES, Y_G1, Y_G2, Y_TAIL, Y_CLOSE, Y_FOOT = (
    0.0, 9.20, 11.10, 14.28, 17.45, 21.30, 22.55)

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)
slide = prs.slides.add_slide(prs.slide_layouts[6])


def rect(x, y, w, h, fill=None, shape=MSO_SHAPE.RECTANGLE):
    box = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        box.fill.background()
    else:
        box.fill.solid()
        box.fill.fore_color.rgb = fill
    box.line.fill.background()
    box.shadow.inherit = False
    return box


def text(x, y, w, h, runs, size=14, color=BODYTEXT, bold=False, font=SANS,
         align=PP_ALIGN.LEFT, spacing=1.2, space=0, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    chunks = runs if isinstance(runs, list) and runs and isinstance(runs[0], list) else [runs]
    for index, chunk in enumerate(chunks):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.alignment = align
        para.line_spacing = spacing
        para.space_after = Pt(space)
        for content, over in (chunk if isinstance(chunk, list) else [(chunk, {})]):
            run = para.add_run()
            run.text = content
            run.font.size = Pt(over.get("size", size))
            run.font.bold = over.get("bold", bold)
            run.font.name = over.get("font", font)
            run.font.color.rgb = over.get("color", color)
    return box


def label(x, y, w, caption):
    return text(x, y, w, 0.24, caption, size=13.5, color=SIGNAL, bold=True, font=MONO)


def proof(x, y, w, line):
    rect(x, y + 0.03, 0.035, 0.30, SIGNAL)
    return text(x + 0.22, y, w - 0.22, 0.4, line, size=13.5, color=AMBER, spacing=1.36)


# ══ Ground ═══════════════════════════════════════════════════════════════
rect(0, 0, W, H, GROUND)

# ══ Hero ═════════════════════════════════════════════════════════════════
slide.shapes.add_picture(str(ASSETS / "hero.png"), Inches(0), Inches(0),
                         width=Inches(W), height=Inches(bp.HERO_IN))
text(M, 0.50, 9.0, 0.3, bp.EYEBROW_L, size=13, color=ORANGE, bold=True, font=MONO)
text(W - M - 6.0, 0.50, 6.0, 0.3, bp.EYEBROW_R, size=13, color=rgb("#9A5330"),
     bold=True, font=MONO, align=PP_ALIGN.RIGHT)

HEAD = dict(size=104, bold=True, font=DISPLAY, spacing=1.17)
text(M, 1.50, 15.0, 1.7, "EVERY ANSWER", color=PAPER, **HEAD)
text(M, 2.86, 15.0, 1.7, "ARRIVES WITH", color=PAPER, **HEAD)
# The clipped line, approximated as two boxes butted together.
text(M + 4.30, 4.22, 6.0, 1.7, "ITS P", color=PAPER, **HEAD)
text(9.28, 4.22, 6.0, 1.7, "AGE.", color=PAGEINK, **HEAD)

# ══ Stakes + legend ══════════════════════════════════════════════════════
rect(0, Y_STAKES, W, 1.90, STAKESBG)
text(M, Y_STAKES + 0.28, 9.4, 1.3,
     [[(bp.PROBLEM_LEAD + " ", {"bold": True, "color": SIGNAL}),
       (bp.PROBLEM_REST, {})]], size=18, spacing=1.34)
for index, (key, value) in enumerate(bp.LEGEND):
    y = Y_STAKES + 0.30 + index * 0.40
    swatch = (AMBER, ORANGE, rgb(bp.art.NEAR))[index]
    rect(11.0, y + 0.03, 0.72, 0.17, swatch, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(11.92, y, 1.2, 0.26, key, size=11.5, color=AMBER, bold=True, font=MONO)
    text(13.1, y, 3.9, 0.3, value, size=12, color=DIM)

# ══ Guarantee 01 ═════════════════════════════════════════════════════════
TXT = W - 2 * M - 3.08 - 0.58
label(M, Y_G1 + 0.28, TXT, "01 — WHAT YOU ASK")
text(M, Y_G1 + 0.54, TXT, 0.7, bp.DECK_1, size=38, bold=True, color=CORE,
     font=DISPLAY, spacing=1.08)
text(M, Y_G1 + 1.22, TXT, 1.2, bp.BODY_1, size=16, spacing=1.44)
proof(M, Y_G1 + 2.36, TXT, bp.PROOF_1)
slide.shapes.add_picture(str(ASSETS / "art-01.png"), Inches(W - M - 3.08),
                         Inches(Y_G1 + 0.22), width=Inches(3.08))
rect(M, Y_G1 + 3.16, W - 2 * M, 0.012, EMBER)

# ══ Guarantee 02 ═════════════════════════════════════════════════════════
slide.shapes.add_picture(str(ASSETS / "art-02.png"), Inches(M),
                         Inches(Y_G2 + 0.22), width=Inches(3.08))
GX = M + 3.08 + 0.58
label(GX, Y_G2 + 0.28, TXT, "02 — WHAT YOU TELL IT")
text(GX, Y_G2 + 0.54, TXT, 0.7, bp.DECK_2, size=38, bold=True, color=CORE,
     font=DISPLAY, spacing=1.08)
text(GX, Y_G2 + 1.22, TXT, 1.2, bp.BODY_2, size=16, spacing=1.44)
proof(GX, Y_G2 + 2.36, TXT, bp.PROOF_2)

# ══ 03 + the figures ═════════════════════════════════════════════════════
rect(0, Y_TAIL, W, 0.012, EMBER)
label(M, Y_TAIL + 0.26, 15.0, "03 — WHO IS IN CHARGE")
text(M, Y_TAIL + 0.52, 15.0, 0.7, bp.DECK_3, size=38, bold=True, color=CORE,
     font=DISPLAY, spacing=1.08)
text(M, Y_TAIL + 1.26, 8.4, 1.5, bp.BODY_3, size=16, spacing=1.44)
proof(M, Y_TAIL + 2.62, 8.4, bp.PROOF_3)
for index, (value, caption) in enumerate(bp.NUMBERS):
    y = Y_TAIL + 1.26 + index * 0.47
    text(9.3, y, 1.35, 0.5, value, size=27, bold=True, color=AMBER,
         font=DISPLAY, align=PP_ALIGN.RIGHT)
    text(10.9, y + 0.08, W - M - 10.9, 0.44, caption, size=13, color=DIM, spacing=1.3)

# ══ Closing ══════════════════════════════════════════════════════════════
band = rect(0, Y_CLOSE, W, 1.25)
band.fill.gradient()
band.fill.gradient_angle = 0
stops = band.fill.gradient_stops
stops[0].color.rgb = SIGNAL
stops[0].position = 0.0
stops[1].color.rgb = rgb("#FFE07A")
stops[1].position = 1.0
text(M, Y_CLOSE + 0.34, W - 2 * M, 0.7,
     [[(bp.CLOSING_LEAD + " ", {"color": PAGEINK}),
       (bp.CLOSING_REST, {"color": rgb("#4A0F04")})]],
     size=38, bold=True, font=DISPLAY, align=PP_ALIGN.CENTER)

# ══ Footer ═══════════════════════════════════════════════════════════════
rect(0, Y_FOOT, W, H - Y_FOOT, GROUND)
rect(0, Y_FOOT, W, 0.012, EMBER)
rect(M, Y_FOOT + 0.30, 0.74, 0.74, PAPER)
slide.shapes.add_picture(str(ASSETS / "qr.png"), Inches(M + 0.04),
                         Inches(Y_FOOT + 0.34), width=Inches(0.66))
names = [(bp.FOOTER_NAMES[0], {"bold": True, "color": PAPER})]
for person in bp.FOOTER_NAMES[1:]:
    names += [("  ·  ", {}), (person, {"bold": True, "color": PAPER})]
text(M + 1.02, Y_FOOT + 0.34, 11.0, 0.3, [names], size=11.5, color=rgb("#8E4A2A"))
text(M + 1.02, Y_FOOT + 0.62, 12.4, 0.4,
     [[("Supervised by ", {}), (bp.FOOTER_SUP, {"bold": True, "color": PAPER}),
       ("  ·  Department of Computer Science & Engineering, Bangladesh University "
        "of Engineering & Technology", {})]],
     size=11.5, color=rgb("#8E4A2A"))
text(W - M - 4.2, Y_FOOT + 0.38, 4.2, 0.6,
     "Level-4 Capstone Project\nDhaka  ·  2026",
     size=11.5, color=rgb("#8E4A2A"), font=MONO, align=PP_ALIGN.RIGHT, spacing=1.55)

prs.save(OUT)
print(f"  {OUT.name}  {OUT.stat().st_size / 1024:.0f} KB  "
      f"({W:.0f}x{H:.0f} in, {len(slide.shapes)} shapes)")
