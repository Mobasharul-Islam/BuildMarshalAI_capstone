# Project Statistics, Reports, and Document Storage

Three things that answer "where is this project, what do I tell people about it,
and what is all of this costing us to keep".

| | |
| --- | --- |
| Statistics | [`backend/project_analytics.py`](../backend/project_analytics.py) — the figures |
| Reports | [`backend/project_report.py`](../backend/project_report.py) — the document built from them |
| Storage | [`backend/document_storage.py`](../backend/document_storage.py) — what the index costs |
| Frontend | the **Statistics** tab on Project Details, the **Report** dialog, the storage panel on **Documents** |
| Tests | `test_project_analytics.py`, `test_project_report.py`, `test_document_storage.py` |

---

## 1. Statistics

Everything is computed from records the application already keeps, so the
Statistics tab, a generated report, and anything the assistant says are the same
numbers.

### The measures

**Earned value** — PMI's method. Planned value, earned value, schedule variance,
SPI, and a projected finish derived from the index. Progress is credited by the
**fixed formula 50/50** rule: a task earns half its value when it starts and the
rest when it finishes. That is a named EVM technique, not a guess, and the
alternatives (`fixed_0_100`, `fixed_25_75`) are selectable from the tab —
switching re-computes everything.

A task's weight is its cost. An unpriced task is weighted by the average of the
priced ones, so a programme that prices only some of its work is not reported as
though the rest did not exist. A programme that prices *nothing* falls back to
counting work, and the report says so.

**Cost** — budget against commitment. Procurement lines are a real commitment;
task costs are a budget.

> **There is deliberately no cost performance index.** CPI is earned value over
> *actual cost*, and this application records budgets and commitments, not an
> actuals ledger. A CPI computed from budgets would read 1.00 forever and mean
> nothing. `cost_performance()` returns `None` with the reason, and the UI prints
> the reason where the number would have been.

**Flow** — throughput per week and its trend, median and 85th-percentile cycle
time, work in progress, blocked share, and ageing WIP by name.

**Schedule health** — overdue, due within a fortnight, unscheduled, and whether
work is planned past the project's own end date.

**Phase** — Planning → Mobilisation → Execution → Closeout → Complete, from
progress and dates, with a recorded status winning when it is decisive.

### What it refuses to claim

A number the records cannot support is not reported:

* No CPI, for the reason above.
* No SPI when nothing was planned to be done by today.
* An average from fewer than three samples comes back with `confident: false`
  and the reason, which the UI prints under the chart.
* Unscheduled work plans no value — it is in the budget and out of the curve,
  and the count of it is reported.
* Earned value is only plotted up to today. Drawing it forward would be a
  forecast dressed as a measurement.

### Risks

`risk_flags()` raises attention items **by rule, not by model** — deterministic,
explainable, and each carrying the number that raised it. Schedule slip, overdue,
blocked, ageing WIP, falling throughput, overrun past the project end, cost ahead
of progress, procurement needed but not ordered, unassigned and unpriced work.

### The assistant's part

`POST /api/projects/{id}/statistics/insights` hands the computed figures to the
model and asks it to **explain them**. The prompt says, in as many words: use
only the numbers given, never invent a cause, and say what you cannot tell from
this data. If the model is unreachable or answers with something unparseable, a
rule-written summary stands in — the same facts, fewer words — and the UI says
which it is looking at.

---

## 2. Reports, at any stage

A report on a project that has not started is a different document from one on a
project closing out. `PHASE_SECTIONS` maps each phase to the sections worth
writing, and a section with nothing to say is **left out** rather than printed
empty.

| Phase | Report | Leads with |
| --- | --- | --- |
| Planning | Project Baseline Report | budget and the people lined up |
| Mobilisation | Project Mobilisation Report | early progress, procurement |
| Execution | Project Progress Report | progress against plan, delivery |
| Closeout | Project Closeout Report | what is still outstanding |
| Complete | Project Final Report | the finished position |

Every report carries a **Basis of This Report** section: the date, the progress
rule, the linear planned-value assumption, what is excluded, and whether the
commentary was written by a model or from the figures alone. Figures nobody can
check are figures nobody should act on.

Rendering reuses `document_generation.PdfDocumentRenderer` and the same
generated-document registry, so a report downloads through the route that already
serves generated documents. The renderer's cover line and footer became
parameters so a report grounded in workspace records does not claim to be
grounded in source PDFs.

