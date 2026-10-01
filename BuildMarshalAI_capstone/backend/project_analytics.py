"""Project statistics: where a project actually is, in numbers.

Everything here is computed from records the application already keeps -- tasks
and their statuses and dates, the cost breakdown, procurement lines, the people
on the project -- so the figures on the Statistics tab, in a generated report,
and in anything the assistant says are the same figures.

The measures are the ones construction and delivery teams actually use:

* **Earned value** (PMI's method): planned value, earned value, schedule
  variance and SPI, projected finish.  Progress is credited by the *fixed
  formula 50/50* rule, which is a named EVM technique rather than a guess: a
  task earns half its value when it starts and the rest when it finishes.
  :data:`PROGRESS_RULES` holds the alternatives.
* **Cost**: budget against what is actually committed.  Procurement lines are a
  real commitment; task costs are a budget.  The two are reported separately
  rather than blended.
* **Flow**: throughput, cycle time, work in progress, and ageing WIP -- the
  measures that tell you whether delivery is steady or stalling.
* **Schedule health**: overdue, due soon, unscheduled, and the longest open
  chain of work.

One rule runs through all of it: **a number the records cannot support is not
reported.**  The app keeps budgets, not an actuals ledger, so there is no cost
performance index here; :func:`cost_performance` says why instead of inventing
one.  A metric with too little data to mean anything comes back with
``confident: False`` and the reason.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from fastapi import Depends, HTTPException
from pydantic import BaseModel

try:  # the notebook puts this directory on sys.path
    from project_management import as_date, cost_breakdown, procurement_summary
    from tasks import TASK_PRIORITIES, TASK_STATUSES
except ModuleNotFoundError:  # imported as backend.project_analytics
    from backend.project_management import as_date, cost_breakdown, procurement_summary
    from backend.tasks import TASK_PRIORITIES, TASK_STATUSES


#: How much of a task's value is earned in each state.
#:
#: "fixed_50_50" is the default because it is the technique most construction
#: programmes actually run, and because it needs nothing the app does not
#: already record.  A blocked task has started, so it keeps what starting
#: earned it -- being blocked is a schedule problem, not a reason to un-earn
#: work that was done.
PROGRESS_RULES: dict[str, dict[str, float]] = {
    "fixed_50_50": {"Open": 0.0, "In Progress": 0.5, "Blocked": 0.5, "Completed": 1.0},
    "fixed_0_100": {"Open": 0.0, "In Progress": 0.0, "Blocked": 0.0, "Completed": 1.0},
    "fixed_25_75": {"Open": 0.0, "In Progress": 0.25, "Blocked": 0.25, "Completed": 1.0},
}

DEFAULT_PROGRESS_RULE = "fixed_50_50"

#: Statuses that mean the work is finished.
DONE_STATUSES = ("Completed",)

#: Phases a project moves through, and the share of value earned that puts it
#: in each one.  Dates move it too: see :func:`project_phase`.
PHASES: tuple[tuple[str, str], ...] = (
    ("planning", "Planning"),
    ("mobilisation", "Mobilisation"),
    ("execution", "Execution"),
    ("closeout", "Closeout"),
    ("complete", "Complete"),
)

#: A metric needs at least this many finished tasks before its average means
#: anything.  Below it the figure is still returned, marked not confident.
MIN_SAMPLE = 3

#: Ageing work in progress past this many days is called out.
STALE_WIP_DAYS = 14

#: A blocked task older than this is a risk, not a status.
STALE_BLOCK_DAYS = 7


# ──────────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────────

def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _as_day(value: Any) -> date | None:
    """A date object from whatever the record stored, or None."""
    settled = as_date(value)
    if not settled:
        return None
    try:
        return date.fromisoformat(settled)
    except ValueError:
        return None


def _stamp_day(value: Any) -> date | None:
    """The day part of a created_at/updated_at timestamp."""
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return _as_day(text)


def _span(task: Mapping[str, Any]) -> tuple[date | None, date | None]:
    """A task's planned window: start and finish, whichever it recorded.

    A task with only a due date is treated as finishing then and starting then,
    which is what a milestone is.
    """
    start = _as_day(task.get("start_time"))
    end = _as_day(task.get("end_time")) or _as_day(task.get("due_date"))
    if start and end and end < start:
        start, end = end, start
    if end and not start:
        start = end
    return start, end


def _round(value: float, places: int = 2) -> float:
    if value != value or value in (float("inf"), float("-inf")):
        return 0.0
    return round(value, places)


def _ratio(numerator: float, denominator: float) -> float | None:
    """A ratio, or None when the denominator makes it meaningless."""
    if not denominator:
        return None
    return _round(numerator / denominator, 3)


def _active(tasks: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Tasks that count: archived ones are kept for the record, not the maths."""
    return [dict(task) for task in tasks if not task.get("archived")]


