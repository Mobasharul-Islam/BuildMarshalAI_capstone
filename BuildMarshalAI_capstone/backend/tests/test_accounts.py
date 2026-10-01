"""Account creation, authentication, and cross-account isolation."""

import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import accounts as accounts_module
from backend.user_roles import register_user_role_routes
from backend.accounts import (
    hash_password,
    migrate_legacy_workspace,
    register_account_routes,
    safe_identifier,
    verify_password,
)

from conftest import build_collection


PASSWORD = "Passw0rd!123"


@pytest.fixture
def api(tmp_path):
    """A FastAPI app with only the account routes mounted."""
    app = FastAPI()
    namespace = {
        "app": app,
        "BASE_DIR": tmp_path / "data",
        "build_account_collection": build_collection,
    }
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    service = register_account_routes(namespace)
    # Roles are created through their own routes, so a test that assigns one
    # needs them mounted too.
    register_user_role_routes(namespace)
    return TestClient(app), namespace, service["registry"]


def register(client, email, name="Owner", account_name="Workspace"):
    response = client.post("/api/auth/register", json={
        "name": name, "email": email, "password": PASSWORD, "account_name": account_name,
    })
    assert response.status_code == 200, response.text
    return response.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── password handling ─────────────────────────────────────────────────────────

def test_passwords_are_salted_and_never_repeat():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second
    assert PASSWORD not in first
    assert verify_password(PASSWORD, first) == (True, False)
    assert verify_password("wrong", first) == (False, False)


def test_legacy_sha256_hash_still_verifies_and_asks_for_rehash():
    legacy = hashlib.sha256(b"admin123").hexdigest()
    assert verify_password("admin123", legacy) == (True, True)
    # needs_rehash describes the stored format; callers only act on it once the
    # password itself has verified.
    assert verify_password("nope", legacy) == (False, True)
    assert verify_password("admin123", "not-a-hash") == (False, False)


def weak_pbkdf2(plain: str, rounds: int = 1_000) -> str:
    """A PBKDF2 hash as an older build, with a lower work factor, stored it."""
    salt = b"0123456789abcdef"
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def test_a_hash_below_the_current_work_factor_asks_for_rehash():
    assert accounts_module.PBKDF2_ITERATIONS >= 600_000     # OWASP's current figure
    assert verify_password(PASSWORD, weak_pbkdf2(PASSWORD)) == (True, True)
    assert verify_password(PASSWORD, hash_password(PASSWORD)) == (True, False)


def test_sign_in_upgrades_a_weak_hash_without_signing_other_devices_out(api):
    client, _, registry = api
    other_device = register(client, "upgrade@example.com")["token"]
    user_id = registry.find_by_email("upgrade@example.com")["id"]
    # As an older build stored it: the same password at a lower work factor.
    with registry.db.transaction() as cur:
        cur.execute("UPDATE users SET data = jsonb_set(data, '{password_hash}', to_jsonb(%s::text)) "
                    "WHERE id = %s", (weak_pbkdf2(PASSWORD), user_id))

    response = client.post("/api/auth/login", json={"email": "upgrade@example.com", "password": PASSWORD})
    assert response.status_code == 200

    stored = registry.get_user(user_id)["password_hash"]
    assert stored.split("$")[1] == str(accounts_module.PBKDF2_ITERATIONS)
    assert verify_password(PASSWORD, stored) == (True, False)
    # The credential did not change, so no session was revoked.
    assert client.get("/api/auth/me", headers=auth(other_device)).status_code == 200


def test_an_unknown_email_costs_one_key_derivation_like_a_wrong_password(api, monkeypatch):
    client, _, _ = api
    register(client, "timing@example.com")
    derivations = []
    real = hashlib.pbkdf2_hmac

    def counting(*args, **kwargs):
        derivations.append(args[3])
        return real(*args, **kwargs)

    monkeypatch.setattr(accounts_module.hashlib, "pbkdf2_hmac", counting)
    for email, password in (("nobody@example.com", PASSWORD), ("timing@example.com", "wrong-pass")):
        derivations.clear()
        assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 401
        # One derivation at the current work factor, whichever way the login fails.
        assert derivations == [accounts_module.PBKDF2_ITERATIONS], email


def test_safe_identifier_rejects_traversal():
    assert safe_identifier("../../etc/passwd", fallback="fallback") == "etcpasswd"
    assert safe_identifier("..", fallback="fallback") == "fallback"
    assert safe_identifier("", fallback="fallback") == "fallback"
    assert safe_identifier("doc-123_v2.pdf") == "doc-123_v2.pdf"


# ── authentication ────────────────────────────────────────────────────────────

