"""Who is on a project: its manager, its members, and the people doing its tasks.

A project's people come from three places, and the People tab shows all three:

* the **manager**, one of the account's users, held as ``manager_id``;
* the **members** added explicitly (``project["members"]``);
* anyone **assigned a task** under the project (``task["assignee_id"]``).

Only those people can be given a task on the project -- the task routes check
it, and the task forms offer no one else. The manager and every assignee are
stored as user ids; the display names beside them (``manager``, ``assignee``)
are refreshed from the user record, so a rename reaches every project and task
and a name typed somewhere can never pass for a person.

Records written before ids existed carry only a name. :func:`resolve_user`
matches such a name to exactly one user, and a name matching none, or several,
is not a person the application can act on.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from fastapi import HTTPException

#: The sources a person can be on a project through, in display order.
SOURCES = ("Manager", "Member", "Task assignee")


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _fold(value: Any) -> str:
    return " ".join(_text(value).split()).casefold()


def member_id(entry: Any) -> str:
    """The user id of one ``members`` entry, whichever shape it was saved in."""
    return _text(entry.get("user_id") if isinstance(entry, Mapping) else entry)


def resolve_user(users: Iterable[Mapping[str, Any]], *, user_id: Any = None,
                 name: Any = None) -> dict[str, Any] | None:
    """The one user named by id, or failing that by exact name or email.

    A name shared by two users names neither of them: picking one would put
    work on the wrong person's desk.
    """
    rows = list(users)
    wanted = _text(user_id)
    if wanted:
        return next((dict(u) for u in rows if _text(u.get("id")) == wanted), None)
    key = _fold(name)
    if not key:
        return None
    matches = [u for u in rows if _fold(u.get("name")) == key or _fold(u.get("email")) == key]
    return dict(matches[0]) if len(matches) == 1 else None


def active(user: Mapping[str, Any]) -> bool:
    return _text(user.get("status") or "Active").casefold() == "active"


# -- the manager -----------------------------------------------------------------

def resolve_manager(data: Mapping[str, Any], users: Sequence[Mapping[str, Any]], *,
                    required: bool) -> dict[str, Any] | None:
    """The manager a create or edit asks for, as a user, or a 422 saying why not.

    ``manager_id`` is what the form sends. A bare ``manager`` name -- from the
    chat, an older client, or a script -- is accepted only when it names exactly
    one user, and the id is what gets stored.
    """
    has_id = "manager_id" in data and _text(data.get("manager_id"))
    has_name = "manager" in data and _text(data.get("manager"))
    if not has_id and not has_name:
        if required:
            raise HTTPException(422, detail="Choose the project manager from the account's users")
        return None
    user = resolve_user(users, user_id=data.get("manager_id")) if has_id \
        else resolve_user(users, name=data.get("manager"))
    if user is None:
        if has_id:
            raise HTTPException(422, detail="The chosen project manager is not a user in this account")
        raise HTTPException(422, detail=(
            f"{_text(data.get('manager'))!r} is not one of this account's users. "
            "Choose the project manager from the user list"))
    if not active(user):
        raise HTTPException(422, detail=f"{user.get('name') or user.get('email')} is not an active user")
    return user


def present_project(project: Mapping[str, Any], users: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The project as clients see it: the manager's name read from their user."""
    shown = dict(project)
    manager = resolve_user(users, user_id=project.get("manager_id")) if project.get("manager_id") else None
    if manager:
        shown["manager"] = manager.get("name") or manager.get("email") or ""
    elif project.get("manager_id"):
        # The user was deleted; the record keeps the id but names nobody.
        shown["manager"] = ""
    else:
        # A legacy record whose manager name never matched a user.
        shown["manager"] = _text(project.get("manager"))
        shown["manager_unlinked"] = bool(shown["manager"])
    return shown


# -- everyone on the project ---------------------------------------------------------