# ──────────────────────────────────────────────────────────────────────────
# Value and progress
# ──────────────────────────────────────────────────────────────────────────

def task_value(task: Mapping[str, Any], fallback: float) -> float:
    """What a task is worth for weighting purposes.

    A priced task is weighted by its price.  An unpriced one is weighted by the
    average price of the priced ones, so a programme that only prices some of
    its work is not reported as though the rest did not exist.
    """
    cost = float(task.get("cost") or 0)
    return cost if cost > 0 else fallback


def progress_of(task: Mapping[str, Any], rule: str = DEFAULT_PROGRESS_RULE) -> float:
    credits = PROGRESS_RULES.get(rule, PROGRESS_RULES[DEFAULT_PROGRESS_RULE])
    return credits.get(_text(task.get("status")), 0.0)


def _fallback_value(tasks: Sequence[Mapping[str, Any]]) -> float:
    priced = [float(task.get("cost") or 0) for task in tasks if float(task.get("cost") or 0) > 0]
    if priced:
        return _round(sum(priced) / len(priced))
    # Nothing is priced, so every task is worth the same: count becomes the
    # unit, which is the honest reading of "we track work, not money".
    return 1.0


def planned_value_on(tasks: Sequence[Mapping[str, Any]], day: date, fallback: float) -> float:
    """Value the plan says should have been earned by ``day``.

    A task's value accrues evenly across its planned window, which is the
    standard linear assumption when a programme has no resource curve.
    """
    total = 0.0
    for task in tasks:
        start, end = _span(task)
        value = task_value(task, fallback)
        if not end:
            continue  # unscheduled work is in no plan, so it plans no value
        if day >= end:
            total += value
        elif start and day > start:
            window = (end - start).days or 1
            total += value * ((day - start).days / window)
    return _round(total)


def earned_value(tasks: Sequence[Mapping[str, Any]], fallback: float,
                 rule: str = DEFAULT_PROGRESS_RULE) -> float:
    return _round(sum(task_value(task, fallback) * progress_of(task, rule) for task in tasks))


def earned_value_metrics(tasks: Sequence[Mapping[str, Any]], *, project: Mapping[str, Any],
                         today: date | None = None,
                         rule: str = DEFAULT_PROGRESS_RULE) -> dict[str, Any]:
    """Planned versus earned value, and what that says about the finish date.

    Returns the figures an EVM report expects -- PV, EV, SV, SPI -- plus a
    projected finish derived from the index.  Where the records cannot support
    a figure it is ``None`` with a reason, never a filled-in guess.
    """
    today = today or _today()
    tasks = _active(tasks)
    fallback = _fallback_value(tasks)
    budget = _round(sum(task_value(task, fallback) for task in tasks))
    planned = planned_value_on(tasks, today, fallback)
    earned = earned_value(tasks, fallback, rule)
    scheduled = [task for task in tasks if _span(task)[1]]

    spi = _ratio(earned, planned)
    end = _as_day(project.get("end_date"))
    start = _as_day(project.get("start_date"))

    projected_finish = None
    if spi and spi > 0 and start and end and end > start:
        # The programme's own duration, stretched by how far behind it is.
        duration = (end - start).days
        projected_finish = (start + timedelta(days=round(duration / spi))).isoformat()

    return {
        "rule": rule,
        "rule_label": "fixed formula 50/50" if rule == "fixed_50_50" else rule.replace("_", " "),
        "budget_at_completion": budget,
        "planned_value": planned,
        "earned_value": earned,
        "schedule_variance": _round(earned - planned),
        "schedule_performance_index": spi,
        "percent_complete": _ratio(earned, budget),
        "percent_planned": _ratio(planned, budget),
        "projected_finish": projected_finish,
        "planned_finish": end.isoformat() if end else None,
        "days_late": (
            (date.fromisoformat(projected_finish) - end).days
            if projected_finish and end else None
        ),
        "unscheduled_tasks": len(tasks) - len(scheduled),
        "priced": any(float(task.get("cost") or 0) > 0 for task in tasks),
        "confident": len(scheduled) >= MIN_SAMPLE,
        "caveat": (
            "" if len(scheduled) >= MIN_SAMPLE
            else "Too few scheduled tasks for the schedule index to mean much."
        ),
    }


