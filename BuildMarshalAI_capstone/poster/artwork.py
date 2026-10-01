"""The poster's conceptual artwork, generated as vector geometry.

Each piece is abstract but not arbitrary: the poster argues that answers arrive
with their proof and that blanks are asked about rather than filled, so the
artwork has to carry those two ideas without a single screenshot.

Radial and fanned forms need hundreds of computed coordinates, which is why
these are generated rather than hand-written. Everything returns an SVG
fragment string, sized in its own viewBox, so the layout can scale it freely.

    python poster/artwork.py      # writes a contact sheet to preview them
"""
from __future__ import annotations

import math
from pathlib import Path

# ── Palette ──────────────────────────────────────────────────────────────
# Hot, but held together by a common warmth: every hue sits between roughly
# 5° and 45° on the wheel, so the sheet reads as one temperature rather than
# as three unrelated brights.
# The governing law of the sheet: light means the evidence exists, falloff
# means less of it, and dark means none. Every value below is a step on that
# one curve, which is what keeps a loud palette from becoming a loud mess.
INK      = "#0F0403"   # ground — the honest dark
NEAR     = "#24080A"   # anything sitting above the ground without lighting up
EMBER    = "#7A1208"   # deep ember; hairlines, outer corona
CRIMSON  = "#B8300F"   # structural red; the edge of anything carrying evidence
VERMIL   = "#D92B0C"   # signal red; hottest gradient base
ORANGE   = "#F2620A"   # mid heat
SAFFRON  = "#FF8A18"
AMBER    = "#FFC93C"   # near-core
GOLD     = "#FFF1C2"   # incandescent paper — display type on the dark ground
CREAM    = "#FFF9EA"   # the core; under 2% of the sheet, only where proof is
PAGE_INK = "#1A0703"   # type printed onto the lit page
DIM      = "#E7A25C"   # captions and far falloff


def _pt(cx: float, cy: float, radius: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees - 90)
    return cx + radius * math.cos(angle), cy + radius * math.sin(angle)


