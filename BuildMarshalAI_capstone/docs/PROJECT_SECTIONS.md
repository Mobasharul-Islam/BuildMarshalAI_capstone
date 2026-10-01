# Project sections and the global Calendar

The Project Details tabs beyond Overview, plus the account-wide Calendar.
Everything is per account and per project: a project id from another account
returns 404 on every route below.

## The project manager

A project's manager is one of the account's users, chosen from a list on the
project form. Nobody types a name. The project stores the user's id
(`manager_id`). `manager`, beside it, is only the display name, and every read
refreshes it from the user record, so renaming a user renames them on every
project.

- **Create** (`POST /api/projects`) requires a manager: `manager_id`, or a
  `manager` name that matches exactly one active user in the account (the chat
  hands the form a name). Anything else is a 422 that says why. `member_ids`
  adds people to the project in the same request, and each must be an active
  user.
- **Edit** (`PUT /api/projects/{id}`) can change the manager to another user.
  It cannot clear the manager.
- **Dates**: a project cannot end before it starts. Its dates cannot be changed
  so that one of its live tasks falls outside them; the refusal names the
  tasks. Tasks are held inside the project's dates (see
  [TASK_MANAGEMENT.md](TASK_MANAGEMENT.md)).
- Projects from before this change named their manager as text. Migration 2
  linked each name that matched exactly one user. A project whose name matched
  nobody (or several people) shows the name with a *not a user* badge until
  someone is chosen.
- Onboarding reads managers and assignees from documents as names. The commit
  matches each to a user, including users created in the same commit. A name
  it cannot match is cleared, and the commit result lists it under *People to
  choose by hand*.

## People

The People tab lists everyone on the project, once each, with every way they
are on it:

| Shown as | Because |
| --- | --- |
| **Manager** | They are the project's manager |
| **Member** | Someone added them (at creation, or with **Add People**) |
| **Task assignee** | They are assigned at least one of the project's tasks (the count is shown) |

Only a **Member** entry can be removed. The manager changes by editing the
project, and an assignee by reassigning the task. Someone who still has open
tasks on the project cannot be removed until those tasks are reassigned (409).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/projects/{id}/members` | Everyone on the project (`sources`, `removable`, `task_count`) plus the active users who are not |
| POST | `/api/projects/{id}/members` | Add one or many (`user_ids`, optional `project_role`); active users of this account only |
| DELETE | `/api/projects/{id}/members/{user_id}` | Remove an explicit membership |
| GET | `/api/projects/{id}/assignees` | Who a task on this project may be given to |

Adding someone twice does nothing. A user from another account is rejected
with 404, and an inactive user with 422. A person removed from the account
drops out of every project.

## Project Documents

The Overview's **Project Documents** section can hold any file type the
Documents page accepts, not only PDFs.

- **Upload** puts a new file straight into the project. A PDF also has its
  text layer kept for document generation.
- **Link existing** opens a picker of the account's other documents. It shows
  where each came from (*Documents*, *Chat upload*, *Project upload*,
  *Onboarding*, *Google Workspace*, *Microsoft 365*) and which projects already
  use it. You can filter it by name, by origin, or to *Unassigned only*.
  Linking copies nothing and indexes nothing: the document gains the project in
  its `project_ids`.
- Uploading bytes the account already holds does not store a second copy. The
  existing document is linked to the project, and the reply says so.
- **Remove from project** (the unlink button) keeps the document. It stays in
  Documents and on any other project it is linked to. With no project left it
  is *Unassigned*.
- Deleting a project unlinks its documents. A document it shared with other
  projects stays on those.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/projects/{id}/source-documents` | Upload a new document into the project |
| GET | `/api/projects/{id}/source-documents` | The project's documents, with every project each belongs to |
| GET | `/api/projects/{id}/linkable-documents` | The account's documents not yet linked to it |
| POST | `/api/projects/{id}/source-documents/link` | Link existing documents: `{"doc_ids": [...]}` |
| DELETE | `/api/projects/{id}/source-documents/{doc_id}` | Unlink (the document is kept) |

The **Documents** page names every project a document belongs to, in full
("Projects: Alpha Tower, Bravo School, Charlie Clinic"), or says *Unassigned*;
so do the upload panel's list and the link picker, and a project's own list
says where else each document is used ("Also on: …"). A document linked to
several projects is still one record. It filters to *All*, *Unassigned* (the orphans) or one project.
`GET /api/documents` returns `project_ids`, `projects`, `unassigned` and
`origin` for each document, and takes `scope=unassigned` or `project_id=` to
filter the same way.

## Project-aware chat

When a question names a project, by its name, the first two or more words of
its name ("Padma View" for "Padma View Specialised Hospital Extension"), or
its project code, as whole words and in any case, retrieval searches only the documents linked to that
project. Only those pages are given to the model. Documents shared with other
projects count, because they are linked to this one too. If two projects'
names overlap ("Tower" and "Tower B"), the longer match wins. A question
naming two projects searches both.

- With no project named, a question asked from a project's page is scoped to
  that project. Anywhere else, the search is account-wide, as before.
- A named project with no documents gets an answer saying so. Other projects'
  documents are not used instead.
- The reply carries `scope` (`project_ids`, `projects`, `reason`), and the chat
  shows it above the answer: *Searched only Riverside School's documents.*

This lives in `backend/chat_scope.py`. The retriever filters its vector
channel by document id (`where: {"doc_id": {"$in": [...]}}`). Page vectors do
not carry project ids, because a link can change without re-embedding.

## Cost

**Total = Baseline + Additional project costs + Sum of task costs.**

