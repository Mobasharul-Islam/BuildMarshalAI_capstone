# Project Onboarding

Bring a project into BuildMarshal either from the documents it already has — a
schedule spreadsheet, a tender package, a contact list — or by simply saying
what you want ("create a project called Website Redesign"). Either way it lands
in an **editable draft**, and nothing reaches the live stores until a confirmed
commit.

Two rules hold the whole feature together.

**The application's schema is the source of truth.** Nothing here has its own
opinion about what a project is, which of a task's fields are mandatory, or what
a valid cost looks like. That all comes from
[`entity_schema.py`](../backend/entity_schema.py), which derives from the modules
that own each record and is reconciled against their constructors at startup.

**The assistant asks rather than guesses.** A creation request missing a
mandatory field becomes an *incomplete* draft record, and the conversation
continues until the schema says it is complete. The questions, and the choices
offered for a field that names another record, are generated from the schema and
the workspace's real data — not by the model — so there is nothing to invent.

| | |
| --- | --- |
| Schema | [`backend/entity_schema.py`](../backend/entity_schema.py) — what every entity is |
| Backend | [`backend/project_onboarding.py`](../backend/project_onboarding.py) |
| Tests | [`test_entity_schema.py`](../backend/tests/test_entity_schema.py), [`test_project_onboarding.py`](../backend/tests/test_project_onboarding.py) |
| Frontend | the **Onboarding** page in `frontend/app.js` |
| Storage | the `onboarding_drafts` table, in the caller's workspace |
| Who | account administrators only |

---

## The entities

Eleven kinds, each mapped onto a record the application already has. The
**Mandatory** column is what the application itself refuses to create without;
`test_entity_schema.py` drives the real route or validator for every one of them.

| Entity | Belongs to | Mandatory | Becomes |
| --- | --- | --- | --- |
| Project type | — | name | a `project_types` entry |
| Task type | — | name | a `task_types` entry |
| Trade | — | name | a `trades` entry |
| External company | — | name | a `vendors` entry |
| Role | — | name | a role in the account's `roles` |
| Project | — | name, project code | a project |
| User | — | name, email | an account member (+ project membership) |
| Task | a project | name, project | a task under it, nesting as subtasks |
| Project cost | a project | name, amount | an entry in the project's `additional_costs` |
| Task cost | a task | amount | the task's `cost`, which rolls into the project total |
| Procurement item | a project | name | a line on the project's Procurement tab |

A field the application gains shows up automatically: task fields are built from
`tasks.TASK_FIELDS`, procurement from `project_management.PROCUREMENT_FIELDS`,
statuses and priorities from the same constants the routes validate against, and
a role's permissions from the real permission catalogue.

`GET /api/onboarding/schema` serves all of this, plus the records each reference
field may point at. The draft editor renders its forms from that response rather
than from a copy, so the mandatory fields the UI marks are the ones the server
enforces.

### The guard against drift

At startup, `reconcile()` runs each record constructor (`_make_project`,
`make_task`, `catalog_entry`, `make_role`, `make_procurement_item`) and compares
the result with what the schema declares. A field the schema claims but the
constructor does not accept **stops the backend from booting**, with a message
naming the field. A field the constructor gained that nothing offers yet is
reported in the schema response instead.

---

## The flow

### 1 — Upload & analyze (optional)

Upload any number of documents. They go through the ordinary ingestion pipeline
(`ingest_document`), so every format the rest of the app accepts is accepted
here, and the pages stay searchable in chat.

**Analyze** reads each document's page text and folds what comes back into the
draft. Records cite the document and page they came from. Re-running is safe: an
entity whose name is already in the draft is *filled in* rather than repeated —
a later document can supply a field an earlier one left blank, never overwrite
one it already found.

The extraction contract is generated from the entity catalogue, so a new entity
or field is offered to the model without an edit. `EXTRACTION_PASSES` is the
extension point for a new document family.