def _f(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


# ── 1 · The cited page ───────────────────────────────────────────────────

def cited_page(width: int = 620, height: int = 620, columns: int = 13,
               rows: int = 10, lit_col: int = 8, lit_row: int = 4,
               uid: str = "a1") -> str:
    """A field of pages, all searched, with the one that answers struck by light.

    The first attempt fanned the pages from a pivot and read as a spray of
    sticks. A field reads immediately as *a lot of paper*, which is the honest
    scale of the problem, and makes the single lit sheet unmistakable. The
    crosshair runs to the frame edge so the eye is led to it from anywhere.
    """
    pad = width * 0.075
    field_w, field_h = width - pad * 2, height - pad * 2
    cell_w, cell_h = field_w / columns, field_h / rows
    page_w, page_h = cell_w * 0.62, cell_h * 0.80
    lx = pad + cell_w * (lit_col + 0.5)
    ly = pad + cell_h * (lit_row + 0.5)

    parts: list[str] = [f'''<defs>
    <radialGradient id="halo{uid}" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{GOLD}" stop-opacity=".85"/>
      <stop offset="35%" stop-color="{AMBER}" stop-opacity=".34"/>
      <stop offset="70%" stop-color="{VERMIL}" stop-opacity=".12"/>
      <stop offset="100%" stop-color="{VERMIL}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="sheet{uid}" x1="0" y1="1" x2="0.4" y2="0">
      <stop offset="0%" stop-color="{ORANGE}"/>
      <stop offset="50%" stop-color="{AMBER}"/>
      <stop offset="100%" stop-color="{CREAM}"/>
    </linearGradient>
  </defs>''']

    parts.append(f'<circle cx="{_f(lx)}" cy="{_f(ly)}" r="{_f(width * 0.46)}" '
                 f'fill="url(#halo{uid})"/>')

    # Every other page: present, legible as paper, deliberately unlit.
    for row in range(rows):
        for col in range(columns):
            if row == lit_row and col == lit_col:
                continue
            cx = pad + cell_w * (col + 0.5)
            cy = pad + cell_h * (row + 0.5)
            distance = math.hypot(cx - lx, cy - ly) / (width * 0.62)
            near = max(0.0, 1.0 - distance)
            shade = CRIMSON if near > 0.45 else EMBER
            opacity = 0.30 + 0.55 * near
            # A deterministic sway, so the field breathes instead of gridding.
            tilt = ((col * 37 + row * 61) % 9 - 4) * 0.55
            parts.append(
                f'<rect x="{_f(cx - page_w / 2)}" y="{_f(cy - page_h / 2)}" '
                f'width="{_f(page_w)}" height="{_f(page_h)}" rx="{_f(page_w * 0.07)}" '
                f'fill="{shade}" fill-opacity="{opacity:.2f}" '
                f'transform="rotate({_f(tilt)} {_f(cx)} {_f(cy)})"/>')

    # The crosshair, run to the frame so the eye is caught from any distance.
    for x1, y1, x2, y2 in ((0, ly, lx - page_w * 1.5, ly),
                           (lx + page_w * 1.5, ly, width, ly),
                           (lx, 0, lx, ly - page_h * 1.25),
                           (lx, ly + page_h * 1.25, lx, height)):
        parts.append(f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}" '
                     f'stroke="{AMBER}" stroke-opacity=".45" stroke-width="1.8" '
                     f'stroke-dasharray="9 7"/>')

    # The page that answers, larger and lifted clear of the field.
    big_w, big_h = page_w * 1.85, page_h * 1.85
    parts.append(f'<rect x="{_f(lx - big_w / 2 + 5)}" y="{_f(ly - big_h / 2 + 7)}" '
                 f'width="{_f(big_w)}" height="{_f(big_h)}" rx="{_f(big_w * 0.06)}" '
                 f'fill="{INK}" fill-opacity=".55"/>')
    parts.append(f'<rect x="{_f(lx - big_w / 2)}" y="{_f(ly - big_h / 2)}" '
                 f'width="{_f(big_w)}" height="{_f(big_h)}" rx="{_f(big_w * 0.06)}" '
                 f'fill="url(#sheet{uid})"/>')
    # Ruled lines on it, so it is unmistakably a page.
    for index in range(5):
        ry = ly - big_h / 2 + big_h * (0.26 + index * 0.13)
        run = big_w * (0.60 if index != 3 else 0.38)
        parts.append(f'<rect x="{_f(lx - big_w * 0.30)}" y="{_f(ry)}" width="{_f(run)}" '
                     f'height="{_f(big_h * 0.032)}" rx="{_f(big_h * 0.016)}" '
                     f'fill="{EMBER}" fill-opacity=".55"/>')

    # The mark that says: this one, and here is how sure.
    ring = max(big_w, big_h) * 0.78
    parts.append(f'<circle cx="{_f(lx)}" cy="{_f(ly)}" r="{_f(ring)}" fill="none" '
                 f'stroke="{CREAM}" stroke-width="3.2" stroke-opacity=".95"/>')
    parts.append(f'<circle cx="{_f(lx)}" cy="{_f(ly)}" r="{_f(ring * 1.30)}" fill="none" '
                 f'stroke="{AMBER}" stroke-width="2" stroke-opacity=".5" '
                 f'stroke-dasharray="4 10"/>')

    return (f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
            f'role="img" aria-label="A field of many small pages in shadow, with one '
            f'page lit, enlarged and ringed, found by a crosshair">'
            + "".join(parts) + "</svg>")


# ── 2 · The honest gap ───────────────────────────────────────────────────