def test_register_creates_account_owner_and_session(api):
    client, _, registry = api
    payload = register(client, "owner@example.com")
    assert payload["user"]["is_owner"] is True
    assert "password_hash" not in payload["user"]
    assert payload["account"]["name"] == "Workspace"
    assert payload["settings"]["top_k"] == 5
    assert registry.workspace(payload["account"]["id"]).root.exists()


def test_duplicate_email_is_rejected_across_accounts(api):
    client, _, _ = api
    register(client, "dup@example.com")
    response = client.post("/api/auth/register", json={
        "name": "Other", "email": "DUP@example.com", "password": PASSWORD,
    })
    assert response.status_code == 409


def test_short_passwords_are_rejected(api):
    client, _, _ = api
    assert client.post("/api/auth/register", json={
        "name": "Weak", "email": "weak@example.com", "password": "short",
    }).status_code == 422


def test_login_logout_and_token_lifecycle(api):
    client, _, _ = api
    register(client, "login@example.com")

    assert client.post("/api/auth/login", json={
        "email": "login@example.com", "password": "wrong",
    }).status_code == 401
    assert client.post("/api/auth/login", json={
        "email": "missing@example.com", "password": PASSWORD,
    }).status_code == 401

    token = client.post("/api/auth/login", json={
        "email": "LOGIN@example.com", "password": PASSWORD,
    }).json()["token"]
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 200

    assert client.post("/api/auth/logout", headers=auth(token)).status_code == 200
    # The token must stop working the moment the session is revoked.
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 401


def test_unauthenticated_and_forged_tokens_are_rejected(api):
    client, _, _ = api
    payload = register(client, "forge@example.com")
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=auth("not-a-token")).status_code == 401
    # A user id was the credential before this change; it must not be one now.
    assert client.get("/api/auth/me", headers=auth(payload["user"]["id"])).status_code == 401


def test_password_change_revokes_other_sessions(api):
    client, _, _ = api
    first = register(client, "rotate@example.com")["token"]
    second = client.post("/api/auth/login", json={
        "email": "rotate@example.com", "password": PASSWORD,
    }).json()["token"]

    changed = client.put("/api/auth/password", headers=auth(second), json={
        "current_password": PASSWORD, "new_password": "N3wPassw0rd!",
    })
    assert changed.status_code == 200
    assert client.get("/api/auth/me", headers=auth(first)).status_code == 401
    assert client.get("/api/auth/me", headers=auth(changed.json()["token"])).status_code == 200


def make_role(client, token, name="Member", permissions=()):
    """Roles are created per account; nothing but the two built-ins is shipped."""
    response = client.post("/api/user-roles", headers=auth(token),
                           json={"name": name, "permissions": list(permissions)})
    assert response.status_code == 200, response.json()
    return response.json()


def test_deactivated_user_cannot_sign_in(api):
    client, _, registry = api
    owner = register(client, "boss@example.com")
    make_role(client, owner["token"])
    member = client.post("/api/users", headers=auth(owner["token"]), json={
        "name": "Member", "email": "member@example.com", "password": PASSWORD, "role": "Member",
    }).json()

    member_token = client.post("/api/auth/login", json={
        "email": "member@example.com", "password": PASSWORD,
    }).json()["token"]
    assert client.get("/api/auth/me", headers=auth(member_token)).status_code == 200

    assert client.delete(f"/api/users/{member['id']}", headers=auth(owner["token"])).status_code == 200
    assert client.get("/api/auth/me", headers=auth(member_token)).status_code == 401
    assert client.post("/api/auth/login", json={
        "email": "member@example.com", "password": PASSWORD,
    }).status_code == 403


def test_owner_cannot_be_deactivated(api):
    client, _, _ = api
    owner = register(client, "owner2@example.com")
    response = client.delete(f"/api/users/{owner['user']['id']}", headers=auth(owner["token"]))
    assert response.status_code == 409


def test_non_admin_member_cannot_create_users(api):
    client, _, _ = api
    owner = register(client, "admin@example.com")
    make_role(client, owner["token"])
    client.post("/api/users", headers=auth(owner["token"]), json={
        "name": "Plain", "email": "plain@example.com", "password": PASSWORD, "role": "Member",
    })
    plain = client.post("/api/auth/login", json={
        "email": "plain@example.com", "password": PASSWORD,
    }).json()["token"]

    assert client.post("/api/users", headers=auth(plain), json={
        "name": "Another", "email": "another@example.com", "password": PASSWORD,
    }).status_code == 403
    # A member may still update their own profile.
    assert client.put("/api/auth/profile", headers=auth(plain), json={"phone": "555"}).status_code == 200


# ── isolation ─────────────────────────────────────────────────────────────────

