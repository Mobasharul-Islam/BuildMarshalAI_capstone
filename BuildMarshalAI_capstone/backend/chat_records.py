"""The project and task records a chat question is about, as prompt text.

Documents answer "what does the specification say"; the workspace's own records
answer "who is on Padma View", "when does Piling end", "what has the project
cost so far". When a question names a project (see chat_scope) or a task, this
builds a compact, plain-text block of those records -- read straight from the
database, no model call -- and the chat puts it in front of the model beside
the retrieved pages.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

try:  # the notebook puts this directory on sys.path
    from chat_scope import find_phrase
except ModuleNotFoundError:  # imported as backend.chat_records
    from backend.chat_scope import find_phrase

#: Task names shorter than this are too likely to be ordinary words.
MIN_TASK_NAME = 4
#: Enough rows for any real project, small enough to stay fast.
MAX_TASK_ROWS = 300


def _t(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def mentioned_tasks(query: str, tasks_by_project: Mapping[str, Sequence[Mapping[str, Any]]],
                    project_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Tasks the question names, as whole words; within ``project_ids`` if given."""
    text = unicodedata.normalize("NFC", str(query or ""))
    wanted = set(project_ids or ())
    found: list[tuple[int, dict[str, Any]]] = []
    for project_id, tasks in tasks_by_project.items():
        if wanted and project_id not in wanted:
            continue
        for task in tasks:
            name = unicodedata.normalize("NFC", _t(task.get("name")))
            if len(name) < MIN_TASK_NAME or task.get("archived"):
                continue
            # "সুপারস্ট্রাকচার (Superstructure)" is named by either half as well.
            forms = [name]
            bracket = re.match(r"^(.*?)\s*\((.+)\)\s*$", name)
            if bracket:
                forms += [part.strip() for part in bracket.groups() if len(part.strip()) >= MIN_TASK_NAME]
            if any(next(find_phrase(form, text), None) for form in forms):
                found.append((len(name), {**task, "project_id": project_id}))
    # Longer names first: "Piling and foundation" is a better match than "Piling".
    found.sort(key=lambda row: -row[0])
    seen: set[str] = set()
    out = []
    for _, task in found:
        if task["id"] not in seen:
            seen.add(task["id"])
            out.append(task)
    return out[:10]


def _person(users: Mapping[str, Mapping[str, Any]], user_id: Any, fallback: Any = "") -> str:
    user = users.get(_t(user_id))
    return _t(user.get("name") or user.get("email")) if user else _t(fallback)


def _task_line(task: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]],
               users: Mapping[str, Mapping[str, Any]], currency: str) -> str:
    parent = by_id.get(_t(task.get("parent_id")))
    parts = [
        _t(task.get("name")) or "(unnamed)",
        f"status {_t(task.get('status')) or 'Open'}",
        f"priority {_t(task.get('priority')) or 'Normal'}",
    ]
    who = _person(users, task.get("assignee_id"), task.get("assignee"))
    parts.append(f"assignee {who or 'unassigned'}")
    for field, label in (("start_time", "start"), ("end_time", "end"), ("due_date", "due"),
                         ("trade", "trade"), ("task_type", "type"), ("field_worker", "on-site worker")):
        if _t(task.get(field)):
            parts.append(f"{label} {_t(task.get(field))}")
    if _money(task.get("cost")):
        parts.append(f"cost {currency} {_money(task.get('cost')):,.2f}")
    if parent:
        parts.append(f"subtask of {_t(parent.get('name'))}")
    if task.get("archived"):
        parts.append("archived")
    if _t(task.get("description")):
        parts.append(f"notes: {_t(task.get('description'))[:200]}")
    return "; ".join(parts)


