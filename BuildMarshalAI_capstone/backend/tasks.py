"""Task domain logic for BuildMarshalAI project task management.

The task routes live in the notebook alongside projects and the other
management endpoints; the rules that decide whether a task record is valid live
here so they can be tested without a GPU or a running backend.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from typing import Any, Iterable, Mapping, Sequence

from fastapi import Depends, HTTPException, Request

try:  # the notebook puts this directory on sys.path
    from permissions import TASK_FIELD_PERMISSIONS
    from project_people import assignable_people, resolve_assignee
except ModuleNotFoundError:  # imported as backend.tasks
    from backend.permissions import TASK_FIELD_PERMISSIONS
    from backend.project_people import assignable_people, resolve_assignee

#: Task field -> the permission needed to change it.
TASK_UPDATE_PERMISSIONS = {
    field: f"task.update.{field}" for field, _label in TASK_FIELD_PERMISSIONS
}
# The assignee is held as a user id beside the display name; changing either
# is the same act.
TASK_UPDATE_PERMISSIONS["assignee_id"] = TASK_UPDATE_PERMISSIONS["assignee"]


# Fields a client may set on a task. Everything else on the record -- id,
# project_id, created_at -- is server-owned.
TASK_FIELDS = (
    "name", "task_type", "parent_id", "trade", "assignee", "assignee_id", "field_worker",
    "start_time", "end_time", "due_date", "priority", "status", "delegation",
    "description", "cost", "archived",
)

TASK_STATUSES = ("Open", "In Progress", "Blocked", "Completed")
TASK_PRIORITIES = ("Low", "Normal", "High", "Urgent")


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def _cost(value: Any) -> float:
    """A task cost; anything unparseable or negative is refused."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, bool):
        raise HTTPException(422, detail="Task cost must be a number")
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(422, detail="Task cost must be a number") from None
    if amount != amount or amount in (float("inf"), float("-inf")):
        raise HTTPException(422, detail="Task cost must be a number")
    if amount < 0:
        raise HTTPException(422, detail="Task cost cannot be negative")
    return round(amount, 2)


