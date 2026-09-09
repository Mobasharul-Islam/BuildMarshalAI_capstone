"""Task domain logic for BuildMarshalAI project task management.

The task routes live in the notebook alongside projects and the other
management endpoints; the rules that decide whether a task record is valid live
here so they can be tested without a GPU or a running backend.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from fastapi import Depends, HTTPException, Request

try:  # the notebook puts this directory on sys.path
    from permissions import TASK_FIELD_PERMISSIONS
except ModuleNotFoundError:  # imported as backend.tasks
    from backend.permissions import TASK_FIELD_PERMISSIONS

#: Task field -> the permission needed to change it.
TASK_UPDATE_PERMISSIONS = {
    field: f"task.update.{field}" for field, _label in TASK_FIELD_PERMISSIONS
}


# Fields a client may set on a task. Everything else on the record -- id,
# project_id, created_at -- is server-owned.
TASK_FIELDS = (
    "name", "task_type", "parent_id", "trade", "assignee", "field_worker",
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
        "assignee":     _text(data.get("assignee")),
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


def validate_task(
    data: Mapping[str, Any],
    project_tasks: Sequence[Mapping[str, Any]],
    task_id: str | None = None,
) -> None:
    """Reject values the UI must not be able to store.

    ``task_id`` is the task being edited, if any; it enables the checks that a
    task is not its own parent and that a move cannot create a loop.
    """
    status = data.get("status")
    if status and status not in TASK_STATUSES:
        raise HTTPException(422, detail=f"Status must be one of: {', '.join(TASK_STATUSES)}")

    priority = data.get("priority")
    if priority and priority not in TASK_PRIORITIES:
        raise HTTPException(422, detail=f"Priority must be one of: {', '.join(TASK_PRIORITIES)}")

    start, end = _text(data.get("start_time")), _text(data.get("end_time"))
    if start and end and end < start:
        raise HTTPException(422, detail="End time cannot be earlier than start time")

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
    required = ("app", "require_account")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Task integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]

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
        project_or_404(workspace, project_id)
        context.require("task.create", "creating tasks")
        data = await request.json()
        if not str(data.get("name", "")).strip():
            raise HTTPException(status_code=422, detail="Task name is required")
        # Opening a task with money already on it is the same act as setting
        # the cost afterwards, so it answers to the same rule.
        if _cost(data.get("cost")) and not context.can_edit_task_cost(data):
            context.require_task_cost_editor(data)
        tasks = workspace.load_tasks()
        project_tasks = tasks.setdefault(project_id, [])
        validate_task(data, project_tasks)
        task = make_task(data, project_id)
        project_tasks.append(task)
        workspace.save_tasks(tasks)
        return task

    @app.put("/api/projects/{project_id}/tasks/{task_id}")
    async def update_task(project_id: str, task_id: str, request: Request,
                          context=Depends(require_account)) -> dict[str, Any]:
        workspace = context.workspace
        project_or_404(workspace, project_id)
        tasks = workspace.load_tasks()
        project_tasks = tasks.get(project_id, [])
        task = task_or_404(project_tasks, task_id)
        data = await request.json()
        if "name" in data and not str(data["name"]).strip():
            raise HTTPException(status_code=422, detail="Task name cannot be empty")
        # Validate the record as it will be, so a partial update that only moves
        # the parent is still checked against the other fields.
        # A cost change is governed separately from the rest of the task: the
        # assignee maintains their own, and otherwise it takes the project cost
        # permission to touch anyone else's.
        if "cost" in data and _cost(data["cost"]) != _cost(task.get("cost")):
            context.require_task_cost_editor(task)
        assert_field_permissions(context, task, data)
        validate_task({**task, **data}, project_tasks, task_id=task_id)
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
    "detach_children", "filter_tasks", "make_task", "register_task_routes",
    "validate_task",
]
