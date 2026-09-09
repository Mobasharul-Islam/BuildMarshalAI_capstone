"""The permission catalogue, and how a user's permissions are resolved.

Two roles are built in and cannot be created or deleted:

* **Super Admin** holds every permission, and is the only role that may manage
  roles themselves. That authority is deliberately not expressible as a
  permission, so it can never be delegated to a role someone creates.
* **System Admin** keeps the account-administration reach it has always had.

Every other role is created per account and is exactly the set of permissions
the Super Admin ticked. Nothing else is hardcoded.

Adding a permission later means appending one entry to ``PERMISSIONS``; the
roles page, the API, and the checks all read from this list.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


SUPER_ADMIN_ROLE = "Super Admin"
SYSTEM_ADMIN_ROLE = "System Admin"

#: Roles that exist without being created, and may not be edited or removed.
BUILTIN_ROLES: tuple[str, ...] = (SUPER_ADMIN_ROLE, SYSTEM_ADMIN_ROLE)

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
])

PERMISSION_KEYS: frozenset[str] = frozenset(entry["key"] for entry in PERMISSIONS)

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
    """Owners are always Super Admin, whatever their stored role label says."""
    return bool(user.get("is_owner")) or user.get("role") == SUPER_ADMIN_ROLE


def is_builtin_admin(user: Mapping[str, Any]) -> bool:
    """Super Admin or System Admin: the two roles that administer the account."""
    return is_super_admin(user) or user.get("role") == SYSTEM_ADMIN_ROLE


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
    "BUILTIN_ROLES", "PERMISSIONS", "PERMISSION_GROUPS", "PERMISSION_KEYS",
    "SUPER_ADMIN_ROLE", "SYSTEM_ADMIN_ROLE", "TASK_FIELD_PERMISSIONS",
    "clean_permissions", "is_builtin_admin", "is_super_admin",
    "permission_catalogue", "resolve_permissions", "role_names",
]
