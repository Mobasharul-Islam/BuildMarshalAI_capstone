"""Project people, costs, timeline, and procurement."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.project_management import (
    PROCUREMENT_STATUSES,
    as_date,
    build_timeline,
    cost_breakdown,
    money,
    procurement_summary,
    quantity,
    register_project_management_routes,
)
from backend.tasks import register_task_routes


# ── helpers ───────────────────────────────────────────────────────────────────

def test_amounts_are_parsed_and_bad_ones_refused():
    assert money(12) == 12.0
    assert money("19.999") == 20.0
    assert money(None) == 0.0
    for bad in ("abc", float("inf"), True, -5):
        with pytest.raises(HTTPException) as exc:
            money(bad)
        assert exc.value.status_code == 422


def test_quantities_allow_fractions_but_not_negatives():
    assert quantity("2.5") == 2.5
    assert quantity(None) == 1.0
    with pytest.raises(HTTPException):
        quantity(-1)


def test_dates_normalise_from_dates_and_date_times():
    assert as_date("2027-03-01") == "2027-03-01"
    assert as_date("2027-03-01T14:30") == "2027-03-01"
    assert as_date("2027-03-01T14:30:00Z") == "2027-03-01"
    assert as_date("not a date") == ""
    assert as_date(None) == ""


# ── cost breakdown ────────────────────────────────────────────────────────────

def test_total_is_baseline_plus_additional_plus_task_costs():
    project = {
        "baseline_cost": 1000,
        "additional_costs": [{"id": "c1", "name": "Insurance", "amount": 250},
                             {"id": "c2", "name": "Permits", "amount": 150.5}],
    }
    tasks = [{"id": "t1", "name": "Slab", "cost": 500}, {"id": "t2", "name": "Wiring", "cost": 99.5}]
    result = cost_breakdown(project, tasks)
    assert result["baseline_cost"] == 1000
    assert result["additional_total"] == 400.5
    assert result["tasks_total"] == 599.5
    assert result["total"] == 2000.0


def test_archived_task_costs_are_shown_but_not_counted():
    project = {"baseline_cost": 0, "additional_costs": []}
    tasks = [{"id": "t1", "name": "Live", "cost": 100},
             {"id": "t2", "name": "Old", "cost": 900, "archived": True}]
    result = cost_breakdown(project, tasks)
    assert result["tasks_total"] == 100
    assert result["total"] == 100
    # The archived row is still listed so the breakdown is complete.
    assert {row["name"] for row in result["tasks"]} == {"Live", "Old"}


def test_an_empty_project_costs_nothing():
    result = cost_breakdown({}, [])
    assert result["total"] == 0 and result["tasks"] == [] and result["additional_costs"] == []


# ── timeline ──────────────────────────────────────────────────────────────────

def test_the_window_covers_the_project_and_every_dated_task():
    project = {"id": "p1", "name": "Tower", "start_date": "2027-03-01", "end_date": "2027-03-31"}
    tasks = [
        {"id": "t1", "name": "Early", "start_time": "2027-02-20T08:00", "end_time": "2027-02-25T17:00"},
        {"id": "t2", "name": "Late", "start_time": "2027-04-01T08:00", "end_time": "2027-04-10T17:00"},
    ]
    timeline = build_timeline(project, tasks)
    # A task running outside the project dates must still be drawable.
    assert timeline["window"]["start"] == "2027-02-20"
    assert timeline["window"]["end"] == "2027-04-10"
    assert timeline["scheduled_count"] == 2


def test_undated_tasks_are_reported_rather_than_dropped():
    timeline = build_timeline(
        {"id": "p1", "name": "Tower", "start_date": "2027-03-01", "end_date": "2027-03-31"},
        [{"id": "t1", "name": "No dates"}],
    )
    assert timeline["unscheduled_count"] == 1
    assert timeline["tasks"][0]["scheduled"] is False


def test_a_reversed_task_range_is_straightened():
    timeline = build_timeline(
        {"id": "p1", "name": "T"},
        [{"id": "t1", "name": "Backwards", "start_time": "2027-03-10", "end_time": "2027-03-01"}],
    )
    row = timeline["tasks"][0]
    assert row["start"] == "2027-03-01" and row["end"] == "2027-03-10"


def test_archived_tasks_stay_off_the_timeline():
    timeline = build_timeline({"id": "p1", "name": "T"},
                              [{"id": "t1", "name": "Old", "start_time": "2027-03-01", "archived": True}])
    assert timeline["tasks"] == []


def test_a_task_falls_back_to_its_due_date():
    timeline = build_timeline({"id": "p1", "name": "T"},
                              [{"id": "t1", "name": "Due only", "due_date": "2027-05-04"}])
    row = timeline["tasks"][0]
    assert row["end"] == "2027-05-04" and row["scheduled"] is True


# ── procurement summary ───────────────────────────────────────────────────────

def test_committed_spend_excludes_cancelled_lines():
    summary = procurement_summary([
        {"quantity": 2, "unit_cost": 100, "status": "Ordered"},
        {"quantity": 3, "unit_cost": 10, "status": "Delivered"},
        {"quantity": 5, "unit_cost": 999, "status": "Cancelled"},
    ])
    assert summary["total"] == 230.0
    assert summary["count"] == 3
    assert summary["by_status"]["Cancelled"] == 1


# ── routes ────────────────────────────────────────────────────────────────────

def build_app(context, registry):
    app = FastAPI()

    async def require_account():
        return context

    namespace = {"app": app, "require_account": require_account, "ACCOUNT_REGISTRY": registry}
    register_task_routes(namespace)
    register_project_management_routes(namespace)
    return TestClient(app)


@pytest.fixture
def project(make_account, registry):
    context = make_account("owner@example.com")
    context.workspace.save_projects({"p1": {
        "id": "p1", "name": "Tower", "project_code": "TWR",
        "start_date": "2027-03-01", "end_date": "2027-03-31",
    }})
    return context, build_app(context, registry), registry


def test_people_can_be_added_listed_and_removed(project, registry):
    context, client, _ = project
    member = registry.create_user(
        account_id=context.account_id, name="Sam Field", email="sam@example.com",
        password="Passw0rd!123", role="User")

    listed = client.get("/api/projects/p1/members").json()
    assert listed["total"] == 0
    assert {u["email"] for u in listed["available"]} >= {"owner@example.com", "sam@example.com"}

    added = client.post("/api/projects/p1/members", json={
        "user_ids": [member["id"], context.user_id], "project_role": "Site crew"})
    assert added.status_code == 200 and added.json()["added"] == 2

    listed = client.get("/api/projects/p1/members").json()
    assert listed["total"] == 2
    assert all(row["project_role"] == "Site crew" for row in listed["members"])
    # Everyone assigned drops out of the "available" list.
    assert not any(u["user_id"] == member["id"] for u in listed["available"])

    # Adding the same person twice does not duplicate them.
    again = client.post("/api/projects/p1/members", json={"user_ids": [member["id"]]})
    assert again.json()["added"] == 0

    removed = client.delete(f"/api/projects/p1/members/{member['id']}")
    assert removed.status_code == 200
    assert client.get("/api/projects/p1/members").json()["total"] == 1


def test_only_people_in_this_account_can_join_a_project(project, registry, make_account):
    _, client, _ = project
    outsider = make_account("neighbour@example.com", name="Neighbour")
    response = client.post("/api/projects/p1/members", json={"user_ids": [outsider.user_id]})
    assert response.status_code == 404
    assert client.get("/api/projects/p1/members").json()["total"] == 0


def test_adding_nobody_is_refused(project):
    _, client, _ = project
    assert client.post("/api/projects/p1/members", json={"user_ids": []}).status_code == 422
    assert client.delete("/api/projects/p1/members/nobody").status_code == 404


def test_costs_persist_and_the_total_tracks_every_part(project):
    context, client, _ = project

    client.put("/api/projects/p1/costs/baseline", json={"amount": 1000})
    added = client.post("/api/projects/p1/costs", json={
        "name": "Site insurance", "details": "12 months", "amount": 250}).json()
    assert added["total"] == 1250

    task = client.post("/api/projects/p1/tasks", json={"name": "Pour slab", "cost": 500}).json()
    assert task["cost"] == 500
    assert client.get("/api/projects/p1/costs").json()["total"] == 1750

    # Editing a task cost must move the project total.
    client.put(f"/api/projects/p1/tasks/{task['id']}", json={"cost": 800})
    breakdown = client.get("/api/projects/p1/costs").json()
    assert breakdown["tasks_total"] == 800 and breakdown["total"] == 2050

    updated = client.put(f"/api/projects/p1/costs/{added['cost']['id']}", json={"amount": 300}).json()
    assert updated["additional_total"] == 300 and updated["total"] == 2100

    deleted = client.delete(f"/api/projects/p1/costs/{added['cost']['id']}").json()
    assert deleted["additional_total"] == 0 and deleted["total"] == 1800

    # Stored on the project record, so it survives a reload.
    assert context.workspace.load_projects()["p1"]["baseline_cost"] == 1000


def test_cost_input_is_validated(project):
    _, client, _ = project
    assert client.post("/api/projects/p1/costs", json={"name": "", "amount": 10}).status_code == 422
    assert client.post("/api/projects/p1/costs", json={"name": "X", "amount": "abc"}).status_code == 422
    assert client.post("/api/projects/p1/costs", json={"name": "X", "amount": -5}).status_code == 422
    assert client.put("/api/projects/p1/costs/nope", json={"amount": 5}).status_code == 404
    assert client.delete("/api/projects/p1/costs/nope").status_code == 404
    assert client.put("/api/projects/p1/costs/baseline", json={"amount": -1}).status_code == 422
    assert client.post("/api/projects/p1/tasks", json={"name": "T", "cost": "free"}).status_code == 422


def test_the_timeline_route_reflects_the_project_and_its_tasks(project):
    _, client, _ = project
    client.post("/api/projects/p1/tasks", json={
        "name": "Framing", "start_time": "2027-03-05T08:00", "end_time": "2027-03-12T17:00"})
    timeline = client.get("/api/projects/p1/timeline").json()
    assert timeline["project"]["start"] == "2027-03-01"
    assert timeline["project"]["end"] == "2027-03-31"
    assert timeline["tasks"][0]["start"] == "2027-03-05"
    assert timeline["tasks"][0]["end"] == "2027-03-12"
    assert timeline["window"]["start"] == "2027-03-01"


def test_procurement_items_round_trip(project):
    _, client, _ = project
    item = client.post("/api/projects/p1/procurement", json={
        "name": "Engineered hardwood", "supplier": "Ethical Flooring", "quantity": 40,
        "unit": "m2", "unit_cost": 55.25, "status": "Ordered", "needed_by": "2027-03-20"}).json()
    assert item["unit_cost"] == 55.25 and item["status"] == "Ordered"

    listed = client.get("/api/projects/p1/procurement").json()
    assert listed["count"] == 1
    assert listed["items"][0]["line_total"] == 2210.0
    assert listed["total"] == 2210.0
    assert listed["statuses"] == list(PROCUREMENT_STATUSES)

    updated = client.put(f"/api/projects/p1/procurement/{item['id']}", json={
        "status": "Delivered", "quantity": 45}).json()
    assert updated["status"] == "Delivered" and updated["quantity"] == 45

    # Cancelling keeps the record but drops it from committed spend.
    client.put(f"/api/projects/p1/procurement/{item['id']}", json={"status": "Cancelled"})
    after = client.get("/api/projects/p1/procurement").json()
    assert after["count"] == 1 and after["total"] == 0

    assert client.delete(f"/api/projects/p1/procurement/{item['id']}").status_code == 200
    assert client.get("/api/projects/p1/procurement").json()["count"] == 0


def test_procurement_input_is_validated(project):
    _, client, _ = project
    assert client.post("/api/projects/p1/procurement", json={"name": " "}).status_code == 422
    assert client.post("/api/projects/p1/procurement", json={
        "name": "X", "status": "Invented"}).status_code == 422
    assert client.post("/api/projects/p1/procurement", json={
        "name": "X", "unit_cost": -1}).status_code == 422
    assert client.put("/api/projects/p1/procurement/nope", json={"name": "Y"}).status_code == 404
    assert client.delete("/api/projects/p1/procurement/nope").status_code == 404


def test_every_section_refuses_an_unknown_project(project):
    _, client, _ = project
    for path in ("/api/projects/nope/members", "/api/projects/nope/costs",
                 "/api/projects/nope/timeline", "/api/projects/nope/procurement"):
        assert client.get(path).status_code == 404, path


def test_another_accounts_project_sections_are_invisible(make_account, registry):
    """Same project id, different workspace: everything must read as missing."""
    neighbour = make_account("neighbour@example.com", name="Neighbour")
    neighbour.workspace.save_projects({"shared": {"id": "shared", "name": "Theirs"}})
    neighbour_client = build_app(neighbour, registry)
    neighbour_client.post("/api/projects/shared/procurement", json={"name": "Private order"})
    neighbour_client.put("/api/projects/shared/costs/baseline", json={"amount": 9999})

    mine = make_account("owner@example.com")
    my_client = build_app(mine, registry)
    for path in ("/api/projects/shared/members", "/api/projects/shared/costs",
                 "/api/projects/shared/timeline", "/api/projects/shared/procurement"):
        assert my_client.get(path).status_code == 404, path
    assert neighbour_client.get("/api/projects/shared/procurement").json()["count"] == 1
