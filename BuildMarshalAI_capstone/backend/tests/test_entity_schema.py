"""The entity schema, and the promise that it is the application's and not its own.

The point of this file is the middle section: every field the schema calls
mandatory is put to the route or the validator that actually enforces it, and
every field it calls optional is shown to be accepted without one.  A schema that
drifted from the application would be a chatbot asking for the wrong things, or
worse, not asking.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.entity_schema import (
    ENTITIES,
    ENTITY_ORDER,
    catalog,
    coerce,
    coerce_fields,
    entity,
    is_complete,
    missing_required,
    permission_catalogue_rows,
    read_date,
    reconcile,
    reference_choices,
    validate_entity,
)
from backend.company_settings import register_company_settings_routes
from backend.project_management import register_project_management_routes
from backend.tasks import TASK_FIELDS, TASK_PRIORITIES, TASK_STATUSES, register_task_routes
from backend.user_roles import register_user_role_routes


# ── shape ─────────────────────────────────────────────────────────────────────

def test_every_entity_is_ordered_after_whatever_it_depends_on():
    position = {kind: index for index, kind in enumerate(ENTITY_ORDER)}
    for kind, spec in ENTITIES.items():
        if spec.parent:
            assert position[spec.parent] < position[kind], f"{kind} is created before its parent"


def test_a_parent_is_always_a_kind_that_exists():
    for spec in ENTITIES.values():
        assert not spec.parent or spec.parent in ENTITIES
        for item in spec.fields:
            assert not item.reference or item.reference in ENTITIES, item.name


def test_the_catalogue_carries_what_a_form_needs_to_render_itself():
    rows = {row["kind"]: row for row in catalog()}
    assert set(rows) == set(ENTITIES)
    task = rows["task"]
    assert task["parent"] == "project" and task["self_parent"] is True
    assert "name" in task["required"]
    status = next(field for field in task["fields"] if field["name"] == "status")
    assert status["options"] == list(TASK_STATUSES)


def test_task_fields_follow_the_task_module_rather_than_a_copy():
    """A field added to ``TASK_FIELDS`` appears here without an edit."""
    offered = {item.name for item in entity("task").fields}
    # parent_id is a link and cost is its own entity; everything else is offered.
    assert offered == set(TASK_FIELDS) - {"parent_id", "cost"}
    priority = entity("task").field_map["priority"]
    assert priority.options == TASK_PRIORITIES


def test_the_permission_catalogue_is_the_real_one():
    keys = {row["key"] for row in permission_catalogue_rows()}
    assert "task.create" in keys and "project.cost.additional" in keys


# ── mandatory fields are the application's, not this file's ───────────────────
#
# Each case drives the route or validator that really enforces the rule.

def _client(register, context, **extra):
    app = FastAPI()

    async def require_account():
        return context

    register({"app": app, "require_account": require_account, **extra})
    return TestClient(app)


@pytest.fixture
def context(make_account):
    ctx = make_account("owner@example.com")
    ctx.workspace.save_projects({"p1": {"id": "p1", "name": "Tower", "project_code": "TWR"}})
    return ctx


def test_a_task_without_a_name_is_refused_by_the_task_route(context):
    """Schema says ``name`` is mandatory for a task; the route agrees."""
    assert "name" in {item.name for item in entity("task").required_fields}
    client = _client(register_task_routes, context)
    assert client.post("/api/projects/p1/tasks", json={"name": "  "}).status_code == 422
    assert client.post("/api/projects/p1/tasks", json={"name": "Pour slab"}).status_code == 200


def test_every_other_task_field_really_is_optional(context):
    """Only ``name`` is mandatory, so a task with nothing else must be accepted."""
    client = _client(register_task_routes, context)
    created = client.post("/api/projects/p1/tasks", json={"name": "Bare"})
    assert created.status_code == 200
    optional = {item.name for item in entity("task").fields if not item.required}
    for name in optional:
        assert not created.json().get(name) or name in ("status", "priority"), name


def test_a_catalogue_entry_without_a_name_is_refused_by_its_route(context):
    for kind, segment in (("task_type", "task-types"), ("project_type", "project-types")):
        assert {item.name for item in entity(kind).required_fields} == {"name"}
    client = _client(register_company_settings_routes, context)
    assert client.post("/api/task-types", json={"name": ""}).status_code == 422
    assert client.post("/api/task-types", json={"name": "Concrete"}).status_code == 200
    # The one optional field really is optional.
    assert client.post("/api/project-types", json={"name": "Tower block"}).status_code == 200


def test_a_role_without_a_name_is_refused_by_the_roles_route(context):
    assert {item.name for item in entity("role_type").required_fields} == {"name"}
    client = _client(register_user_role_routes, context, ACCOUNT_REGISTRY=None)
    assert client.post("/api/user-roles", json={"name": " "}).status_code == 422
    assert client.post("/api/user-roles", json={"name": "Site Lead"}).status_code == 200


def test_a_project_cost_needs_a_name_and_an_amount_per_the_cost_route(context):
    assert {item.name for item in entity("project_cost").required_fields} == {"name", "amount"}
    client = _client(register_project_management_routes, context,
                     ACCOUNT_REGISTRY=_NoUsers())
    assert client.post("/api/projects/p1/costs", json={"amount": 10}).status_code == 422
    assert client.post("/api/projects/p1/costs",
                       json={"name": "Hoarding", "amount": "not a number"}).status_code == 422
    assert client.post("/api/projects/p1/costs", json={"name": "Hoarding", "amount": 1200}).status_code == 200


def test_a_procurement_line_needs_a_name_per_its_route(context):
    assert {item.name for item in entity("procurement").required_fields} == {"name"}
    client = _client(register_project_management_routes, context, ACCOUNT_REGISTRY=_NoUsers())
    assert client.post("/api/projects/p1/procurement", json={"unit_cost": 5}).status_code == 422
    assert client.post("/api/projects/p1/procurement", json={"name": "Rebar"}).status_code == 200


def test_a_task_cost_needs_an_amount_and_nothing_else():
    assert {item.name for item in entity("task_cost").required_fields} == {"amount"}
    with pytest.raises(HTTPException):
        validate_entity("task_cost", {})
    validate_entity("task_cost", {"amount": 500})


def test_a_user_needs_an_email_because_validate_email_says_so():
    assert {item.name for item in entity("user").required_fields} == {"name", "email"}
    with pytest.raises(HTTPException):
        validate_entity("user", {"name": "Sam", "email": ""})
    with pytest.raises(HTTPException):
        validate_entity("user", {"name": "Sam", "email": "sam-at-example"})
    validate_entity("user", {"name": "Sam", "email": "sam@example.com"})


def test_a_project_needs_a_name_and_a_code_because_the_route_says_so():
    """``create_project`` is defined in the notebook and cannot be imported, so
    the guard is checked where it lives."""
    assert {item.name for item in entity("project").required_fields} == {"name", "project_code"}
    source = (Path(__file__).resolve().parents[1] / "run_backend.py").read_text(encoding="utf-8")
    body = source[source.index("async def create_project"):][:1200]
    assert 'data.get("name", "").strip()' in body and "Name is required" in body
    assert 'data.get("project_code", "").strip()' in body and "Project code is required" in body


class _NoUsers:
    """Stands in for the account registry where a route only needs the lookup."""

    @staticmethod
    def users_for_account(_account_id):
        return []


# ── completeness ──────────────────────────────────────────────────────────────

def test_a_missing_parent_is_reported_like_any_other_mandatory_field():
    missing = missing_required("task", {"name": "Pour slab"}, has_parent=False)
    assert [row["label"] for row in missing] == ["Project"]
    assert missing[0]["reference"] == "project"
    assert is_complete("task", {"name": "Pour slab"}) is True


def test_zero_is_an_answer_but_nothing_is_not():
    """A cost of nothing is a real figure; an unanswered cost is not."""
    assert missing_required("task_cost", {"amount": 0}) == []
    assert [row["name"] for row in missing_required("task_cost", {"amount": ""})] == ["amount"]
    assert [row["name"] for row in missing_required("task_cost", {})] == ["amount"]


def test_a_role_with_no_permissions_is_still_complete():
    """Permissions are optional: a named role a Super Admin fills in later is valid."""
    assert is_complete("role_type", {"name": "Site Lead", "permissions": []})


# ── coercion ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("written,expected", [
    ("2027-03-01", "2027-03-01"),
    ("2027/3/1", "2027-03-01"),
    ("14/03/2027", "2027-03-14"),
    ("2027-03-01T08:00:00Z", "2027-03-01"),
    ("some time in spring", ""),
    ("", ""),
])
def test_dates_are_read_however_the_document_wrote_them(written, expected):
    assert read_date(written) == expected
    assert coerce("task", "due_date", written) == expected


def test_money_goes_through_the_applications_own_parser():
    assert coerce("project_cost", "amount", "1200.5") == 1200.5
    with pytest.raises(HTTPException):
        coerce("project_cost", "amount", -1)
    with pytest.raises(HTTPException):
        coerce("project_cost", "amount", "lots")


def test_an_enum_is_matched_case_insensitively_or_refused():
    assert coerce("task", "status", "in progress") == "In Progress"
    with pytest.raises(HTTPException) as error:
        coerce("task", "status", "nearly done")
    assert "must be one of" in str(error.value.detail)


def test_coercion_ignores_anything_that_is_not_a_field_of_that_entity():
    fields = coerce_fields("task", {"name": "Pour slab", "id": "hacked", "salary": 10})
    assert fields == {"name": "Pour slab"}


def test_an_unknown_entity_is_refused_rather_than_invented():
    with pytest.raises(HTTPException):
        entity("sandwich")


# ── live choices ──────────────────────────────────────────────────────────────

def test_reference_choices_come_from_the_workspace(make_account, registry):
    context = make_account("owner@example.com")
    context.workspace.save_projects({"p1": {"id": "p1", "name": "Tower", "project_code": "TWR"}})
    mgmt = context.workspace.load_mgmt()
    mgmt["task_types"] = [{"id": "ta-1", "name": "Concrete Pour"}]
    context.workspace.save_mgmt(mgmt)

    projects = reference_choices("project", workspace=context.workspace)
    assert projects == [{"id": "p1", "label": "Tower", "detail": "TWR"}]
    assert [row["label"] for row in reference_choices("task_type", workspace=context.workspace)] \
        == ["Concrete Pour"]
    people = reference_choices("user", workspace=context.workspace, registry=registry,
                              account_id=context.account_id)
    assert [row["detail"] for row in people] == ["owner@example.com"]
    # The built-in roles are offered even before any custom one is made.
    assert "Super Admin" in [row["label"] for row in
                             reference_choices("role_type", workspace=context.workspace)]


# ── the guard against drift ───────────────────────────────────────────────────

def test_reconcile_refuses_to_start_when_the_schema_claims_a_field_that_is_not_there():
    def make_thin_task(*_args, **_kwargs):
        return {"id": "x", "name": ""}

    with pytest.raises(RuntimeError) as error:
        reconcile({"task": make_thin_task}, server_owned={"task": ("id",)})
    assert "entity_schema declares field" in str(error.value)
    assert "task" in str(error.value)


def test_reconcile_reports_a_field_the_constructor_gained_but_nobody_offered():
    from backend.tasks import make_task

    def make_task_plus(*_args, **_kwargs):
        return {**make_task({}, "p"), "hazard_rating": ""}

    notes = reconcile(
        {"task": make_task_plus},
        server_owned={"task": ("id", "project_id", "created_at", "updated_at", "parent_id", "cost")},
    )
    assert notes == ["task: hazard_rating not offered by onboarding"]


def test_reconcile_is_happy_with_the_real_constructors():
    from backend.company_settings import catalog_entry
    from backend.project_management import make_procurement_item
    from backend.tasks import make_task
    from backend.user_roles import make_role

    notes = reconcile(
        {
            "task": lambda: make_task({}, "p"),
            "task_type": lambda: catalog_entry({}, "ta"),
            "project_type": lambda: catalog_entry({}, "pr"),
            "role_type": lambda: make_role({}),
            "procurement": lambda: make_procurement_item({}, "p"),
        },
        server_owned={
            "task": ("id", "project_id", "created_at", "updated_at", "parent_id", "cost"),
            "task_type": ("id", "created_at"), "project_type": ("id", "created_at"),
            "role_type": ("id", "created_at", "updated_at"),
            "procurement": ("id", "project_id", "created_at", "updated_at"),
        },
    )
    assert notes == []
