# User roles and permissions

Two roles exist without being created. Everything else is made per account on
the **User Roles** page and is exactly the permissions ticked for it. No job
title is hardcoded anywhere.

## The two built-in roles

| Role | What it is |
| --- | --- |
| **Super Admin** | Full access. The only role that can create, edit, or delete roles. The registering user gets it, and an account owner counts as one whatever their stored label says. |
| **System Admin** | Account administration, unchanged from before roles became configurable: users, company information, and the workspace catalogues. |

Neither can be edited, deleted, or redefined — `POST /api/user-roles` with
either name returns 409.

### Where the brief conflicted

§1 says Super Admin "remains the only role allowed to manage system-level
permissions **and company information**". §2 says to keep System Admin's
"current permissions/functionality **intact**", and editing company information
is current System Admin functionality.

Resolved as:

* **Role management → Super Admin only.** This is new functionality, so
  restricting it alters nothing System Admin previously had.
* **Company information → unchanged (Super Admin + System Admin).** Taking it
  away would alter System Admin's existing reach, which §2 forbids.

Neither is delegatable to a custom role either way. Change
`require_super_admin` on `PUT /api/company` if you want the stricter reading.

## Why role management is not a permission

The catalogue deliberately contains no key for creating roles, editing roles,
assigning roles, or editing company information. A permission that could be
ticked would be an authority a Super Admin could hand out by accident. The
check is `context.require_super_admin()`, and `test_user_roles.py` asserts no
catalogue key starts with `role.`, `permission.`, or `company.`.

## The permission catalogue

24 permissions in 5 groups, defined once in `backend/permissions.py`:

| Group | Permissions |
| --- | --- |
| Projects | Project Creation · Project Details — Update · Add People to a Project |
| Costs | Project Base Cost — Update · Additional Project Cost — Add & Update · Project Cost — Add & Update |
| Tasks | Task Creation · Task Deletion |
| Task details | One per field: name, task type, trade, assignee, on-site worker, start time, end time, due date, priority, status, delegation, description, parent task, archive state |
| Company settings | Create/Edit Task Types · Create/Edit Project Types |

**Adding one later** means appending an entry to `PERMISSIONS`. The roles page,
the API, and every check read from that list, so nothing else changes. A key
that no longer exists is dropped on save rather than stored, so a role written
against an older build cannot grant something undefined.

## How permissions resolve

```python
def resolve_permissions(user, roles):
    if is_builtin_admin(user):          # Super Admin or System Admin
        return PERMISSION_KEYS
    ...match user["role"] against the account's roles, case-insensitively...
    return frozenset()                   # unknown or missing role: nothing
```

Resolution is read fresh on each request from `AccountContext.permissions`, so
a permission removed from a role applies to that user's **next request** rather
than their next sign-in.

An unknown role resolves to nothing. Deleting a role therefore fails closed,
not open — and deleting one that people still hold is refused outright (409)
so it cannot happen by accident.

## Cost permissions

| What | Who |
| --- | --- |
| Project baseline | `project.cost.base` |
| Additional project costs | `project.cost.additional` |
| Any task's cost | `project.cost.task` |
| Your own task's cost | The assignee, always — no permission needed |

The three are independent grants. The assignee exception means the person doing
the work can record what it cost without being able to touch anyone else's
numbers; `is_assigned` matches the task's `assignee` against the user's display
name, falling back to their email.

Two details worth keeping:

* The task rule fires only when the cost **changes**. The task form saves the
  whole record, so a member updating a status re-sends the existing cost.
* Creating a task with money already on it is the same act as setting the cost
  afterwards, so it answers to the same rule.

The same applies to task fields: `assert_field_permissions` compares each
submitted field against its stored value and only refuses the ones that
actually differ.

## Enforcement

Server-side on every write. A few examples:

| Route | Guard |
| --- | --- |
| `POST /api/projects` | `project.create` |
| `PUT /api/projects/{id}` | `project.update` |
| `POST /api/projects/{id}/members` | `project.people.manage` |
| `PUT /api/projects/{id}/costs/baseline` | `project.cost.base` |
| `POST /api/projects/{id}/tasks` | `task.create` (+ cost rule if priced) |
| `PUT /api/projects/{id}/tasks/{id}` | per changed field, plus the cost rule |
| `POST/PUT/DELETE /api/task-types` | `task_type.manage` or an administrator |
| `POST/PUT/DELETE /api/user-roles` | **Super Admin only** |

`GET /api/user-roles` returns `can_manage` and `my_permissions`; the cost
breakdown returns `can_edit_baseline`, `can_edit_additional`, and
`editable_task_costs`. The UI uses these to decide what to draw — a
convenience, not the control. A forged request still gets 403.

## Migration from the previous model

The earlier build shipped a hardcoded list of business roles. On first
resolution of a workspace, `_seed_roles` creates a role record for **each role
label its users already hold**, granting the permissions that label carried:
the day-to-day task and project work for everyone, plus the three cost
permissions for anything named "Project Manager". Nobody loses access when
roles become data. It runs once; after that the file is the source of truth.

A brand-new account has **no** custom roles, because none are shipped. A user
can still be created without one — they hold no permissions until a Super Admin
assigns them a role, which fails closed.

## Storage

| Record | File under `accounts/<account_id>/` |
| --- | --- |
| Roles | `user_roles.json` |

Roles are per account and isolated like everything else; a role created in one
workspace is invisible in another.
