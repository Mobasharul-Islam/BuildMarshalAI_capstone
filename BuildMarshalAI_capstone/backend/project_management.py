"""Project people, costs, timeline, and procurement.

These are the Project Details tabs beyond Overview. Registered like the other
integration modules so the routes resolve the caller's workspace through
``require_account``; every record therefore belongs to one account and one
project inside it.

Storage follows the existing shape (PostgreSQL tables, through the workspace):

* ``members``, ``baseline_cost`` and ``additional_costs`` are attributes of the
  project record (the ``projects`` table).
* Task costs are a field on the task (the ``tasks`` table).
* Procurement items are their own records, keyed by project id exactly like
  tasks (the ``procurement_items`` table).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from fastapi import Depends, HTTPException, Request

try:  # the notebook puts this directory on sys.path
    from project_people import active, assignee_of, member_id, project_people
except ModuleNotFoundError:  # imported as backend.project_management
    from backend.project_people import active, assignee_of, member_id, project_people


PROCUREMENT_STATUSES = ("Requested", "Quoted", "Ordered", "Delivered", "Cancelled")

# Fields a client may set on a procurement item.
PROCUREMENT_FIELDS = (
    "name", "description", "supplier", "trade", "quantity", "unit",
    "unit_cost", "status", "needed_by", "ordered_on", "notes",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def money(value: Any, field: str = "amount") -> float:
    """Parse a currency amount, rejecting anything that is not a number."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, bool):
        raise HTTPException(422, detail=f"{field} must be a number")
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(422, detail=f"{field} must be a number") from None
    if amount != amount or amount in (float("inf"), float("-inf")):
        raise HTTPException(422, detail=f"{field} must be a number")
    if amount < 0:
        raise HTTPException(422, detail=f"{field} cannot be negative")
    return round(amount, 2)


def quantity(value: Any) -> float:
    if value in (None, ""):
        return 1.0
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise HTTPException(422, detail="Quantity must be a number") from None
    if amount < 0:
        raise HTTPException(422, detail="Quantity cannot be negative")
    return round(amount, 4)


def as_date(value: Any) -> str:
    """Normalise a date or date-time string to YYYY-MM-DD, or ''."""
    text = _text(value)
    if not text:
        return ""
    candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).date().isoformat()
    except ValueError:
        pass
    try:
        return date.fromisoformat(candidate[:10]).isoformat()
    except ValueError:
        return ""