def value_curve(tasks: Sequence[Mapping[str, Any]], *, project: Mapping[str, Any],
                today: date | None = None, points: int = 24,
                rule: str = DEFAULT_PROGRESS_RULE) -> dict[str, Any]:
    """The S-curve: planned value over the programme, against value earned to date.

    Earned value is only plotted up to today -- drawing it into the future would
    be a forecast dressed as a measurement.
    """
    today = today or _today()
    tasks = _active(tasks)
    fallback = _fallback_value(tasks)
    bounds = [day for task in tasks for day in _span(task) if day]
    bounds += [day for day in (_as_day(project.get("start_date")), _as_day(project.get("end_date"))) if day]
    if not bounds:
        return {"points": [], "start": None, "end": None, "today": today.isoformat()}

    start, end = min(bounds), max(bounds)
    if end <= start:
        end = start + timedelta(days=1)
    step = max(1, (end - start).days // max(1, points - 1))

    earned_now = earned_value(tasks, fallback, rule)
    days: list[date] = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=step)
    if days[-1] != end:
        days.append(end)
    if start <= today <= end and today not in days:
        days.append(today)
        days.sort()

    rows = []
    for day in days:
        row = {"date": day.isoformat(), "planned": planned_value_on(tasks, day, fallback)}
        if day <= today:
            # Earned value is only known now; the curve to date is the share of
            # today's earned value the plan expected by then, which is the
            # closest honest reconstruction without a progress history.
            row["earned"] = _round(earned_now * _share_earned_by(tasks, day, today, fallback, rule))
        rows.append(row)
    return {
        "points": rows, "start": start.isoformat(), "end": end.isoformat(),
        "today": today.isoformat(),
        "budget_at_completion": _round(sum(task_value(task, fallback) for task in tasks)),
    }


def _share_earned_by(tasks: Sequence[Mapping[str, Any]], day: date, today: date,
                     fallback: float, rule: str) -> float:
    """How much of today's earned value had been earned by ``day``.

    Uses each finished task's own finish date where it has one, so the curve
    reflects when work actually landed rather than assuming it all landed at
    once.
    """
    if day >= today:
        return 1.0
    total = earned_value(tasks, fallback, rule)
    if not total:
        return 0.0
    so_far = 0.0
    for task in tasks:
        credit = task_value(task, fallback) * progress_of(task, rule)
        if not credit:
            continue
        start, finish = _span(task)
        if _text(task.get("status")) in DONE_STATUSES:
            # Finished work is credited on the day it finished.
            if finish and finish <= day:
                so_far += credit
        elif start and start <= day:
            # Work in progress earned its share when it started.
            so_far += credit
    return _round(min(1.0, so_far / total), 4)


# ──────────────────────────────────────────────────────────────────────────
# Cost
# ──────────────────────────────────────────────────────────────────────────