def honest_gap(width: int = 620, height: int = 620, teeth: int = 40,
               missing: tuple[int, ...] = (6, 7, 19, 31), uid: str = "a2") -> str:
    """A ring of radial teeth with a few deliberately left hollow.

    What is known is solid and hot; what was never supplied stays an outline.
    The composition is only complete when the gaps are filled from outside —
    which is the whole of the second guarantee, without a word of interface.
    """
    cx, cy = width / 2, height / 2
    inner, outer = width * 0.215, width * 0.415
    gap_deg = 360 / teeth * 0.30
    parts: list[str] = [f'''<defs>
    <linearGradient id="tooth{uid}" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%" stop-color="{CRIMSON}"/>
      <stop offset="60%" stop-color="{ORANGE}"/>
      <stop offset="100%" stop-color="{AMBER}"/>
    </linearGradient>
    <radialGradient id="core{uid}" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{VERMIL}" stop-opacity=".30"/>
      <stop offset="100%" stop-color="{VERMIL}" stop-opacity="0"/>
    </radialGradient>
  </defs>''']
    parts.append(f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(outer)}" fill="url(#core{uid})"/>')

    for index in range(teeth):
        start = 360 / teeth * index + gap_deg / 2
        end = 360 / teeth * (index + 1) - gap_deg / 2
        a1 = _pt(cx, cy, inner, start)
        a2 = _pt(cx, cy, outer, start)
        a3 = _pt(cx, cy, outer, end)
        a4 = _pt(cx, cy, inner, end)
        path = (f'M {_f(a1[0])} {_f(a1[1])} L {_f(a2[0])} {_f(a2[1])} '
                f'A {_f(outer)} {_f(outer)} 0 0 1 {_f(a3[0])} {_f(a3[1])} '
                f'L {_f(a4[0])} {_f(a4[1])} '
                f'A {_f(inner)} {_f(inner)} 0 0 0 {_f(a1[0])} {_f(a1[1])} Z')
        if index in missing:
            parts.append(f'<path d="{path}" fill="none" stroke="{SAFFRON}" '
                         f'stroke-width="2.4" stroke-dasharray="7 6" stroke-opacity=".85"/>')
        else:
            parts.append(f'<path d="{path}" fill="url(#tooth{uid})"/>')

    # An arrow entering each gap from outside: the question being asked.
    for index in missing:
        mid = 360 / teeth * (index + 0.5)
        tip = _pt(cx, cy, outer * 1.05, mid)
        tail = _pt(cx, cy, outer * 1.40, mid)
        parts.append(f'<line x1="{_f(tail[0])}" y1="{_f(tail[1])}" '
                     f'x2="{_f(tip[0])}" y2="{_f(tip[1])}" stroke="{GOLD}" '
                     f'stroke-width="3" stroke-linecap="round" stroke-opacity=".9"/>')
        head = 9.0
        left = _pt(cx, cy, outer * 1.05 + head * 1.7, mid - 1.9)
        right = _pt(cx, cy, outer * 1.05 + head * 1.7, mid + 1.9)
        parts.append(f'<polygon points="{_f(tip[0])},{_f(tip[1])} '
                     f'{_f(left[0])},{_f(left[1])} {_f(right[0])},{_f(right[1])}" fill="{GOLD}"/>')

    parts.append(f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(inner * 0.60)}" '
                 f'fill="none" stroke="{CREAM}" stroke-opacity=".30" stroke-width="2"/>')
    return (f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
            f'role="img" aria-label="A ring of radiating teeth, four of them left hollow '
            f'with arrows pointing into the gaps from outside">' + "".join(parts) + "</svg>")


# ── 3 · Header burst ─────────────────────────────────────────────────────

def burst(width: int = 1800, height: int = 420, rays: int = 34, uid: str = "a3") -> str:
    """Rays fanning from the upper corner — heat and arrival, behind the title."""
    cx, cy = width * 0.965, -height * 0.22
    parts: list[str] = []
    for index in range(rays):
        share = index / (rays - 1)
        angle = 188 + 82 * share
        span = 1.05 + 1.25 * ((index * 7919) % 11) / 11.0     # deterministic variety
        far = height * (2.4 + 1.5 * ((index * 5407) % 7) / 7.0)
        a = _pt(cx, cy, far, angle - span / 2)
        b = _pt(cx, cy, far, angle + span / 2)
        colour = (AMBER, ORANGE, VERMIL, SAFFRON)[index % 4]
        opacity = 0.05 + 0.10 * ((index * 3169) % 5) / 5.0
        parts.append(f'<polygon points="{_f(cx)},{_f(cy)} {_f(a[0])},{_f(a[1])} '
                     f'{_f(b[0])},{_f(b[1])}" fill="{colour}" fill-opacity="{opacity:.3f}"/>')
    return (f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
            f'preserveAspectRatio="none" aria-hidden="true">' + "".join(parts) + "</svg>")


