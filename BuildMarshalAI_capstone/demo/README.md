# Demonstration kit

Everything needed to show BuildMarshalAI end to end **without a GPU**, and to
regenerate the screenshots and clips in the demonstration deck.

| | |
| --- | --- |
| `project-pack/` | Nine synthetic project documents — the demo's input |
| `demo_server.py` | A local backend: the real route modules, no models |
| `providers.py` | Simulated Google Workspace and Microsoft 365 |
| `seed_onboarding.py` | Builds an onboarding draft through the real API |
| `materialise_index.py` | Renders real page images, vectors and tiles to disk |
| `capture_screens.py` | Drives headless Chrome and saves `screens/*.png` |
| `make_clips.py` | Assembles `clips/*.gif`, acting out each click |

### The pointer in the clips

A cut between two screenshots tells a viewer that something changed but not *what*
*was pressed*. So each transition is acted out: the pointer travels to the control, a
ring pulses under it, and only then does the next screen appear.

The positions are not drawn by hand. `capture_screens.py` records the bounding box of
every element it clicks -- as a *fraction* of the viewport, so nothing downstream has to
know the device pixel ratio -- into `screens/gestures.json`. A scroll is recorded too,
and gets a mouse-wheel glyph rather than a pointer, because nothing was clicked.

## Run it

```bash
python scripts/make_demo_pack.py      # the seven documents
python demo/demo_server.py            # backend + seeded workspace
python demo/seed_onboarding.py        # the onboarding draft
python demo/materialise_index.py      # real files, so storage measures something
```

Then open <http://127.0.0.1:8000> and sign in as `rafiqul.islam@purbachalcon.example`
with `PadmaView2026!`.

To rebuild the deck's images, with the server running:

```bash
python demo/capture_screens.py
python demo/make_clips.py
```

## What is real and what is not

**Real:** tasks, costs, procurement, company settings, roles and permissions,
onboarding, analytics, reports and storage are registered from `backend/*.py`
exactly as the notebook registers them, against a real `AccountWorkspace` with
real authentication. Every figure on screen was computed by the production code.

**Stood in for:** the routes that live inside the notebook (project CRUD,
upload, document listing) are reimplemented here, and retrieval answers from a
fixed script in `demo_server.py` rather than from ColPali and a model — those
need a GPU. Google and Microsoft report as not connected.

**Not a deployment target.** One seeded account, a known password, no retrieval
stack. `demo/.demo-runtime/` holds the seeded workspace and is not committed;
`--reset` rebuilds it.

## The project

**Padma View Specialised Hospital Extension** — a ৳ 60,00,00,000 (৳ 60 crore),
8,400 m² six-storey hospital extension in Sector 11, Uttara, Dhaka, for a fictional
health foundation. Nothing and nobody in it is real.

Bangladeshi in every way that matters — money in Taka with lakh/crore grouping, and
the constraints that really bite here: monsoon casting limits, Friday closure, RAJUK
approval, Fire Service clearance and imported lift lead times — but written in
English, which is the working language of the application.

Two projects at other stages sit alongside it — a Banasree school in planning and an
Agrabad office refurbishment complete — so reports can be shown at all three phases.

The data is deliberately mid-flight: SPI 0.96, the Level 2 slab overdue in the monsoon,
the glazing sample blocked with a 12-week lead behind it, and the lift letter-of-credit
date already passed. See `project-pack/README.md` for the facts worth asking about.

### Bangla in the documents

The documents carry a little Bangla, the way a real Dhaka project pack does: the
project, client and contractor names as a bilingual line, a Bangla name column on the
team sheet, three room labels on the floor plan, and one term in the monsoon clause.
Everything else — and everything inside the application — is English.

Bengali needs complex text shaping, which reportlab and Pillow cannot do, so the PDFs
are printed from HTML by headless Chrome, which shapes correctly and embeds the shaped
glyphs.

### Google and Microsoft are simulated

`providers.py` answers with the same shapes the real routes do, from a fixed set of
files, messages and events, so Drive indexing, mail and calendar can be shown without
anybody signing in to anything. **Nothing reaches a provider.** Every response carries
`"simulated": true`. The integration code itself is untouched; what is stood in for is
the service on the other end of the wire.