def test_members_are_scoped_to_their_own_account(api):
    client, _, _ = api
    first = register(client, "a@example.com", account_name="Alpha")
    second = register(client, "b@example.com", account_name="Beta")

    client.post("/api/users", headers=auth(first["token"]), json={
        "name": "Alpha Member", "email": "am@example.com", "password": PASSWORD,
    })

    alpha_users = client.get("/api/users", headers=auth(first["token"])).json()
    beta_users = client.get("/api/users", headers=auth(second["token"])).json()
    assert alpha_users["total"] == 2
    assert beta_users["total"] == 1
    assert {u["email"] for u in beta_users["users"]} == {"b@example.com"}

    # A valid id from the other account must be indistinguishable from a missing one.
    other_id = first["user"]["id"]
    assert client.get(f"/api/users/{other_id}", headers=auth(second["token"])).status_code == 404
    assert client.put(f"/api/users/{other_id}", headers=auth(second["token"]),
                      json={"name": "hijacked"}).status_code == 404
    assert client.delete(f"/api/users/{other_id}", headers=auth(second["token"])).status_code == 404
    assert client.get(f"/api/users/{other_id}", headers=auth(first["token"])).json()["name"] == "Owner"


def test_settings_and_conversations_are_per_account(api):
    client, _, _ = api
    first = register(client, "s1@example.com")
    second = register(client, "s2@example.com")

    client.put("/api/account/settings", headers=auth(first["token"]),
               json={"top_k": 17, "company_name": "Alpha Construction"})
    client.put("/api/conversations", headers=auth(first["token"]), json={
        "conversations": {"c1": {"id": "c1", "title": "Alpha chat", "messages": []}},
    })

    assert client.get("/api/account/settings", headers=auth(first["token"])).json()["settings"]["top_k"] == 17
    assert client.get("/api/account/settings", headers=auth(second["token"])).json()["settings"]["top_k"] == 5
    assert client.get("/api/conversations", headers=auth(first["token"])).json()["conversations"].keys() == {"c1"}
    assert client.get("/api/conversations", headers=auth(second["token"])).json()["conversations"] == {}
    assert client.delete("/api/conversations/c1", headers=auth(second["token"])).status_code == 404
    assert client.delete("/api/conversations/c1", headers=auth(first["token"])).status_code == 200


def test_workspaces_do_not_share_directories_or_indexes(api):
    client, _, registry = api
    first = register(client, "w1@example.com")
    second = register(client, "w2@example.com")
    one = registry.workspace(first["account"]["id"])
    two = registry.workspace(second["account"]["id"])

    assert one.root != two.root
    assert not one.root.is_relative_to(two.root)
    assert one.collection is not two.collection

    page = one.pages_dir / "doc_page_1.png"
    page.write_bytes(b"image")
    # The other workspace must not resolve a path that lives in this one, even
    # when the absolute path is handed to it directly.
    assert one.resolve_page_path(str(page)) == str(page)
    assert two.resolve_page_path(str(page)) == ""
    assert two.contains(page) is False


def test_deleting_an_account_removes_its_data_and_sessions(api):
    client, _, registry = api
    first = register(client, "gone@example.com")
    second = register(client, "stays@example.com")
    workspace = registry.workspace(first["account"]["id"])
    (workspace.pages_dir / "page.png").write_bytes(b"image")
    workspace.collection.add(ids=["doc_p1"], embeddings=[[0.1]], metadatas=[{}], documents=[""])

    assert client.delete("/api/account", headers=auth(first["token"])).status_code == 200
    # The whole directory must be gone, not merely unlinked from the registry:
    # the vector index has to be released first or the removal silently fails.
    assert not workspace.root.exists()
    assert workspace._client is None
    assert client.get("/api/auth/me", headers=auth(first["token"])).status_code == 401
    assert client.get("/api/auth/me", headers=auth(second["token"])).status_code == 200
    # The email is released so it can be registered again.
    assert client.post("/api/auth/register", json={
        "name": "Again", "email": "gone@example.com", "password": PASSWORD,
    }).status_code == 200


def test_only_the_owner_can_delete_an_account(api):
    client, _, _ = api
    owner = register(client, "keeper@example.com")
    client.post("/api/users", headers=auth(owner["token"]), json={
        "name": "Admin Member", "email": "adminmember@example.com",
        "password": PASSWORD, "role": "Head (System Admin)",
    })
    member = client.post("/api/auth/login", json={
        "email": "adminmember@example.com", "password": PASSWORD,
    }).json()["token"]

    assert client.delete("/api/account", headers=auth(member)).status_code == 403
    # An administrator may still rename the workspace.
    assert client.put("/api/account", headers=auth(member), json={"name": "Renamed"}).status_code == 200


# ── legacy migration ──────────────────────────────────────────────────────────