def project_block(project: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]],
                  procurement: Sequence[Mapping[str, Any]],
                  users: Mapping[str, Mapping[str, Any]]) -> str:
    """Everything the workspace holds about one project, as compact text."""
    currency = _t(project.get("currency")) or "USD"
    lines = [f"PROJECT: {_t(project.get('name'))} (code {_t(project.get('project_code')) or '—'})"]
    fields = [("status", "Status"), ("type", "Type"), ("start_date", "Start date"),
              ("end_date", "End date"), ("description", "Description")]
    for key, label in fields:
        if _t(project.get(key)):
            lines.append(f"- {label}: {_t(project.get(key))[:400]}")
    manager = _person(users, project.get("manager_id"), project.get("manager"))
    lines.append(f"- Manager: {manager or 'not set'}")
    address = ", ".join(_t(project.get(k)) for k in ("address_line1", "address_line2", "city",
                                                     "state", "postal_code", "country") if _t(project.get(k)))
    if address:
        lines.append(f"- Address: {address}")
    members = [_person(users, (m.get("user_id") if isinstance(m, Mapping) else m))
               + (f" ({_t(m.get('project_role'))})" if isinstance(m, Mapping) and _t(m.get("project_role")) else "")
               for m in project.get("members", []) or []]
    members = [m for m in members if m.strip()]
    lines.append(f"- Members: {', '.join(members) if members else 'none added'}")

    live = [t for t in tasks if not t.get("archived")]
    baseline = _money(project.get("baseline_cost"))
    extra = project.get("additional_costs", []) or []
    extra_total = sum(_money(c.get("amount")) for c in extra)
    task_total = sum(_money(t.get("cost")) for t in live)
    lines.append(f"- Cost: baseline {currency} {baseline:,.2f}; additional {currency} {extra_total:,.2f}; "
                 f"tasks {currency} {task_total:,.2f}; total {currency} {baseline + extra_total + task_total:,.2f}")
    # A parent task that carries a cost of its own while its subtasks carry
    # theirs counts the same work twice. Say so, with the figure that does not.
    parents = {_t(t.get("parent_id")) for t in live if _t(t.get("parent_id"))}
    overlapping = []
    for task in live:
        if _t(task.get("id")) in parents and _money(task.get("cost")):
            children = sum(_money(c.get("cost")) for c in live if _t(c.get("parent_id")) == _t(task.get("id")))
            if children:
                overlapping.append(f"{_t(task.get('name'))} {currency} {_money(task.get('cost')):,.2f} "
                                   f"(its subtasks {currency} {children:,.2f})")
    if overlapping:
        leaf_total = sum(_money(t.get("cost")) for t in live if _t(t.get("id")) not in parents)
        lines.append(f"  - NOTE: {len(overlapping)} parent task(s) carry a cost of their own as well as subtasks "
                     f"with costs, so the task total above counts that work twice. Task costs without the parent "
                     f"tasks: {currency} {leaf_total:,.2f}. Overlapping parents: " + "; ".join(overlapping[:12]))
    for cost in extra[:30]:
        lines.append(f"  - additional cost: {_t(cost.get('name'))} {currency} {_money(cost.get('amount')):,.2f}"
                     + (f" ({_t(cost.get('details') or cost.get('description'))[:120]})"
                        if _t(cost.get("details") or cost.get("description")) else ""))

    counts: dict[str, int] = {}
    for task in live:
        counts[_t(task.get("status")) or "Open"] = counts.get(_t(task.get("status")) or "Open", 0) + 1
    lines.append(f"- Tasks: {len(live)} live ({', '.join(f'{n} {s}' for s, n in sorted(counts.items())) or 'none'})"
                 + (f", {len(tasks) - len(live)} archived" if len(tasks) > len(live) else ""))
    # Counted here, from the records as they are now, rather than left to the
    # model to tally from the list (and never carried over from an earlier answer).
    workload: dict[str, dict[str, int]] = {}
    for task in live:
        who = _person(users, task.get("assignee_id"), task.get("assignee")) or "Unassigned"
        row = workload.setdefault(who, {})
        row["total"] = row.get("total", 0) + 1
        status = _t(task.get("status")) or "Open"
        row[status] = row.get(status, 0) + 1
    if workload:
        ranked = sorted(workload.items(), key=lambda kv: (kv[0] == "Unassigned", -kv[1]["total"], kv[0]))
        lines.append("- Workload by assignee (live tasks): " + "; ".join(
            f"{who} {counts['total']} ("
            + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()) if s != "total") + ")"
            for who, counts in ranked))
    by_id = {_t(t.get("id")): t for t in tasks}
    for task in tasks[:MAX_TASK_ROWS]:
        lines.append(f"  - {_task_line(task, by_id, users, currency)}")
    if len(tasks) > MAX_TASK_ROWS:
        lines.append(f"  - … and {len(tasks) - MAX_TASK_ROWS} more tasks")

    if procurement:
        committed = sum(_money(p.get("quantity")) * _money(p.get("unit_cost"))
                        for p in procurement if p.get("status") != "Cancelled")
        lines.append(f"- Procurement: {len(procurement)} lines, committed {currency} {committed:,.2f}")
        for item in procurement[:60]:
            lines.append(f"  - {_t(item.get('name'))}: {_t(item.get('status'))}, supplier {_t(item.get('supplier')) or '—'}, "
                         f"{_money(item.get('quantity')):g} {_t(item.get('unit'))} × {currency} {_money(item.get('unit_cost')):,.2f}"
                         + (f", needed by {_t(item.get('needed_by'))}" if _t(item.get("needed_by")) else ""))
    return "\n".join(lines)


def task_block(task: Mapping[str, Any], project: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]],
               users: Mapping[str, Mapping[str, Any]]) -> str:
    """One task in full, with its project, parent and subtasks."""
    currency = _t(project.get("currency")) or "USD"
    by_id = {_t(t.get("id")): t for t in tasks}
    lines = [f"TASK: {_t(task.get('name'))} (project {_t(project.get('name'))})",
             f"- {_task_line(task, by_id, users, currency)}"]
    subtasks = [t for t in tasks if _t(t.get("parent_id")) == _t(task.get("id"))]
    for sub in subtasks[:50]:
        lines.append(f"  - subtask: {_task_line(sub, by_id, users, currency)}")
    return "\n".join(lines)