def assignee_of(task: Mapping[str, Any], users: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The user a task is assigned to, by id or (for older tasks) by name."""
    if task.get("assignee_id"):
        return resolve_user(users, user_id=task.get("assignee_id"))
    return resolve_user(users, name=task.get("assignee"))


def project_people(project: Mapping[str, Any], tasks: Iterable[Mapping[str, Any]],
                   users: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Everyone on the project, once each, with every way they are on it."""
    by_id = {_text(u.get("id")): u for u in users}
    rows: dict[str, dict[str, Any]] = {}

    def add(user_id: str, source: str, **extra: Any) -> None:
        user = by_id.get(user_id)
        if not user:
            return      # a removed account member drops out of the project
        row = rows.setdefault(user_id, {
            "user_id": user_id,
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "role": user.get("role", ""),
            "department": user.get("department", ""),
            "designation": user.get("designation", ""),
            "status": user.get("status", "Active"),
            "sources": [],
            "project_role": "",
            "added_at": None,
            "task_count": 0,
        })
        if source not in row["sources"]:
            row["sources"].append(source)
        for key, value in extra.items():
            if value and not row.get(key):
                row[key] = value

    if project.get("manager_id"):
        add(_text(project["manager_id"]), "Manager")
    for entry in project.get("members", []) or []:
        extra = entry if isinstance(entry, Mapping) else {}
        add(member_id(entry), "Member", project_role=_text(extra.get("project_role")),
            added_at=extra.get("added_at"))
    for task in tasks:
        user = assignee_of(task, users)
        if user:
            add(_text(user["id"]), "Task assignee")
            rows[_text(user["id"])]["task_count"] += 1

    ordered = sorted(rows.values(), key=lambda row: (
        min(SOURCES.index(s) for s in row["sources"]), _fold(row["name"] or row["email"])))
    for row in ordered:
        row["sources"].sort(key=SOURCES.index)
        # Only an explicit membership can be taken away on the People tab; the
        # manager changes with the project, an assignee with the task.
        row["removable"] = "Member" in row["sources"]
    return ordered


def project_people_ids(project: Mapping[str, Any], tasks: Iterable[Mapping[str, Any]],
                       users: Sequence[Mapping[str, Any]]) -> set[str]:
    return {row["user_id"] for row in project_people(project, tasks, users)}


# -- task assignment ----------------------------------------------------------------

def resolve_assignee(data: Mapping[str, Any], project: Mapping[str, Any],
                     tasks: Sequence[Mapping[str, Any]], users: Sequence[Mapping[str, Any]],
                     ) -> tuple[str, str] | None:
    """The (id, name) a task write assigns, or None if it does not touch the assignee.

    ``("", "")`` clears the assignment. Anyone else must already be on the
    project; the refusal says so rather than quietly storing a stranger.
    """
    if "assignee_id" not in data and "assignee" not in data:
        return None
    wanted_id = _text(data.get("assignee_id"))
    wanted_name = _text(data.get("assignee"))
    if not wanted_id and not wanted_name:
        return "", ""
    people = project_people(project, tasks, users)
    on_project = {row["user_id"] for row in people}
    if wanted_id:
        user = resolve_user(users, user_id=wanted_id)
        if user is None:
            raise HTTPException(422, detail="The chosen assignee is not a user in this account")
    else:
        # A name is looked up among the project's people first: two account
        # users may share it while only one of them is on this project.
        user = resolve_user([u for u in users if _text(u.get("id")) in on_project], name=wanted_name) \
            or resolve_user(users, name=wanted_name)
        if user is None:
            raise HTTPException(422, detail=(
                f"{wanted_name!r} is not a user in this account. "
                "Assign the task to someone on the project"))
    if _text(user["id"]) not in on_project:
        who = user.get("name") or user.get("email")
        raise HTTPException(422, detail=(
            f"{who} is not on {project.get('name') or 'this project'}. "
            "Add them on the project's People tab before assigning them a task"))
    return _text(user["id"]), _text(user.get("name") or user.get("email"))


def assignable_people(project: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]],
                      users: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The people a task on this project may be given to (active users only)."""
    return [
        {"user_id": row["user_id"], "name": row["name"], "email": row["email"],
         "sources": row["sources"]}
        for row in project_people(project, tasks, users) if active(row)
    ]


__all__ = [
    "SOURCES", "active", "assignable_people", "assignee_of", "member_id", "present_project",
    "project_people", "project_people_ids", "resolve_assignee", "resolve_manager",
    "resolve_user",
]