def test_legacy_single_tenant_data_moves_into_one_owned_account(tmp_path):
    from backend.accounts import AccountRegistry

    base = tmp_path / "buildmarshal"
    (base / "pages").mkdir(parents=True)
    (base / "documents").mkdir(parents=True)
    page = base / "pages" / "old_page_1.png"
    page.write_bytes(b"legacy-image")
    (base / "documents" / "old.pdf").write_bytes(b"%PDF-1.4")
    (base / "metadata.json").write_text(json.dumps({
        "documents": {"old": {"name": "old.pdf", "page_count": 1, "pages": [
            {"page_num": 1, "image_path": str(page), "text_content": "legacy"},
        ]}}
    }), encoding="utf-8")
    (base / "users.json").write_text(json.dumps({
        "legacy-admin": {
            "id": "legacy-admin", "name": "Administrator",
            "email": "admin@buildmarshal.com", "role": "Head (Super Admin)",
            "password_hash": hashlib.sha256(b"admin123").hexdigest(), "status": "Active",
        }
    }), encoding="utf-8")

    registry = AccountRegistry(base, build_collection)
    account_id = migrate_legacy_workspace(registry, base)
    assert account_id

    workspace = registry.workspace(account_id)
    documents = workspace.load_metadata()["documents"]
    assert documents["old"]["name"] == "old.pdf"
    moved = workspace.pages_dir / "old_page_1.png"
    assert moved.exists() and documents["old"]["pages"][0]["image_path"] == str(moved)
    assert not (base / "pages").exists()

    user = registry.get_user("legacy-admin")
    assert user["account_id"] == account_id and user["is_owner"] is True
    # The shipped credential still works and is upgraded on use.
    assert verify_password("admin123", user["password_hash"]) == (True, True)

    # Running again is a no-op rather than a second migration.
    assert migrate_legacy_workspace(registry, base) is None
    assert len(registry.list_accounts()) == 1


def test_deleting_an_account_releases_the_real_vector_index(tmp_path):
    """Deletion must work against a real ChromaDB client, not just the double.

    ChromaDB holds its SQLite file open for the client's lifetime, so a
    workspace that does not close its client leaves the whole directory behind
    on Windows while still reporting success.
    """
    import chromadb

    from backend.accounts import AccountRegistry

    def real_collection(chroma_dir):
        client = chromadb.PersistentClient(path=str(chroma_dir))
        try:
            collection = client.get_collection(name="document_pages")
        except Exception:
            collection = client.create_collection(
                name="document_pages", metadata={"hnsw:space": "cosine"}
            )
        return client, collection

    registry = AccountRegistry(tmp_path / "data", real_collection)
    account, _ = registry.register_account(
        account_name="Real", name="Real Owner", email="real@example.com", password=PASSWORD,
    )
    workspace = registry.workspace(account["id"])
    workspace.collection.add(ids=["doc_p1"], embeddings=[[0.1, 0.2, 0.3]], documents=["page"])
    assert workspace.collection.count() == 1
    root = workspace.root

    registry.delete_account(account["id"])
    assert not root.exists()

    # A new account must be able to reuse the path with a working client.
    second, _ = registry.register_account(
        account_name="Real Again", name="Owner", email="again@example.com", password=PASSWORD,
    )
    reused = registry.workspace(second["id"])
    reused.collection.add(ids=["doc_p1"], embeddings=[[0.4, 0.5, 0.6]], documents=["page"])
    assert reused.collection.count() == 1


def test_member_cannot_promote_themselves(api):
    client, _, _ = api
    owner = register(client, "chief@example.com")
    make_role(client, owner["token"], "Member")
    make_role(client, owner["token"], "Site Lead")
    member = client.post("/api/users", headers=auth(owner["token"]), json={
        "name": "Plain", "email": "plainuser@example.com", "password": PASSWORD, "role": "Member",
    }).json()
    token = client.post("/api/auth/login", json={
        "email": "plainuser@example.com", "password": PASSWORD,
    }).json()["token"]

    escalate = client.put(f"/api/users/{member['id']}", headers=auth(token),
                          json={"role": "Head (Super Admin)"})
    assert escalate.status_code == 403
    reactivate = client.put(f"/api/users/{member['id']}", headers=auth(token),
                            json={"status": "Inactive"})
    assert reactivate.status_code == 403
    assert client.get(f"/api/users/{member['id']}", headers=auth(token)).json()["role"] == "Member"

    # Editing their own profile fields still works, including resending the
    # unchanged role.
    ok = client.put(f"/api/users/{member['id']}", headers=auth(token),
                    json={"name": "Plain Renamed", "role": "Member"})
    assert ok.status_code == 200 and ok.json()["name"] == "Plain Renamed"

    # An administrator may still change it.
    promoted = client.put(f"/api/users/{member['id']}", headers=auth(owner["token"]),
                          json={"role": "Site Lead"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "Site Lead"

    # A role outside the catalogue is refused rather than stored verbatim.
    unknown = client.put(f"/api/users/{member['id']}", headers=auth(owner["token"]),
                         json={"role": "Sysadmin"})
    assert unknown.status_code == 422