### 2 — Review & complete

The draft renders as a tree — each project with its tasks, their subtasks, the
costs on each, procurement and the people — plus the standalone catalogues:

```
Draft
├── Project: Website Redesign            WEB-2027
│   ├── Task: Database Migration
│   │   └── Task cost: 50,000
│   ├── Task: UI Development
│   ├── Project cost: Site hoarding      12,000
│   └── People: John Doe
└── Task type: Inspection
```

Every record can be edited, added, deleted or moved, by hand or by asking.

**Incomplete records are shown, not hidden.** One missing a mandatory field is
flagged amber with exactly what it needs, and each missing field is a button that
opens the editor focused on it:

```
⚠ Task: Database Migration          ⚠ Incomplete
  Missing required fields:  [Project] [Task type]
```

The forms come from the schema: a field that names another record is a **select
of the records that actually exist**, never free text, so there is no way to type
a project that nobody has.

#### Creating and editing in conversation

**Review & complete** lists every kind of record the draft holds, each in its
own section — projects, people, tasks, task and project costs, procurement,
external companies, trades, task and project types, roles — built from the
schema's own list of kinds rather than a fixed set, so a kind added later
appears too. Each row says where it belongs ("In Padma View › Piling", "On
Padma View"), every row opens for editing, and the summary tiles jump to their
section. **By project** switches to the hierarchy: each project with its tasks,
costs and people beneath it. A task outside its drafted project's dates is
marked with the reason and cannot be onboarded until it is moved.

Confirming links the documents the draft was built from to the project they
describe, so the new project's **Project Documents** lists them and a chat
question naming it searches them. A document belongs to each project one of its
items belongs to; with a single project in the draft, every attached document
is that project's.

The command bar takes a sentence, typed or dictated through the existing
voice-transcription service:

> **Admin:** Create a task called Database Migration
>
> **Marshal:** Added task Database Migration.
> **Task: Database Migration** still needs Project.
> - **Project** — choose one of: Website Redesign, Harbour Works

The record is in the draft from the first message, incomplete, and the
conversation keeps the floor until it is complete. The model decides what the
administrator *meant*; the schema decides what is still missing and what the
valid answers are, and that half of the reply is composed on the server.

What stops fabrication:

* The prompt carries the entity definitions with the mandatory fields marked,
  and the records that already exist, and says in as many words that leaving a
  mandatory field out is correct and guessing is not.
* A value that is not one of an enum's options is **refused**, not snapped to the
  nearest one — the assistant has to ask again.
* A reference that matches no existing record is dropped, and the field is
  reported as still missing.
* A parent is resolved from a name, or taken when there is exactly one candidate.
  Two candidates and no name is ambiguous, so it is asked about.
* A project code is never generated. `create_project` requires one, and inventing
  an identifier is exactly what must not happen.

Operations are `create`, `update`, `delete`, `move`, `select` and `deselect`.
Each is applied or reported with a reason, so a four-part instruction never loses
its three good parts to one bad one.

### 3 — Select, with dependencies enforced

`dependencies_of()` is the single definition of the hierarchy, derived from the
schema: a record depends on its parent, and on its same-kind parent where the
entity nests. Selection closure, cascade, deletion and commit ordering all read
it, so they cannot drift apart.

* Ticking a task pulls in its project; ticking a task cost pulls in its task,
  that task's parents and the project. The page says what it added and why.
* Unticking a project unticks every task, cost and procurement line under it.
* Deleting a record deletes everything that depended on it, and clears the
  project memberships that pointed at it.
* A task can never be its own ancestor, and a subtask can never sit under a task
  in another project. A refused edit leaves the record exactly as it was.

### 4 — Confirm & onboard

The confirmation step re-validates **on the server, against live data, at the
moment of the commit** — not against whatever the client last saw. For every
selected record it says whether committing would **create** or **reuse**:

| Entity | Matched on |
| --- | --- |
| Project | project code, then name |
| Task | name plus parent, within the target project |
| User | email address |
| Types, trades, companies, roles | name |
| Project cost | name, within the project |
| Task cost | the task already carrying that figure |
| Procurement item | name, within the project |

**Nothing is created while anything selected is incomplete.** The plan returns
`can_commit: false`, the Onboard button is disabled, and a commit attempted
anyway is refused with a 422 naming the records. That check is on the server, so
a stale client cannot get past it.

The commit itself is **one unit of work**. Every store is read once, mutated in
memory and written at the end; users, which the registry writes one at a time,
are recorded and deleted if anything later fails. Any exception restores every
store and re-raises, so a partial onboarding cannot leave inconsistent data.

Creation order is the schema's: catalogues, then projects and people, then tasks
parent-first, then the costs and procurement that hang off them — through the
same constructors the ordinary create routes use, so an onboarded project is
indistinguishable from one typed in by hand.

---

## People and roles

**Passwords.** `create_user` needs one. A first-login password is generated per
person at commit time and returned to the administrator **once**, in the commit
result. It is never written to the draft.

**Roles.** The model proposes a permission set for each role it finds, pre-ticked
in the draft for review — a role grants real authority, so the editor puts the
full permission catalogue in front of the administrator before anything is
created. Creating roles stays Head (Super Admin) work; a Head (System Admin)'s commit reports
role records as skipped. A role named on a person but absent from the account is
dropped and reported rather than stored as a label that resolves to no
permissions.

---

## API

All routes need an account administrator. Everything before `/commit` is
read-only with respect to the live stores.

| Method | Route | Does |
| --- | --- | --- |
| `GET` | `/api/onboarding/schema` | The entity definitions and the live choices |
| `GET` | `/api/onboarding/drafts` | List drafts, newest first |
| `POST` | `/api/onboarding/drafts` | Start one |
| `GET` | `/api/onboarding/drafts/{id}` | The draft, with completeness and dependencies spelled out |
| `DELETE` | `/api/onboarding/drafts/{id}` | Discard it |
| `POST` | `/api/onboarding/drafts/{id}/documents` | Index and attach a document |
| `DELETE` | `/api/onboarding/drafts/{id}/documents/{doc_id}` | Detach one |
| `POST` | `/api/onboarding/drafts/{id}/analyze` | Read the documents into draft records |
| `POST` | `/api/onboarding/drafts/{id}/items` | Add a record |
| `PATCH` | `/api/onboarding/drafts/{id}/items/{item_id}` | Edit one |
| `DELETE` | `/api/onboarding/drafts/{id}/items/{item_id}` | Remove it and its dependants |
| `PUT` | `/api/onboarding/drafts/{id}/selection` | Replace the selection, closed over the hierarchy |
| `POST` | `/api/onboarding/drafts/{id}/command` | Create or edit from a sentence |
| `GET` | `/api/onboarding/drafts/{id}/plan` | What committing would do |
| `POST` | `/api/onboarding/drafts/{id}/commit` | Without `confirm`, reports; with it, creates |

A draft belongs to one account, like every other record: a draft id from another
account reads as missing. A committed draft cannot be committed again.

---

## Adding to it later

* **Another entity** — add an `EntitySpec` to `ENTITIES` and its position to
  `ENTITY_ORDER`, a matching branch in `match_existing`, and a commit branch. Add
  an icon to `ONBOARDING_ICONS` in the frontend. The forms, the extraction
  contract, the assistant's prompt, the missing-field questions, the tree and the
  dependency rules all follow from the spec. If it hangs off something, set
  `parent` — and only that.
* **Another field** — add a `FieldSpec`. If the record constructor already
  accepts it there is nothing else to do; if it does not, `reconcile` says so at
  startup.
* **Another document format** — nothing here changes. Onboarding uses
  `ingest_document`, so a format added to the ingestion pipeline is read here
  automatically.
