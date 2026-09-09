# Task management

Tasks belong to a project, and projects belong to an account, so a user only
ever sees and edits tasks in their own workspace. Records live in
`accounts/<account_id>/tasks.json` keyed by project id.

## Where it appears

| Place | What you can do |
| --- | --- |
| **Tasks** (sidebar) | The Task Manager: project tabs, filters, the task tree, create, view, edit, archive, delete |
| **Projects → Project Details → Project Tasks** | See the project's tasks, add one, click through to the Task Manager |

## The Task Manager

- **Project tabs** — *All Projects* plus a tab per project you open from the
  *+ Open project…* selector. The Project column is shown only on *All
  Projects*, where it is not redundant.
- **Filters** — task name (debounced), trade, and under *More filters* status,
  priority, and assignee. *Clear Filters* resets them.
- **Task tree** — subtasks nest under their parent and expand with the chevron.
  A task whose parent is filtered out is shown at the root so it can never
  become invisible.
- **Show Archived** reveals archived tasks; **Move Checked to Bottom** sinks
  completed ones.
- **Detail panel** — click a row. Every field is editable, with *Mark Done* /
  *Reopen*, *Archive* / *Restore*, *Save*, and *Delete task*.

## Task fields

| Field | Notes |
| --- | --- |
| `name` | Required; cannot be blank |
| `task_type` | From the account's task types |
| `parent_id` | `null` for a root task; must be another task in the same project |
| `trade` | From the account's trades |
| `assignee` | An account member |
| `field_worker` | A team member |
| `start_time`, `end_time` | `datetime-local`; the end cannot precede the start |
| `due_date` | Kept for compatibility with earlier task records |
| `priority` | `Low`, `Normal`, `High`, `Urgent` |
| `status` | `Open`, `In Progress`, `Blocked`, `Completed` |
| `delegation`, `description` | Free text |
| `archived` | Hidden from listings unless `show_archived=true` |

`id`, `project_id`, `created_at`, and `updated_at` are server-owned; a client
cannot set them, and an update touches only the fields it sends.

## Endpoints

All require `Authorization: Bearer <session token>`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/projects/{project_id}/tasks` | List, with `name`, `trade`, `status` (comma-separated), `assignee`, `priority`, `parent_id` (`root` or an id), `show_archived` |
| GET | `/api/projects/{project_id}/tasks/{task_id}` | One task plus its `subtasks` and `parent` |
| POST | `/api/projects/{project_id}/tasks` | Create |
| PUT | `/api/projects/{project_id}/tasks/{task_id}` | Partial update |
| DELETE | `/api/projects/{project_id}/tasks/{task_id}` | Delete; subtasks are lifted to the deleted task's own parent |
| GET | `/api/task-types` | The task-type list behind the Task type dropdown; also reports `can_edit` |
| POST/PUT/DELETE | `/api/task-types[/{id}]` | Administrators only. See [COMPANY_SETTINGS.md](COMPANY_SETTINGS.md) |

## Rules enforced server-side

- A blank name is rejected on create and on update.
- `status` and `priority` must be one of the allowed values.
- `end_time` cannot be earlier than `start_time`.
- A parent must be a task in the same project; a task cannot be its own parent,
  and a move that would close a loop of subtasks is rejected.
- Deleting a task re-parents its subtasks rather than orphaning them.
- A project id from another account returns **404**, so tasks cannot be reached,
  edited, or deleted across accounts.

## Code layout

`backend/tasks.py` holds the task rules and routes and is registered with the
other integration modules (`register_task_routes`). Keeping it out of the
notebook means the logic is unit-testable without a GPU —
`backend/tests/test_tasks.py` covers the record rules, the filters, and every
route, including cross-account isolation.

The frontend Task Manager lives in `frontend/app.js` between the project module
and the connected-workspace module, and reuses the existing table, filter-bar,
form, and CRUD-modal components.
