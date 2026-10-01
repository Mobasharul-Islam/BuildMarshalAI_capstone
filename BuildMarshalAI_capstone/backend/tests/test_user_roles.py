"""User Roles: the catalogue, who may manage it, and how permissions resolve."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.accounts import AccountContext
from backend.permissions import (
    BUILTIN_ROLES,
    PERMISSION_KEYS,
    canonical_role,
    clean_permissions,
    is_builtin_admin,
    is_super_admin,
    permission_catalogue,
    resolve_permissions,
    role_names,
)
from backend.user_roles import register_user_role_routes, validate_role_name


# ── the catalogue ─────────────────────────────────────────────────────────────

def test_the_catalogue_covers_everything_the_brief_asked_for():
    for key in (
        "task.create", "task.delete", "project.create",
        "project.cost.additional", "project.cost.task", "project.cost.base",
        "project.people.manage", "task_type.manage", "project_type.manage",
        "task.update.start_time", "task.update.end_time", "task.update.priority",
        "task.update.status", "task.update.assignee", "task.update.trade",
    ):
        assert key in PERMISSION_KEYS, f"{key} is not in the catalogue"


def test_every_permission_has_a_name_a_description_and_a_group():
    for group in permission_catalogue():
        assert group["group"]
        for entry in group["permissions"]:
            assert entry["name"] and entry["description"] and entry["key"]


def test_role_management_is_not_offered_as_a_permission():
    """Head (Super Admin) authority must not be delegatable through a custom role."""
    forbidden = ("role", "permission", "company")
    for key in PERMISSION_KEYS:
        assert not any(word in key.split(".")[0] for word in forbidden), key


def test_unknown_permission_keys_are_dropped_rather_than_stored():
    cleaned = clean_permissions(["task.create", "not.a.permission", "task.create"])
    assert cleaned == ["task.create"]


# ── resolution ────────────────────────────────────────────────────────────────

def test_builtin_administrators_hold_everything():
    for role in BUILTIN_ROLES:
        assert resolve_permissions({"role": role}, []) == PERMISSION_KEYS
    assert resolve_permissions({"role": "Anything", "is_owner": True}, []) == PERMISSION_KEYS


def test_a_custom_role_holds_exactly_what_it_was_given():
    roles = [{"name": "Site Lead", "permissions": ["task.create", "task.update.status"]}]
    held = resolve_permissions({"role": "Site Lead"}, roles)
    assert held == {"task.create", "task.update.status"}


def test_role_matching_ignores_case():
    roles = [{"name": "Site Lead", "permissions": ["task.create"]}]
    assert resolve_permissions({"role": "site lead"}, roles) == {"task.create"}


def test_an_unknown_or_missing_role_holds_nothing():
    """Fail closed: a deleted role must not leave its holders with free rein."""
    assert resolve_permissions({"role": "Deleted"}, []) == frozenset()
    assert resolve_permissions({"role": ""}, []) == frozenset()
    assert resolve_permissions({}, []) == frozenset()


def test_only_super_admin_and_owners_count_as_super_admin():
    assert is_super_admin({"role": "Head (Super Admin)"})
    assert is_super_admin({"role": "Site Lead", "is_owner": True})
    assert not is_super_admin({"role": "Head (System Admin)"})
    assert not is_super_admin({"role": "Site Lead"})


def test_the_builtins_carry_their_new_names():
    assert BUILTIN_ROLES == ("Head (Super Admin)", "Head (System Admin)")


def test_a_former_builtin_name_still_means_the_builtin():
    """An older client or an import may still send the old labels."""
    assert canonical_role("Super Admin") == "Head (Super Admin)"
    assert canonical_role("system admin") == "Head (System Admin)"
    assert canonical_role("Site Lead") == "Site Lead"
    assert is_super_admin({"role": "Super Admin"})
    assert is_builtin_admin({"role": "System Admin"})
    assert not is_super_admin({"role": "System Admin"})


def test_no_custom_role_may_take_a_builtin_name_old_or_new(owner, registry):
    client = build_app(owner, registry)
    for name in ("Head (Super Admin)", "Head (System Admin)", "Super Admin", "system admin"):
        refused = client.post("/api/user-roles", json={"name": name})
        assert refused.status_code == 409, name


def test_the_builtin_rows_have_stable_ids(owner, registry):
    roles = build_app(owner, registry).get("/api/user-roles").json()["roles"]
    builtin = {r["name"]: r["id"] for r in roles if r["builtin"]}
    assert builtin == {"Head (Super Admin)": "builtin-super-admin",
                       "Head (System Admin)": "builtin-system-admin"}


def test_assignable_names_are_the_builtins_plus_created_roles():
    names = role_names([{"name": "Site Lead"}, {"name": "Estimator"}])
    assert names == ["Head (Super Admin)", "Head (System Admin)", "Site Lead", "Estimator"]


# ── routes ────────────────────────────────────────────────────────────────────

def build_app(context: AccountContext, registry) -> TestClient:
    app = FastAPI()

    async def require_account():
        return context

    register_user_role_routes({"app": app, "require_account": require_account,
                               "ACCOUNT_REGISTRY": registry})
    return TestClient(app)


def as_role(context: AccountContext, role: str) -> AccountContext:
    return AccountContext(user={**context.user, "is_owner": False, "role": role},
                          account=context.account, workspace=context.workspace,
                          token=context.token)


@pytest.fixture
def owner(make_account):
    return make_account("owner@example.com")


def test_the_builtin_roles_are_always_listed_and_never_editable(owner, registry):
    body = build_app(owner, registry).get("/api/user-roles").json()
    builtins = [r for r in body["roles"] if r["builtin"]]
    assert [r["name"] for r in builtins] == list(BUILTIN_ROLES)
    assert all(r["editable"] is False for r in builtins)
    assert all(set(r["permissions"]) == PERMISSION_KEYS for r in builtins)


def test_a_super_admin_can_create_edit_and_delete_a_role(owner, registry):
    client = build_app(owner, registry)
    created = client.post("/api/user-roles", json={
        "name": "Site Lead", "description": "Runs the site",
        "permissions": ["task.create", "task.update.status", "nonsense"]})
    assert created.status_code == 200
    role = created.json()
    # The unknown key was dropped rather than stored.
    assert role["permissions"] == ["task.create", "task.update.status"]

    updated = client.put(f"/api/user-roles/{role['id']}",
                         json={"permissions": ["task.create"]})
    assert updated.status_code == 200 and updated.json()["permissions"] == ["task.create"]

    assert client.delete(f"/api/user-roles/{role['id']}").status_code == 200
    assert [r["name"] for r in client.get("/api/user-roles").json()["roles"]] == list(BUILTIN_ROLES)


@pytest.mark.parametrize("role", ["Head (System Admin)", "Site Lead", ""])
def test_only_a_super_admin_may_manage_roles(owner, registry, role):
    """Head (System Admin) included: role management is Head (Super Admin) work alone."""
    build_app(owner, registry).post("/api/user-roles", json={"name": "Site Lead"})
    client = build_app(as_role(owner, role), registry)

    listed = client.get("/api/user-roles")
    assert listed.status_code == 200, "everyone may look"
    assert listed.json()["can_manage"] is False

    existing = next(r for r in listed.json()["roles"] if not r["builtin"])
    assert client.post("/api/user-roles", json={"name": "Sneaky"}).status_code == 403
    assert client.put(f"/api/user-roles/{existing['id']}",
                      json={"name": "Sneaky"}).status_code == 403
    assert client.delete(f"/api/user-roles/{existing['id']}").status_code == 403


def test_a_builtin_name_cannot_be_redefined(owner, registry):
    client = build_app(owner, registry)
    for name in BUILTIN_ROLES:
        clash = client.post("/api/user-roles", json={"name": name})
        assert clash.status_code == 409 and "built-in" in clash.json()["detail"]


def test_duplicate_and_blank_role_names_are_refused(owner, registry):
    client = build_app(owner, registry)
    client.post("/api/user-roles", json={"name": "Site Lead"})
    assert client.post("/api/user-roles", json={"name": "site lead"}).status_code == 409
    assert client.post("/api/user-roles", json={"name": "  "}).status_code == 422


def test_renaming_a_role_follows_the_people_holding_it(owner, registry):
    client = build_app(owner, registry)
    role = client.post("/api/user-roles", json={"name": "Site Lead"}).json()
    member = registry.create_user(account_id=owner.account_id, name="Sam",
                                  email="sam@example.com", password="Passw0rd!123",
                                  role="Site Lead")

    renamed = client.put(f"/api/user-roles/{role['id']}", json={"name": "Site Manager"})
    assert renamed.status_code == 200 and renamed.json()["renamed_users"] == 1
    assert registry.get_user(member["id"])["role"] == "Site Manager"


def test_a_role_in_use_cannot_be_deleted(owner, registry):
    client = build_app(owner, registry)
    role = client.post("/api/user-roles", json={"name": "Site Lead"}).json()
    registry.create_user(account_id=owner.account_id, name="Sam", email="sam@example.com",
                         password="Passw0rd!123", role="Site Lead")

    blocked = client.delete(f"/api/user-roles/{role['id']}")
    assert blocked.status_code == 409
    assert "assigned to 1 user" in blocked.json()["detail"]


def test_the_permission_catalogue_route_is_readable_by_any_member(owner, registry):
    client = build_app(as_role(owner, "Site Lead"), registry)
    body = client.get("/api/permissions").json()
    assert body["total"] == len(PERMISSION_KEYS)
    assert [g["group"] for g in body["groups"]]


def test_roles_are_isolated_per_account(make_account, registry):
    first = make_account("first@example.com")
    second = make_account("second@example.com", name="Second")
    build_app(first, registry).post("/api/user-roles", json={"name": "Only Here"})

    names = [r["name"] for r in build_app(second, registry).get("/api/user-roles").json()["roles"]]
    assert "Only Here" not in names
