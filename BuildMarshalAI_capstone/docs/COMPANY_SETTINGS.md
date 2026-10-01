# Company Settings

Three per-account records that the rest of the app reads from: the **company
profile**, the **task-type** catalog, and the **project-type** catalog. Every
member of an account can read all three. Only an administrator can change them.

## Who counts as an administrator

`backend/accounts.py` already defined the rule, and Company Settings uses it
unchanged:

```python
ADMIN_ROLES = frozenset(SYSTEM_ROLES)   # ("Head (Super Admin)", "Head (System Admin)")

@property
def is_admin(self) -> bool:
    return bool(self.user.get("is_owner")) or self.user.get("role") in ADMIN_ROLES
```

The account owner is always an administrator regardless of their role label.
Every other role is created per account on the User Roles page and holds only
the permissions ticked for it. Task types and project types additionally answer
to the `task_type.manage` and `project_type.manage` permissions, so a custom
role can be allowed to curate them without being an administrator. Editing the
company profile stays with the two built-in administrator roles; see
[ROLES_AND_COSTS.md](ROLES_AND_COSTS.md).

## Where the check lives

Every write route calls `context.require_admin()` before touching anything, so
the refusal is a 403 from the server:

```python
@app.put("/api/company")
async def update_company(request: Request, context=Depends(require_account)):
    context.require_admin()
    ...
```

The read routes additionally return `can_edit`, and the frontend uses it only to
decide whether to draw the Edit and Add buttons. Hiding a button is a courtesy;
it is not the control. A member who calls the endpoint directly still gets 403,
which `test_all_features.py` checks for all seven write routes.

## Storage

| Record | Stored in (PostgreSQL, per account) | Loader |
| --- | --- | --- |
| Company profile | `account_state` → `company` | `AccountWorkspace.load_company()` |
| Task types | `catalog_entries`, kind `task_types` | `AccountWorkspace.load_mgmt()` |
| Project types | `catalog_entries`, kind `project_types` | `AccountWorkspace.load_mgmt()` |

`load_mgmt()` backfills any key missing from `DEFAULT_MANAGEMENT`, so an account
created before project types existed picks up the six defaults on its next read
rather than needing a migration.

An account that has never opened Company Info still shows something useful: the
profile is seeded from the account name and the contact details already in
the account settings. Saving writes the four overlapping fields back to the
settings so the rest of the app keeps reading the same values it always did.

## Routes

| Method | Path | Who |
| --- | --- | --- |
| GET | `/api/company` | Any member; returns `{company, can_edit}` |
| PUT | `/api/company` | Administrators |
| GET | `/api/task-types` | Any member; returns `{task_types, total, can_edit}` |
| POST/PUT/DELETE | `/api/task-types[/{id}]` | Administrators |
| GET | `/api/project-types` | Any member; returns `{project_types, total, can_edit}` |
| POST/PUT/DELETE | `/api/project-types[/{id}]` | Administrators |

## Rules enforced server-side

- A blank name is rejected on create and on update (422).
- Names are unique per catalog, compared case-insensitively (409). Renaming an
  entry to what it already is stays allowed.
- A type still referenced by a task or a project cannot be deleted (409). The
  message names the count, so the answer is "change those first", not a silent
  dangling value.
- Company email and contact email must look like addresses; a website must carry
  an `http://` or `https://` scheme (422).
- Unknown fields in a company payload are ignored rather than stored, so a
  client cannot smuggle `role` or `status` in through this route.

## Where the catalogs are used

- **Task types** fill the Task type dropdown on the task form.
- **Project types** fill the Type dropdown on the project create/edit form and
  the Type filter on the projects list. Both read the account's own catalog, so
  a type added here appears in those controls immediately. A project holding a
  type that was later removed keeps its value, shown as `(retired)` in the form
  so an unrelated edit does not silently reassign it.
