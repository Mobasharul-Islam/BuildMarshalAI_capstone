"""Generate the poster's HTML.

Written rather than hand-authored because one number governs the whole sheet:
the lit page's four corners. They place the artwork, and they clip the third
line of the headline so the word PAGE is printed as ink ON the page while the
rest of the line burns as light against the dark. Hand-keeping two copies of
that polygon in sync would be a bug waiting to happen.

    python poster/build_poster.py     # writes poster/poster.html
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import artwork as art  # noqa: E402

OUT = HERE / "poster.html"

# ── The sheet ────────────────────────────────────────────────────────────
W_IN, H_IN = 18.0, 24.0
MARGIN = 1.15
UNITS = 100                      # hundredths of an inch; the SVG grid
HERO_IN = 9.2

# The lit page, in hero units. Everything downstream derives from this.
# Landscape, because a drawing sheet is, and because a portrait page large
# enough to hold the word PAGE would reach up and chop the two lines above it.
# Its top edge is set to pass BELOW line 2's descenders and to slice
# diagonally through PAGE — so P burns as light and AGE prints as ink.
PAGE_CX, PAGE_CY = 1160.0, 702.0
PAGE_W, PAGE_H = 500.0, 380.0
PAGE_ANGLE = -6.5

HERO_W, HERO_H = int(W_IN * UNITS), int(HERO_IN * UNITS)
CORNERS = art.page_corners(PAGE_CX, PAGE_CY, PAGE_W, PAGE_H, PAGE_ANGLE)
CLIP = ", ".join(f"{x / HERO_W * 100:.3f}% {y / HERO_H * 100:.3f}%" for x, y in CORNERS)

# ── Copy ─────────────────────────────────────────────────────────────────
# Managerial throughout: what the person running the job gets, never how it is
# built. No product, tool, model or version names anywhere on the sheet.
HEADLINE = ("EVERY ANSWER", "ARRIVES WITH", 'ITS <span class="w">PAGE</span>.')
HEAD_INDENT = 4.30               # inches; tuned so PAGE lands on the page

EYEBROW_L = "FOR THE PERSON WHO SIGNS IT OFF"
EYEBROW_R = "LEVEL-4 CAPSTONE 2026"

PROBLEM_LEAD = "Construction documents are contractual."
PROBLEM_REST = ("Slabs specified at one concrete strength, piles at another, both buried "
                "in a ninety-page specification. An assistant that confuses the two does "
                "not look wrong — it looks certain. Then the floor comes out and the "
                "claim comes in.")

LEGEND = (
    ("LIT", "the evidence exists, and you are shown it"),
    ("DIMMED", "less certain — and told to you as less certain"),
    ("DARK", "nothing in the record, so nothing is claimed"),
)

DECK_1 = "Every answer shows its page."
BODY_1 = ("Ask about the response period, the concrete schedule, the latest stamped "
          "revision. Back comes the answer with the document, the page, and how sure "
          "it is — one click from seeing it yourself. Tables, drawings and stamps are "
          "found, not just typed paragraphs.")
PROOF_1 = "When the documents do not settle it, it says so — then names what it does hold."

DECK_2 = "Blanks get a question, not a guess."
BODY_2 = ("Say what you want made — a project, a task, a person, a cost, an order. It "
          "works out what is mandatory, asks for each missing piece one question at a "
          "time, and keeps what you have already told it. The form opens once, complete.")
PROOF_2 = ("A person, trade or category that does not exist is never accepted, "
           "and never quietly corrected.")

DECK_3 = "Nothing moves without your say-so."
BODY_3 = ("A programme or cost plan becomes a reviewable draft of projects, tasks and "
          "costs — nothing is committed until you confirm it. Schedule and cost health "
          "read off the live programme, flagging the slip early. Mail, diary and files "
          "act only on your word.")
PROOF_3 = ("Every company's records sit apart by structure, "
           "not by a setting someone can switch off.")

NUMBERS = (
    ("0", "answers given without a page you can open and check"),
    ("0", "blanks filled with a guess — it asks you instead"),
    ("1", "click from any answer to the page, table or stamp behind it"),
    ("11", "kinds of record raised from one plain sentence"),
    ("591", "automated checks it must pass before anyone on site relies on it"),
)

CLOSING_LEAD = "Fluency is cheap."
CLOSING_REST = "On a contract, only the page counts."

FOOTER_NAMES = ("Md. Mobasharul Islam", "[Team member 2]", "[Team member 3]")
FOOTER_SUP = "[Supervisor name]"


def css() -> str:
    return f"""
@page {{ size: {W_IN}in {H_IN}in; margin: 0; }}
:root{{
  --ground:{art.INK}; --near:{art.NEAR}; --ember:{art.EMBER};
  --struct:{art.CRIMSON}; --signal:{art.VERMIL}; --mid:{art.ORANGE};
  --orange:{art.SAFFRON}; --amber:{art.AMBER}; --paper:{art.GOLD};
  --core:{art.CREAM}; --pageink:{art.PAGE_INK}; --dim:{art.DIM};
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{W_IN}in;height:{H_IN}in;overflow:hidden}}
body{{
  background:var(--ground); color:var(--paper);
  font-family:'Inter',Arial,sans-serif; line-height:1.34;
  -webkit-print-color-adjust:exact; print-color-adjust:exact;
}}
.display{{font-family:'Bodoni Moda',Didot,'Times New Roman',serif}}
.mono{{font-family:'IBM Plex Mono',monospace}}