def cost_performance(project: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]],
                     procurement: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Budget against what has actually been committed.

    There is deliberately no cost performance index.  CPI is earned value over
    *actual cost*, and this application records budgets and commitments, not an
    actuals ledger -- a CPI computed from budgets would always read 1.00 and
    mean nothing.  What can be said honestly is said: what was budgeted, what is
    committed against it, and where the commitment is concentrated.
    """
    breakdown = cost_breakdown(project, tasks)
    ordered = procurement_summary(list(procurement))
    committed = _round(ordered["total"])
    budget = _round(breakdown["total"])

    by_trade: dict[str, float] = defaultdict(float)
    for task in _active(tasks):
        cost = float(task.get("cost") or 0)
        if cost:
            by_trade[_text(task.get("trade")) or "Unassigned trade"] += cost

    return {
        "currency": breakdown.get("currency", "USD"),
        "baseline": breakdown["baseline_cost"],
        "additional": breakdown["additional_total"],
        "tasks": breakdown["tasks_total"],
        "budget": budget,
        "committed_procurement": committed,
        "procurement_by_status": ordered["by_status"],
        "remaining": _round(budget - committed),
        "committed_share": _ratio(committed, budget),
        "by_trade": [
            {"label": label, "value": _round(value)}
            for label, value in sorted(by_trade.items(), key=lambda row: -row[1])
        ],
        "priced_tasks": breakdown["task_cost_count"],
        "unpriced_tasks": sum(1 for task in _active(tasks) if not float(task.get("cost") or 0)),
        "cost_performance_index": None,
        "index_note": (
            "A cost performance index needs recorded actual spend. This workspace "
            "holds budgets and procurement commitments, so committed-against-budget "
            "is reported instead."
        ),
    }


# ──────────────────────────────────────────────────────────────────────────
# Flow
# ──────────────────────────────────────────────────────────────────────────

def flow_metrics(tasks: Sequence[Mapping[str, Any]], *, today: date | None = None,
                 weeks: int = 8) -> dict[str, Any]:
    """Throughput, cycle time, work in progress, and what is ageing.

    The measures a delivery team reads weekly: are we finishing work at a steady
    rate, how long does a task take once started, and how much is open at once.
    """
    today = today or _today()
    tasks = _active(tasks)
    done = [task for task in tasks if _text(task.get("status")) in DONE_STATUSES]
    in_progress = [task for task in tasks if _text(task.get("status")) == "In Progress"]
    blocked = [task for task in tasks if _text(task.get("status")) == "Blocked"]

    # Throughput per week, from when each finished task was last touched.
    finished_on = [
        _span(task)[1] or _stamp_day(task.get("updated_at"))
        for task in done
    ]
    finished_on = [day for day in finished_on if day]
    buckets: list[dict[str, Any]] = []
    for index in range(weeks - 1, -1, -1):
        week_end = today - timedelta(days=7 * index)
        week_start = week_end - timedelta(days=6)
        buckets.append({
            "week_ending": week_end.isoformat(),
            "completed": sum(1 for day in finished_on if week_start <= day <= week_end),
        })
    recent = [row["completed"] for row in buckets]

    cycle_times = []
    for task in done:
        start, end = _span(task)
        if start and end and end >= start:
            cycle_times.append((end - start).days + 1)

    ageing = []
    for task in in_progress:
        start, _ = _span(task)
        started = start or _stamp_day(task.get("created_at"))
        if started and (today - started).days >= STALE_WIP_DAYS:
            ageing.append({
                "id": task.get("id"), "name": _text(task.get("name")),
                "days": (today - started).days, "assignee": _text(task.get("assignee")),
            })
    ageing.sort(key=lambda row: -row["days"])

    return {
        "throughput": buckets,
        "throughput_per_week": _round(statistics.mean(recent), 2) if recent else 0.0,
        "throughput_trend": _trend(recent),
        "cycle_time_days": _round(statistics.median(cycle_times), 1) if cycle_times else None,
        "cycle_time_p85": (
            _round(sorted(cycle_times)[max(0, math.ceil(0.85 * len(cycle_times)) - 1)], 1)
            if cycle_times else None
        ),
        "cycle_time_samples": len(cycle_times),
        "work_in_progress": len(in_progress),
        "blocked": len(blocked),
        "blocked_share": _ratio(len(blocked), len(tasks)),
        "ageing_wip": ageing[:10],
        "completed": len(done),
        "total": len(tasks),
        "confident": len(cycle_times) >= MIN_SAMPLE,
        "caveat": (
            "" if len(cycle_times) >= MIN_SAMPLE
            else "Cycle time needs a few finished tasks with both a start and an end date."
        ),
    }


def _trend(values: Sequence[float]) -> str:
    """Whether the recent half is running above or below the earlier half."""
    if len(values) < 4 or not any(values):
        return "flat"
    half = len(values) // 2
    earlier, later = values[:half], values[half:]
    before = statistics.mean(earlier) if earlier else 0.0
    after = statistics.mean(later) if later else 0.0
    if before == after:
        return "flat"
    change = (after - before) / (before or 1)
    if change > 0.15:
        return "rising"
    if change < -0.15:
        return "falling"
    return "flat"


# ──────────────────────────────────────────────────────────────────────────
# Schedule health and distributions
# ──────────────────────────────────────────────────────────────────────────

def schedule_health(tasks: Sequence[Mapping[str, Any]], *, project: Mapping[str, Any],
                    today: date | None = None) -> dict[str, Any]:
    today = today or _today()
    tasks = _active(tasks)
    open_tasks = [task for task in tasks if _text(task.get("status")) not in DONE_STATUSES]

    overdue, due_soon, unscheduled = [], [], []
    for task in open_tasks:
        _, end = _span(task)
        if not end:
            unscheduled.append(task)
        elif end < today:
            overdue.append({"id": task.get("id"), "name": _text(task.get("name")),
                            "due": end.isoformat(), "days": (today - end).days,
                            "assignee": _text(task.get("assignee")),
                            "priority": _text(task.get("priority"))})
        elif (end - today).days <= 14:
            due_soon.append({"id": task.get("id"), "name": _text(task.get("name")),
                             "due": end.isoformat(), "days": (end - today).days,
                             "assignee": _text(task.get("assignee"))})
    overdue.sort(key=lambda row: -row["days"])
    due_soon.sort(key=lambda row: row["days"])

    project_end = _as_day(project.get("end_date"))
    latest = max((end for _, end in (_span(task) for task in tasks) if end), default=None)
    return {
        "overdue": overdue[:20], "overdue_count": len(overdue),
        "due_soon": due_soon[:20], "due_soon_count": len(due_soon),
        "unscheduled_count": len(unscheduled),
        "open_count": len(open_tasks),
        "project_end": project_end.isoformat() if project_end else None,
        "last_task_end": latest.isoformat() if latest else None,
        # Work planned past the project's own end date is a programme problem
        # whoever set the end date will want to know about.
        "overruns_project_end": bool(project_end and latest and latest > project_end),
        "days_to_project_end": (project_end - today).days if project_end else None,
    }


def distributions(tasks: Sequence[Mapping[str, Any]],
                  members: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The counts the charts draw: status, priority, trade, and who is loaded."""
    tasks = _active(tasks)
    status = Counter(_text(task.get("status")) or "Open" for task in tasks)
    priority = Counter(_text(task.get("priority")) or "Normal" for task in tasks)
    trade = Counter(_text(task.get("trade")) or "Unassigned" for task in tasks)

    load: dict[str, dict[str, int]] = defaultdict(lambda: {"open": 0, "done": 0})
    for task in tasks:
        who = _text(task.get("assignee")) or "Unassigned"
        bucket = "done" if _text(task.get("status")) in DONE_STATUSES else "open"
        load[who][bucket] += 1

    known = {_text(member.get("name")) for member in members}
    return {
        "status": [{"label": name, "value": status.get(name, 0)} for name in TASK_STATUSES],
        "priority": [{"label": name, "value": priority.get(name, 0)} for name in TASK_PRIORITIES],
        "trade": [{"label": label, "value": count}
                  for label, count in trade.most_common(8)],
        "assignee_load": sorted(
            [{"label": who, "open": counts["open"], "done": counts["done"],
              "on_project": who in known}
             for who, counts in load.items()],
            key=lambda row: -(row["open"] + row["done"]),
        )[:12],
        "unassigned": load.get("Unassigned", {"open": 0, "done": 0})["open"],
    }


