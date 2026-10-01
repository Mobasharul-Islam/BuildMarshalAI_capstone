"""Who may change project and task costs.

Costs answer to three separate permissions -- baseline, additional, and task --
so a role can be given one without the others. On top of that, whoever a task
is assigned to may always price that task, so the person doing the work can
record what it cost without being able to touch anyone else's numbers.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.accounts import AccountContext
from backend.project_management import register_project_management_routes
from backend.tasks import register_task_routes

BASE = "project.cost.base"
ADDITIONAL = "project.cost.additional"
TASK_COST = "project.cost.task"
TASK_WORK = ("task.create", "task.update.status", "task.update.description",
             "task.update.assignee")


def as_role(context: AccountContext, role: str, *, name: str | None = None) -> AccountContext:
    """The same account, seen as a member holding a particular role.

    ``name`` picks one of the account's real people (see the ``project``
    fixture), because a task is assigned to a user, not to a name.
    """
    user = dict(context.user)
    if name is not None:
        user = next((dict(u) for u in context.people if u.get("name") == name), None) \
            or {**context.user, "name": name}
    user.update({"is_owner": False, "role": role})
    ctx = AccountContext(user=user, account=context.account,
                         workspace=context.workspace, token=context.token)
    ctx.people = context.people
    return ctx


def build_app(context: AccountContext, registry) -> TestClient:
    app = FastAPI()

    async def require_account():
        return context

    namespace = {"app": app, "require_account": require_account, "ACCOUNT_REGISTRY": registry}
    register_task_routes(namespace)
    register_project_management_routes(namespace)
    return TestClient(app)


def define_role(context: AccountContext, name: str, permissions) -> None:
    """Write a role straight to the workspace, as the roles API would."""
    roles = context.workspace.load_roles()
    roles = [r for r in roles if r["name"] != name]
    roles.append({"id": f"role-{name.lower().replace(' ', '-')}", "name": name,
                  "description": "", "permissions": list(permissions)})
    context.workspace.save_roles(roles)


@pytest.fixture
def project(make_account, registry):
    context = make_account("owner@example.com")
    # Real people: tasks are assigned to users, and only to people on the project.
    sam = registry.create_user(account_id=context.account_id, name="Sam Field",
                               email="sam@example.com", password="Passw0rd!123", role="Worker")
    alex = registry.create_user(account_id=context.account_id, name="Alex Other",
                                email="alex@example.com", password="Passw0rd!123", role="Worker")
    context.people = [context.user, sam, alex]
    context.workspace.save_projects({"p1": {
        "id": "p1", "name": "Tower", "project_code": "TWR", "baseline_cost": 0,
        "members": [{"user_id": u["id"]} for u in context.people],
    }})
    # A cost holder, and a worker who holds no cost permission at all.
    define_role(context, "Cost Holder", [BASE, ADDITIONAL, TASK_COST, *TASK_WORK])
    define_role(context, "Worker", list(TASK_WORK))
    define_role(context, "Baseline Only", [BASE, *TASK_WORK])
    return context


# ── project baseline and additional costs ─────────────────────────────────────

@pytest.mark.parametrize("role", ["Cost Holder", "Head (Super Admin)", "Head (System Admin)"])
def test_a_cost_holder_or_administrator_may_set_the_baseline(project, registry, role):
    client = build_app(as_role(project, role), registry)
    saved = client.put("/api/projects/p1/costs/baseline", json={"amount": 25000})
    assert saved.status_code == 200
    assert saved.json()["baseline_cost"] == 25000


def test_a_role_without_the_permission_cannot_set_the_baseline(project, registry):
    client = build_app(as_role(project, "Worker"), registry)
    blocked = client.put("/api/projects/p1/costs/baseline", json={"amount": 25000})
    assert blocked.status_code == 403
    assert "baseline" in blocked.json()["detail"]
    assert project.workspace.load_projects()["p1"].get("baseline_cost", 0) == 0


def test_a_role_with_no_role_at_all_holds_nothing(project, registry):
    """An unassigned or deleted role must fail closed, not open."""
    client = build_app(as_role(project, ""), registry)
    assert client.put("/api/projects/p1/costs/baseline", json={"amount": 1}).status_code == 403
    assert client.post("/api/projects/p1/tasks", json={"name": "X"}).status_code == 403


def test_the_three_cost_permissions_are_independent(project, registry):
    """Baseline and additional costs are separate grants."""
    client = build_app(as_role(project, "Baseline Only"), registry)
    assert client.put("/api/projects/p1/costs/baseline",
                      json={"amount": 500}).status_code == 200
    refused = client.post("/api/projects/p1/costs", json={"name": "Crane", "amount": 10})
    assert refused.status_code == 403
    assert "project costs" in refused.json()["detail"]


def test_additional_costs_need_their_own_permission(project, registry):
    holder = build_app(as_role(project, "Cost Holder"), registry)
    created = holder.post("/api/projects/p1/costs", json={"name": "Crane hire", "amount": 4000})
    assert created.status_code == 200
    cost_id = created.json()["cost"]["id"]

    worker = build_app(as_role(project, "Worker"), registry)
    assert worker.post("/api/projects/p1/costs",
                       json={"name": "Sneaky", "amount": 1}).status_code == 403
    assert worker.put(f"/api/projects/p1/costs/{cost_id}",
                      json={"amount": 999999}).status_code == 403
    assert worker.delete(f"/api/projects/p1/costs/{cost_id}").status_code == 403
    assert holder.get("/api/projects/p1/costs").json()["additional_costs"][0]["amount"] == 4000


def test_everyone_may_still_read_the_breakdown(project, registry):
    build_app(as_role(project, "Cost Holder"), registry).put(
        "/api/projects/p1/costs/baseline", json={"amount": 1000})

    worker = build_app(as_role(project, "Worker"), registry)
    read = worker.get("/api/projects/p1/costs")
    assert read.status_code == 200
    assert read.json()["baseline_cost"] == 1000
    assert read.json()["can_edit_project_cost"] is False
    assert read.json()["can_edit_baseline"] is False
    assert read.json()["can_edit_additional"] is False


# ── task costs ────────────────────────────────────────────────────────────────

def make_task(client, **fields):
    body = {"name": "Pour slab", **fields}
    response = client.post("/api/projects/p1/tasks", json=body)
    assert response.status_code == 200, response.json()
    return response.json()


def test_the_assignee_may_set_their_own_task_cost(project, registry):
    holder = build_app(as_role(project, "Cost Holder"), registry)
    task = make_task(holder, assignee="Sam Field")

    sam = build_app(as_role(project, "Worker", name="Sam Field"), registry)
    updated = sam.put(f"/api/projects/p1/tasks/{task['id']}", json={"cost": 750})
    assert updated.status_code == 200 and updated.json()["cost"] == 750


def test_another_member_cannot_touch_someone_elses_task_cost(project, registry):
    holder = build_app(as_role(project, "Cost Holder"), registry)
    task = make_task(holder, assignee="Sam Field")

    other = build_app(as_role(project, "Worker", name="Alex Other"), registry)
    blocked = other.put(f"/api/projects/p1/tasks/{task['id']}", json={"cost": 5000})
    assert blocked.status_code == 403
    assert "assigned user" in blocked.json()["detail"]
    assert holder.get(f"/api/projects/p1/tasks/{task['id']}").json()["cost"] == 0


def test_the_task_cost_permission_covers_anyone_elses_task(project, registry):
    holder = build_app(as_role(project, "Cost Holder"), registry)
    task = make_task(holder, assignee="Sam Field")
    assert holder.put(f"/api/projects/p1/tasks/{task['id']}",
                      json={"cost": 1200}).status_code == 200


def test_a_member_may_still_edit_the_rest_of_a_task_they_do_not_own(project, registry):
    """Only the cost is restricted; the fields their role allows stay open."""
    holder = build_app(as_role(project, "Cost Holder"), registry)
    task = make_task(holder, assignee="Sam Field")

    other = build_app(as_role(project, "Worker", name="Alex Other"), registry)
    changed = other.put(f"/api/projects/p1/tasks/{task['id']}",
                        json={"status": "In Progress", "description": "Rebar tied"})
    assert changed.status_code == 200 and changed.json()["status"] == "In Progress"


def test_resending_an_unchanged_cost_is_not_a_permission_error(project, registry):
    """A full-record save from the task form must not trip the cost rule."""
    holder = build_app(as_role(project, "Cost Holder"), registry)
    task = make_task(holder, assignee="Sam Field", cost=300)

    other = build_app(as_role(project, "Worker", name="Alex Other"), registry)
    resend = other.put(f"/api/projects/p1/tasks/{task['id']}",
                       json={"status": "In Progress", "cost": 300})
    assert resend.status_code == 200


def test_opening_a_task_with_a_cost_answers_to_the_same_rule(project, registry):
    other = build_app(as_role(project, "Worker", name="Alex Other"), registry)
    assert other.post("/api/projects/p1/tasks",
                      json={"name": "Padded", "assignee": "Sam Field",
                            "cost": 9000}).status_code == 403

    mine = other.post("/api/projects/p1/tasks",
                      json={"name": "Mine", "assignee": "Alex Other", "cost": 100})
    assert mine.status_code == 200 and mine.json()["cost"] == 100

    free = other.post("/api/projects/p1/tasks", json={"name": "Free", "assignee": "Sam Field"})
    assert free.status_code == 200


def test_the_breakdown_reports_which_task_costs_this_user_may_edit(project, registry):
    holder = build_app(as_role(project, "Cost Holder"), registry)
    mine = make_task(holder, assignee="Sam Field")
    theirs = holder.post("/api/projects/p1/tasks",
                         json={"name": "Other", "assignee": "Alex Other"}).json()

    sam = build_app(as_role(project, "Worker", name="Sam Field"), registry)
    editable = sam.get("/api/projects/p1/costs").json()["editable_task_costs"]
    assert mine["id"] in editable and theirs["id"] not in editable


def test_an_unassigned_task_is_not_editable_by_just_anyone(project, registry):
    holder = build_app(as_role(project, "Cost Holder"), registry)
    task = make_task(holder, assignee="")

    other = build_app(as_role(project, "Worker", name="Alex Other"), registry)
    assert other.put(f"/api/projects/p1/tasks/{task['id']}",
                     json={"cost": 50}).status_code == 403


def test_a_member_with_no_name_is_matched_on_their_email(project, registry):
    holder = build_app(as_role(project, "Cost Holder"), registry)
    task = make_task(holder, assignee="owner@example.com")

    # The owner, seen as a Worker: the task named them by email, not by name.
    nameless = build_app(as_role(project, "Worker"), registry)
    assert nameless.put(f"/api/projects/p1/tasks/{task['id']}",
                        json={"cost": 60}).status_code == 200
