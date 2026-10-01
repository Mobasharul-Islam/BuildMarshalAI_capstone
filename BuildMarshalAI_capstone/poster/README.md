# Capstone poster — 18 × 24 in

**PAGE AS SUN.** One governing law runs the whole sheet: *light means the evidence
exists, falloff means less of it, dark means none.* The poster's own physics
perform the product's promise before a word is read — and the legend under the
hero states the law, so the abstraction reads as meaning rather than as decoration.

The signature move is in the headline. The lit page **clips** the third line, so
the word **PAGE** is printed as ink *on a page* while the rest of the line burns as
light against the dark. The claim is printed on its own evidence.

| File | What it is |
| --- | --- |
| `BuildMarshalAI-poster-18x24.pdf` | **Print this.** 18 × 24 in trim, vector text, fonts embedded, one page. |
| `BuildMarshalAI-poster-18x24.pptx` | Editable — every word is a text box; only the artwork is an image. |
| `BuildMarshalAI-poster-preview.png` | Screen proof. |
| `poster.html` | Rendered source. Generated — edit `build_poster.py`, not this. |
| `build_poster.py` | Copy, layout and the page geometry that drives the clip. |
| `artwork.py` | The conceptual artwork, as computed vector geometry. |
| `previous-green-version/` | The earlier screenshot-led version, kept for comparison. |

## Before it is printed

Three placeholders need real values — in `build_poster.py` (then rebuild) or
directly in the `.pptx`: `[Team member 2]`, `[Team member 3]`, `[Supervisor name]`.

## Rebuilding

```bash
python poster/build_poster.py    # copy + layout  -> poster.html
python poster/render.py          # poster.html    -> PDF + PNG proof
python poster/rasterise.py       # artwork        -> assets/*.png (for PowerPoint)
python poster/build_pptx.py      # -> the editable .pptx
python poster/embed_fonts.py "Bodoni Moda:wght@700;800;900" "Inter:wght@400;500;600;700" "IBM Plex Mono:wght@400;500;600"
```

### The three things that will bite

**Fonts must be pinned, not linked.** Google Fonts serves Bodoni Moda and Inter as
*variable* fonts, and Chrome cannot embed a variable instance into a PDF — it falls
back to Type3 glyph programs, which is what a print shop's preflight is most likely
to reject. `embed_fonts.py` pins each weight to a static instance and inlines it.
After any font change, verify:

```bash
python -c "from pypdf import PdfReader; f=PdfReader('poster/BuildMarshalAI-poster-18x24.pdf').pages[0]['/Resources']['/Font']; print('Type3:', sum(1 for _,x in f.items() if x.get_object().get('/Subtype')=='/Type3'))"
```

It must print `Type3: 0`.

**`clip-path` percentages resolve against the element's own box**, not its parent.
Both headline layers are therefore sized to the full hero and positioned by padding.
Move the headline with `padding`, never with `left`/`top`, or the ink layer drifts
off the page.

**The sheet is measured, not estimated.** The vertical budget is tuned to exactly
24.00in with `overflow:hidden` on the body, so anything that overflows is silently
cropped rather than visibly broken. After a copy change, re-measure the band heights
before trusting the render.

## Constraints this poster is built to

- Red / orange / yellow only, on a warm near-black ground.
- No screenshots. All imagery is conceptual vector artwork.
- **No product, tool, model, framework or version names anywhere on the sheet** —
  the content is managerial throughout. `build_poster.py` has a terminology audit
  in its build notes; the current sheet passes with 411 visible words and zero hits.
- Reads at three distances: the claim at 3 m, the three promises at 1 m, the proof
  lines and figures at 30 cm.

## Where the figures come from

| On the poster | Source |
| --- | --- |
| 591 automated checks | `pytest backend/tests` |
| 11 kinds of record from one sentence | `chat_entities.CHAT_KINDS` |
| 0 answers without a page, 0 blanks guessed | the two guarantees the test suite holds in place |