# ── Contact sheet ────────────────────────────────────────────────────────

def contact_sheet() -> str:
    pieces = [("The cited page", cited_page()), ("The honest gap", honest_gap())]
    cells = "".join(
        f'<figure><div class="art">{svg}</div><figcaption>{title}</figcaption></figure>'
        for title, svg in pieces)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Artwork</title><style>
 body{{background:{INK};margin:0;padding:30px;display:grid;
      grid-template-columns:1fr 1fr;gap:30px;font:14px system-ui,sans-serif}}
 figure{{margin:0}} .art{{background:{INK};border:1px solid #4a2018;border-radius:12px}}
 svg{{width:100%;height:auto;display:block}}
 figcaption{{color:{AMBER};margin-top:10px;letter-spacing:.08em;text-transform:uppercase}}
 .banner{{grid-column:1/-1;background:{EMBER};border-radius:12px;overflow:hidden}}
</style></head><body>
<div class="banner">{burst()}</div>{cells}</body></html>"""


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "artwork-sheet.html"
    out.write_text(contact_sheet(), encoding="utf-8")
    print(f"  {out}")


# ── 4 · The hero: a field in shadow, and the one page that is lit ────────
#
# Units here are hundredths of an inch, so the hero's SVG maps 1:1 onto the
# sheet and the page's corners can be handed straight to a CSS clip-path. That
# shared geometry is the point: the headline's last line is printed as ink
# where it crosses the page and as light where it does not, and the two must
# agree to within a hair or the effect collapses.

def page_corners(cx: float, cy: float, width: float, height: float,
                 angle: float) -> list[tuple[float, float]]:
    """The four corners of the lit page, already rotated."""
    radians = math.radians(angle)
    cos, sin = math.cos(radians), math.sin(radians)
    corners = []
    for dx, dy in ((-width / 2, -height / 2), (width / 2, -height / 2),
                   (width / 2, height / 2), (-width / 2, height / 2)):
        corners.append((cx + dx * cos - dy * sin, cy + dx * sin + dy * cos))
    return corners


def page_field(width: int, height: int, columns: int = 22, rows: int = 12,
               uid: str = "f1") -> str:
    """Everything that was searched and is not the answer.

    It has to read as *a lot of paper* at three metres and as individual sheets
    at thirty centimetres, while never competing with the lit page. So: low
    contrast, a deterministic sway, and a falloff toward the light source.
    """
    cell_w, cell_h = width / columns, height / rows
    page_w, page_h = cell_w * 0.46, cell_h * 0.62
    lx, ly = width * 0.64, height * 0.72
    parts: list[str] = []
    for row in range(rows):
        for col in range(columns):
            cx = cell_w * (col + 0.5)
            cy = cell_h * (row + 0.5)
            near = max(0.0, 1.0 - math.hypot(cx - lx, cy - ly) / (width * 0.52))
            shade = CRIMSON if near > 0.70 else (EMBER if near > 0.34 else NEAR)
            opacity = 0.06 + 0.17 * near
            tilt = ((col * 37 + row * 61) % 13 - 6) * 0.9
            # A little jitter off the grid, or the field reads as a chequerboard.
            cx += ((col * 53 + row * 29) % 7 - 3) * cell_w * 0.055
            cy += ((col * 71 + row * 43) % 7 - 3) * cell_h * 0.07
            parts.append(
                f'<rect x="{_f(cx - page_w / 2)}" y="{_f(cy - page_h / 2)}" '
                f'width="{_f(page_w)}" height="{_f(page_h)}" rx="{_f(page_w * 0.06)}" '
                f'fill="{shade}" fill-opacity="{opacity:.2f}" '
                f'transform="rotate({_f(tilt)} {_f(cx)} {_f(cy)})"/>')
    return (f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
            f'preserveAspectRatio="none" aria-hidden="true">' + "".join(parts) + "</svg>")


def lit_page(width: int, height: int, cx: float, cy: float, page_w: float,
             page_h: float, angle: float = -6.5, uid: str = "s1",
             part: str = "both") -> str:
    """The one page that answers, burning, with its corona.

    It is the poster's only light source, so every other bright thing on the
    sheet is downstream of it. The struck line inside is the thirty-centimetre
    reward: the specific line that settled the question, bracketed.
    """
    corners = page_corners(cx, cy, page_w, page_h, angle)
    points = " ".join(f"{_f(x)},{_f(y)}" for x, y in corners)
    radians = math.radians(angle)
    ux, uy = math.cos(radians), math.sin(radians)          # along the page width
    vx, vy = -math.sin(radians), math.cos(radians)         # down the page height

    def on_page(u: float, v: float) -> tuple[float, float]:
        """A point on the page, in page-relative fractions from its centre."""
        return (cx + u * page_w * ux + v * page_h * vx,
                cy + u * page_w * uy + v * page_h * vy)

    parts: list[str] = [f'''<defs>
    <radialGradient id="corona{uid}" cx="50%" cy="50%" r="50%">
      <stop offset="0%"   stop-color="{CREAM}" stop-opacity=".55"/>
      <stop offset="18%"  stop-color="{AMBER}" stop-opacity=".40"/>
      <stop offset="42%"  stop-color="{SAFFRON}" stop-opacity=".22"/>
      <stop offset="68%"  stop-color="{VERMIL}" stop-opacity=".10"/>
      <stop offset="100%" stop-color="{EMBER}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="paper{uid}" x1="0.1" y1="1" x2="0.65" y2="0">
      <stop offset="0%"   stop-color="{ORANGE}"/>
      <stop offset="34%"  stop-color="{SAFFRON}"/>
      <stop offset="68%"  stop-color="{AMBER}"/>
      <stop offset="100%" stop-color="{CREAM}"/>
    </linearGradient>
  </defs>''']

    # Drawn in two parts so the headline can sit BETWEEN them: lit by the
    # corona, then overprinted by the opaque sheet where the two overlap.
    if part in ("corona", "both"):
        parts.append(f'<ellipse cx="{_f(cx)}" cy="{_f(cy)}" rx="{_f(page_w * 2.35)}" '
                     f'ry="{_f(page_h * 1.75)}" fill="url(#corona{uid})"/>')
    if part == "corona":
        return (f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
                f'preserveAspectRatio="none" aria-hidden="true">' + "".join(parts) + "</svg>")
    parts.append(f'<polygon points="{points}" fill="url(#paper{uid})"/>')

    # Ruled text, and the one struck line that settled the question.
    struck = 3
    for index in range(6):
        v = 0.04 + index * 0.072
        run = (0.62, 0.70, 0.52, 0.68, 0.44, 0.36)[index]
        a = on_page(-0.33, v)
        b = on_page(-0.33 + run, v)
        weight = page_h * 0.020
        colour = PAGE_INK if index != struck else VERMIL
        opacity = ".26" if index != struck else ".88"
        parts.append(f'<line x1="{_f(a[0])}" y1="{_f(a[1])}" x2="{_f(b[0])}" '
                     f'y2="{_f(b[1])}" stroke="{colour}" stroke-opacity="{opacity}" '
                     f'stroke-width="{_f(weight)}" stroke-linecap="round"/>')
    # The bracket that marks it.
    top = on_page(-0.40, 0.04 + struck * 0.072 - 0.034)
    bottom = on_page(-0.40, 0.04 + struck * 0.072 + 0.034)
    tick = on_page(-0.365, 0.04 + struck * 0.072)
    parts.append(f'<path d="M {_f(top[0])} {_f(top[1])} L {_f(tick[0])} {_f(tick[1])} '
                 f'L {_f(bottom[0])} {_f(bottom[1])}" fill="none" stroke="{PAGE_INK}" '
                 f'stroke-width="{_f(page_h * 0.016)}" stroke-opacity=".8"/>')

    # A hairline keyline: the edge of a thing that carries evidence.
    parts.append(f'<polygon points="{points}" fill="none" stroke="{CREAM}" '
                 f'stroke-opacity=".55" stroke-width="{_f(page_w * 0.006)}"/>')
    return (f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
            f'preserveAspectRatio="none" role="img" aria-label="A single document page '
            f'burning with light, one line on it struck and bracketed">'
            + "".join(parts) + "</svg>")
