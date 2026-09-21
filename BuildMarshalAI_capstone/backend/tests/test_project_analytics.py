"""Project statistics: the figures, and the things they refuse to claim.

The measures matter less than the discipline around them, so a good half of
this file is about what the module declines to report -- no cost index without
actuals, no confident average from two samples, no schedule index from a
programme with no dates.
"""

from datetime import date, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.project_analytics import (
    DEFAULT_PROGRESS_RULE,
    PROGRESS_RULES,
    build_statistics,
    cost_performance,
    distributions,
    earned_value,
    earned_value_metrics,
    flow_metrics,
    headline_numbers,
    insight_prompt,
    parse_insights,
    planned_value_on,
    progress_of,
    project_phase,
    register_project_analytics_routes,
    risk_flags,
    rule_based_summary,
    schedule_health,
    value_curve,
)

TODAY = date(2027, 4, 1)

PROJECT = {
    "id": "p1", "name": "Riverside Tower", "project_code": "RVT", "status": "Active",
    "manager": "Dana", "start_date": "2027-01-01", "end_date": "2027-06-30",
    "baseline_cost": 100000,
    "additional_costs": [{"id": "c1", "name": "Hoarding", "amount": 20000}],
}


def task(name, status, cost=1000, start="2027-01-01", end="2027-02-01", **extra):
    return {"id": name, "name": name, "status": status, "cost": cost,
            "start_time": start, "end_time": end, **extra}


# ── value and progress ────────────────────────────────────────────────────────

def test_the_fifty_fifty_rule_credits_starting_and_finishing():
    assert progress_of(task("a", "Open")) == 0.0
    assert progress_of(task("a", "In Progress")) == 0.5
    assert progress_of(task("a", "Completed")) == 1.0
    # Blocked work was started, so it keeps what starting earned it.
    assert progress_of(task("a", "Blocked")) == 0.5


def test_another_rule_can_be_asked_for():
    blocked = task("a", "In Progress")
    assert progress_of(blocked, "fixed_0_100") == 0.0
    assert progress_of(blocked, "fixed_25_75") == 0.25
    # An unknown rule falls back rather than crediting nothing.
    assert progress_of(blocked, "invented") == PROGRESS_RULES[DEFAULT_PROGRESS_RULE]["In Progress"]


def test_planned_value_accrues_across_the_window_not_at_the_end():
    tasks = [task("a", "Open", cost=1000, start="2027-01-01", end="2027-01-11")]
    assert planned_value_on(tasks, date(2026, 12, 31), 1000) == 0
    assert planned_value_on(tasks, date(2027, 1, 6), 1000) == pytest.approx(500, abs=1)
    assert planned_value_on(tasks, date(2027, 1, 11), 1000) == 1000
    assert planned_value_on(tasks, date(2027, 3, 1), 1000) == 1000


def test_work_with_no_dates_plans_no_value():
    """It is still in the budget; it is simply in no plan."""
    tasks = [{"id": "a", "name": "a", "status": "Open", "cost": 500}]
    assert planned_value_on(tasks, TODAY, 500) == 0
    metrics = earned_value_metrics(tasks, project=PROJECT, today=TODAY)
    assert metrics["budget_at_completion"] == 500
    assert metrics["unscheduled_tasks"] == 1


def test_an_unpriced_task_is_weighted_by_what_the_priced_ones_average():
    tasks = [task("a", "Completed", cost=1000), task("b", "Completed", cost=3000),
             {"id": "c", "name": "c", "status": "Open", "start_time": "2027-01-01",
              "end_time": "2027-02-01"}]
    # The unpriced task is worth the 2000 average, so the budget is 6000.
    assert earned_value_metrics(tasks, project=PROJECT, today=TODAY)["budget_at_completion"] == 6000


def test_a_programme_that_prices_nothing_counts_work_instead():
    tasks = [{"id": str(i), "name": str(i), "status": s, "start_time": "2027-01-01",
              "end_time": "2027-02-01"} for i, s in enumerate(["Completed", "Open"])]
    metrics = earned_value_metrics(tasks, project=PROJECT, today=TODAY)
    assert metrics["budget_at_completion"] == 2 and metrics["earned_value"] == 1
    assert metrics["priced"] is False