def account_overview(projects: Mapping[str, Mapping[str, Any]],
                     tasks_by_project: Mapping[str, Sequence[Mapping[str, Any]]],
                     users: Mapping[str, Mapping[str, Any]], limit: int = 100) -> str:
    """Every project in the account, one line each."""
    if not projects:
        return ""
    lines = [f"ALL PROJECTS IN THIS WORKSPACE ({len(projects)}):"]
    for project in list(projects.values())[:limit]:
        live = [t for t in tasks_by_project.get(_t(project.get("id")), []) if not t.get("archived")]
        done = sum(1 for t in live if _t(t.get("status")) == "Completed")
        manager = _person(users, project.get("manager_id"), project.get("manager"))
        lines.append(
            f"- {_t(project.get('name'))} (code {_t(project.get('project_code')) or '—'}): "
            f"status {_t(project.get('status')) or '—'}; {_t(project.get('start_date')) or '?'} → "
            f"{_t(project.get('end_date')) or '?'}; manager {manager or 'not set'}; "
            f"{len(live)} tasks ({done} completed)" + ("; archived" if project.get("archived") else ""))
    if len(projects) > limit:
        lines.append(f"- … and {len(projects) - limit} more")
    return "\n".join(lines)


#: The most document text sent with one question. Well inside Gemini's context,
#: large enough for a real project pack (the demo pack is about 40,000 characters).
MAX_DOCUMENT_CHARS = 200_000


def documents_context(workspace: Any, project_ids: Iterable[str],
                      max_chars: int = MAX_DOCUMENT_CHARS) -> dict[str, Any]:
    """The full text of every document linked to these projects, page by page.

    Retrieval picks the pages most like the question; this sends all of them,
    so an answer never depends on retrieval having found the right page.
    Returns ``{"text", "documents", "truncated"}``.
    """
    try:
        from document_links import project_documents
    except ModuleNotFoundError:
        from backend.document_links import project_documents
    wanted = [pid for pid in project_ids if pid]
    if not wanted:
        return {"text": "", "documents": 0, "truncated": False}
    projects = workspace.load_projects()
    documents = project_documents(workspace.load_metadata().get("documents", {}), wanted)
    parts: list[str] = []
    used, truncated = 0, False
    for doc_id, document in sorted(documents.items(), key=lambda kv: _t(kv[1].get("name"))):
        linked = [_t(projects[p].get("name")) for p in (document.get("project_ids") or [document.get("project_id")])
                  if p in projects]
        header = (f"DOCUMENT: {_t(document.get('name')) or doc_id} "
                  f"(projects: {', '.join(linked) or '—'}; {int(document.get('page_count') or 0)} pages)")
        body = [header]
        for page in document.get("pages", []) or []:
            text = _t(page.get("text_content"))
            if text:
                body.append(f"[{_t(document.get('name'))} p.{page.get('page_num', '?')}] {text}")
        if len(body) == 1:
            body.append("(no extractable text; see the page images, if retrieved)")
        block = "\n".join(body)
        if used + len(block) > max_chars:
            block = block[: max(0, max_chars - used)] + "\n[… cut: the document text limit was reached]"
            truncated = True
        parts.append(block)
        used += len(block)
        if truncated:
            break
    return {"text": "\n\n".join(parts), "documents": len(documents), "truncated": truncated}


def records_context(query: str, workspace: Any, users: Sequence[Mapping[str, Any]],
                    project_ids: Iterable[str] = ()) -> dict[str, Any]:
    """The records block for a question: its named projects and named tasks.

    Returns ``{"text", "project_ids", "task_ids"}``; ``text`` is empty when the
    question names neither.
    """
    projects = workspace.load_projects()
    tasks_by_project = workspace.load_tasks()
    scoped = [pid for pid in project_ids if pid in projects]
    tasks = mentioned_tasks(query, tasks_by_project, scoped or None)
    project_order = list(dict.fromkeys([*scoped, *(t["project_id"] for t in tasks)]))
    people = {_t(u.get("id")): u for u in users}
    if not project_order:
        # No project named: the model still gets the account's projects, one
        # line each, so it never has only the retrieved pages to go on.
        return {"text": account_overview(projects, tasks_by_project, people),
                "project_ids": [], "task_ids": []}
    procurement = workspace.load_procurement() if hasattr(workspace, "load_procurement") else {}
    blocks = [task_block(t, projects[t["project_id"]], tasks_by_project.get(t["project_id"], []), people)
              for t in tasks if t["project_id"] in projects]
    blocks += [project_block(projects[pid], tasks_by_project.get(pid, []), procurement.get(pid, []) or [], people)
               for pid in project_order]
    return {"text": "\n\n".join(blocks), "project_ids": project_order,
            "task_ids": [t["id"] for t in tasks]}


__all__ = ["MAX_TASK_ROWS", "account_overview", "mentioned_tasks", "project_block", "records_context", "task_block"]
