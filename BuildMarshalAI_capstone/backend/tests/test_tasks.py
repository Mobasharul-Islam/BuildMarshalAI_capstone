"""Project task management: record rules, filters, and the REST routes."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.tasks import (
    TASK_PRIORITIES,
    TASK_STATUSES,
    apply_task_updates,
    detach_children,
    filter_tasks,
    make_task,
    register_task_routes,
    validate_task,
)


# ── record construction ───────────────────────────────────────────────────────

def test_a_new_task_gets_sensible_defaults():
    task = make_task({"name": "  Pour slab  "}, "p1")
    assert task["name"] == "Pour slab"
    assert task["project_id"] == "p1"
    assert task["status"] == "Open"
    assert task["priority"] == "Normal"
    assert task["parent_id"] is None
    assert task["archived"] is False
    assert task["created_at"] and task["updated_at"]


def test_every_editable_field_round_trips():
    data = {
        "name": "Rebar inspection", "task_type": "Inspection", "trade": "Concrete",
        "assignee": "Sam", "field_worker": "Alex", "start_time": "2027-03-01T08:00",
        "end_time": "2027-03-01T12:00", "due_date": "2027-03-01", "priority": "High",
        "status": "In Progress", "delegation": "Subcontractor", "description": "Check spacing",
    }
    task = make_task(data, "p1")
    for key, value in data.items():
        assert task[key] == value, key


def test_updates_touch_only_supplied_fields_and_bump_the_timestamp():
    task = make_task({"name": "Original", "trade": "Concrete"}, "p1")
    before = task["updated_at"]
    apply_task_updates(task, {"status": "Completed", "id": "hacked", "project_id": "other"})
    assert task["status"] == "Completed"
    assert task["trade"] == "Concrete"
    # Server-owned fields are not client-settable.
    assert task["id"] != "hacked" and task["project_id"] == "p1"
    assert task["updated_at"] >= before


def test_clearing_a_parent_sends_the_task_back_to_the_root():
    task = make_task({"name": "Child", "parent_id": "p-root"}, "p1")
    assert task["parent_id"] == "p-root"
    apply_task_updates(task, {"parent_id": ""})
    assert task["parent_id"] is None


# ── validation ────────────────────────────────────────────────────────────────

def test_unknown_status_and_priority_are_refused():
    for payload, word in (({"status": "Wibble"}, "Status"), ({"priority": "Wibble"}, "Priority")):
        with pytest.raises(HTTPException) as exc:
            validate_task(payload, [])
        assert exc.value.status_code == 422
        assert word in exc.value.detail
    # The permitted values pass.
    for status in TASK_STATUSES:
        validate_task({"status": status}, [])
    for priority in TASK_PRIORITIES:
        validate_task({"priority": priority}, [])


def test_an_end_before_its_start_is_refused():
    with pytest.raises(HTTPException) as exc:
        validate_task({"start_time": "2027-03-02T09:00", "end_time": "2027-03-01T09:00"}, [])
    assert "End time" in exc.value.detail
    validate_task({"start_time": "2027-03-01T09:00", "end_time": "2027-03-01T10:00"}, [])


def test_a_parent_outside_the_project_is_refused():
    with pytest.raises(HTTPException) as exc:
        validate_task({"parent_id": "elsewhere"}, [{"id": "a", "parent_id": None}])
    assert "not in this project" in exc.value.detail


def test_a_task_cannot_be_its_own_parent():
    tasks = [{"id": "a", "parent_id": None}]
    with pytest.raises(HTTPException) as exc:
        validate_task({"parent_id": "a"}, tasks, task_id="a")
    assert "own parent" in exc.value.detail


def test_a_move_that_would_create_a_loop_is_refused():
    # a -> b -> c; making a a child of c would close the loop.
    tasks = [
        {"id": "a", "parent_id": None},
        {"id": "b", "parent_id": "a"},
        {"id": "c", "parent_id": "b"},
    ]
    with pytest.raises(HTTPException) as exc:
        validate_task({"parent_id": "c"}, tasks, task_id="a")
    assert "loop" in exc.value.detail
    # A legal move is still allowed.
    validate_task({"parent_id": "a"}, tasks, task_id="c")


# ── filters ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_tasks():
    return [
        {"id": "1", "name": "Pour slab", "trade": "Concrete", "status": "Open",
         "assignee": "Sam", "priority": "High", "parent_id": None, "archived": False},
        {"id": "2", "name": "Cure slab", "trade": "Concrete", "status": "Completed",
         "assignee": "Alex", "priority": "Normal", "parent_id": "1", "archived": False},
        {"id": "3", "name": "Wire panel", "trade": "Electrical", "status": "Open",
         "assignee": "Sam", "priority": "Normal", "parent_id": None, "archived": True},
    ]


def test_archived_tasks_are_hidden_unless_asked_for(sample_tasks):
    assert {t["id"] for t in filter_tasks(sample_tasks)} == {"1", "2"}
    assert {t["id"] for t in filter_tasks(sample_tasks, show_archived=True)} == {"1", "2", "3"}


def test_filters_narrow_the_list(sample_tasks):
    assert [t["id"] for t in filter_tasks(sample_tasks, name="slab")] == ["1", "2"]
    assert [t["id"] for t in filter_tasks(sample_tasks, trade="Concrete")] == ["1", "2"]
    assert [t["id"] for t in filter_tasks(sample_tasks, status="Completed")] == ["2"]
    assert [t["id"] for t in filter_tasks(sample_tasks, status="Open,Completed")] == ["1", "2"]
    assert [t["id"] for t in filter_tasks(sample_tasks, assignee="Alex")] == ["2"]
    assert [t["id"] for t in filter_tasks(sample_tasks, priority="High")] == ["1"]


def test_parent_filter_selects_roots_or_children(sample_tasks):
    assert [t["id"] for t in filter_tasks(sample_tasks, parent_id="root")] == ["1"]
    assert [t["id"] for t in filter_tasks(sample_tasks, parent_id="1")] == ["2"]


def test_filtering_does_not_mutate_the_stored_tasks(sample_tasks):
    filter_tasks(sample_tasks, name="slab")[0]["name"] = "changed"
    assert sample_tasks[0]["name"] == "Pour slab"


def test_deleting_a_task_lifts_its_children_to_the_grandparent():
    tasks = [
        {"id": "a", "parent_id": None},
        {"id": "b", "parent_id": "a"},
        {"id": "c", "parent_id": "b"},
    ]
    detach_children(tasks, "b")
    assert next(t for t in tasks if t["id"] == "c")["parent_id"] == "a"


# ── routes ────────────────────────────────────────────────────────────────────

def build_app(context):
    app = FastAPI()

    async def require_account():
        return context

    register_task_routes({"app": app, "require_account": require_account})
    return TestClient(app)


@pytest.fixture
def project(make_account):
    context = make_account("owner@example.com")
    context.workspace.save_projects({"p1": {"id": "p1", "name": "Tower", "project_code": "TWR"}})
    return context, build_app(context)


def test_tasks_can_be_created_listed_read_edited_and_deleted(project):
    context, client = project

    created = client.post("/api/projects/p1/tasks", json={
        "name": "Pour slab", "trade": "Concrete", "assignee": "Sam", "priority": "High",
    })
    assert created.status_code == 200
    task = created.json()
    assert task["project_id"] == "p1" and task["status"] == "Open"

    listed = client.get("/api/projects/p1/tasks").json()
    assert listed["total"] == 1 and listed["tasks"][0]["id"] == task["id"]

    child = client.post("/api/projects/p1/tasks", json={
        "name": "Cure slab", "parent_id": task["id"],
    }).json()

    detail = client.get(f"/api/projects/p1/tasks/{task['id']}").json()
    assert [s["id"] for s in detail["subtasks"]] == [child["id"]]
    assert detail["parent"] is None

    edited = client.put(f"/api/projects/p1/tasks/{task['id']}", json={
        "status": "In Progress", "description": "Started",
    })
    assert edited.status_code == 200
    assert edited.json()["status"] == "In Progress"
    assert edited.json()["name"] == "Pour slab"

    assert client.delete(f"/api/projects/p1/tasks/{task['id']}").status_code == 200
    remaining = client.get("/api/projects/p1/tasks").json()["tasks"]
    # The subtask survives and is lifted to the root.
    assert [t["id"] for t in remaining] == [child["id"]]
    assert remaining[0]["parent_id"] is None


def test_tasks_persist_across_reloads(project):
    context, client = project
    client.post("/api/projects/p1/tasks", json={"name": "Persisted"})
    # Read straight from the workspace store, as a fresh process would.
    stored = context.workspace.load_tasks()["p1"]
    assert [t["name"] for t in stored] == ["Persisted"]


def test_a_task_without_a_name_is_refused(project):
    _, client = project
    assert client.post("/api/projects/p1/tasks", json={"name": "   "}).status_code == 422
    task = client.post("/api/projects/p1/tasks", json={"name": "Valid"}).json()
    assert client.put(f"/api/projects/p1/tasks/{task['id']}", json={"name": ""}).status_code == 422


def test_tasks_of_an_unknown_project_are_not_found(project):
    _, client = project
    assert client.get("/api/projects/nope/tasks").status_code == 404
    assert client.post("/api/projects/nope/tasks", json={"name": "x"}).status_code == 404
    assert client.get("/api/projects/p1/tasks/nope").status_code == 404
    assert client.put("/api/projects/p1/tasks/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/projects/p1/tasks/nope").status_code == 404


def test_another_accounts_project_is_invisible(make_account):
    """A task list must resolve the project through the caller's workspace."""
    neighbour = make_account("neighbour@example.com", name="Neighbour")
    neighbour.workspace.save_projects({"shared-id": {"id": "shared-id", "name": "Theirs"}})
    neighbour_client = build_app(neighbour)
    neighbour_client.post("/api/projects/shared-id/tasks", json={"name": "Private task"})

    mine = make_account("owner@example.com")
    my_client = build_app(mine)
    # Same project id, different workspace: it must read as missing.
    assert my_client.get("/api/projects/shared-id/tasks").status_code == 404
    assert neighbour_client.get("/api/projects/shared-id/tasks").json()["total"] == 1


def test_archived_tasks_are_hidden_from_the_default_listing(project):
    _, client = project
    task = client.post("/api/projects/p1/tasks", json={"name": "Old work"}).json()
    client.put(f"/api/projects/p1/tasks/{task['id']}", json={"archived": True})

    assert client.get("/api/projects/p1/tasks").json()["total"] == 0
    assert client.get("/api/projects/p1/tasks?show_archived=true").json()["total"] == 1


def test_the_routes_reject_a_loop_and_an_invalid_status(project):
    _, client = project
    parent = client.post("/api/projects/p1/tasks", json={"name": "Parent"}).json()
    child = client.post("/api/projects/p1/tasks", json={
        "name": "Child", "parent_id": parent["id"]}).json()

    looped = client.put(f"/api/projects/p1/tasks/{parent['id']}", json={"parent_id": child["id"]})
    assert looped.status_code == 422 and "loop" in looped.json()["detail"]

    bad = client.put(f"/api/projects/p1/tasks/{child['id']}", json={"status": "Nope"})
    assert bad.status_code == 422