def cost_breakdown(project: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The project's full cost picture.

    Total = baseline + additional project costs + the sum of task costs, which
    is the definition the Cost tab presents.
    """
    baseline = money(project.get("baseline_cost", 0), "Baseline cost")
    additional = [dict(item) for item in project.get("additional_costs", []) or []]
    additional_total = round(sum(money(item.get("amount", 0)) for item in additional), 2)

    task_rows = [
        {
            "id": task["id"],
            "name": task.get("name", ""),
            "status": task.get("status", ""),
            "trade": task.get("trade", ""),
            "archived": bool(task.get("archived")),
            "cost": money(task.get("cost", 0), "Task cost"),
        }
        for task in tasks
    ]
    # Archived tasks stay visible in the breakdown but do not inflate the total.
    billable = [row for row in task_rows if not row["archived"]]
    tasks_total = round(sum(row["cost"] for row in billable), 2)

    return {
        "baseline_cost": baseline,
        "additional_costs": additional,
        "additional_total": additional_total,
        "tasks": task_rows,
        "tasks_total": tasks_total,
        "task_cost_count": sum(1 for row in billable if row["cost"] > 0),
        "total": round(baseline + additional_total + tasks_total, 2),
        "currency": project.get("currency", "USD"),
    }


def build_timeline(project: Mapping[str, Any], tasks: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Project and task bars for the Gantt view.

    A task with no dates of its own still appears, marked ``scheduled: False``,
    so nothing silently disappears from the chart.
    """
    rows: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("archived"):
            continue
        start = as_date(task.get("start_time"))
        end = as_date(task.get("end_time")) or as_date(task.get("due_date"))
        if end and start and end < start:
            start, end = end, start
        rows.append({
            "id": task["id"],
            "name": task.get("name", ""),
            "status": task.get("status", ""),
            "trade": task.get("trade", ""),
            "assignee": task.get("assignee", ""),
            "parent_id": task.get("parent_id"),
            "start": start,
            "end": end or start,
            "scheduled": bool(start or end),
        })

    dated = [row for row in rows if row["start"] or row["end"]]
    bounds = [value for row in dated for value in (row["start"], row["end"]) if value]
    project_start = as_date(project.get("start_date"))
    project_end = as_date(project.get("end_date"))
    if bounds:
        bounds.extend(filter(None, (project_start, project_end)))
        window_start, window_end = min(bounds), max(bounds)
    else:
        window_start, window_end = project_start, project_end

    return {
        "project": {
            "id": project.get("id"),
            "name": project.get("name", ""),
            "start": project_start,
            "end": project_end,
            "status": project.get("status", ""),
        },
        # The drawing window covers the project and every dated task, so a task
        # that runs past the project end is still visible.
        "window": {"start": window_start, "end": window_end},
        "tasks": rows,
        "scheduled_count": len(dated),
        "unscheduled_count": len(rows) - len(dated),
    }


def make_procurement_item(data: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    status = _text(data.get("status"), "Requested") or "Requested"
    if status not in PROCUREMENT_STATUSES:
        raise HTTPException(422, detail=f"Status must be one of: {', '.join(PROCUREMENT_STATUSES)}")
    now = _now()
    return {
        "id": uuid.uuid4().hex[:12],
        "project_id": project_id,
        "name": _text(data.get("name")),
        "description": _text(data.get("description")),
        "supplier": _text(data.get("supplier")),
        "trade": _text(data.get("trade")),
        "quantity": quantity(data.get("quantity")),
        "unit": _text(data.get("unit"), "ea") or "ea",
        "unit_cost": money(data.get("unit_cost"), "Unit cost"),
        "status": status,
        "needed_by": as_date(data.get("needed_by")),
        "ordered_on": as_date(data.get("ordered_on")),
        "notes": _text(data.get("notes")),
        "created_at": now,
        "updated_at": now,
    }


def apply_procurement_updates(item: dict[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    for field in PROCUREMENT_FIELDS:
        if field not in data:
            continue
        if field == "quantity":
            item[field] = quantity(data[field])
        elif field == "unit_cost":
            item[field] = money(data[field], "Unit cost")
        elif field == "status":
            status = _text(data[field])
            if status not in PROCUREMENT_STATUSES:
                raise HTTPException(422, detail=f"Status must be one of: {', '.join(PROCUREMENT_STATUSES)}")
            item[field] = status
        elif field in ("needed_by", "ordered_on"):
            item[field] = as_date(data[field])
        else:
            item[field] = _text(data[field])
    item["updated_at"] = _now()
    return item


def procurement_summary(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    priced = [
        {**item, "line_total": round(float(item.get("quantity", 0)) * float(item.get("unit_cost", 0)), 2)}
        for item in items
    ]
    # A cancelled line is kept for the record but excluded from the committed
    # spend so the figure reflects what is actually on order.
    committed = round(sum(i["line_total"] for i in priced if i.get("status") != "Cancelled"), 2)
    by_status = {status: 0 for status in PROCUREMENT_STATUSES}
    for item in priced:
        by_status[item.get("status", "Requested")] = by_status.get(item.get("status", "Requested"), 0) + 1
    return {"items": priced, "total": committed, "count": len(priced), "by_status": by_status}


def register_project_management_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register the People, Cost, Timeline, and Procurement routes."""
    required = ("app", "require_account", "ACCOUNT_REGISTRY")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Project management integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]
    registry = namespace["ACCOUNT_REGISTRY"]

    def project_or_404(workspace: Any, project_id: str) -> dict[str, Any]:
        project = workspace.load_projects().get(project_id)
        if not project:
            raise HTTPException(404, detail="Project not found")
        return project

    def save_project(workspace: Any, project: Mapping[str, Any]) -> dict[str, Any]:
        projects = workspace.load_projects()
        projects[project["id"]] = dict(project)
        workspace.save_projects(projects)
        return projects[project["id"]]

    def project_tasks(workspace: Any, project_id: str) -> list[dict[str, Any]]:
        return workspace.load_tasks().get(project_id, [])

    # ── People ────────────────────────────────────────────────────────────

    def member_rows(context: Any, project: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Everyone on the project: its manager, its members, and its assignees."""
        return project_people(project, project_tasks(context.workspace, project["id"]),
                              registry.users_for_account(context.account_id))

    @app.get("/api/projects/{project_id}/members")
    async def list_members(project_id: str, context=Depends(require_account)) -> dict[str, Any]:
        project = project_or_404(context.workspace, project_id)
        members = member_rows(context, project)
        # The picker offers the active users who are not on the project in any
        # way yet; the manager and the assignees are already there.
        on_project = {row["user_id"] for row in members}
        available = [
            {"user_id": u["id"], "name": u.get("name", ""), "email": u.get("email", ""),
             "role": u.get("role", ""), "department": u.get("department", "")}
            for u in registry.users_for_account(context.account_id)
            if u["id"] not in on_project and active(u)
        ]
        return {"members": members, "available": available, "total": len(members)}

    @app.post("/api/projects/{project_id}/members", name="add_project_members")
    async def add_members(project_id: str, request: Request, context=Depends(require_account)) -> dict[str, Any]:
        context.require("project.people.manage", "adding people to a project")
        project = project_or_404(context.workspace, project_id)
        data = await request.json()
        raw = data.get("user_ids")
        if raw is None and data.get("user_id"):
            raw = [data["user_id"]]
        if not isinstance(raw, list) or not raw:
            raise HTTPException(422, detail="Select at least one person to add")

        # Only members of this account can join its projects.
        account_users = {u["id"]: u for u in registry.users_for_account(context.account_id)}
        unknown = [uid for uid in raw if uid not in account_users]
        if unknown:
            raise HTTPException(404, detail="One or more of those people are not in this account")

        inactive = [uid for uid in raw if not active(account_users[uid])]
        if inactive:
            raise HTTPException(422, detail="Only active users can be added to a project")

        members = list(project.get("members", []) or [])
        existing = {member_id(entry) for entry in members}
        added = 0
        for user_id in raw:
            if user_id in existing:
                continue
            members.append({
                "user_id": user_id,
                "project_role": _text(data.get("project_role")),
                "added_at": _now(),
            })
            existing.add(user_id)
            added += 1
        project = {**project, "members": members}
        save_project(context.workspace, project)
        return {"added": added, "members": member_rows(context, project)}

    @app.delete("/api/projects/{project_id}/members/{user_id}")
    async def remove_member(project_id: str, user_id: str, context=Depends(require_account)) -> dict[str, Any]:
        context.require("project.people.manage", "removing people from a project")
        project = project_or_404(context.workspace, project_id)
        members = list(project.get("members", []) or [])
        remaining = [entry for entry in members if member_id(entry) != user_id]
        if len(remaining) == len(members):
            if user_id == project.get("manager_id"):
                raise HTTPException(409, detail=(
                    "This is the project manager. Choose a different manager "
                    "by editing the project instead"))
            raise HTTPException(404, detail="That person is not a member of this project")
        # Someone with work on the project is on it whatever the member list
        # says, so taking them off would leave tasks with a stranger.
        users = registry.users_for_account(context.account_id)
        theirs = [task for task in project_tasks(context.workspace, project_id)
                  if not task.get("archived")
                  and (assignee_of(task, users) or {}).get("id") == user_id]
        if theirs:
            raise HTTPException(409, detail=(
                f"They are assigned {len(theirs)} open task{'' if len(theirs) == 1 else 's'} "
                "on this project. Reassign them first"))
        project = {**project, "members": remaining}
        save_project(context.workspace, project)
        return {"removed": True, "members": member_rows(context, project)}

    # ── Cost ──────────────────────────────────────────────────────────────

    def cost_view(context: Any, project: Mapping[str, Any], project_id: str) -> dict[str, Any]:
        """The cost breakdown plus what this caller is allowed to change.

        Every cost route returns this same shape. A write that answered with
        less would leave the client believing the permissions had gone away,
        and it would hide the controls until the page was reloaded.
        """
        tasks = project_tasks(context.workspace, project_id)
        return {
            **cost_breakdown(project, tasks),
            "can_edit_project_cost": context.can_edit_project_cost,
            "can_edit_baseline": context.can("project.cost.base"),
            "can_edit_additional": context.can("project.cost.additional"),
            "editable_task_costs": [
                task.get("id") for task in tasks if context.can_edit_task_cost(task)
            ],
        }

    @app.get("/api/projects/{project_id}/costs")
    async def get_costs(project_id: str, context=Depends(require_account)) -> dict[str, Any]:
        return cost_view(context, project_or_404(context.workspace, project_id), project_id)

    @app.put("/api/projects/{project_id}/costs/baseline")
    async def set_baseline(project_id: str, request: Request, context=Depends(require_account)) -> dict[str, Any]:
        context.require("project.cost.base", "changing the baseline cost")
        project = project_or_404(context.workspace, project_id)
        data = await request.json()
        project = {**project, "baseline_cost": money(data.get("amount"), "Baseline cost")}
        save_project(context.workspace, project)
        return cost_view(context, project, project_id)

    @app.post("/api/projects/{project_id}/costs")
    async def add_cost(project_id: str, request: Request, context=Depends(require_account)) -> dict[str, Any]:
        context.require("project.cost.additional", "adding project costs")
        project = project_or_404(context.workspace, project_id)
        data = await request.json()
        name = _text(data.get("name"))
        if not name:
            raise HTTPException(422, detail="Cost name is required")
        entry = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "details": _text(data.get("details")),
            "amount": money(data.get("amount")),
            "created_at": _now(),
            "updated_at": _now(),
        }
        project = {**project, "additional_costs": list(project.get("additional_costs", []) or []) + [entry]}
        save_project(context.workspace, project)
        return {"cost": entry, **cost_view(context, project, project_id)}

    @app.put("/api/projects/{project_id}/costs/{cost_id}")
    async def update_cost(project_id: str, cost_id: str, request: Request,
                          context=Depends(require_account)) -> dict[str, Any]:
        context.require("project.cost.additional", "editing project costs")
        project = project_or_404(context.workspace, project_id)
        data = await request.json()
        costs = [dict(item) for item in project.get("additional_costs", []) or []]
        entry = next((item for item in costs if item["id"] == cost_id), None)
        if not entry:
            raise HTTPException(404, detail="Cost not found")
        if "name" in data:
            name = _text(data["name"])
            if not name:
                raise HTTPException(422, detail="Cost name cannot be empty")
            entry["name"] = name
        if "details" in data:
            entry["details"] = _text(data["details"])
        if "amount" in data:
            entry["amount"] = money(data["amount"])
        entry["updated_at"] = _now()
        project = {**project, "additional_costs": costs}
        save_project(context.workspace, project)
        return {"cost": entry, **cost_view(context, project, project_id)}

    @app.delete("/api/projects/{project_id}/costs/{cost_id}")
    async def delete_cost(project_id: str, cost_id: str, context=Depends(require_account)) -> dict[str, Any]:
        context.require("project.cost.additional", "removing project costs")
        project = project_or_404(context.workspace, project_id)
        costs = [dict(item) for item in project.get("additional_costs", []) or []]
        remaining = [item for item in costs if item["id"] != cost_id]
        if len(remaining) == len(costs):
            raise HTTPException(404, detail="Cost not found")
        project = {**project, "additional_costs": remaining}
        save_project(context.workspace, project)
        return {"deleted": True, **cost_view(context, project, project_id)}

    # ── Timeline ──────────────────────────────────────────────────────────

    @app.get("/api/projects/{project_id}/timeline")
    async def get_timeline(project_id: str, context=Depends(require_account)) -> dict[str, Any]:
        project = project_or_404(context.workspace, project_id)
        return build_timeline(project, project_tasks(context.workspace, project_id))

    # ── Procurement ───────────────────────────────────────────────────────

    @app.get("/api/projects/{project_id}/procurement")
    async def list_procurement(project_id: str, status: str = "", context=Depends(require_account)) -> dict[str, Any]:
        project_or_404(context.workspace, project_id)
        items = context.workspace.load_procurement().get(project_id, [])
        if status:
            wanted = [s.strip() for s in status.split(",") if s.strip()]
            items = [item for item in items if item.get("status") in wanted]
        return {**procurement_summary(items), "statuses": list(PROCUREMENT_STATUSES)}

    @app.post("/api/projects/{project_id}/procurement")
    async def create_procurement(project_id: str, request: Request,
                                 context=Depends(require_account)) -> dict[str, Any]:
        context.require("procurement.manage", "changing procurement")
        project_or_404(context.workspace, project_id)
        data = await request.json()
        if not _text(data.get("name")):
            raise HTTPException(422, detail="Item name is required")
        store = context.workspace.load_procurement()
        item = make_procurement_item(data, project_id)
        store.setdefault(project_id, []).append(item)
        context.workspace.save_procurement(store)
        return item

    @app.put("/api/projects/{project_id}/procurement/{item_id}")
    async def update_procurement(project_id: str, item_id: str, request: Request,
                                 context=Depends(require_account)) -> dict[str, Any]:
        context.require("procurement.manage", "changing procurement")
        project_or_404(context.workspace, project_id)
        store = context.workspace.load_procurement()
        items = store.get(project_id, [])
        item = next((i for i in items if i["id"] == item_id), None)
        if not item:
            raise HTTPException(404, detail="Procurement item not found")
        data = await request.json()
        if "name" in data and not _text(data["name"]):
            raise HTTPException(422, detail="Item name cannot be empty")
        apply_procurement_updates(item, data)
        store[project_id] = items
        context.workspace.save_procurement(store)
        return item

    @app.delete("/api/projects/{project_id}/procurement/{item_id}")
    async def delete_procurement(project_id: str, item_id: str,
                                 context=Depends(require_account)) -> dict[str, Any]:
        context.require("procurement.manage", "changing procurement")
        project_or_404(context.workspace, project_id)
        store = context.workspace.load_procurement()
        items = store.get(project_id, [])
        remaining = [i for i in items if i["id"] != item_id]
        if len(remaining) == len(items):
            raise HTTPException(404, detail="Procurement item not found")
        store[project_id] = remaining
        context.workspace.save_procurement(store)
        return {"message": "Procurement item deleted", "id": item_id}

    return {"procurement_statuses": list(PROCUREMENT_STATUSES)}


__all__ = [
    "PROCUREMENT_FIELDS", "PROCUREMENT_STATUSES", "apply_procurement_updates",
    "as_date", "build_timeline", "cost_breakdown", "make_procurement_item",
    "money", "procurement_summary", "quantity", "register_project_management_routes",
]