# ──────────────────────────────────────────────────────────────────────────
# Phase
# ──────────────────────────────────────────────────────────────────────────

def project_phase(project: Mapping[str, Any], value: Mapping[str, Any],
                  health: Mapping[str, Any], today: date | None = None) -> dict[str, Any]:
    """Where in its life the project is, so a report can suit the moment.

    Status wins when it is decisive -- a project someone marked Completed is
    complete -- and otherwise progress and dates decide.
    """
    today = today or _today()
    status = _text(project.get("status"))
    complete = value.get("percent_complete")
    start = _as_day(project.get("start_date"))

    if status in ("Completed", "Cancelled"):
        key = "complete"
    elif complete is None or complete <= 0:
        key = "planning" if not start or start > today else "mobilisation"
    elif complete >= 0.995:
        key = "complete"
    elif complete >= 0.85:
        key = "closeout"
    elif complete < 0.15 and (not start or start > today):
        key = "planning"
    elif complete < 0.15:
        key = "mobilisation"
    else:
        key = "execution"

    label = dict(PHASES)[key]
    return {
        "key": key, "label": label,
        "index": [name for name, _ in PHASES].index(key) + 1,
        "of": len(PHASES),
        "percent_complete": complete,
        "status": status,
        "reason": _phase_reason(key, complete, status, health),
    }


def _phase_reason(key: str, complete: float | None, status: str,
                  health: Mapping[str, Any]) -> str:
    if key == "complete" and status in ("Completed", "Cancelled"):
        return f"The project is marked {status.lower()}."
    share = f"{round((complete or 0) * 100)}% of planned value earned"
    if key == "planning":
        return f"Nothing has started yet ({share})."
    if key == "mobilisation":
        return f"Work has just begun ({share})."
    if key == "closeout":
        return f"Most of the work is done ({share}); {health.get('open_count', 0)} task(s) remain."
    if key == "complete":
        return f"All planned work is earned ({share})."
    return f"Delivery is under way ({share})."


# ──────────────────────────────────────────────────────────────────────────
# Risks, from rules
# ──────────────────────────────────────────────────────────────────────────