def test_the_schedule_index_and_the_finish_it_projects():
    tasks = [task("a", "Completed"), task("b", "Open"), task("c", "Open"), task("d", "Open")]
    metrics = earned_value_metrics(tasks, project=PROJECT, today=TODAY)
    # All four were planned to finish by February; one is done.
    assert metrics["planned_value"] == 4000 and metrics["earned_value"] == 1000
    assert metrics["schedule_performance_index"] == 0.25
    assert metrics["schedule_variance"] == -3000
    # A quarter of the pace stretches a 180-day programme roughly four-fold.
    assert metrics["projected_finish"] > metrics["planned_finish"]
    assert metrics["days_late"] > 0


def test_a_programme_with_nothing_planned_yet_has_no_index():
    tasks = [task("a", "Open", start="2027-05-01", end="2027-06-01")]
    metrics = earned_value_metrics(tasks, project=PROJECT, today=TODAY)
    assert metrics["planned_value"] == 0
    assert metrics["schedule_performance_index"] is None
    assert metrics["projected_finish"] is None


def test_too_few_scheduled_tasks_is_reported_rather_than_asserted():
    metrics = earned_value_metrics([task("a", "Completed")], project=PROJECT, today=TODAY)
    assert metrics["confident"] is False
    assert "Too few scheduled tasks" in metrics["caveat"]


def test_the_curve_stops_earning_at_today():
    tasks = [task("a", "Completed", end="2027-02-01"), task("b", "Open", end="2027-06-01")]
    curve = value_curve(tasks, project=PROJECT, today=TODAY)
    assert curve["points"]
    for row in curve["points"]:
        if row["date"] <= TODAY.isoformat():
            assert "earned" in row
        else:
            # Drawing earned value into the future would be a forecast wearing
            # a measurement's clothes.
            assert "earned" not in row
    assert curve["points"] == sorted(curve["points"], key=lambda row: row["date"])


def test_the_curve_is_monotonic_because_planned_value_cannot_go_down():
    tasks = [task(str(i), "Open", start="2027-01-01", end="2027-05-01") for i in range(4)]
    points = value_curve(tasks, project=PROJECT, today=TODAY)["points"]
    planned = [row["planned"] for row in points]
    assert planned == sorted(planned)


def test_an_unknown_progress_rule_is_refused():
    with pytest.raises(HTTPException):
        build_statistics(project=PROJECT, tasks=[], rule="whatever-feels-right")


# ── cost ──────────────────────────────────────────────────────────────────────

def test_cost_reports_budget_against_commitment():
    tasks = [task("a", "Completed", cost=5000, trade="Concrete"),
             task("b", "Open", cost=3000, trade="Steel")]
    procurement = [
        {"name": "Rebar", "quantity": 10, "unit_cost": 100, "status": "Ordered"},
        {"name": "Cancelled line", "quantity": 99, "unit_cost": 999, "status": "Cancelled"},
    ]
    cost = cost_performance(PROJECT, tasks, procurement)
    assert cost["baseline"] == 100000 and cost["additional"] == 20000
    assert cost["tasks"] == 8000 and cost["budget"] == 128000
    # A cancelled line is not a commitment.
    assert cost["committed_procurement"] == 1000
    assert cost["by_trade"][0] == {"label": "Concrete", "value": 5000}


def test_there_is_no_cost_index_and_the_reason_is_given():
    """CPI from budgets would read 1.00 forever and mean nothing."""
    cost = cost_performance(PROJECT, [task("a", "Completed", cost=5000)])
    assert cost["cost_performance_index"] is None
    assert "actual spend" in cost["index_note"]


def test_unpriced_work_is_counted_so_the_gap_is_visible():
    tasks = [task("a", "Open", cost=1000), {"id": "b", "name": "b", "status": "Open"}]
    cost = cost_performance(PROJECT, tasks)
    assert cost["priced_tasks"] == 1 and cost["unpriced_tasks"] == 1


# ── flow ──────────────────────────────────────────────────────────────────────