/* ── Hero ─────────────────────────────────────────────────────────── */
.hero{{position:relative; width:{W_IN}in; height:{HERO_IN}in; overflow:hidden}}
.hero .layer{{position:absolute; inset:0}}
.hero .layer svg{{width:100%; height:100%; display:block}}

.eyebrow{{
  position:absolute; top:0.62in; left:{MARGIN}in; right:{MARGIN}in; z-index:6;
  display:flex; justify-content:space-between; font-size:13pt; font-weight:500;
  letter-spacing:.24em; text-transform:uppercase;
}}
.eyebrow .l{{color:var(--orange)}} .eyebrow .r{{color:#9A5330}}

.headline{{
  position:absolute; inset:0; z-index:5;
  padding:1.62in 0 0 {MARGIN}in;
  font-size:104pt; line-height:1.17; letter-spacing:-0.02em;
  font-weight:800; white-space:nowrap; pointer-events:none;
}}
.headline .l3{{padding-left:{HEAD_INDENT}in}}
/* The same three lines twice: light against the dark, then ink where the
   page covers them. The sheet between the two layers does the masking. */
.headline.light{{color:var(--paper)}}
.headline.ink{{color:var(--pageink); z-index:7; clip-path:polygon({CLIP})}}

/* ── Stakes + legend ──────────────────────────────────────────────── */
.stakes{{
  display:grid; grid-template-columns:1fr 6.1in; gap:0.75in; align-items:start;
  padding:0.28in {MARGIN}in 0.26in; background:#1B0604;
  border-top:1px solid var(--ember); border-bottom:1px solid var(--ember);
}}
.stakes .p{{font-size:18pt; line-height:1.34; color:#F0C79B}}
.stakes .p b{{color:var(--signal); font-weight:700}}
.legend{{display:grid; gap:0.095in}}
.legend .row{{display:flex; align-items:center; gap:0.2in}}
.legend .swatch{{width:0.72in; height:0.17in; border-radius:0.09in; flex:0 0 auto}}
.legend .k{{font-size:11.5pt; font-weight:600; letter-spacing:.2em; color:var(--amber);
           width:1.1in; flex:0 0 auto}}
.legend .v{{font-size:12pt; color:var(--dim)}}

/* ── Guarantees ───────────────────────────────────────────────────── */
.guarantee{{display:grid; align-items:center; padding:0.20in {MARGIN}in 0.18in}}
.g-one{{grid-template-columns:1fr 3.08in; gap:0.58in}}
.g-two{{grid-template-columns:3.08in 1fr; gap:0.58in}}
.g-num{{font-size:13.5pt; font-weight:600; letter-spacing:.2em; color:var(--signal)}}
.deck{{
  font-size:38pt; line-height:1.08; font-weight:700; color:var(--core);
  margin:0.09in 0 0.14in; letter-spacing:-0.014em;
}}
.body{{font-size:16pt; line-height:1.44; color:#F0C79B}}
.proof{{
  font-size:13.5pt; line-height:1.36; color:var(--amber); margin-top:0.15in;
  padding-left:0.24in; border-left:3px solid var(--signal);
}}
.ring svg{{width:100%; height:auto; display:block}}
.hairline{{height:1px; background:var(--ember); margin:0 {MARGIN}in}}

/* ── Third promise + the figures ──────────────────────────────────── */
.tail{{
  padding:0.22in {MARGIN}in 0.18in;
  border-top:1px solid var(--ember);
}}
.tail-cols{{display:grid; grid-template-columns:1fr 6.6in; gap:0.7in;
            margin-top:0.10in; align-items:start}}
.figures{{display:grid; gap:0.065in}}
.figures .row{{display:flex; align-items:baseline; gap:0.24in}}
.figures .n{{
  font-family:'Bodoni Moda',serif; font-size:27pt; font-weight:700; line-height:1;
  color:var(--amber); width:1.35in; text-align:right; flex:0 0 auto;
}}
.figures .t{{font-size:13pt; line-height:1.3; color:var(--dim)}}

/* ── Closing ──────────────────────────────────────────────────────── */
.closing{{
  padding:0.30in {MARGIN}in 0.28in; text-align:center;
  /* Starts at signal red, not oxblood: the ink-dark text has to hold its
     contrast at the cool end of the band as well as the hot one. */
  background:linear-gradient(94deg,{art.VERMIL} 0%,{art.ORANGE} 26%,
              {art.SAFFRON} 54%,{art.AMBER} 80%,#FFE07A 100%);
}}
.closing p{{font-size:38pt; line-height:1.14; font-weight:700;
           color:{art.PAGE_INK}; letter-spacing:-0.016em}}
.closing b{{color:#4A0F04; font-weight:700}}

/* ── Footer ───────────────────────────────────────────────────────── */
footer{{
  padding:0.20in {MARGIN}in; display:flex; align-items:center; gap:0.34in;
  border-top:1px solid var(--ember); font-size:11.5pt; color:#8E4A2A;
}}
footer .qr{{width:0.74in;height:0.74in;background:var(--paper);padding:0.04in;
           border-radius:0.04in;flex:0 0 auto}}
footer .qr img{{width:100%;height:100%;display:block}}
footer .grow{{flex:1; line-height:1.5}}
footer b{{color:var(--paper); font-weight:600}}
"""


def hero() -> str:
    field = art.page_field(HERO_W, HERO_H, columns=22, rows=13, uid="hf")
    corona = art.lit_page(HERO_W, HERO_H, PAGE_CX, PAGE_CY, PAGE_W, PAGE_H,
                          PAGE_ANGLE, uid="hc", part="corona")
    sheet = art.lit_page(HERO_W, HERO_H, PAGE_CX, PAGE_CY, PAGE_W, PAGE_H,
                         PAGE_ANGLE, uid="hs", part="sheet")
    lines = "".join(
        f'<div class="l{i + 1}">{line}</div>' for i, line in enumerate(HEADLINE))
    return f"""<section class="hero">
  <div class="layer">{field}</div>
  <div class="layer">{corona}</div>
  <div class="eyebrow mono">
    <span class="l">{EYEBROW_L}</span><span class="r">{EYEBROW_R}</span>
  </div>
  <div class="headline display light">{lines}</div>
  <div class="layer" style="z-index:6">{sheet}</div>
  <div class="headline display ink" aria-hidden="true">{lines}</div>
</section>"""


def build() -> str:
    swatches = (f"linear-gradient(90deg,{art.AMBER},{art.CREAM})",
                f"linear-gradient(90deg,{art.NEAR},{art.SAFFRON})",
                art.NEAR)
    legend = "".join(
        f'<div class="row"><span class="swatch" style="background:{bg}"></span>'
        f'<span class="k">{key}</span><span class="v">{value}</span></div>'
        for (key, value), bg in zip(LEGEND, swatches))
    figures = "".join(
        f'<div class="row"><div class="n">{value}</div><div class="t">{label}</div></div>'
        for value, label in NUMBERS)
    names = " &nbsp;·&nbsp; ".join(f"<b>{n}</b>" for n in FOOTER_NAMES)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BuildMarshalAI — Capstone Poster</title>
<link rel="stylesheet" href="fonts.css">
<style>{css()}</style>
</head>
<body>

{hero()}

<section class="stakes">
  <p class="p"><b>{PROBLEM_LEAD}</b> {PROBLEM_REST}</p>
  <div class="legend">{legend}</div>
</section>

<section class="guarantee g-one">
  <div>
    <p class="g-num mono">01 — WHAT YOU ASK</p>
    <h2 class="deck display">{DECK_1}</h2>
    <p class="body">{BODY_1}</p>
    <p class="proof">{PROOF_1}</p>
  </div>
  <div class="ring">{art.cited_page(620, 560, columns=8, rows=6,
                                    lit_col=5, lit_row=3, uid="g1")}</div>
</section>

<div class="hairline"></div>

<section class="guarantee g-two">
  <div class="ring">{art.honest_gap(620, 560, teeth=24,
                                    missing=(3, 4, 11, 18), uid="g2")}</div>
  <div>
    <p class="g-num mono">02 — WHAT YOU TELL IT</p>
    <h2 class="deck display">{DECK_2}</h2>
    <p class="body">{BODY_2}</p>
    <p class="proof">{PROOF_2}</p>
  </div>
</section>

<section class="tail">
  <p class="g-num mono">03 — WHO IS IN CHARGE</p>
  <h2 class="deck display">{DECK_3}</h2>
  <div class="tail-cols">
    <div>
      <p class="body">{BODY_3}</p>
      <p class="proof">{PROOF_3}</p>
    </div>
    <div class="figures">{figures}</div>
  </div>
</section>

<section class="closing">
  <p class="display">{CLOSING_LEAD} <b>{CLOSING_REST}</b></p>
</section>

<footer>
  <div class="qr"><img src="assets/qr.png" alt="Project repository"></div>
  <div class="grow">
    <p>{names}</p>
    <p>Supervised by <b>{FOOTER_SUP}</b> &nbsp;·&nbsp; Department of Computer Science
       &amp; Engineering, Bangladesh University of Engineering &amp; Technology</p>
  </div>
  <div class="mono" style="text-align:right;line-height:1.55">
    Level-4 Capstone Project<br>Dhaka &nbsp;·&nbsp; 2026
  </div>
</footer>

</body>
</html>
"""


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"  {OUT.name}  {OUT.stat().st_size / 1024:.0f} KB")
    print(f"  page corners: " + "  ".join(f"({x/100:.2f},{y/100:.2f})" for x, y in CORNERS))
