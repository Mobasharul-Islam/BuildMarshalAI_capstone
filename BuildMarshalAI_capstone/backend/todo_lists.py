"""To-do lists: build one from the account's tasks, download it, or mail it out.

Three things, sharing one builder so what you download is what recipients get:

* **Build** -- gather outstanding tasks under a filter, and resolve who would
  receive them from the roles picked.
* **Download** -- the same list as a PDF or CSV, for the person asking.
* **Send** -- mail it through the account's own connected Google or Microsoft
  account, to everyone holding the chosen roles.

Sending is outward-facing, so it needs the ``todo.send`` permission *and* an
explicit ``confirm``: without it the route reports who would be written to and
sends nothing.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

#: Statuses that still need doing. A to-do list of finished work is not one.
OPEN_STATUSES: tuple[str, ...] = ("Open", "In Progress", "Blocked")

#: Column order for both the PDF table and the CSV.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("name", "Task"),
    ("project_name", "Project"),
    ("assignee", "Assignee"),
    ("priority", "Priority"),
    ("status", "Status"),
    ("due_date", "Due"),
)


class TodoFilter(BaseModel):
    """What goes on the list."""

    project_id: str | None = None
    statuses: list[str] = Field(default_factory=lambda: list(OPEN_STATUSES))
    assignee: str = ""
    due_before: str = ""
    include_archived: bool = False


class TodoRequest(TodoFilter):
    """A list plus who it is for."""

    roles: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)
    # Give each person only the tasks assigned to them, rather than the whole
    # list. Off by default: a shared list is the usual coordination document.
    per_recipient: bool = False
    title: str = "To-do list"
    note: str = ""
    account_id: str = ""
    provider: str = ""
    confirm: bool = False


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def matches(task: Mapping[str, Any], spec: TodoFilter) -> bool:
    if task.get("archived") and not spec.include_archived:
        return False
    if spec.statuses and _text(task.get("status")) not in spec.statuses:
        return False
    if spec.assignee and _text(task.get("assignee")).casefold() != spec.assignee.casefold():
        return False
    if spec.due_before:
        due = _text(task.get("due_date"))
        # A task with no due date is never "due before" a given day.
        if not due or due > spec.due_before:
            return False
    return True


def collect_tasks(workspace: Any, spec: TodoFilter) -> list[dict[str, Any]]:
    """The tasks this filter selects, newest deadlines first."""
    projects = workspace.load_projects()
    everything = workspace.load_tasks()
    wanted = [spec.project_id] if spec.project_id else list(everything)

    rows: list[dict[str, Any]] = []
    for project_id in wanted:
        project = projects.get(project_id) or {}
        for task in everything.get(project_id, []) or []:
            if not matches(task, spec):
                continue
            rows.append({
                "id": task.get("id"),
                "name": _text(task.get("name")) or "(untitled task)",
                "project_id": project_id,
                "project_name": _text(project.get("name")) or "(unknown project)",
                "assignee": _text(task.get("assignee")),
                "priority": _text(task.get("priority")) or "Normal",
                "status": _text(task.get("status")) or "Open",
                "due_date": _text(task.get("due_date")),
                "description": _text(task.get("description")),
            })
    # Dated work first, in date order; undated trails behind it.
    rows.sort(key=lambda row: (not row["due_date"], row["due_date"], row["project_name"]))
    return rows


def resolve_recipients(users: Sequence[Mapping[str, Any]], roles: Iterable[str],
                       user_ids: Iterable[str]) -> list[dict[str, str]]:
    """Active members holding one of these roles, plus anyone named directly.

    Deactivated members are skipped: mailing a to-do list to someone who can no
    longer sign in helps nobody.
    """
    wanted_roles = {_text(role).casefold() for role in roles if _text(role)}
    wanted_ids = {_text(uid) for uid in user_ids if _text(uid)}
    seen: set[str] = set()
    chosen: list[dict[str, str]] = []
    for user in users:
        if _text(user.get("status")).casefold() == "inactive":
            continue
        email = _text(user.get("email"))
        if not email or email.casefold() in seen:
            continue
        by_role = _text(user.get("role")).casefold() in wanted_roles
        if by_role or _text(user.get("id")) in wanted_ids:
            seen.add(email.casefold())
            chosen.append({"id": _text(user.get("id")), "name": _text(user.get("name")),
                           "email": email, "role": _text(user.get("role"))})
    return chosen


def tasks_for(rows: Sequence[Mapping[str, Any]], person: Mapping[str, str]) -> list[Mapping[str, Any]]:
    """The subset of the list assigned to one person, matched like task costs."""
    handles = {person.get("name", "").casefold(), person.get("email", "").casefold()} - {""}
    return [row for row in rows if _text(row.get("assignee")).casefold() in handles]


def as_text(title: str, note: str, rows: Sequence[Mapping[str, Any]],
            greeting: str = "") -> str:
    """The list as the body of an email."""
    lines: list[str] = []
    if greeting:
        lines += [f"Hello {greeting},", ""]
    lines.append(title)
    if note:
        lines += ["", note]
    lines.append("")
    if not rows:
        lines.append("Nothing outstanding.")
    for row in rows:
        due = f" — due {row['due_date']}" if row["due_date"] else ""
        who = f" — {row['assignee']}" if row.get("assignee") else ""
        lines.append(f"* [{row['priority']}] {row['name']} ({row['project_name']}){who}{due}")
        lines.append(f"    Status: {row['status']}")
    lines += ["", f"{len(rows)} item{'' if len(rows) == 1 else 's'}.",
              f"Generated {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')} by BuildMarshal."]
    return "\n".join(lines)


def as_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _key, label in COLUMNS])
    for row in rows:
        writer.writerow([row.get(key, "") for key, _label in COLUMNS])
    return buffer.getvalue()


def as_pdf(title: str, note: str, rows: Sequence[Mapping[str, Any]]) -> bytes:
    """A printable table, using the same FPDF the other exports use."""
    from fpdf import FPDF

    def safe(value: Any) -> str:
        # FPDF's core fonts are latin-1; replace rather than raise on anything else.
        return str(value if value is not None else "").encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF(orientation="L")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=14)

    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 10, safe(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 6, safe(f"Generated {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}"),
             new_x="LMARGIN", new_y="NEXT")
    if note:
        pdf.ln(2)
        pdf.set_font("helvetica", "I", 10)
        pdf.multi_cell(0, 5, safe(note))
    pdf.ln(4)

    widths = (86, 56, 44, 24, 28, 28)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_fill_color(240, 242, 245)
    for (_key, label), width in zip(COLUMNS, widths):
        pdf.cell(width, 8, safe(label), border=1, fill=True)
    pdf.ln()

    pdf.set_font("helvetica", "", 9)
    if not rows:
        pdf.cell(sum(widths), 8, safe("Nothing outstanding."), border=1)
        pdf.ln()
    for row in rows:
        for (key, _label), width in zip(COLUMNS, widths):
            value = safe(row.get(key, ""))
            # Keep every row on one line; the full text lives in the app.
            budget = max(4, int(width / 1.9))
            if len(value) > budget:
                value = value[: budget - 1] + "…"
            pdf.cell(width, 7, value, border=1)
        pdf.ln()

    output = pdf.output()
    return bytes(output) if not isinstance(output, (bytes, bytearray)) else bytes(output)


def register_todo_list_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    required = ("app", "require_account")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"To-do list integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]
    registry = namespace.get("ACCOUNT_REGISTRY")

    def members(context: Any) -> list[dict[str, Any]]:
        if registry is None:
            return []
        return list(registry.users_for_account(context.account_id))

    def senders() -> dict[str, Any]:
        # Read late: the workspace modules register after this one may load.
        return namespace.get("MAIL_SENDERS") or {}

    @app.post("/api/todo-list/preview")
    async def preview(body: TodoRequest, context=Depends(require_account)) -> dict[str, Any]:
        """Build the list and say who would receive it. Nothing is sent."""
        rows = collect_tasks(context.workspace, body)
        people = resolve_recipients(members(context), body.roles, body.user_ids)
        return {
            "title": body.title,
            "tasks": rows,
            "total": len(rows),
            "recipients": people,
            "per_recipient": body.per_recipient,
            "breakdown": [
                {**person, "count": len(tasks_for(rows, person))} for person in people
            ] if body.per_recipient else [],
            "can_send": context.can("todo.send"),
            "providers": sorted(senders()),
        }

    @app.post("/api/todo-list/download")
    async def download(body: TodoRequest, fmt: str = "pdf",
                       context=Depends(require_account)) -> Any:
        """The same list, for the person asking. No permission needed to read
        your own account's tasks."""
        rows = collect_tasks(context.workspace, body)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        if fmt == "csv":
            return StreamingResponse(
                io.BytesIO(as_csv(rows).encode("utf-8-sig")),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="todo-list-{stamp}.csv"'},
            )
        if fmt != "pdf":
            raise HTTPException(422, "Format must be pdf or csv")
        return StreamingResponse(
            io.BytesIO(as_pdf(body.title, body.note, rows)),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="todo-list-{stamp}.pdf"'},
        )

    @app.post("/api/todo-list/send")
    async def send(body: TodoRequest, context=Depends(require_account)) -> dict[str, Any]:
        """Mail the list to everyone holding the chosen roles."""
        context.require("todo.send", "sending a to-do list to other people")

        rows = collect_tasks(context.workspace, body)
        people = resolve_recipients(members(context), body.roles, body.user_ids)
        if not people:
            raise HTTPException(422, "No active users hold the roles you picked")

        available = senders()
        provider = body.provider or next(iter(sorted(available)), "")
        if provider not in available:
            raise HTTPException(
                503,
                "Connect a Google or Microsoft account before sending a to-do list",
            )
        if not body.account_id.strip():
            raise HTTPException(422, "Choose which connected account to send from")

        # Everything above is read-only. Nothing leaves the building without a
        # deliberate confirm, and the caller is told exactly who would be mailed.
        if not body.confirm:
            return {
                "confirmation_required": True,
                "action": "send_todo_list",
                "provider": provider,
                "total": len(rows),
                "recipients": people,
            }

        send_email = available[provider]
        sent, skipped, failed = [], [], []
        for person in people:
            theirs = tasks_for(rows, person) if body.per_recipient else rows
            if body.per_recipient and not theirs:
                skipped.append({**person, "reason": "nothing assigned"})
                continue
            text = as_text(body.title, body.note, theirs, greeting=person["name"])
            try:
                send_email(context.workspace, body.account_id, person["email"],
                           body.title, text)
                sent.append({**person, "count": len(theirs)})
            except HTTPException as error:
                # One bad address must not lose the rest of the send.
                failed.append({**person, "reason": str(error.detail)[:200]})
            except Exception as error:  # pragma: no cover - provider transport
                failed.append({**person, "reason": str(error)[:200]})

        return {
            "sent": len(sent), "skipped": len(skipped), "failed": len(failed),
            "total": len(rows), "provider": provider,
            "details": {"sent": sent, "skipped": skipped, "failed": failed},
        }

    return {"open_statuses": list(OPEN_STATUSES)}


__all__ = [
    "COLUMNS", "OPEN_STATUSES", "TodoFilter", "TodoRequest", "as_csv", "as_pdf",
    "as_text", "collect_tasks", "matches", "register_todo_list_routes",
    "resolve_recipients", "tasks_for",
]