def test_throughput_buckets_the_last_weeks_and_reads_the_trend():
    tasks = [task(f"old{i}", "Completed", start="2027-02-01", end="2027-02-07") for i in range(4)]
    tasks += [task(f"new{i}", "Completed", start="2027-03-20", end="2027-03-28") for i in range(1)]
    flow = flow_metrics(tasks, today=TODAY, weeks=8)
    assert len(flow["throughput"]) == 8
    assert sum(row["completed"] for row in flow["throughput"]) >= 1
    assert flow["throughput_trend"] in ("rising", "falling", "flat")


def test_cycle_time_needs_a_sample_before_it_is_confident():
    one = flow_metrics([task("a", "Completed", start="2027-01-01", end="2027-01-10")], today=TODAY)
    assert one["cycle_time_days"] == 10 and one["confident"] is False
    assert "few finished tasks" in one["caveat"]

    many = flow_metrics([task(str(i), "Completed", start="2027-01-01", end="2027-01-10")
                         for i in range(4)], today=TODAY)
    assert many["confident"] is True and many["caveat"] == ""


def test_work_in_progress_that_has_aged_is_named():
    stale = task("Slab", "In Progress", start="2027-01-01", end="2027-05-01", assignee="Sam")
    fresh = task("Fit-out", "In Progress",
                 start=(TODAY - timedelta(days=2)).isoformat(), end="2027-05-01")
    flow = flow_metrics([stale, fresh], today=TODAY)
    assert flow["work_in_progress"] == 2
    assert [row["name"] for row in flow["ageing_wip"]] == ["Slab"]
    assert flow["ageing_wip"][0]["assignee"] == "Sam"


def test_archived_work_is_kept_for_the_record_but_not_the_maths():
    tasks = [task("a", "Completed"), task("b", "Open", archived=True)]
    assert flow_metrics(tasks, today=TODAY)["total"] == 1
    assert earned_value(tasks, 1000) == 1000


# ── schedule ──────────────────────────────────────────────────────────────────

def test_overdue_and_due_soon_are_separated_and_ordered():
    tasks = [
        task("Late", "Open", end="2027-03-01"),
        task("Later", "Open", end="2027-02-01"),
        task("Soon", "Open", end=(TODAY + timedelta(days=3)).isoformat()),
        task("Distant", "Open", end="2027-06-01"),
        task("Done", "Completed", end="2027-01-01"),
    ]
    health = schedule_health(tasks, project=PROJECT, today=TODAY)
    assert [row["name"] for row in health["overdue"]] == ["Later", "Late"]
    assert [row["name"] for row in health["due_soon"]] == ["Soon"]
    assert health["open_count"] == 4


def test_work_planned_past_the_project_end_is_called_out():
    tasks = [task("a", "Open", end="2027-09-01")]
    health = schedule_health(tasks, project=PROJECT, today=TODAY)
    assert health["overruns_project_end"] is True
    assert health["last_task_end"] == "2027-09-01"


def test_a_task_with_only_a_due_date_is_treated_as_a_milestone():
    tasks = [{"id": "m", "name": "Handover", "status": "Open", "due_date": "2027-03-01"}]
    health = schedule_health(tasks, project=PROJECT, today=TODAY)
    assert [row["name"] for row in health["overdue"]] == ["Handover"]


# ── phase ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("statuses,expected", [
    (["Open"] * 4, "planning"),
    (["In Progress"] + ["Open"] * 9, "mobilisation"),
    (["Completed", "Completed", "In Progress", "Open"], "execution"),
    (["Completed"] * 9 + ["In Progress"], "closeout"),
    (["Completed"] * 4, "complete"),
])
def test_the_phase_follows_the_work(statuses, expected):
    project = {**PROJECT, "start_date": "2027-05-01"} if expected == "planning" else PROJECT
    tasks = [task(str(i), status) for i, status in enumerate(statuses)]
    stats = build_statistics(project=project, tasks=tasks, today=TODAY)
    assert stats["phase"]["key"] == expected
    assert stats["phase"]["reason"]


def test_a_project_marked_complete_is_complete_whatever_the_tasks_say():
    stats = build_statistics(project={**PROJECT, "status": "Completed"},
                             tasks=[task("a", "Open")], today=TODAY)
    assert stats["phase"]["key"] == "complete"
    assert "marked completed" in stats["phase"]["reason"]


# ── risks ─────────────────────────────────────────────────────────────────────