| Method | Route |
| --- | --- |
| `GET` | `/api/projects/{id}/statistics?rule=` |
| `POST` | `/api/projects/{id}/statistics/insights` |
| `GET` | `/api/projects/{id}/report/preview` — what it would contain; writes nothing |
| `POST` | `/api/projects/{id}/report` — writes the PDF |
| `GET` | `/api/projects/{id}/reports` — every report for this project |

---

## 3. Document storage

Indexing one PDF page costs far more than the page: an original, a rendered
image, a ColPali multi-vector (the largest by far), a pooled vector in Chroma,
and often a vision tile. A few hundred pages is gigabytes, and none of it
announces itself.

### Three principles

**Originals are never touched.** They are the only thing that cannot be rebuilt.

**Reclaim the free wins first.** Files nobody owns, then bytes that are simply
duplicated, then caches that can be rebuilt on demand. Anything lossy comes last
and only when asked.

**Nothing is deleted without being described first.** `plan_sweep()` is read-only
and returns the very lists `run_sweep()` consumes, so the confirmation is the
truth rather than a summary of it.

### What it reclaims

| Action | Safe? | What it does |
| --- | --- | --- |
| **Orphans** | always | Derived files whose document is gone |
| **Duplicates** | asks | Collapses byte-identical documents, keeping the first |
| **Compact** | asks | Rewrites oversized page images as WebP; abandons a rewrite that would not shrink |
| **Evict** | asks | Drops rebuildable caches for the coldest documents, only as far as the budget requires |

### A leak that was fixed on the way

Deleting a document removed its page images, its original and its vectors from
the index — but the ColPali cache and the vision tiles are keyed by page
*filename*, not by document, so they outlived it permanently and unreachably.
Over a workspace's life that was the single largest avoidable cost.

`delete_document_files()` now removes them, and it was extracted from the delete
route so a storage sweep collapses a duplicate the same way a hand-deletion does,
rather than growing a second, divergent cleanup path.

### Deduplication

`ingest_document` records a SHA-256 content hash. An upload whose bytes are
already indexed short-circuits before the expensive part — rendering every page,
embedding each one, storing the result — and reuses the existing document,
reporting `status: "duplicate"`. The check lives in `ingest_document` itself,
so every path uses it: the Documents upload, project sources, onboarding, and
Drive/OneDrive/mail imports. Its scope is the project the file is being filed
into (`ingestion_formats.find_duplicate`): the same tender uploaded twice to one
project is indexed once, while the same tender as a source of two projects is
indexed for each, because a document belongs to one project and reusing it
would move it out of the other.

### Knowing warm from cold

Serving a page image records `accessed_at`. Without it an eviction can only go on
age, which throws away the wrong things.

| Method | Route |
| --- | --- |
| `GET` | `/api/storage` — where the space went, and what could be reclaimed |
| `GET` | `/api/storage/plan?actions=` — exactly what a sweep would remove |
| `POST` | `/api/storage/sweep` — without `confirm`, reports; with it, reclaims |
| `PUT` | `/api/storage/policy` — budget, warm window, page size and quality, dedup |

Reading storage needs no special standing; sweeping and policy changes are
administrator work.

---

## The charts

Plain inline SVG — no chart library, in keeping with the rest of the app. Forms
were chosen by the data's job: a **KPI row** for the headline figures (not a
one-bar chart), a **line** for the S-curve, a **stacked bar** for part-to-whole,
**columns** for throughput, horizontal **bars** for magnitude, and a **meter**
for one ratio against a limit (not a two-slice pie).

The series colours were **validated, not chosen by eye**. The obvious mapping —
green for done, red for blocked — was tried first and failed outright: ΔE 4.1
under deuteranopia, meaning a red-green reader cannot tell those two segments
apart at all. The palette in use is the validated categorical set, assigned in
fixed order and never cycled, with:

* a legend whenever there are two or more series, so identity is never colour
  alone;
* a direct label on every stacked segment — which is also what the two lighter
  slots' sub-3:1 contrast is relieved by;
* a **Table view** toggle showing the same figures as text;
* severity written out beside every risk dot.

The app has no dark mode, so the light steps ship alone; the matching validated
dark steps are recorded in a comment next to them for whoever adds one.
