"""The project report, at whatever stage the project has reached.

A report on a project that has not started is a different document from a report
on one that is closing out, and pretending otherwise produces pages of "N/A".
So the phase decides what is in it: :data:`PHASE_SECTIONS` maps each phase to
the sections worth writing, and a section that would say nothing is left out
rather than filled with nothing.

Everything factual comes from :mod:`project_analytics`, which computes from the
same records the dashboard reads, so a report can never disagree with the
Statistics tab. The assistant writes the narrative *around* those figures and is
given them rather than asked for them; where it cannot be reached, the report is
still produced from the numbers alone.

Rendering reuses :class:`document_generation.PdfDocumentRenderer` and the same
generated-document registry, so a report downloads through the route that
already serves generated documents.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

try:  # the notebook puts this directory on sys.path
    from document_generation import (
        DocumentTemplate, PdfDocumentRenderer, SectionResult, SectionSpec,
    )
    from project_analytics import (
        DEFAULT_PROGRESS_RULE, PROGRESS_RULES, build_statistics, insight_prompt,
        parse_insights, rule_based_summary,
    )
    from project_management import as_date
except ModuleNotFoundError:  # imported as backend.project_report
    from backend.document_generation import (
        DocumentTemplate, PdfDocumentRenderer, SectionResult, SectionSpec,
    )
    from backend.project_analytics import (
        DEFAULT_PROGRESS_RULE, PROGRESS_RULES, build_statistics, insight_prompt,
        parse_insights, rule_based_summary,
    )
    from backend.project_management import as_date


#: Every section a report can contain, with what it is for.
SECTIONS: dict[str, str] = {
    "summary": "Executive Summary",
    "phase": "Where the Project Stands",
    "progress": "Progress and Schedule",
    "cost": "Cost Position",
    "delivery": "Delivery Performance",
    "workload": "Work and People",
    "procurement": "Procurement",
    "risks": "Risks and Attention",
    "actions": "Recommended Actions",
    "closeout": "Closeout Position",
    "basis": "Basis of This Report",
}

#: Which sections suit which phase.  A planning report has no delivery
#: performance to report on; a closeout report leads with what is outstanding.
PHASE_SECTIONS: dict[str, tuple[str, ...]] = {
    "planning": ("summary", "phase", "cost", "workload", "risks", "actions", "basis"),
    "mobilisation": ("summary", "phase", "progress", "cost", "workload", "procurement",
                     "risks", "actions", "basis"),
    "execution": ("summary", "phase", "progress", "cost", "delivery", "workload",
                  "procurement", "risks", "actions", "basis"),
    "closeout": ("summary", "phase", "progress", "cost", "delivery", "closeout",
                 "procurement", "risks", "actions", "basis"),
    "complete": ("summary", "phase", "progress", "cost", "delivery", "closeout",
                 "workload", "basis"),
}

#: What each phase's report is called.
PHASE_TITLES: dict[str, str] = {
    "planning": "Project Baseline Report",
    "mobilisation": "Project Mobilisation Report",
    "execution": "Project Progress Report",
    "closeout": "Project Closeout Report",
    "complete": "Project Final Report",
}


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _money(value: Any, currency: str = "") -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    prefix = f"{currency} " if currency and currency != "USD" else "$"
    return f"{prefix}{amount:,.0f}"


def _percent(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _index(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def _table(section: SectionResult, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    section.table_columns = list(columns)
    section.table_rows = [list(row) for row in rows]


# ──────────────────────────────────────────────────────────────────────────
# The sections
#
# Each builder returns a SectionResult or None.  Returning None is how a section
# says it has nothing to report, and it is left out of the document entirely.
# ──────────────────────────────────────────────────────────────────────────

def _summary(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    section = SectionResult(key="summary", heading=SECTIONS["summary"])
    written = _text(insights.get("summary"))
    if written:
        section.paragraphs.append(written)
    headline = stats.get("headline") or []
    formatters = {"percent": _percent, "index": _index, "money": _money,
                  "number": lambda v: "—" if v is None else f"{float(v):g}",
                  "count": lambda v: "—" if v is None else f"{int(v)}"}
    _table(section, ["Measure", "Value"], [
        [row["label"], formatters.get(row.get("format"), str)(row.get("value"))]
        for row in headline
    ])
    for line in insights.get("highlights", [])[:4]:
        section.bullets.append(f"Going well: {line}")
    for line in insights.get("concerns", [])[:4]:
        section.bullets.append(f"Watch: {line}")
    if not insights.get("available"):
        section.warning = _text(insights.get("note")) or (
            "Written from the figures alone; no narrative was generated."
        )
    return section


def _phase(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    phase = stats.get("phase") or {}
    project = stats.get("project") or {}
    section = SectionResult(key="phase", heading=SECTIONS["phase"])
    section.paragraphs.append(
        f"{project.get('name') or 'This project'} is in {phase.get('label', 'progress').lower()} "
        f"(stage {phase.get('index')} of {phase.get('of')}). {phase.get('reason', '')}".strip()
    )
    _table(section, ["", ""], [
        ["Project", _text(project.get("name"))],
        ["Code", _text(project.get("code")) or "—"],
        ["Manager", _text(project.get("manager")) or "—"],
        ["Recorded status", _text(project.get("status")) or "—"],
        ["Planned window",
         f"{as_date(project.get('start_date')) or '—'} to {as_date(project.get('end_date')) or '—'}"],
        ["Report date", stats.get("as_of", "")],
    ])
    return section


def _progress(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    value = stats.get("value") or {}
    schedule = stats.get("schedule") or {}
    if not value.get("budget_at_completion"):
        return None
    section = SectionResult(key="progress", heading=SECTIONS["progress"])
    spi = value.get("schedule_performance_index")
    verdict = (
        "ahead of plan" if spi and spi > 1.05 else
        "in line with plan" if spi and spi >= 0.95 else
        "slightly behind plan" if spi and spi >= 0.85 else
        "behind plan" if spi else "not yet measurable against the plan"
    )
    section.paragraphs.append(
        f"{_percent(value.get('percent_complete'))} of planned value has been earned against "
        f"{_percent(value.get('percent_planned'))} planned by today, which puts delivery "
        f"{verdict}. Progress is credited by the {value.get('rule_label', 'fixed formula')} rule."
    )
    rows = [
        ["Budget at completion", _money(value.get("budget_at_completion"))],
        ["Planned value to date", _money(value.get("planned_value"))],
        ["Earned value to date", _money(value.get("earned_value"))],
        ["Schedule variance", _money(value.get("schedule_variance"))],
        ["Schedule performance index", _index(spi)],
        ["Planned finish", value.get("planned_finish") or "—"],
        ["Projected finish at this rate", value.get("projected_finish") or "—"],
    ]
    if value.get("days_late"):
        rows.append(["Projected slippage", f"{value['days_late']} days"])
    _table(section, ["Measure", "Value"], rows)

    if schedule.get("overdue_count"):
        section.bullets.append(
            f"{schedule['overdue_count']} task(s) are past their date; the oldest by "
            f"{schedule['overdue'][0]['days']} days."
        )
    if schedule.get("due_soon_count"):
        section.bullets.append(f"{schedule['due_soon_count']} task(s) fall due in the next two weeks.")
    if schedule.get("overruns_project_end"):
        section.bullets.append(
            f"Work is scheduled to {schedule['last_task_end']}, past the project's "
            f"{schedule['project_end']}."
        )
    if value.get("caveat"):
        section.warning = value["caveat"]
    elif value.get("unscheduled_tasks"):
        section.warning = (
            f"{value['unscheduled_tasks']} task(s) have no dates and are therefore "
            "absent from the planned-value curve."
        )
    return section


def _cost(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    cost = stats.get("cost") or {}
    if not cost.get("budget"):
        return None
    currency = cost.get("currency", "USD")
    section = SectionResult(key="cost", heading=SECTIONS["cost"])
    section.paragraphs.append(
        f"The budget stands at {_money(cost.get('budget'), currency)}, of which "
        f"{_money(cost.get('committed_procurement'), currency)} is committed through "
        f"procurement ({_percent(cost.get('committed_share'))} of budget)."
    )
    _table(section, ["Line", "Amount"], [
        ["Baseline", _money(cost.get("baseline"), currency)],
        ["Additional project costs", _money(cost.get("additional"), currency)],
        ["Task costs", _money(cost.get("tasks"), currency)],
        ["Total budget", _money(cost.get("budget"), currency)],
        ["Committed (procurement)", _money(cost.get("committed_procurement"), currency)],
        ["Uncommitted", _money(cost.get("remaining"), currency)],
    ])
    for row in (cost.get("by_trade") or [])[:6]:
        section.bullets.append(f"{row['label']}: {_money(row['value'], currency)}")
    if cost.get("unpriced_tasks"):
        section.bullets.append(
            f"{cost['unpriced_tasks']} task(s) carry no cost, so the figures above "
            "cover only the priced work."
        )
    section.warning = cost.get("index_note")
    return section


def _delivery(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    flow = stats.get("flow") or {}
    if not flow.get("completed"):
        return None
    section = SectionResult(key="delivery", heading=SECTIONS["delivery"])
    trend = {"rising": "rising", "falling": "falling", "flat": "steady"}.get(
        flow.get("throughput_trend"), "steady")
    section.paragraphs.append(
        f"The team is completing about {flow.get('throughput_per_week', 0)} task(s) a week and the "
        f"rate is {trend}. {flow.get('completed', 0)} of {flow.get('total', 0)} tasks are done."
    )
    rows = [
        ["Completed", f"{flow.get('completed', 0)} of {flow.get('total', 0)}"],
        ["Throughput", f"{flow.get('throughput_per_week', 0)} per week ({trend})"],
        ["Work in progress", str(flow.get("work_in_progress", 0))],
        ["Blocked", f"{flow.get('blocked', 0)} ({_percent(flow.get('blocked_share'))})"],
    ]
    if flow.get("cycle_time_days") is not None:
        rows.append(["Cycle time (median)", f"{flow['cycle_time_days']} days"])
        rows.append(["Cycle time (85th percentile)", f"{flow.get('cycle_time_p85')} days"])
    _table(section, ["Measure", "Value"], rows)
    for row in (flow.get("ageing_wip") or [])[:5]:
        who = f" ({row['assignee']})" if row.get("assignee") else ""
        section.bullets.append(f"\"{row['name']}\"{who} has been in progress {row['days']} days.")
    if flow.get("caveat"):
        section.warning = flow["caveat"]
    return section


def _workload(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    distributions = stats.get("distributions") or {}
    load = distributions.get("assignee_load") or []
    if not load:
        return None
    section = SectionResult(key="workload", heading=SECTIONS["workload"])
    section.paragraphs.append(
        "How the open work is spread, and where it has landed by trade."
    )
    _table(section, ["Person", "Open", "Done"],
           [[row["label"], str(row["open"]), str(row["done"])] for row in load[:12]])
    for row in (distributions.get("trade") or [])[:6]:
        section.bullets.append(f"{row['label']}: {row['value']} task(s)")
    if distributions.get("unassigned"):
        section.warning = (
            f"{distributions['unassigned']} open task(s) have nobody assigned."
        )
    return section


def _procurement(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    cost = stats.get("cost") or {}
    by_status = cost.get("procurement_by_status") or {}
    if not sum(by_status.values() or [0]):
        return None
    section = SectionResult(key="procurement", heading=SECTIONS["procurement"])
    section.paragraphs.append(
        f"{sum(by_status.values())} procurement line(s), "
        f"{_money(cost.get('committed_procurement'), cost.get('currency', 'USD'))} committed."
    )
    _table(section, ["Status", "Lines"],
           [[status, str(count)] for status, count in by_status.items()])
    return section


def _risks(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    risks = stats.get("risks") or []
    if not risks:
        section = SectionResult(key="risks", heading=SECTIONS["risks"])
        section.paragraphs.append("No rule-based risk flags were raised against this project.")
        return section
    section = SectionResult(key="risks", heading=SECTIONS["risks"])
    section.paragraphs.append(
        f"{len(risks)} item(s) were flagged from the figures. Each one names the measure "
        "that raised it."
    )
    _table(section, ["Severity", "Flag", "Detail"],
           [[row["severity"].title(), row["title"], row["detail"]] for row in risks[:15]])
    return section


def _actions(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    actions = insights.get("actions") or []
    if not actions:
        return None
    section = SectionResult(key="actions", heading=SECTIONS["actions"])
    section.paragraphs.append("Suggested next steps, each tied to the figure behind it.")
    _table(section, ["Action", "Why"],
           [[row.get("title", ""), row.get("why", "")] for row in actions[:8]])
    if _text(insights.get("outlook")):
        section.paragraphs.append(insights["outlook"])
    return section


def _closeout(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    schedule = stats.get("schedule") or {}
    flow = stats.get("flow") or {}
    section = SectionResult(key="closeout", heading=SECTIONS["closeout"])
    outstanding = schedule.get("open_count", 0)
    if outstanding:
        section.paragraphs.append(
            f"{outstanding} task(s) remain open, of which {schedule.get('overdue_count', 0)} "
            f"are already past their date and {flow.get('blocked', 0)} are blocked."
        )
        rows = [[row["name"], row["due"], f"{row['days']} days late", row.get("assignee") or "—"]
                for row in (schedule.get("overdue") or [])[:12]]
        if rows:
            _table(section, ["Task", "Due", "Overdue by", "Assignee"], rows)
    else:
        section.paragraphs.append("All tasks on this project are complete.")
    return section


def _basis(stats: Mapping[str, Any], insights: Mapping[str, Any]) -> SectionResult | None:
    value = stats.get("value") or {}
    cost = stats.get("cost") or {}
    section = SectionResult(key="basis", heading=SECTIONS["basis"])
    section.paragraphs.append(
        "So the figures can be checked rather than taken on trust, this is what they "
        "were computed from and what they do not cover."
    )
    section.bullets.extend([
        f"Figures are as at {stats.get('as_of')}, from this workspace's tasks, costs "
        "and procurement records.",
        f"Progress is credited by the {value.get('rule_label', 'fixed formula 50/50')} "
        "rule: a task earns half its value when it starts and the rest when it finishes.",
        "Planned value accrues evenly across each task's planned window.",
        _text(cost.get("index_note")),
    ])
    if value.get("unscheduled_tasks"):
        section.bullets.append(
            f"{value['unscheduled_tasks']} task(s) have no dates and are excluded from the "
            "planned-value curve, though their value is in the budget."
        )
    if not value.get("priced"):
        section.bullets.append(
            "No task carries a cost, so every task is weighted equally and the value "
            "figures are counts of work rather than money."
        )
    if not insights.get("available"):
        section.bullets.append(
            "The narrative in this report was written from the figures alone, without a "
            "language model."
        )
    section.bullets = [line for line in section.bullets if line]
    return section


#: Section key -> builder.
BUILDERS: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], SectionResult | None]] = {
    "summary": _summary, "phase": _phase, "progress": _progress, "cost": _cost,
    "delivery": _delivery, "workload": _workload, "procurement": _procurement,
    "risks": _risks, "actions": _actions, "closeout": _closeout, "basis": _basis,
}


def build_sections(stats: Mapping[str, Any], insights: Mapping[str, Any],
                   sections: Sequence[str] | None = None) -> list[SectionResult]:
    """The sections this report should contain, in order.

    Anything that would say nothing is dropped rather than printed empty.
    """
    phase = (stats.get("phase") or {}).get("key", "execution")
    wanted = list(sections) if sections else list(PHASE_SECTIONS.get(phase, PHASE_SECTIONS["execution"]))
    built = []
    for key in wanted:
        builder = BUILDERS.get(key)
        if not builder:
            continue
        section = builder(stats, insights)
        if section is not None:
            built.append(section)
    return built


def report_title(stats: Mapping[str, Any], override: str = "") -> str:
    if _text(override):
        return _text(override)
    phase = (stats.get("phase") or {}).get("key", "execution")
    name = _text((stats.get("project") or {}).get("name")) or "Project"
    return f"{name} - {PHASE_TITLES.get(phase, 'Project Report')}"


def report_template(stats: Mapping[str, Any], built: Sequence[SectionResult]) -> DocumentTemplate:
    """A template shaped to the sections that were actually built.

    The renderer takes a template so it can lay out a contents page; building it
    from the sections keeps the two from disagreeing.
    """
    phase = stats.get("phase") or {}
    return DocumentTemplate(
        kind="project_report",
        label=PHASE_TITLES.get(phase.get("key", "execution"), "Project Report"),
        description=(
            f"Status as at {stats.get('as_of')}, with the project in "
            f"{phase.get('label', 'progress').lower()}."
        ),
        sections=tuple(
            SectionSpec(section.key, section.heading, "", "") for section in built
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    title: str = ""
    instructions: str = ""
    rule: str = DEFAULT_PROGRESS_RULE
    sections: list[str] = Field(default_factory=list)
    #: Off skips the language model entirely and writes from the figures.
    narrative: bool = True


def register_project_report_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register the project report routes.

    The report is written into the account's generated-documents directory and
    registered in the same registry the document generator uses, so it lists and
    downloads through the routes that already exist.
    """
    required = ("app", "require_account")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Project report integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]
    registry = namespace.get("ACCOUNT_REGISTRY")
    renderer: PdfDocumentRenderer | None = None

    def get_renderer() -> PdfDocumentRenderer:
        # Built on first use: constructing it registers fonts, which is wasted
        # work in a deployment where no report is ever asked for.
        nonlocal renderer
        if renderer is None:
            renderer = PdfDocumentRenderer()
        return renderer

    def project_or_404(workspace: Any, project_id: str) -> dict[str, Any]:
        project = workspace.load_projects().get(project_id)
        if not project:
            raise HTTPException(404, detail="Project not found")
        return project

    def gather(context: Any, project_id: str, rule: str) -> dict[str, Any]:
        workspace = context.workspace
        project = project_or_404(workspace, project_id)
        members = []
        if registry is not None:
            people = {user["id"]: user for user in registry.users_for_account(context.account_id)}
            for entry in project.get("members", []) or []:
                user = people.get(entry.get("user_id") if isinstance(entry, dict) else entry)
                if user:
                    members.append(user)
        return build_statistics(
            project=project,
            tasks=workspace.load_tasks().get(project_id, []),
            procurement=workspace.load_procurement().get(project_id, []),
            members=members, rule=rule,
        )

    async def narrate(stats: Mapping[str, Any], instructions: str) -> dict[str, Any]:
        import asyncio

        generate = namespace.get("vl_generate")
        if not callable(generate):
            return rule_based_summary(stats)
        messages = [
            {"role": "system", "content": (
                "You are BuildMarshalAI's project analyst. You explain computed figures "
                "to the team running a construction project. You never state a number "
                "that was not given to you, and you never invent a cause."
            )},
            {"role": "user", "content": [{"type": "text",
                                          "text": insight_prompt(stats, instructions)}]},
        ]
        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(
                None, lambda: generate(messages, max_new_tokens=1800))
        except Exception as error:  # pragma: no cover - model transport
            return {**rule_based_summary(stats),
                    "note": f"Marshal could not be reached: {str(error)[:160]}"}
        insights = parse_insights(raw)
        return insights if insights.get("summary") else rule_based_summary(stats)

    # Reports share the generated-document register with document generation,
    # so a report downloads through the route that already serves those.
    def load_registry(workspace: Any) -> dict[str, Any]:
        return workspace.load_generated()

    def save_registry(workspace: Any, data: Mapping[str, Any]) -> None:
        workspace.save_generated(data)

    @app.get("/api/projects/{project_id}/report/preview")
    async def preview_report(project_id: str, rule: str = DEFAULT_PROGRESS_RULE,
                             context=Depends(require_account)) -> dict[str, Any]:
        """What the report would contain, without writing a PDF or calling a model."""
        if rule not in PROGRESS_RULES:
            raise HTTPException(422, detail=f"Progress rule must be one of: {', '.join(PROGRESS_RULES)}")
        stats = gather(context, project_id, rule)
        insights = rule_based_summary(stats)
        built = build_sections(stats, insights)
        phase = stats.get("phase") or {}
        return {
            "title": report_title(stats),
            "phase": phase,
            "as_of": stats.get("as_of"),
            "sections": [{"key": section.key, "heading": section.heading}
                         for section in built],
            "available_sections": [{"key": key, "heading": heading}
                                   for key, heading in SECTIONS.items()],
            "headline": stats.get("headline"),
        }

    @app.post("/api/projects/{project_id}/report", status_code=201)
    async def generate_report(project_id: str, body: ReportRequest,
                              context=Depends(require_account)) -> dict[str, Any]:
        """Write the report for wherever this project has got to."""
        if body.rule not in PROGRESS_RULES:
            raise HTTPException(422, detail=f"Progress rule must be one of: {', '.join(PROGRESS_RULES)}")
        unknown = set(body.sections) - set(SECTIONS)
        if unknown:
            raise HTTPException(422, detail=f"Unknown section(s): {', '.join(sorted(unknown))}")

        workspace = context.workspace
        project = project_or_404(workspace, project_id)
        stats = gather(context, project_id, body.rule)
        insights = (await narrate(stats, body.instructions) if body.narrative
                    else rule_based_summary(stats))
        built = build_sections(stats, insights, body.sections or None)
        if not built:
            raise HTTPException(422, detail="There is nothing to report on this project yet")

        title = report_title(stats, body.title)
        generated_id = uuid.uuid4().hex[:12]
        stamp = datetime.now(timezone.utc)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("_")[:80] or "project-report"
        output = Path(workspace.generated_dir) / f"{safe}-{generated_id}.pdf"
        get_renderer().render(
            output_path=output, title=title,
            template=report_template(stats, built), project=project,
            sections=built, generated_at=stamp.strftime("%d %B %Y, %H:%M UTC"),
            # This report is grounded in the workspace's own records, not in
            # source PDFs, and the cover should not claim otherwise.
            evidence_policy=(
                "Computed from this workspace's task, cost and procurement records "
                f"as at {stats.get('as_of')}. See Basis of This Report."
            ),
            footer_note="BuildMarshalAI - project report from workspace records",
        )

        record = {
            "id": generated_id, "project_id": project_id, "doc_kind": "project_report",
            "title": title, "file_path": str(output),
            "generated_at": stamp.isoformat(),
            "phase": (stats.get("phase") or {}).get("key"),
            "phase_label": (stats.get("phase") or {}).get("label"),
            "as_of": stats.get("as_of"),
            "sections": [section.key for section in built],
            "narrative": bool(insights.get("available")),
            "size_bytes": output.stat().st_size if output.exists() else 0,
        }
        data = load_registry(workspace)
        data[generated_id] = record
        save_registry(workspace, data)
        return {**{key: value for key, value in record.items() if key != "file_path"},
                "download_url": f"/api/generated-documents/{generated_id}/download",
                "headline": stats.get("headline"),
                "insights": insights}

    @app.get("/api/projects/{project_id}/reports")
    async def list_reports(project_id: str, context=Depends(require_account)) -> dict[str, Any]:
        """Every report written for this project, newest first."""
        rows = [
            {key: value for key, value in record.items() if key != "file_path"}
            for record in load_registry(context.workspace).values()
            if record.get("project_id") == project_id
            and record.get("doc_kind") == "project_report"
        ]
        rows.sort(key=lambda row: str(row.get("generated_at", "")), reverse=True)
        return {"reports": rows, "total": len(rows)}

    return {"sections": list(SECTIONS), "phases": list(PHASE_SECTIONS)}


__all__ = [
    "BUILDERS", "PHASE_SECTIONS", "PHASE_TITLES", "SECTIONS", "ReportRequest",
    "build_sections", "register_project_report_routes", "report_template",
    "report_title",
]