def full_stats(tasks, procurement=()):
    return build_statistics(project=PROJECT, tasks=tasks, procurement=list(procurement),
                            today=TODAY)


def test_every_flag_carries_the_number_that_raised_it():
    tasks = [task("Late", "Open", end="2027-02-01"),
             task("Stuck", "Blocked", start="2027-01-01", end="2027-05-01"),
             task("a", "Completed"), task("b", "Open")]
    flags = full_stats(tasks)["risks"]
    assert flags
    for flag in flags:
        assert flag["severity"] in ("high", "medium", "low")
        assert flag["title"] and flag["detail"]
    # Severest first, so the top of the list is the thing to read.
    order = ["high", "medium", "low"]
    assert [order.index(flag["severity"]) for flag in flags] == sorted(
        order.index(flag["severity"]) for flag in flags)


def test_procurement_needed_soon_but_not_ordered_is_flagged():
    procurement = [{"name": "Curtain wall", "status": "Requested",
                    "needed_by": (TODAY + timedelta(days=10)).isoformat(),
                    "quantity": 1, "unit_cost": 100}]
    keys = {flag["key"] for flag in full_stats([task("a", "Open")], procurement)["risks"]}
    assert "procurement" in keys


def test_an_ordered_item_is_not_flagged():
    procurement = [{"name": "Rebar", "status": "Ordered",
                    "needed_by": (TODAY + timedelta(days=10)).isoformat(),
                    "quantity": 1, "unit_cost": 100}]
    keys = {flag["key"] for flag in full_stats([task("a", "Open")], procurement)["risks"]}
    assert "procurement" not in keys


def test_a_healthy_project_raises_nothing_alarming():
    tasks = [task(str(i), "Completed", start="2027-01-01", end="2027-02-01", assignee="Sam")
             for i in range(5)]
    flags = full_stats(tasks)["risks"]
    assert not [flag for flag in flags if flag["severity"] == "high"]


def test_cost_running_ahead_of_progress_is_flagged():
    tasks = [task("a", "Open", cost=1000, end="2027-06-01")]
    procurement = [{"name": "Everything", "quantity": 1, "unit_cost": 200000, "status": "Ordered"}]
    keys = {flag["key"] for flag in full_stats(tasks, procurement)["risks"]}
    assert "over_budget" in keys


# ── the whole picture ─────────────────────────────────────────────────────────

def test_the_statistics_bundle_carries_everything_a_page_needs():
    stats = full_stats([task("a", "Completed", trade="Concrete", assignee="Sam"),
                        task("b", "In Progress", trade="Steel")])
    for key in ("project", "phase", "value", "cost", "flow", "schedule",
                "distributions", "curve", "risks", "headline", "as_of"):
        assert key in stats, key
    assert len(stats["headline"]) == 6
    assert {row["key"] for row in stats["headline"]} == {
        "complete", "spi", "budget", "committed", "throughput", "overdue"}


def test_distributions_cover_every_status_even_the_empty_ones():
    rows = distributions([task("a", "Open")])
    assert [row["label"] for row in rows["status"]] == ["Open", "In Progress", "Blocked", "Completed"]
    assert rows["status"][0]["value"] == 1 and rows["status"][3]["value"] == 0


def test_unassigned_work_is_counted_separately():
    rows = distributions([task("a", "Open"), task("b", "Open", assignee="Sam")])
    assert rows["unassigned"] == 1
    assert {row["label"] for row in rows["assignee_load"]} == {"Unassigned", "Sam"}


def test_headline_tones_flag_the_bad_news():
    stats = full_stats([task("Late", "Open", end="2027-01-01")])
    tones = {row["key"]: row.get("tone") for row in stats["headline"]}
    assert tones["overdue"] == "bad"


# ── what the assistant may add ────────────────────────────────────────────────

def test_the_insight_prompt_carries_the_figures_and_the_ban_on_inventing_them():
    prompt = insight_prompt(full_stats([task("a", "Completed")]), "focus on the concrete")
    assert "Riverside Tower" in prompt
    assert "ONLY the numbers given" in prompt
    assert "Never invent a cause" in prompt
    assert "focus on the concrete" in prompt


