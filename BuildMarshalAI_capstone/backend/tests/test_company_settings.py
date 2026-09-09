"""Company profile, task types, and project types: shape and who may change them."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.accounts import AccountContext
from backend.company_settings import (
    apply_company_updates,
    company_profile,
    count_project_type_usage,
    count_task_type_usage,
    empty_company,
    register_company_settings_routes,
    validate_company,
)


# ── the profile record ────────────────────────────────────────────────────────

def test_a_new_workspace_is_seeded_from_what_the_account_already_knows():
    profile = company_profile(
        None,
        {"company_name": "Marshal Build Co", "company_phone": "+61 2 5550 1000"},
        {"name": "Marshal workspace"},
    )
    assert profile["name"] == "Marshal Build Co"
    assert profile["phone"] == "+61 2 5550 1000"
    # Nothing invented for the fields nobody has filled in.
    assert profile["legal_name"] == "" and profile["tax_id"] == ""


def test_the_account_name_stands_in_until_a_company_name_is_given():
    assert company_profile(None, {}, {"name": "Marshal workspace"})["name"] == "Marshal workspace"


def test_stored_values_win_over_the_seeded_ones():
    profile = company_profile({"name": "Renamed Pty Ltd"}, {"company_name": "Old Name"}, {})
    assert profile["name"] == "Renamed Pty Ltd"


def test_an_edit_records_who_made_it():
    profile = apply_company_updates(empty_company(), {"name": "Marshal"}, {"name": "Dana"})
    assert profile["name"] == "Marshal" and profile["updated_by"] == "Dana"
    assert profile["updated_at"]


def test_unknown_fields_are_ignored_rather_than_stored():
    profile = apply_company_updates(empty_company(), {"name": "M", "role": "System Admin"}, {})
    assert "role" not in profile


@pytest.mark.parametrize("payload, message", [
    ({"name": "  "}, "cannot be empty"),
    ({"email": "not-an-address"}, "not a valid address"),
    ({"contact_email": "nope@nodot"}, "not a valid address"),
    ({"website": "buildmarshal.ai"}, "must start with http"),
])
def test_invalid_details_are_refused_with_a_specific_reason(payload, message):
    with pytest.raises(HTTPException) as raised:
        validate_company(payload)
    assert message in raised.value.detail


def test_an_absent_name_key_is_not_treated_as_a_blank_name():
    validate_company({"phone": "+61 2 5550 1000"})  # a partial edit must not trip the check


# ── usage counting ────────────────────────────────────────────────────────────

def test_task_type_usage_is_counted_across_every_project():
    tasks = {"p1": [{"task_type": "Inspection"}, {"task_type": "Phase"}],
             "p2": [{"task_type": "inspection"}]}
    assert count_task_type_usage(tasks, "Inspection") == 2
    assert count_task_type_usage(tasks, "Delivery") == 0


def test_project_type_usage_ignores_case():
    projects = {"p1": {"type": "Commercial"}, "p2": {"type": "commercial"}, "p3": {"type": ""}}
    assert count_project_type_usage(projects, "Commercial") == 2


# ── routes ────────────────────────────────────────────────────────────────────

def build_app(context: AccountContext) -> TestClient:
    app = FastAPI()

    async def require_account():
        return context

    register_company_settings_routes({"app": app, "require_account": require_account})
    return TestClient(app)


def demote(context: AccountContext, role: str = "User") -> AccountContext:
    """Turn the owner into an ordinary member of the same account."""
    return AccountContext(
        user={**context.user, "is_owner": False, "role": role},
        account=context.account, workspace=context.workspace, token=context.token,
    )


def test_an_administrator_may_read_and_edit_the_company(make_account):
    client = build_app(make_account("owner@example.com"))

    read = client.get("/api/company").json()
    assert read["can_edit"] is True

    saved = client.put("/api/company", json={
        "name": "Marshal Build Co", "city": "Sydney", "website": "https://buildmarshal.ai",
    })
    assert saved.status_code == 200
    assert saved.json()["company"]["city"] == "Sydney"
    # And it is durable, not just echoed back.
    assert client.get("/api/company").json()["company"]["name"] == "Marshal Build Co"


@pytest.mark.parametrize("role", ["Super Admin", "System Admin"])
def test_every_administrator_role_may_edit(make_account, role):
    slug = role.replace(" ", "")
    client = build_app(demote(make_account(slug + "@example.com"), role))
    assert client.get("/api/company").json()["can_edit"] is True
    assert client.put("/api/company", json={"name": "Marshal"}).status_code == 200


@pytest.mark.parametrize("role", ["User", "Guest", "Project Manager", "HR"])
def test_an_ordinary_member_may_read_but_not_write(make_account, role):
    client = build_app(demote(make_account(role + "@example.com"), role))

    read = client.get("/api/company")
    assert read.status_code == 200
    assert read.json()["can_edit"] is False

    # The server refuses regardless of what the client chose to display.
    blocked = client.put("/api/company", json={"name": "Hijacked"})
    assert blocked.status_code == 403
    assert "administrator" in blocked.json()["detail"]


def test_editing_the_company_keeps_the_settings_copy_in_step(make_account):
    context = make_account("owner@example.com")
    client = build_app(context)
    client.put("/api/company", json={"name": "Marshal Build Co", "email": "hq@example.com"})
    settings = context.workspace.load_settings()
    assert settings["company_name"] == "Marshal Build Co"
    assert settings["company_email"] == "hq@example.com"


def test_one_accounts_company_is_invisible_to_another(make_account):
    first = make_account("first@example.com")
    second = make_account("second@example.com", name="Second")
    build_app(first).put("/api/company", json={"name": "First Co", "tax_id": "111"})

    other = build_app(second).get("/api/company").json()["company"]
    assert other["name"] != "First Co" and other["tax_id"] == ""


# ── the type catalogs ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("segment, key", [("task-types", "task_types"),
                                          ("project-types", "project_types")])
def test_catalogs_ship_with_defaults_and_report_editability(make_account, segment, key):
    client = build_app(make_account(segment + "@example.com"))
    body = client.get("/api/" + segment).json()
    assert body["total"] == len(body[key]) > 0
    assert body["can_edit"] is True


@pytest.mark.parametrize("segment, key", [("task-types", "task_types"),
                                          ("project-types", "project_types")])
def test_an_administrator_can_add_and_remove_a_type(make_account, segment, key):
    client = build_app(make_account("admin-" + segment + "@example.com"))

    created = client.post("/api/" + segment, json={"name": "Handover", "description": "Final"})
    assert created.status_code == 200
    entry = created.json()
    assert entry["name"] == "Handover" and entry["status"] == "Active"
    assert "Handover" in [item["name"] for item in client.get("/api/" + segment).json()[key]]

    removed = client.delete("/api/" + segment + "/" + entry["id"])
    assert removed.status_code == 200
    assert "Handover" not in [item["name"] for item in client.get("/api/" + segment).json()[key]]


@pytest.mark.parametrize("segment", ["task-types", "project-types"])
def test_an_ordinary_member_may_list_but_not_change_a_catalog(make_account, segment):
    client = build_app(demote(make_account("member-" + segment + "@example.com")))

    listed = client.get("/api/" + segment)
    assert listed.status_code == 200 and listed.json()["can_edit"] is False

    existing = listed.json()[segment.replace("-", "_")][0]["id"]
    assert client.post("/api/" + segment, json={"name": "Sneaky"}).status_code == 403
    assert client.put("/api/" + segment + "/" + existing, json={"name": "Sneaky"}).status_code == 403
    assert client.delete("/api/" + segment + "/" + existing).status_code == 403


@pytest.mark.parametrize("segment", ["task-types", "project-types"])
def test_a_blank_or_duplicate_name_is_refused(make_account, segment):
    client = build_app(make_account("dupe-" + segment + "@example.com"))

    assert client.post("/api/" + segment, json={"name": "   "}).status_code == 422
    client.post("/api/" + segment, json={"name": "Handover"})
    clash = client.post("/api/" + segment, json={"name": "handover"})
    assert clash.status_code == 409 and "already exists" in clash.json()["detail"]


@pytest.mark.parametrize("segment", ["task-types", "project-types"])
def test_renaming_onto_another_entry_is_refused(make_account, segment):
    client = build_app(make_account("rename-" + segment + "@example.com"))
    first = client.post("/api/" + segment, json={"name": "Handover"}).json()
    client.post("/api/" + segment, json={"name": "Defects"})

    clash = client.put("/api/" + segment + "/" + first["id"], json={"name": "Defects"})
    assert clash.status_code == 409
    # Renaming an entry to what it already is stays allowed.
    same = client.put("/api/" + segment + "/" + first["id"], json={"name": "Handover"})
    assert same.status_code == 200


@pytest.mark.parametrize("segment", ["task-types", "project-types"])
def test_an_unknown_entry_is_not_found(make_account, segment):
    client = build_app(make_account("missing-" + segment + "@example.com"))
    assert client.put("/api/" + segment + "/nope", json={"name": "X"}).status_code == 404
    assert client.delete("/api/" + segment + "/nope").status_code == 404


def test_a_task_type_in_use_cannot_be_deleted(make_account):
    context = make_account("inuse-task@example.com")
    client = build_app(context)
    entry = client.post("/api/task-types", json={"name": "Handover"}).json()
    context.workspace.save_tasks({"p1": [{"id": "t1", "task_type": "Handover"}]})

    blocked = client.delete("/api/task-types/" + entry["id"])
    assert blocked.status_code == 409
    assert "used by 1 task" in blocked.json()["detail"]

    # Once nothing references it, the delete goes through.
    context.workspace.save_tasks({"p1": [{"id": "t1", "task_type": "Phase"}]})
    assert client.delete("/api/task-types/" + entry["id"]).status_code == 200


def test_a_project_type_in_use_cannot_be_deleted(make_account):
    context = make_account("inuse-project@example.com")
    client = build_app(context)
    entry = client.post("/api/project-types", json={"name": "Marine"}).json()
    context.workspace.save_projects({"p1": {"id": "p1", "type": "Marine"},
                                     "p2": {"id": "p2", "type": "Marine"}})

    blocked = client.delete("/api/project-types/" + entry["id"])
    assert blocked.status_code == 409
    assert "used by 2 projects" in blocked.json()["detail"]


def test_catalogs_are_isolated_per_account(make_account):
    first = make_account("cat-first@example.com")
    second = make_account("cat-second@example.com", name="Second")
    build_app(first).post("/api/task-types", json={"name": "Only Here"})

    names = [item["name"] for item in build_app(second).get("/api/task-types").json()["task_types"]]
    assert "Only Here" not in names