def risk_flags(*, project: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]],
               value: Mapping[str, Any], cost: Mapping[str, Any],
               flow: Mapping[str, Any], health: Mapping[str, Any],
               procurement: Sequence[Mapping[str, Any]] = (),
               today: date | None = None) -> list[dict[str, Any]]:
    """Things worth someone's attention, found by rule rather than by model.

    Deterministic, explainable, and each one carries the number that raised it
    so nobody has to take it on trust.  The assistant writes prose *about* these;
    it does not decide them.
    """
    today = today or _today()
    tasks = _active(tasks)
    flags: list[dict[str, Any]] = []

    def flag(severity: str, key: str, title: str, detail: str, **extra: Any) -> None:
        flags.append({"severity": severity, "key": key, "title": title,
                      "detail": detail, **extra})

    spi = value.get("schedule_performance_index")
    if spi is not None and value.get("confident"):
        if spi < 0.85:
            flag("high", "schedule_slip", "The programme is behind plan",
                 f"Schedule index {spi:.2f} — about "
                 f"{round((1 - spi) * 100)}% less value earned than planned by today."
                 + (f" On this rate it finishes around {value['projected_finish']}."
                    if value.get("projected_finish") else ""),
                 metric=spi)
        elif spi < 0.95:
            flag("medium", "schedule_drift", "The programme is drifting",
                 f"Schedule index {spi:.2f}; a little behind plan.", metric=spi)

    if health.get("overdue_count"):
        worst = health["overdue"][0]
        flag("high" if health["overdue_count"] > 5 else "medium", "overdue",
             f"{health['overdue_count']} task(s) are past their date",
             f"The oldest is \"{worst['name']}\", {worst['days']} day(s) overdue.",
             metric=health["overdue_count"])

    if flow.get("blocked"):
        flag("high" if (flow.get("blocked_share") or 0) > 0.15 else "medium", "blocked",
             f"{flow['blocked']} task(s) are blocked",
             f"That is {round((flow.get('blocked_share') or 0) * 100)}% of the work on this project.",
             metric=flow["blocked"])

    if flow.get("ageing_wip"):
        oldest = flow["ageing_wip"][0]
        flag("medium", "ageing_wip",
             f"{len(flow['ageing_wip'])} task(s) have been in progress a long time",
             f"\"{oldest['name']}\" has been open {oldest['days']} days.",
             metric=len(flow["ageing_wip"]))

    if flow.get("throughput_trend") == "falling":
        flag("medium", "throughput_falling", "Delivery is slowing",
             f"Completions are down against the previous weeks "
             f"(now about {flow.get('throughput_per_week', 0)} per week).")

    if health.get("overruns_project_end"):
        flag("high", "overrun", "Work is planned past the project end date",
             f"The last task ends {health['last_task_end']}, after the project's "
             f"{health['project_end']}.")

    if health.get("unscheduled_count"):
        flag("low", "unscheduled",
             f"{health['unscheduled_count']} open task(s) have no dates",
             "Unscheduled work is invisible to the programme and to the schedule index.",
             metric=health["unscheduled_count"])

    share = cost.get("committed_share")
    if share is not None and share > 1.0:
        flag("high", "over_budget", "Committed cost is over budget",
             f"{cost['committed_procurement']:,.0f} committed against a "
             f"{cost['budget']:,.0f} budget.", metric=share)
    elif share is not None and share > 0.9 and (value.get("percent_complete") or 0) < 0.75:
        flag("medium", "burn_rate", "Cost is running ahead of progress",
             f"{round(share * 100)}% of budget is committed with "
             f"{round((value.get('percent_complete') or 0) * 100)}% of value earned.",
             metric=share)

    if cost.get("unpriced_tasks") and cost.get("priced_tasks"):
        flag("low", "unpriced", f"{cost['unpriced_tasks']} task(s) have no cost",
             "The cost picture covers only part of the work.",
             metric=cost["unpriced_tasks"])

    late_orders = [
        item for item in procurement
        if _text(item.get("status")) in ("Requested", "Quoted")
        and _as_day(item.get("needed_by")) and _as_day(item.get("needed_by")) <= today + timedelta(days=30)
    ]
    if late_orders:
        flag("high", "procurement", f"{len(late_orders)} item(s) are needed soon but not ordered",
             f"Including \"{_text(late_orders[0].get('name'))}\", needed "
             f"{as_date(late_orders[0].get('needed_by'))}.", metric=len(late_orders))

    unassigned = sum(1 for task in tasks
                     if not _text(task.get("assignee"))
                     and _text(task.get("status")) not in DONE_STATUSES)
    if unassigned:
        flag("low", "unassigned", f"{unassigned} open task(s) have nobody on them",
             "Unowned work tends to be the work that slips.", metric=unassigned)

    order = {"high": 0, "medium": 1, "low": 2}
    flags.sort(key=lambda row: order.get(row["severity"], 3))
    return flags


# ──────────────────────────────────────────────────────────────────────────
# The whole picture
# ──────────────────────────────────────────────────────────────────────────