def make_task(data: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    """Build a new task record from client input."""
    now = datetime.now(timezone.utc).isoformat()
    parent = _text(data.get("parent_id"))
    return {
        "id":           str(uuid.uuid4()),
        "project_id":   project_id,
        "name":         _text(data.get("name")),
        "task_type":    _text(data.get("task_type")),
        # None means the task sits at the root of the project.
        "parent_id":    parent or None,
        "trade":        _text(data.get("trade")),
        # The display name; ``assignee_id`` is the user it refers to. The
        # routes fill both from the user record, never from free text alone.
        "assignee":     _text(data.get("assignee")),
        "assignee_id":  _text(data.get("assignee_id")),
        "field_worker": _text(data.get("field_worker")),
        "start_time":   _text(data.get("start_time")),
        "end_time":     _text(data.get("end_time")),
        "due_date":     _text(data.get("due_date")),
        "priority":     _text(data.get("priority"), "Normal") or "Normal",
        "status":       _text(data.get("status"), "Open") or "Open",
        "delegation":   _text(data.get("delegation")),
        # Task costs roll up into the project total on the Cost tab.
        "cost":         _cost(data.get("cost")),
        "description":  _text(data.get("description")),
        "archived":     bool(data.get("archived", False)),
        "created_at":   now,
        "updated_at":   now,
    }


def apply_task_updates(task: dict[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the client-settable fields of ``data`` onto ``task`` in place."""
    for field in TASK_FIELDS:
        if field not in data:
            continue
        if field == "parent_id":
            task[field] = _text(data[field]) or None
        elif field == "archived":
            task[field] = bool(data[field])
        elif field == "cost":
            task[field] = _cost(data[field])
        else:
            task[field] = _text(data[field])
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    return task


def project_window(project: Mapping[str, Any] | None) -> tuple[datetime | None, datetime | None]:
    """The first and last moments a task of this project may be scheduled.

    A project's dates are whole days, so its window runs from the start of its
    first day to the end of its last. A missing (or unreadable) date leaves that
    side open.
    """
    if not project:
        return None, None

    def day(value: Any) -> date | None:
        text = _text(value)[:10]
        try:
            return date.fromisoformat(text) if text else None
        except ValueError:
            return None

    first, last = day(project.get("start_date")), day(project.get("end_date"))
    return (datetime.combine(first, time.min) if first else None,
            datetime.combine(last, time.max) if last else None)


def check_within_project(data: Mapping[str, Any], project: Mapping[str, Any] | None) -> None:
    """Refuse a task scheduled outside its project: start <= task start <= task end <= end."""
    low, high = project_window(project)
    if low is None and high is None:
        return
    name = _text((project or {}).get("name")) or "the project"
    for field, label in (("start_time", "Start time"), ("end_time", "End time")):
        when = parse_when(data.get(field), label)
        if when is None:
            continue
        if low is not None and when < low:
            raise HTTPException(422, detail=(
                f"{label} {when:%Y-%m-%d %H:%M} is before {name} starts on {low:%Y-%m-%d}. "
                "A task must fall within its project's dates"))
        if high is not None and when > high:
            raise HTTPException(422, detail=(
                f"{label} {when:%Y-%m-%d %H:%M} is after {name} ends on {high:%Y-%m-%d}. "
                "A task must fall within its project's dates"))


def tasks_outside_project(project: Mapping[str, Any],
                          tasks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The live tasks a project's (new) dates would leave outside them."""
    outside = []
    for task in tasks:
        if task.get("archived"):
            continue
        try:
            check_within_project(task, project)
        except HTTPException:
            outside.append(dict(task))
    return outside


def check_project_dates(project: Mapping[str, Any],
                        tasks: Iterable[Mapping[str, Any]] = ()) -> None:
    """Refuse project dates that end before they start, or that would leave
    one of the project's live tasks outside them."""
    for field, label in (("start_date", "Start date"), ("end_date", "End date")):
        text = _text(project.get(field))
        if text:
            try:
                date.fromisoformat(text[:10])
            except ValueError:
                raise HTTPException(422, detail=f"{label} {text!r} is not a valid date") from None
    low, high = project_window(project)
    if low and high and high < low:
        raise HTTPException(422, detail="The project's end date cannot be earlier than its start date")
    outside = tasks_outside_project(project, tasks)
    if outside:
        names = ", ".join(_text(t.get("name")) or "(unnamed)" for t in outside[:3])
        more = f" and {len(outside) - 3} more" if len(outside) > 3 else ""
        raise HTTPException(422, detail=(
            f"{len(outside)} task{'' if len(outside) == 1 else 's'} would fall outside those dates "
            f"({names}{more}). Move {'it' if len(outside) == 1 else 'them'} first, or keep the "
            "project's dates wide enough"))


def validate_task(
    data: Mapping[str, Any],
    project_tasks: Sequence[Mapping[str, Any]],
    task_id: str | None = None,
    project: Mapping[str, Any] | None = None,
) -> None:
    """Reject values the UI must not be able to store.

    ``task_id`` is the task being edited, if any; it enables the checks that a
    task is not its own parent and that a move cannot create a loop. ``project``
    is the task's project when its dates are being set: the task must then fall
    within the project's dates.
    """
    status = data.get("status")
    if status and status not in TASK_STATUSES:
        raise HTTPException(422, detail=f"Status must be one of: {', '.join(TASK_STATUSES)}")

    priority = data.get("priority")
    if priority and priority not in TASK_PRIORITIES:
        raise HTTPException(422, detail=f"Priority must be one of: {', '.join(TASK_PRIORITIES)}")

    # Dates must be real dates, a task cannot end before it starts, and it must
    # fall within its project: project start <= task start <= task end <= project end.
    start = parse_when(data.get("start_time"), "Start time")
    end = parse_when(data.get("end_time"), "End time")
    parse_when(data.get("due_date"), "Due date")
    if start and end and end < start:
        raise HTTPException(422, detail="End time cannot be earlier than start time")
    check_within_project(data, project)

    parent_id = _text(data.get("parent_id")) or None
    if not parent_id:
        return

    by_id = {task["id"]: task for task in project_tasks}
    if parent_id not in by_id:
        raise HTTPException(422, detail="Parent task is not in this project")
    if task_id is None:
        return
    if parent_id == task_id:
        raise HTTPException(422, detail="A task cannot be its own parent")

    # Walk up from the proposed parent; reaching this task means a loop.
    seen: set[str] = set()
    cursor: str | None = parent_id
    while cursor:
        if cursor == task_id:
            raise HTTPException(422, detail="That parent would create a loop of subtasks")
        if cursor in seen:
            break
        seen.add(cursor)
        cursor = by_id.get(cursor, {}).get("parent_id")


def parse_when(value: Any, label: str) -> datetime | None:
    """A task date or date-time as a datetime, None if empty, 422 if not a date."""
    text = _text(value)
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(candidate[:10]), datetime.min.time()) \
                if len(candidate) == 10 else None
        except ValueError:
            parsed = None
        if parsed is None:
            raise HTTPException(422, detail=f"{label} {text!r} is not a valid date") from None
    # Compare everything as naive local time: the forms send no zone.
    return parsed.replace(tzinfo=None)


def filter_tasks(
    tasks: Iterable[Mapping[str, Any]],
    *,
    name: str = "",
    trade: str = "",
    status: str = "",
    assignee: str = "",
    priority: str = "",
    parent_id: str = "",
    show_archived: bool = False,
) -> list[dict[str, Any]]:
    """Apply the task list filters used by the Task Manager."""
    result = [dict(task) for task in tasks]
    if not show_archived:
        result = [t for t in result if not t.get("archived")]
    if name:
        result = [t for t in result if name.lower() in str(t.get("name", "")).lower()]
    if trade:
        result = [t for t in result if t.get("trade") == trade]
    if status:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        result = [t for t in result if t.get("status") in wanted]
    if assignee:
        result = [t for t in result if t.get("assignee") == assignee]
    if priority:
        result = [t for t in result if t.get("priority") == priority]
    # "root" selects only top-level tasks, which is how the tree view loads.
    if parent_id == "root":
        result = [t for t in result if not t.get("parent_id")]
    elif parent_id:
        result = [t for t in result if t.get("parent_id") == parent_id]
    return result


def detach_children(project_tasks: list[dict[str, Any]], task_id: str) -> None:
    """Lift a deleted task's subtasks to its own parent so none are orphaned."""
    removed = next((t for t in project_tasks if t["id"] == task_id), None)
    if removed is None:
        return
    parent_id = removed.get("parent_id")
    for child in project_tasks:
        if child.get("parent_id") == task_id:
            child["parent_id"] = parent_id




def assert_field_permissions(context: Any, task: Mapping[str, Any],
                            data: Mapping[str, Any]) -> None:
    """Refuse the fields this role may not change.

    Only fields whose value actually differs are checked. The task form saves
    the whole record, so a member editing the status re-sends every other field
    unchanged; treating those as attempted edits would refuse the save.
    """
    denied = [
        field for field in data
        if field in TASK_UPDATE_PERMISSIONS
        and str(data.get(field) or "") != str(task.get(field) or "")
        and not context.can(TASK_UPDATE_PERMISSIONS[field])
    ]
    if denied:
        readable = ", ".join(sorted(denied))
        raise HTTPException(403, f"Your role does not allow changing: {readable}")


def register_task_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register the project task endpoints.

    Registered with the other integration modules so this file is importable
    from wherever the notebook resolved it, and so the routes can resolve the
    caller's workspace through ``require_account``.
    """
    required = ("app", "require_account", "ACCOUNT_REGISTRY")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Task integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]
    registry = namespace["ACCOUNT_REGISTRY"]

    def account_users(context: Any) -> list[dict[str, Any]]:
        return list(registry.users_for_account(context.account_id))

    def bind_assignee(context: Any, project: Mapping[str, Any],
                      project_tasks: Sequence[Mapping[str, Any]], data: dict[str, Any]) -> None:
        """Replace whatever the client sent for the assignee with a real person.

        Only someone already on the project -- its manager, a member, or an
        assignee of one of its tasks -- can be given the task.
        """
        chosen = resolve_assignee(data, project, project_tasks, account_users(context))
        if chosen is not None:
            data["assignee_id"], data["assignee"] = chosen

    def project_or_404(workspace: Any, project_id: str) -> dict[str, Any]:
        project = workspace.load_projects().get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    def task_or_404(project_tasks: Sequence[Mapping[str, Any]], task_id: str) -> dict[str, Any]:
        task = next((t for t in project_tasks if t["id"] == task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.get("/api/projects/{project_id}/tasks")
    async def list_tasks(
        project_id: str,
        name: str = "",
        trade: str = "",
        status: str = "",
        assignee: str = "",
        priority: str = "",
        parent_id: str = "",
        show_archived: bool = False,
        context=Depends(require_account),
    ) -> dict[str, Any]:
        project_or_404(context.workspace, project_id)
        tasks = filter_tasks(
            context.workspace.load_tasks().get(project_id, []),
            name=name, trade=trade, status=status, assignee=assignee,
            priority=priority, parent_id=parent_id, show_archived=show_archived,
        )
        return {"tasks": tasks, "total": len(tasks)}

    @app.get("/api/projects/{project_id}/assignees")
    async def list_assignees(project_id: str, context=Depends(require_account)) -> dict[str, Any]:
        """Who a task on this project may be assigned to."""
        project = project_or_404(context.workspace, project_id)
        project_tasks = context.workspace.load_tasks().get(project_id, [])
        people = assignable_people(project, project_tasks, account_users(context))
        return {"assignees": people, "total": len(people)}

    @app.get("/api/projects/{project_id}/tasks/{task_id}")
    async def get_task(project_id: str, task_id: str, context=Depends(require_account)) -> dict[str, Any]:
        project_or_404(context.workspace, project_id)
        project_tasks = context.workspace.load_tasks().get(project_id, [])
        task = task_or_404(project_tasks, task_id)
        return {
            **task,
            "subtasks": [t for t in project_tasks if t.get("parent_id") == task_id],
            "parent": next((t for t in project_tasks if t["id"] == task.get("parent_id")), None),
        }

    @app.post("/api/projects/{project_id}/tasks")
    async def create_task(project_id: str, request: Request, context=Depends(require_account)) -> dict[str, Any]:
        workspace = context.workspace
        project = project_or_404(workspace, project_id)
        context.require("task.create", "creating tasks")
        data = dict(await request.json())
        if not str(data.get("name", "")).strip():
            raise HTTPException(status_code=422, detail="Task name is required")
        bind_assignee(context, project, workspace.load_tasks().get(project_id, []), data)
        # Opening a task with money already on it is the same act as setting
        # the cost afterwards, so it answers to the same rule.
        if _cost(data.get("cost")) and not context.can_edit_task_cost(data):
            context.require_task_cost_editor(data)
        tasks = workspace.load_tasks()
        project_tasks = tasks.setdefault(project_id, [])
        validate_task(data, project_tasks, project=project)
        task = make_task(data, project_id)
        project_tasks.append(task)
        workspace.save_tasks(tasks)
        return task

    @app.put("/api/projects/{project_id}/tasks/{task_id}")
    async def update_task(project_id: str, task_id: str, request: Request,
                          context=Depends(require_account)) -> dict[str, Any]:
        workspace = context.workspace
        project = project_or_404(workspace, project_id)
        tasks = workspace.load_tasks()
        project_tasks = tasks.get(project_id, [])
        task = task_or_404(project_tasks, task_id)
        data = dict(await request.json())
        if "name" in data and not str(data["name"]).strip():
            raise HTTPException(status_code=422, detail="Task name cannot be empty")
        # Re-sending the assignee the task already has is not a reassignment:
        # the whole-record save of an older task must still go through.
        if (_text(data.get("assignee_id")) and _text(data.get("assignee_id")) == _text(task.get("assignee_id"))) \
                or ("assignee_id" not in data and _text(data.get("assignee")) == _text(task.get("assignee"))
                    and "assignee" in data):
            data.pop("assignee", None)
            data.pop("assignee_id", None)
        else:
            bind_assignee(context, project, project_tasks, data)
        # Validate the record as it will be, so a partial update that only moves
        # the parent is still checked against the other fields.
        # A cost change is governed separately from the rest of the task: the
        # assignee maintains their own, and otherwise it takes the project cost
        # permission to touch anyone else's.
        if "cost" in data and _cost(data["cost"]) != _cost(task.get("cost")):
            context.require_task_cost_editor(task)
        assert_field_permissions(context, task, data)
        # The project's window is checked whenever the dates change. A task
        # saved before the rule existed can still have its status or notes
        # edited without first being moved.
        dates_changed = any(field in data and _text(data[field]) != _text(task.get(field))
                            for field in ("start_time", "end_time"))
        validate_task({**task, **data}, project_tasks, task_id=task_id,
                      project=project if dates_changed else None)
        apply_task_updates(task, data)
        tasks[project_id] = project_tasks
        workspace.save_tasks(tasks)
        return task

    @app.delete("/api/projects/{project_id}/tasks/{task_id}", name="delete_task_route")
    async def delete_task(project_id: str, task_id: str, context=Depends(require_account)) -> dict[str, Any]:
        context.require("task.delete", "deleting tasks")
        workspace = context.workspace
        project_or_404(workspace, project_id)
        tasks = workspace.load_tasks()
        project_tasks = tasks.get(project_id, [])
        task_or_404(project_tasks, task_id)
        # Subtasks would otherwise be orphaned and invisible.
        detach_children(project_tasks, task_id)
        tasks[project_id] = [t for t in project_tasks if t["id"] != task_id]
        workspace.save_tasks(tasks)
        return {"message": "Task deleted"}

    return {"statuses": list(TASK_STATUSES), "priorities": list(TASK_PRIORITIES)}


__all__ = [
    "TASK_FIELDS", "TASK_PRIORITIES", "TASK_STATUSES", "apply_task_updates",
    "check_project_dates", "check_within_project", "detach_children", "filter_tasks", "make_task", "parse_when",
    "project_window", "register_task_routes", "tasks_outside_project", "validate_task",
]
