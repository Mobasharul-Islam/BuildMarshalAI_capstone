"""Permissions added after roles existed must not take anything away.

Trades, external companies, the contact directory, procurement and documents
used to be open to every member. They now have permissions of their own, and
the upgrade that introduced them grants them once to every role that already
existed -- so nobody loses an ability overnight -- while a role made afterwards
starts without them, and a key an administrator removes stays removed.
"""
from __future__ import annotations

from pathlib import Path

from backend import permissions as perms
from backend.accounts import AccountContext, AccountRegistry
from backend.tests.conftest import build_collection
from backend.user_roles import make_role

NEW_KEYS = {"trade.manage", "vendor.manage", "contact.manage", "procurement.manage",
            "document.upload", "document.delete"}


def test_the_new_permissions_are_in_the_catalogue() -> None:
    assert NEW_KEYS <= perms.PERMISSION_KEYS
    groups = {row["key"]: row["group"] for row in perms.PERMISSIONS}
    assert groups["document.upload"] == groups["document.delete"] == "Documents"


def test_an_existing_role_is_granted_them_once() -> None:
    roles = [{"name": "Foreman", "permissions": ["task.create"]}]
    assert perms.apply_permission_upgrades(roles) is True
    assert NEW_KEYS | {"task.create"} == set(roles[0]["permissions"])
    assert perms.apply_permission_upgrades(roles) is False, "a second pass must change nothing"


def test_a_key_an_administrator_removes_stays_removed() -> None:
    roles = [{"name": "Foreman", "permissions": ["task.create"]}]
    perms.apply_permission_upgrades(roles)
    roles[0]["permissions"] = ["task.create"]          # taken away on the roles page
    perms.apply_permission_upgrades(roles)
    assert roles[0]["permissions"] == ["task.create"]


def test_a_role_made_now_starts_without_them() -> None:
    role = make_role({"name": "Site Engineer", "permissions": ["task.create"]})
    assert perms.apply_permission_upgrades([role]) is False
    assert role["permissions"] == ["task.create"]


def test_a_role_file_from_before_is_upgraded_when_its_workspace_first_loads(tmp_path: Path) -> None:
    data = tmp_path / "data"
    registry = AccountRegistry(data, build_collection)
    account, _owner = registry.register_account(account_name="Old Co", name="Owner",
                                                email="owner@example.test", password="Passw0rd!123")
    # A roles file written before the upgrade existed: no marker, no new keys.
    registry.workspace(account["id"]).save_roles(
        [{"id": "role-1", "name": "Foreman", "permissions": ["task.create"]}])

    restarted = AccountRegistry(data, build_collection)        # the next process start
    workspace = restarted.workspace(account["id"])
    role = workspace.load_roles()[0]
    assert NEW_KEYS <= set(role["permissions"])
    assert role["upgrades"] == list(perms.UPGRADE_IDS)

    member = restarted.create_user(account_id=account["id"], name="Rahim",
                                   email="rahim@example.test", password="Passw0rd!123",
                                   role="Foreman")
    context = AccountContext(user=member, account=account, workspace=workspace, token="t")
    assert context.can("trade.manage") and context.can("document.upload")


def test_a_role_without_the_keys_is_refused(tmp_path: Path) -> None:
    registry = AccountRegistry(tmp_path / "data", build_collection)
    account, _owner = registry.register_account(account_name="New Co", name="Owner",
                                                email="owner2@example.test", password="Passw0rd!123")
    workspace = registry.workspace(account["id"])
    workspace.save_roles([make_role({"name": "Reader", "permissions": []})])
    member = registry.create_user(account_id=account["id"], name="Karim",
                                  email="karim@example.test", password="Passw0rd!123", role="Reader")
    context = AccountContext(user=member, account=account, workspace=workspace, token="t")
    for key in NEW_KEYS:
        assert not context.can(key), key