def test_a_narrative_is_read_back_into_the_shape_the_page_draws():
    parsed = parse_insights('''```json
    {"summary": "Behind plan.", "highlights": ["Foundations done"],
     "concerns": ["Glazing blocked"],
     "actions": [{"title": "Unblock glazing", "why": "It is the only blocker"}],
     "outlook": "Late without intervention"}
    ```''')
    assert parsed["available"] is True
    assert parsed["summary"] == "Behind plan."
    assert parsed["actions"] == [{"title": "Unblock glazing", "why": "It is the only blocker"}]


def test_an_unreadable_narrative_is_not_treated_as_one():
    parsed = parse_insights("I had a look and it seems fine to me")
    assert parsed["available"] is False and parsed["summary"] == ""


def test_the_fallback_summary_says_the_same_things_without_a_model():
    stats = full_stats([task("Late", "Open", end="2027-01-01"), task("a", "Completed")])
    summary = rule_based_summary(stats)
    assert "Riverside Tower" in summary["summary"]
    assert summary["available"] is False
    assert summary["concerns"]


# ── routes ────────────────────────────────────────────────────────────────────

def build_app(context, model=None):
    app = FastAPI()

    async def require_account():
        return context

    namespace = {"app": app, "require_account": require_account, "ACCOUNT_REGISTRY": None}
    if model is not None:
        namespace["vl_generate"] = model
    register_project_analytics_routes(namespace)
    return TestClient(app)


@pytest.fixture
def project(make_account):
    context = make_account("owner@example.com")
    context.workspace.save_projects({"p1": {**PROJECT}})
    # These routes run against the real clock, so the dates are relative to it.
    today = date.today()
    context.workspace.save_tasks({"p1": [
        task("a", "Completed", start=(today - timedelta(days=40)).isoformat(),
             end=(today - timedelta(days=30)).isoformat(), trade="Concrete", assignee="Sam"),
        task("b", "In Progress", start=(today - timedelta(days=20)).isoformat(),
             end=(today + timedelta(days=20)).isoformat(), trade="Steel", assignee="Priya"),
        task("Late", "Open", start=(today - timedelta(days=20)).isoformat(),
             end=(today - timedelta(days=5)).isoformat()),
    ]})
    return context


def test_the_statistics_route_answers_with_the_whole_picture(project):
    client = build_app(project)
    body = client.get("/api/projects/p1/statistics").json()
    assert body["project"]["name"] == "Riverside Tower"
    assert body["value"]["budget_at_completion"] == 3000
    assert body["schedule"]["overdue_count"] == 1
    assert body["risks"]


def test_the_statistics_route_accepts_another_progress_rule(project):
    client = build_app(project)
    fifty = client.get("/api/projects/p1/statistics").json()["value"]["earned_value"]
    strict = client.get("/api/projects/p1/statistics?rule=fixed_0_100").json()["value"]["earned_value"]
    # Under 0/100 the in-progress task earns nothing, so less is earned.
    assert strict < fifty


def test_an_unknown_rule_is_refused_by_the_route(project):
    assert build_app(project).get("/api/projects/p1/statistics?rule=vibes").status_code == 422


def test_a_project_from_another_account_is_simply_missing(project):
    assert build_app(project).get("/api/projects/nope/statistics").status_code == 404


def test_insights_fall_back_to_the_figures_when_no_model_is_configured(project):
    body = build_app(project).post("/api/projects/p1/statistics/insights", json={}).json()
    assert body["insights"]["available"] is False
    assert "Riverside Tower" in body["insights"]["summary"]
    assert body["risks"]


def test_insights_use_the_model_when_it_answers(project):
    def model(messages, max_new_tokens=1800, model=None):
        return '{"summary": "Behind on the glazing package.", "concerns": ["Glazing"]}'

    body = build_app(project, model).post("/api/projects/p1/statistics/insights",
                                          json={"instructions": "be brief"}).json()
    assert body["insights"]["summary"] == "Behind on the glazing package."
    assert body["insights"]["available"] is True


def test_a_model_that_fails_does_not_fail_the_request(project):
    def model(messages, max_new_tokens=1800, model=None):
        raise RuntimeError("the proxy is down")

    body = build_app(project, model).post("/api/projects/p1/statistics/insights", json={}).json()
    assert body["insights"]["available"] is False
    assert "could not be reached" in body["insights"]["note"]
