"""The permission catalogue, and how a user's permissions are resolved.

Two roles are built in and cannot be created or deleted:

* **Head (Super Admin)** holds every permission, and is the only role that may
  manage roles themselves. That authority is deliberately not expressible as a
  permission, so it can never be delegated to a role someone creates.
* **Head (System Admin)** keeps the account-administration reach it has always had.

Every other role is created per account and is exactly the set of permissions
the Head (Super Admin) ticked. Nothing else is hardcoded.

The two were called "Super Admin" and "System Admin" before. Stored users were
renamed by database migration 2, and :func:`canonical_role` still reads the old
labels, so an older client or import cannot create a third spelling.

Adding a permission later means appending one entry to ``PERMISSIONS``; the
roles page, the API, and the checks all read from this list.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


SUPER_ADMIN_ROLE = "Head (Super Admin)"
SYSTEM_ADMIN_ROLE = "Head (System Admin)"

#: Roles that exist without being created, and may not be edited or removed.
BUILTIN_ROLES: tuple[str, ...] = (SUPER_ADMIN_ROLE, SYSTEM_ADMIN_ROLE)

#: The built-ins' former names. Reserved, so no custom role can take them.
LEGACY_ROLE_NAMES: dict[str, str] = {
    "Super Admin": SUPER_ADMIN_ROLE,
    "System Admin": SYSTEM_ADMIN_ROLE,
}

#: Stable ids for the built-ins, independent of their display names.
BUILTIN_ROLE_IDS: dict[str, str] = {
    SUPER_ADMIN_ROLE: "builtin-super-admin",
    SYSTEM_ADMIN_ROLE: "builtin-system-admin",
}


def canonical_role(name: Any) -> str:
    """A role label with a built-in's former name replaced by its current one."""
    text = str(name or "").strip()
    folded = text.casefold()
    for legacy, current in LEGACY_ROLE_NAMES.items():
        if folded == legacy.casefold():
            return current
    for builtin in BUILTIN_ROLES:
        if folded == builtin.casefold():
            return builtin
    return text


def reserved_role_names() -> set[str]:
    """Names no custom role may use: the built-ins, current and former."""
    return {name.casefold() for name in (*BUILTIN_ROLES, *LEGACY_ROLE_NAMES)}

#: Task fields a role can be granted permission to change, in form order.
#: ``cost`` is deliberately absent: it answers to the project cost permissions
#: plus the rule that the assignee maintains their own task's figure.
TASK_FIELD_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("name", "Name"),
    ("task_type", "Task type"),
    ("trade", "Trade"),
    ("assignee", "Assignee"),
    ("field_worker", "On-site worker"),
    ("start_time", "Start time"),
    ("end_time", "End time"),
    ("due_date", "Due date"),
    ("priority", "Priority"),
    ("status", "Status"),
    ("delegation", "Delegation"),
    ("description", "Description"),
    ("parent_id", "Parent task"),
    ("archived", "Archive state"),
)


def _task_field_permissions() -> list[dict[str, str]]:
    return [
        {
            "key": f"task.update.{field}",
            "name": f"Task Details — {label}",
            "description": f"Change the {label.lower()} of an existing task.",
            "group": "Task details",
        }
        for field, label in TASK_FIELD_PERMISSIONS
    ]


#: Every permission a custom role can be granted. Order drives the UI.
PERMISSIONS: tuple[dict[str, str], ...] = tuple([
    {
        "key": "project.create",
        "name": "Project Creation",
        "description": "Create new projects in this workspace.",
        "group": "Projects",
    },
    {
        "key": "project.update",
        "name": "Project Details — Update",
        "description": "Edit a project's name, dates, status, and other details.",
        "group": "Projects",
    },
    {
        "key": "project.people.manage",
        "name": "Add People to a Project",
        "description": "Assign members to a project and remove them from it.",
        "group": "Projects",
    },
    {
        "key": "project.cost.base",
        "name": "Project Base Cost — Update",
        "description": "Set the baseline figure a project's total is built on.",
        "group": "Costs",
    },
    {
        "key": "project.cost.additional",
        "name": "Additional Project Cost — Add & Update",
        "description": "Add, edit, and remove costs that do not belong to a single task.",
        "group": "Costs",
    },
    {
        "key": "project.cost.task",
        "name": "Project Cost — Add & Update",
        "description": (
            "Set the cost on any task in a project. Without this, a user can "
            "still price the tasks assigned to them."
        ),
        "group": "Costs",
    },
    {
        "key": "task.create",
        "name": "Task Creation",
        "description": "Create tasks and subtasks under a project.",
        "group": "Tasks",
    },
    {
        "key": "task.delete",
        "name": "Task Deletion",
        "description": "Delete tasks from a project.",
        "group": "Tasks",
    },
    *_task_field_permissions(),
    {
        "key": "todo.send",
        "name": "Send To-Do Lists",
        "description": (
            "Email a generated to-do list to other members through a connected "
            "Google or Microsoft account. Building and downloading one needs no "
            "permission."
        ),
        "group": "To-do lists",
    },
    {
        "key": "task_type.manage",
        "name": "Create/Edit Task Types",
        "description": "Add, rename, and remove the task types this workspace offers.",
        "group": "Company settings",
    },
    {
        "key": "project_type.manage",
        "name": "Create/Edit Project Types",
        "description": "Add, rename, and remove the project types this workspace offers.",
        "group": "Company settings",
    },
    {
        "key": "trade.manage",
        "name": "Create/Edit Trades",
        "description": "Add, rename, and remove the trades this workspace offers.",
        "group": "Company settings",
    },
    {
        "key": "vendor.manage",
        "name": "Create/Edit External Companies",
        "description": "Add, edit, and remove suppliers, subcontractors, and consultants.",
        "group": "Company settings",
    },
    {
        "key": "contact.manage",
        "name": "Manage the Contact Directory",
        "description": "Add, edit, and remove people in the account's contact directory.",
        "group": "Company settings",
    },
    {
        "key": "procurement.manage",
        "name": "Procurement — Add & Update",
        "description": "Add, edit, and remove the procurement lines on a project.",
        "group": "Projects",
    },
    {
        "key": "document.upload",
        "name": "Upload Documents",
        "description": (
            "Upload files, and import them from Drive, OneDrive, Gmail or Outlook, "
            "into the searchable document index."
        ),
        "group": "Documents",
    },
    {
        "key": "document.delete",
        "name": "Delete Documents",
        "description": "Remove a document and its pages from the index.",
        "group": "Documents",
    },
])