def build_statistics(*, project: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]],
                     procurement: Sequence[Mapping[str, Any]] = (),
                     members: Sequence[Mapping[str, Any]] = (),
                     today: date | None = None,
                     rule: str = DEFAULT_PROGRESS_RULE) -> dict[str, Any]:
    """Everything the Statistics tab and a report need, in one pass."""
    today = today or _today()
    if rule not in PROGRESS_RULES:
        raise HTTPException(422, detail=f"Progress rule must be one of: {', '.join(PROGRESS_RULES)}")

    value = earned_value_metrics(tasks, project=project, today=today, rule=rule)
    cost = cost_performance(project, tasks, procurement)
    flow = flow_metrics(tasks, today=today)
    health = schedule_health(tasks, project=project, today=today)
    phase = project_phase(project, value, health, today)
    return {
        "project": {
            "id": project.get("id"), "name": _text(project.get("name")),
            "code": _text(project.get("project_code")), "status": _text(project.get("status")),
            "manager": _text(project.get("manager")),
            "start_date": as_date(project.get("start_date")),
            "end_date": as_date(project.get("end_date")),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": today.isoformat(),
        "phase": phase,
        "value": value,
        "cost": cost,
        "flow": flow,
        "schedule": health,
        "distributions": distributions(tasks, members),
        "curve": value_curve(tasks, project=project, today=today, rule=rule),
        "risks": risk_flags(project=project, tasks=tasks, value=value, cost=cost,
                            flow=flow, health=health, procurement=procurement, today=today),
        "rules": list(PROGRESS_RULES),
        "headline": headline_numbers(value, cost, flow, health),
    }


def headline_numbers(value: Mapping[str, Any], cost: Mapping[str, Any],
                     flow: Mapping[str, Any], health: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The six figures worth putting at the top of a page or a report."""
    spi = value.get("schedule_performance_index")
    return [
        {"key": "complete", "label": "Value earned",
         "value": value.get("percent_complete"), "format": "percent",
         "tone": "muted"},
        {"key": "spi", "label": "Schedule index", "value": spi, "format": "index",
         "tone": "good" if spi and spi >= 0.95 else "warn" if spi and spi >= 0.85 else "bad" if spi else "muted",
         "note": value.get("caveat")},
        {"key": "budget", "label": "Budget", "value": cost.get("budget"), "format": "money"},
        {"key": "committed", "label": "Committed", "value": cost.get("committed_procurement"),
         "format": "money",
         "tone": "bad" if (cost.get("committed_share") or 0) > 1 else "good"},
        {"key": "throughput", "label": "Tasks per week",
         "value": flow.get("throughput_per_week"), "format": "number",
         "tone": {"rising": "good", "falling": "bad"}.get(flow.get("throughput_trend"), "muted"),
         "note": flow.get("throughput_trend")},
        {"key": "overdue", "label": "Overdue", "value": health.get("overdue_count"),
         "format": "count", "tone": "bad" if health.get("overdue_count") else "good"},
    ]


# ──────────────────────────────────────────────────────────────────────────
# What the assistant is allowed to add
# ──────────────────────────────────────────────────────────────────────────

_INSIGHT_RULES = """You are writing the commentary on a construction project's
statistics for the people running it.

You are given the figures and the flags the system already computed. Your job is
to explain them, not to add to them.

Rules:
- Use ONLY the numbers given. Never state a figure that is not in the data.
- Never invent a cause. If the data does not say why something slipped, say what
  would show why ("the blocked tasks have no reason recorded").
- Say what you cannot tell from this data when it matters to the reading.
- Address the reader as the team running the project. Plain words, no jargon
  beyond the named indices, no filler, no motivational language.

Return ONE JSON object:
{
  "summary": "two or three sentences on where the project stands",
  "highlights": ["something going well, with its number"],
  "concerns": ["something to watch, with its number"],
  "actions": [{"title": "what to do", "why": "which number says so"}],
  "outlook": "one sentence on what the trend implies, or what is unknowable"
}
Return JSON only, with no commentary and no code fence."""


def insight_prompt(statistics: Mapping[str, Any], instructions: str = "") -> str:
    """The prompt behind the narrative, carrying the computed figures verbatim."""
    slim = {
        "project": statistics.get("project"),
        "as_of": statistics.get("as_of"),
        "phase": statistics.get("phase"),
        "value": statistics.get("value"),
        "cost": {key: value for key, value in (statistics.get("cost") or {}).items()
                 if key != "by_trade"},
        "flow": {key: value for key, value in (statistics.get("flow") or {}).items()
                 if key != "throughput"},
        "schedule": {key: value for key, value in (statistics.get("schedule") or {}).items()
                     if key not in ("overdue", "due_soon")},
        "overdue_examples": (statistics.get("schedule") or {}).get("overdue", [])[:5],
        "distributions": statistics.get("distributions"),
        "risks": statistics.get("risks"),
    }
    extra = f"\n\nThe reader also asked: {_text(instructions)}" if _text(instructions) else ""
    return (f"{_INSIGHT_RULES}{extra}\n\n--- FIGURES ---\n"
            f"{json.dumps(slim, indent=1, default=str)}\n--- END ---")


def parse_insights(raw: str) -> dict[str, Any]:
    """Read the narrative back, keeping only the shape the page renders."""
    text = _text(raw)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    parsed: Any = None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, Mapping):
        return {"summary": "", "highlights": [], "concerns": [], "actions": [],
                "outlook": "", "available": False}

    def lines(key: str) -> list[str]:
        rows = parsed.get(key)
        return [_text(row) for row in rows if _text(row)][:6] if isinstance(rows, list) else []

    actions = parsed.get("actions")
    return {
        "summary": _text(parsed.get("summary")),
        "highlights": lines("highlights"),
        "concerns": lines("concerns"),
        "actions": [
            {"title": _text(row.get("title")), "why": _text(row.get("why"))}
            for row in actions if isinstance(row, Mapping) and _text(row.get("title"))
        ][:6] if isinstance(actions, list) else [],
        "outlook": _text(parsed.get("outlook")),
        "available": True,
    }


def rule_based_summary(statistics: Mapping[str, Any]) -> dict[str, Any]:
    """The commentary when no model is reachable.

    Thinner than the written version, but it is the same facts, so a report
    generated without a model is still a report rather than a gap.
    """
    phase = statistics.get("phase") or {}
    value = statistics.get("value") or {}
    risks = statistics.get("risks") or []
    percent = round((value.get("percent_complete") or 0) * 100)
    spi = value.get("schedule_performance_index")
    pace = (
        "in line with the plan" if spi is None or spi >= 0.95
        else "a little behind plan" if spi >= 0.85 else "behind plan"
    )
    return {
        "summary": (f"{statistics.get('project', {}).get('name', 'The project')} is in "
                    f"{phase.get('label', 'progress').lower()}, with {percent}% of planned "
                    f"value earned, {pace}."),
        "highlights": [],
        "concerns": [f"{row['title']}: {row['detail']}" for row in risks[:4]],
        "actions": [],
        "outlook": value.get("caveat") or "",
        "available": False,
        "note": "Written from the figures alone; Marshal was not reachable.",
    }


# ──────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────

class InsightRequest(BaseModel):
    instructions: str = ""
    rule: str = DEFAULT_PROGRESS_RULE


def register_project_analytics_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register the project statistics routes.

    Read-only: nothing here changes a project.  The figures come from the same
    stores the dashboard tabs read, so the Statistics tab can never disagree
    with the Cost or Timeline tab.
    """
    required = ("app", "require_account")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Project analytics integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]
    registry = namespace.get("ACCOUNT_REGISTRY")

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
            members=members,
            rule=rule,
        )

    async def compose(prompt: str, max_tokens: int = 1800) -> str:
        import asyncio

        generate = namespace.get("vl_generate")
        if not callable(generate):
            raise RuntimeError("no model is configured")
        messages = [
            {"role": "system", "content": (
                "You are BuildMarshalAI's project analyst. You explain computed "
                "figures to the team running a construction project. You never state "
                "a number that was not given to you, and you never invent a cause."
            )},
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: generate(messages, max_new_tokens=max_tokens)
        )

    @app.get("/api/projects/{project_id}/statistics")
    async def project_statistics(project_id: str, rule: str = DEFAULT_PROGRESS_RULE,
                                 context=Depends(require_account)) -> dict[str, Any]:
        """Every figure the Statistics tab draws, in one call."""
        return gather(context, project_id, rule)

    @app.post("/api/projects/{project_id}/statistics/insights")
    async def project_insights(project_id: str, body: InsightRequest,
                               context=Depends(require_account)) -> dict[str, Any]:
        """Marshal's reading of the figures.

        The figures are computed first and passed in; the model explains them and
        is told, in as many words, not to state a number it was not given.
        """
        statistics_data = gather(context, project_id, body.rule)
        try:
            raw = await compose(insight_prompt(statistics_data, body.instructions))
            insights = parse_insights(raw)
            if not insights["available"] or not insights["summary"]:
                insights = rule_based_summary(statistics_data)
        except Exception as error:  # pragma: no cover - model transport
            insights = {**rule_based_summary(statistics_data),
                        "note": f"Marshal could not be reached: {str(error)[:160]}"}
        return {"insights": insights, "as_of": statistics_data["as_of"],
                "risks": statistics_data["risks"]}

    return {"rules": list(PROGRESS_RULES), "phases": [key for key, _ in PHASES]}


__all__ = [
    "DEFAULT_PROGRESS_RULE", "DONE_STATUSES", "MIN_SAMPLE", "PHASES",
    "PROGRESS_RULES", "STALE_BLOCK_DAYS", "STALE_WIP_DAYS", "build_statistics",
    "cost_performance", "distributions", "earned_value", "earned_value_metrics",
    "flow_metrics", "headline_numbers", "planned_value_on", "progress_of",
    "project_phase", "risk_flags", "schedule_health", "task_value", "value_curve",
]