- **Baseline** — one figure per project.
- **Additional costs** — named line items with details and an amount, added,
  edited, and deleted from the Cost tab. Stored on the project record.
- **Task costs** — each task carries a `cost`; the Cost tab edits them inline
  and the project total updates immediately, because the total is recomputed
  server-side from the tasks each time it is read.

Archived tasks stay in the breakdown for the record but do not count toward the
total. Amounts must be numbers and cannot be negative.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/projects/{id}/costs` | Full breakdown and totals |
| PUT | `/api/projects/{id}/costs/baseline` | Set the baseline |
| POST/PUT/DELETE | `/api/projects/{id}/costs[/{cost_id}]` | Additional costs |

Task costs are set through the existing task routes (`cost` field).

## Timeline

A Gantt view of the project bar and every dated task, coloured by status.

`GET /api/projects/{id}/timeline` returns the project bar, the task rows, and a
drawing `window`. The window spans the project **and** every dated task, so a
task running outside the project dates is still visible. A task with no dates is
returned with `scheduled: false` and listed under the chart rather than being
silently dropped. A reversed task range is straightened.

## Procurement

The fifth tab (labelled **Procore** in the reference screenshots) is implemented
as procurement: materials and services ordered for the project.

Each item has a name, description, supplier, trade, quantity, unit, unit cost,
status, needed-by date, and notes. Line total is quantity × unit cost.
**Cancelled** lines stay on the record but are excluded from committed spend.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/projects/{id}/procurement` | Items, line totals, committed spend, status counts |
| POST/PUT/DELETE | `/api/projects/{id}/procurement[/{item_id}]` | Manage items |

Statuses: `Requested`, `Quoted`, `Ordered`, `Delivered`, `Cancelled`.

Procurement is deliberately **not** part of the project cost total, which is
defined as baseline + additional + task costs; committed spend is reported
separately on the Procurement tab.

Items live in the `procurement_items` table, keyed by account and project id, and
are removed when the project is deleted.

## Global Calendar

A month grid combining four sources, each with its own colour:

| Source | Colour | Where it comes from |
| --- | --- | --- |
| Project dates | blue | The account's projects (`start_date` → `end_date`) |
| Task dates | green | Every project's tasks (`start_time` → `end_time`, falling back to `due_date`) |
| Google Calendar | amber | `GET /api/google/calendar/events` for the connected account |
| Outlook Calendar | purple | `GET /api/microsoft/calendar/events` for the connected account |

Multi-day items are drawn on every day they span. Each source can be toggled
off, months are navigable, and clicking a day lists everything on it with a link
out to the provider event where there is one.

The connected-calendar fetch reuses the existing provider slices and endpoints
from the Google Workspace and Microsoft 365 pages — there is no second
integration path. If a provider is not connected its row simply shows zero. A
provider that errors is reported in a banner without blocking the rest.

### Day panel: details and navigation

Clicking a day lists everything on it. Each row behaves in two ways:

- **The title** of a project or task is a link that navigates straight to that
  project's dashboard or to the task in the Task Manager with its detail panel
  open. Provider events have no such page, so their title is plain text.
- **Clicking anywhere else on the row** expands a compact detail popover:
  - *Project* — code, manager, status, type, start, end, **total cost** (fetched
    on demand from `/api/projects/{id}/costs`), description.
  - *Task* — project, status, priority, trade, assignee, on-site worker, start,
    end, due date, cost, description.
  - *Provider event* — calendar, start, end, location, organiser, attendees,
    details, plus **Edit event** and a link out to Google/Outlook.

### Editing a connected calendar event

The **Edit event** button opens a form for title, date, end date, start time,
end time, location, attendees, and description. Saving writes through to the
**real** Google or Outlook calendar on the connected account, then reloads the
month from the provider so the grid shows what the calendar now holds.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/google/calendar/events/{event_id}?account_id=` | Read one event back from Google |
| PATCH | `/api/google/calendar/events/{event_id}` | Partial update |
| GET | `/api/microsoft/calendar/events/{event_id}?account_id=` | Read one event back from Graph |
| PATCH | `/api/microsoft/calendar/events/{event_id}` | Partial update |
| POST | `/api/google/calendar/events` | Create an event; `add_meet` attaches a Google Meet link |
| POST | `/api/microsoft/calendar/events` | Create an event; `add_online_meeting` attaches a Teams meeting |

Both are **partial**: only the fields supplied are sent, so an unspecified field
keeps whatever the provider already has. Both require `confirm: true`, matching
the create/send endpoints — without it the response is a
`{"confirmation_required": true}` proposal and nothing is written.

Validation and errors:

- An empty title or an end before the start returns **422**; so does a request
  with nothing to change.
- An event id the calendar does not have returns **404**, as does an
  `account_id` this workspace has not linked.
- Expired or revoked authorisation returns **401** with "reconnect this
  account"; a permission failure returns **403**; rate limiting returns **429**.
  The Google mapping is shared by insert and patch, so both report the same way.
- The Outlook reshaping is shared by list, read, and update, so all three return
  the same field names as Google and the frontend renders either with one code
  path.

## Code layout

`backend/project_management.py` holds the people, cost, timeline, and
procurement rules and routes, registered with the other integration modules.
Its pure helpers (`cost_breakdown`, `build_timeline`, `procurement_summary`,
`money`, `as_date`) are unit-tested in
`backend/tests/test_project_management.py`.

The frontend sections live in `frontend/app.js` between the project module and
the connected-workspace module, and reuse the existing table, filter, form, and
CRUD-modal components.