PERMISSION_KEYS: frozenset[str] = frozenset(entry["key"] for entry in PERMISSIONS)

#: Permissions added after roles already existed, each with the id of the
#: release that introduced it. Every one guards something that, before it, any
#: member could do -- so a role that existed then is granted it once, keeping
#: its people exactly as capable as they were. A role remembers which of these
#: it has been through, so a key an administrator later takes away stays away,
#: and a role created afterwards starts without them.
PERMISSION_UPGRADES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("2026-09-access-controls", (
        "trade.manage", "vendor.manage", "contact.manage", "procurement.manage",
        "document.upload", "document.delete",
    )),
)

UPGRADE_IDS: tuple[str, ...] = tuple(upgrade_id for upgrade_id, _ in PERMISSION_UPGRADES)


def apply_permission_upgrades(roles: Sequence[dict[str, Any]]) -> bool:
    """Grant each role the upgrades it has not been through yet, once.

    Mutates the roles in place and says whether anything changed, so the
    caller saves only when it must.
    """
    changed = False
    for role in roles:
        done = set(role.get("upgrades") or ())
        for upgrade_id, keys in PERMISSION_UPGRADES:
            if upgrade_id in done:
                continue
            role["permissions"] = sorted(set(clean_permissions(role.get("permissions") or ())) | set(keys))
            done.add(upgrade_id)
            changed = True
        role["upgrades"] = sorted(done)
    return changed

#: Groups in the order the roles page should render them.
PERMISSION_GROUPS: tuple[str, ...] = tuple(
    dict.fromkeys(entry["group"] for entry in PERMISSIONS)
)


def permission_catalogue() -> list[dict[str, Any]]:
    """The catalogue as the roles page consumes it: grouped, in order."""
    return [
        {
            "group": group,
            "permissions": [dict(entry) for entry in PERMISSIONS if entry["group"] == group],
        }
        for group in PERMISSION_GROUPS
    ]


def clean_permissions(values: Iterable[Any]) -> list[str]:
    """Keep only keys this build knows about, de-duplicated and in catalogue order.

    A key that no longer exists is dropped rather than stored, so a role saved
    against an older build cannot silently grant something undefined.
    """
    wanted = {str(value).strip() for value in values or ()}
    return [entry["key"] for entry in PERMISSIONS if entry["key"] in wanted]


def is_super_admin(user: Mapping[str, Any]) -> bool:
    """Owners are always Head (Super Admin), whatever their stored role label says."""
    return bool(user.get("is_owner")) or canonical_role(user.get("role")) == SUPER_ADMIN_ROLE


def is_builtin_admin(user: Mapping[str, Any]) -> bool:
    """Head (Super Admin) or Head (System Admin): the two roles that administer the account."""
    return is_super_admin(user) or canonical_role(user.get("role")) == SYSTEM_ADMIN_ROLE


def resolve_permissions(user: Mapping[str, Any],
                        roles: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    """Which permissions this user holds.

    The built-in administrators hold everything. Everyone else holds exactly
    what their role was given -- and nothing at all if their role was deleted,
    which fails closed rather than open.
    """
    if is_builtin_admin(user):
        return PERMISSION_KEYS
    role_name = str(user.get("role") or "").strip().casefold()
    if not role_name:
        return frozenset()
    for role in roles or ():
        if str(role.get("name") or "").strip().casefold() == role_name:
            return frozenset(clean_permissions(role.get("permissions") or ()))
    return frozenset()


def role_names(roles: Sequence[Mapping[str, Any]]) -> list[str]:
    """Every assignable role name: the two built-ins plus what was created."""
    names = list(BUILTIN_ROLES)
    for role in roles or ():
        name = str(role.get("name") or "").strip()
        if name and name.casefold() not in {n.casefold() for n in names}:
            names.append(name)
    return names


__all__ = [
    "BUILTIN_ROLES", "BUILTIN_ROLE_IDS", "LEGACY_ROLE_NAMES", "PERMISSIONS", "PERMISSION_GROUPS",
    "PERMISSION_KEYS", "PERMISSION_UPGRADES", "SUPER_ADMIN_ROLE", "SYSTEM_ADMIN_ROLE",
    "TASK_FIELD_PERMISSIONS", "UPGRADE_IDS", "apply_permission_upgrades", "canonical_role",
    "clean_permissions", "is_builtin_admin", "is_super_admin", "permission_catalogue",
    "reserved_role_names", "resolve_permissions", "role_names",
]
