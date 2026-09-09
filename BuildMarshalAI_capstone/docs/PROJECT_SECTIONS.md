# Project sections and the global Calendar

The Project Details tabs beyond Overview, plus the account-wide Calendar.
Everything is per account and per project: a project id from another account
returns 404 on every route below.

## People

Assign account members to a project. Members are the people already in the
account (**Company Settings → User**); the project stores only their ids, so
nothing is duplicated and a person removed from the account drops out of the
project automatically.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/projects/{id}/members` | Assigned people plus who else is available |
| POST | `/api/projects/{id}/members` | Add one or many (`user_ids`, optional `project_role`) |
| DELETE | `/api/projects/{id}/members/{user_id}` | Remove from the project only |

Adding someone twice is a no-op. A user from another account is rejected with
404.

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

Items live in `accounts/<account_id>/procurement.json`, keyed by project id, and
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
