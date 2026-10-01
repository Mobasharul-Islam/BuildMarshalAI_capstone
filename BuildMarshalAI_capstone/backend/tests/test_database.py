"""PostgreSQL storage: what the database layer itself guarantees.

Round-trips exactly (order, empty groups, awkward values), writes only what
changed, rolls back atomically, cascades account deletion, enforces unique
emails in the database, keeps the data directory paired with its database,
imports a JSON-era installation once -- and stores no records in files.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import psycopg
import pytest
from fastapi import HTTPException

from backend.accounts import (
    BINDING_FILE, AccountRegistry, DataDirectoryMismatch, hash_password, verify_password,
)
from backend.database import PROJECTS, TASKS, Database, default_database, normalise
from backend.json_storage_import import IMPORT_KEY, import_json_storage

from conftest import build_collection

PASSWORD = "Passw0rd!123"


@pytest.fixture
def registry(tmp_path):
    return AccountRegistry(tmp_path / "data", build_collection)


@pytest.fixture
def owner(registry):
    account, user = registry.register_account(
        account_name="Harbour Works", name="Owner", email="owner@example.com", password=PASSWORD)
    return registry, account, registry.workspace(account["id"])


# -- values ----------------------------------------------------------------------

def test_values_postgres_would_reject_are_made_storable():
    record = {"text": "page one\x00page two", "nan": float("nan"), "inf": float("inf"),
              "nested": [{"k\x00ey": "v\x00"}], "tuple": (1, 2), "path": Path("a/b")}
    assert normalise(record) == {"text": "page onepage two", "nan": None, "inf": None,
                                 "nested": [{"key": "v"}], "tuple": [1, 2], "path": str(Path("a/b"))}


def test_a_document_with_nul_characters_in_its_page_text_is_stored(owner):
    _, _, workspace = owner
    workspace.save_metadata({"documents": {"d1": {"name": "scan.pdf", "pages": [
        {"page_num": 1, "text_content": "Clause 2.1\x00 RFI period"}]}}})
    text = workspace.load_metadata()["documents"]["d1"]["pages"][0]["text_content"]
    assert text == "Clause 2.1 RFI period"


# -- round trips -----------------------------------------------------------------

def test_every_store_reads_back_what_was_saved(owner):
    _, _, workspace = owner
    projects = {f"p{n}": {"id": f"p{n}", "name": f"Project {n}", "project_code": f"P-{n}"}
                for n in (3, 1, 2)}                      # deliberately not sorted
    tasks = {"p3": [{"id": "t2", "name": "Second"}, {"id": "t1", "name": "First"}], "p1": [], "p2": []}
    procurement = {"p1": [{"id": "x", "name": "Lifts", "status": "Requested"}]}
    roles = [{"id": "r1", "name": "Site Supervisor", "permissions": ["task.create"]}]
    conversations = {"c1": {"id": "c1", "title": "RFIs", "messages": [{"role": "user", "content": "hi"}]}}
    drafts = {"d1": {"id": "d1", "status": "open", "items": {}}}
    generated = {"g1": {"id": "g1", "project_id": "p1", "doc_kind": "tender_summary"}}
    evidence = [{"id": "e1", "doc_id": "d1", "rating": "relevant"},
                {"id": "e2", "doc_id": "d1", "rating": "not_relevant"}]

    workspace.save_projects(projects)
    workspace.save_tasks(tasks)
    workspace.save_procurement(procurement)
    workspace.save_roles(roles)
    workspace.save_conversations(conversations)
    workspace.save_onboarding(drafts)
    workspace.save_generated(generated)
    workspace.save_evidence(evidence)
    workspace.save_company({"name": "Harbour Works Ltd", "website": "https://example.com"})

    assert workspace.load_projects() == projects
    assert list(workspace.load_projects()) == ["p3", "p1", "p2"]           # insertion order kept
    assert workspace.load_tasks() == tasks                                  # empty groups kept
    assert [t["id"] for t in workspace.load_tasks()["p3"]] == ["t2", "t1"]
    assert workspace.load_procurement() == procurement
    assert workspace.load_roles() == roles
    assert workspace.load_conversations() == conversations
    assert workspace.load_onboarding() == drafts
    assert workspace.load_generated() == generated
    assert workspace.load_evidence() == evidence
    assert workspace.load_company() == {"name": "Harbour Works Ltd", "website": "https://example.com"}


def test_the_management_store_keeps_catalogues_and_non_list_settings(owner):
    _, _, workspace = owner
    mgmt = workspace.load_mgmt()
    assert [t["name"] for t in mgmt["trades"]][:2] == ["Carpentry", "Concrete"]
    mgmt["vendors"].append({"id": "v1", "name": "Aquaseal"})
    mgmt["storage_policy"] = {"budget_mb": 512}                            # not a list
    mgmt["team_members"] = []
    workspace.save_mgmt(mgmt)
    again = workspace.load_mgmt()
    assert again == mgmt and list(again) == list(mgmt)


def test_list_items_without_ids_or_with_duplicate_ids_survive(owner):
    _, _, workspace = owner
    tasks = {"p1": [{"name": "no id"}, {"id": "dup", "name": "a"}, {"id": "dup", "name": "b"}]}
    workspace.save_tasks(tasks)
    assert workspace.load_tasks() == tasks


def test_metadata_keeps_keys_other_than_documents(owner):
    _, _, workspace = owner
    workspace.save_metadata({"documents": {"d1": {"name": "a.pdf", "digest": "abc"}}, "note": {"x": 1}})
    assert workspace.load_metadata() == {"documents": {"d1": {"name": "a.pdf", "digest": "abc"}},
                                         "note": {"x": 1}}


# -- writes only what changed ------------------------------------------------------

def test_a_save_writes_only_the_rows_that_changed(owner):
    registry, account, workspace = owner
    projects = {f"p{n}": {"id": f"p{n}", "name": f"Project {n}"} for n in range(50)}
    assert registry.db.sync_rows(PROJECTS, account["id"], [
        {"id": k, "name": v["name"], "project_code": "", "status": "", "data": v}
        for k, v in projects.items()]) == {"inserted": 50, "updated": 0, "deleted": 0}

    projects["p7"]["name"] = "Renamed"
    del projects["p49"]
    counts = registry.db.sync_rows(PROJECTS, account["id"], [
        {"id": k, "name": v["name"], "project_code": "", "status": "", "data": v}
        for k, v in projects.items()])
    assert counts == {"inserted": 0, "updated": 1, "deleted": 1}


def test_typed_columns_are_real_indexed_columns(owner):
    registry, account, workspace = owner
    workspace.save_tasks({"p1": [{"id": "t1", "name": "Pour slab", "status": "Blocked",
                                  "parent_id": None, "archived": False}]})
    with registry.db.transaction() as cur:
        cur.execute("SELECT project_id, name, status, archived FROM tasks WHERE account_id = %s",
                    (account["id"],))
        assert cur.fetchone() == {"project_id": "p1", "name": "Pour slab", "status": "Blocked",
                                  "archived": False}


# -- transactions ---------------------------------------------------------------------

def test_an_atomic_block_that_fails_leaves_nothing_behind(owner):
    registry, account, workspace = owner
    workspace.save_projects({"p1": {"id": "p1", "name": "Before"}})
    with pytest.raises(RuntimeError):
        with workspace.atomic():
            workspace.save_projects({"p1": {"id": "p1", "name": "During"}})
            registry.create_user(account_id=account["id"], name="New", email="new@example.com",
                                 password=PASSWORD)
            raise RuntimeError("boom")
    assert workspace.load_projects()["p1"]["name"] == "Before"
    assert registry.find_by_email("new@example.com") is None


def test_concurrent_saves_of_one_store_do_not_interleave(owner):
    registry, account, workspace = owner
    errors = []

    def writer(n):
        try:
            for i in range(10):
                workspace.save_projects({f"w{n}": {"id": f"w{n}", "name": f"{n}-{i}"}})
        except Exception as error:            # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    # The last complete save wins; no mixture of two saves, no duplicate keys.
    assert len(workspace.load_projects()) == 1


# -- accounts, users, sessions ------------------------------------------------------------

def test_deleting_an_account_cascades_through_every_table(owner):
    registry, account, workspace = owner
    workspace.save_projects({"p1": {"id": "p1", "name": "P"}})
    workspace.save_tasks({"p1": [{"id": "t1"}]})
    workspace.token_store("google").write(b"ciphertext")
    registry.issue_session(registry.find_by_email("owner@example.com"))
    registry.delete_account(account["id"])
    with registry.db.transaction() as cur:
        for table in ("accounts", "users", "sessions", "projects", "tasks", "catalog_entries",
                      "account_state", "oauth_token_stores"):
            cur.execute(f"SELECT count(*) AS n FROM {table}")
            assert cur.fetchone()["n"] == 0, table


def test_email_uniqueness_is_enforced_by_the_database(owner):
    registry, account, _ = owner
    # Straight past the application's own check: the unique index still refuses.
    with pytest.raises(psycopg.errors.UniqueViolation):
        with registry.db.transaction() as cur:
            cur.execute("""INSERT INTO users (id, account_id, email, data)
                           VALUES ('x', %s, 'OWNER@example.com', '{}')""", (account["id"],))
    with pytest.raises(HTTPException) as refused:
        registry.create_user(account_id=account["id"], name="Twin", email="Owner@Example.com",
                             password=PASSWORD)
    assert refused.value.status_code == 409


def test_sessions_are_rows_that_expire_and_revoke(owner):
    registry, _, _ = owner
    user = registry.find_by_email("owner@example.com")
    token = registry.issue_session(user)
    assert registry.resolve_session(token)["user_id"] == user["id"]
    with registry.db.transaction() as cur:
        cur.execute("UPDATE sessions SET expires_at = now() - interval '1 minute'")
    assert registry.resolve_session(token) is None
    with registry.db.transaction() as cur:
        cur.execute("SELECT count(*) AS n FROM sessions")
        assert cur.fetchone()["n"] == 0                  # an expired session is removed


def test_passwords_are_stored_hashed_in_the_database(owner):
    registry, _, _ = owner
    with registry.db.transaction() as cur:
        cur.execute("SELECT data::text AS raw FROM users")
        raw = cur.fetchone()["raw"]
    assert PASSWORD not in raw and "pbkdf2_sha256$" in raw


# -- the data directory belongs to one database -------------------------------------------

def test_a_data_directory_is_paired_with_its_database(tmp_path, owner):
    registry, _, _ = owner
    assert json.loads((registry.base_dir / BINDING_FILE).read_text())["id"]
    # The same directory again (a restart) is fine.
    AccountRegistry(registry.base_dir, build_collection)
    # Another directory against the same, populated database is refused.
    with pytest.raises(DataDirectoryMismatch):
        AccountRegistry(tmp_path / "somewhere-else", build_collection)


def test_a_deliberate_rebind_is_allowed(tmp_path, owner, monkeypatch):
    monkeypatch.setenv("BUILDMARSHAL_ALLOW_REBIND", "1")
    AccountRegistry(tmp_path / "moved", build_collection)
    assert default_database().get_meta("data_dir_binding")["path"].endswith("moved")


# -- no records in files ---------------------------------------------------------------

def test_a_whole_workflow_writes_no_json_record_files(owner):
    registry, account, workspace = owner
    workspace.save_projects({"p1": {"id": "p1", "name": "P"}})
    workspace.save_tasks({"p1": [{"id": "t1"}]})
    workspace.save_settings({"model": "m"})
    workspace.save_company({"name": "C"})
    workspace.save_roles([{"id": "r", "name": "R"}])
    workspace.save_evidence([{"id": "e"}])
    workspace.add_evidence({"id": "e2", "doc_id": "d", "rating": "relevant"})
    workspace.token_store("google").write(b"x")
    registry.issue_session(registry.find_by_email("owner@example.com"))
    stray = [p.relative_to(registry.base_dir).as_posix() for p in registry.base_dir.rglob("*")
             if p.is_file() and p.suffix in (".json", ".enc")]
    assert stray == [BINDING_FILE]


def test_evidence_appends_and_keeps_only_the_newest(owner):
    _, _, workspace = owner
    for n in range(7):
        workspace.add_evidence({"id": f"e{n}", "doc_id": "d", "rating": "relevant"}, keep=5)
    assert [row["id"] for row in workspace.load_evidence()] == ["e2", "e3", "e4", "e5", "e6"]


# -- importing a JSON-era installation ----------------------------------------------------

def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_a_json_era_installation_is_imported_once_and_its_files_kept(tmp_path):
    base = tmp_path / "old"
    account_id = "acc1"
    write(base / "accounts.json", {account_id: {"id": account_id, "name": "Old Co", "status": "Active",
                                                "owner_user_id": "u1", "created_at": "2026-08-01T00:00:00+00:00"}})
    write(base / "users.json", {
        "u1": {"id": "u1", "account_id": account_id, "name": "Old Owner", "email": "old@example.com",
               "password_hash": hash_password(PASSWORD), "role": "Super Admin", "is_owner": True,
               "status": "Active", "created_at": "2026-08-01T00:00:00+00:00"},
        "stray": {"id": "stray", "account_id": "gone", "email": "x@example.com"},
    })
    write(base / "sessions.json", {})
    root = base / "accounts" / account_id
    write(root / "projects.json", {"p1": {"id": "p1", "name": "Riverside", "project_code": "RVT"}})
    write(root / "tasks.json", {"p1": [{"id": "t1", "name": "Piling"}]})
    write(root / "metadata.json", {"documents": {"d1": {"name": "spec.pdf", "pages": []}}})
    write(root / "user_roles.json", [{"id": "r1", "name": "Site Supervisor", "permissions": []}])
    write(root / "settings.json", {"model": "old-model", "top_k": 7})
    write(root / "evidence_feedback.json", [{"id": "e1", "doc_id": "d1", "rating": "relevant"}])
    (root / "google_workspace_accounts.enc").write_bytes(b"encrypted-blob")
    (root / "documents").mkdir(parents=True)
    (root / "documents" / "d1.pdf").write_bytes(b"%PDF")

    registry = AccountRegistry(base, build_collection)
    report = import_json_storage(registry, base)
    assert report["accounts"] == 1 and report["users"] == 1
    assert report["users_skipped"] == [{"id": "stray", "reason": "no such account"}]

    workspace = registry.workspace(account_id)
    assert workspace.load_projects()["p1"]["name"] == "Riverside"
    assert workspace.load_tasks() == {"p1": [{"id": "t1", "name": "Piling"}]}
    assert workspace.load_metadata()["documents"]["d1"]["name"] == "spec.pdf"
    assert workspace.load_roles()[0]["name"] == "Site Supervisor"
    assert workspace.load_settings()["top_k"] == 7
    assert workspace.load_evidence()[0]["id"] == "e1"
    assert workspace.token_store("google").read() == b"encrypted-blob"
    user = registry.find_by_email("old@example.com")
    assert verify_password(PASSWORD, user["password_hash"])[0]      # the old login still works
    assert user["role"] == "Head (Super Admin)"     # a former built-in name is stored as the new one

    # The JSON files are kept, out of the way; uploaded files are untouched.
    backup = Path(report["backup"])
    assert (backup / "accounts.json").exists()
    assert (backup / "accounts" / account_id / "projects.json").exists()
    assert not (base / "accounts.json").exists() and not (root / "projects.json").exists()
    assert (root / "documents" / "d1.pdf").exists()

    # Once only.
    assert import_json_storage(registry, base) is None
    assert registry.db.get_meta(IMPORT_KEY)["status"] == "imported"


def test_a_failed_import_changes_nothing_and_can_run_again(tmp_path, monkeypatch):
    base = tmp_path / "old"
    write(base / "accounts.json", {"a": {"id": "a", "name": "A"}})
    write(base / "accounts" / "a" / "projects.json", {"p1": {"id": "p1"}})
    registry = AccountRegistry(base, build_collection)

    from backend import accounts as accounts_module
    original = accounts_module.AccountWorkspace.save_projects

    def broken(self, data):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(accounts_module.AccountWorkspace, "save_projects", broken)
    with pytest.raises(RuntimeError):
        import_json_storage(registry, base)
    assert registry.list_accounts() == []                  # rolled back as one transaction
    assert (base / "accounts.json").exists()               # and nothing was moved

    monkeypatch.setattr(accounts_module.AccountWorkspace, "save_projects", original)
    assert import_json_storage(registry, base)["accounts"] == 1


# -- configuration ---------------------------------------------------------------------

def test_without_a_database_url_the_error_says_what_to_do():
    from backend.database import DatabaseNotConfigured

    with pytest.raises(DatabaseNotConfigured, match="BUILDMARSHAL_DATABASE_URL"):
        Database("")


def test_migrations_are_recorded_and_idempotent():
    database = default_database()
    assert database.schema_version() >= 2
    assert database.migrate() == []


def test_migration_2_renames_roles_links_people_and_lists_projects(owner):
    """Rows written before migration 2 come out in the new shape."""
    registry, account, workspace = owner
    database = default_database()
    account_id = account["id"]
    sam = registry.create_user(account_id=account_id, name="Sam Field", email="sam@example.com",
                               password=PASSWORD, role="")
    twin_a = registry.create_user(account_id=account_id, name="Jo Twin", email="jo1@example.com",
                                  password=PASSWORD, role="")
    registry.create_user(account_id=account_id, name="Jo Twin", email="jo2@example.com",
                         password=PASSWORD, role="")
    workspace.save_projects({
        "p1": {"id": "p1", "name": "Tower", "project_code": "TWR", "manager": "sam field"},
        "p2": {"id": "p2", "name": "Annex", "project_code": "ANX", "manager": "Jo Twin"},
    })
    workspace.save_tasks({"p1": [{"id": "t1", "name": "Pour", "assignee": "Sam Field"},
                                 {"id": "t2", "name": "Tie", "assignee": "Jo Twin"}]})
    workspace.save_metadata({"documents": {
        "d1": {"name": "Spec.pdf", "project_id": "p1"}, "d2": {"name": "Loose.pdf"}}})
    with database.transaction() as cur:
        # Undo what this build's writers already do, to stand in for old rows.
        cur.execute("UPDATE users SET role = 'System Admin', data = jsonb_set(data, '{role}', '\"System Admin\"') "
                    "WHERE id = %s", (sam["id"],))
        cur.execute("UPDATE documents SET data = data - 'project_ids' WHERE account_id = %s", (account_id,))
        cur.execute("INSERT INTO account_state (account_id, key, data) VALUES (%s, 'settings', %s) "
                    "ON CONFLICT (account_id, key) DO UPDATE SET data = EXCLUDED.data",
                    (account_id, json.dumps({"top_k": 5, "voice_api_url": "https://x.ngrok-free.dev"})))
        cur.execute("DELETE FROM schema_migrations WHERE version = 2")
    assert database.migrate() == [2]

    with database.transaction() as cur:
        cur.execute("SELECT role, data->>'role' AS stored FROM users WHERE id = %s", (sam["id"],))
        row = cur.fetchone()
        assert (row["role"], row["stored"]) == ("Head (System Admin)", "Head (System Admin)")
        cur.execute("SELECT data FROM account_state WHERE account_id = %s AND key = 'settings'", (account_id,))
        assert "voice_api_url" not in cur.fetchone()["data"]
    projects = workspace.load_projects()
    assert projects["p1"]["manager_id"] == sam["id"]
    assert "manager_id" not in projects["p2"]          # two users share the name: left unlinked
    tasks = {t["id"]: t for t in workspace.load_tasks()["p1"]}
    assert tasks["t1"]["assignee_id"] == sam["id"] and "assignee_id" not in tasks["t2"]
    documents = workspace.load_metadata()["documents"]
    assert documents["d1"]["project_ids"] == ["p1"] and documents["d2"]["project_ids"] == []
    assert twin_a["id"]
