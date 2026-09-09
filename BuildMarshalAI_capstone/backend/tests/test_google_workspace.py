import json
from datetime import datetime

import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI

from backend.document_generation import register_kaggle_routes
from backend.google_workspace import (
    EncryptedAccountStore,
    _account_id,
    _credentials_expiry,
    _gmail_body,
    _headers,
    _safe_name,
    register_google_workspace_routes,
)


def test_google_credentials_expiry_normalizes_aware_timestamp_to_naive_utc():
    expiry = _credentials_expiry("2026-08-28T16:00:00+06:00")
    assert expiry == datetime(2026, 8, 28, 10, 0, 0)
    assert expiry.tzinfo is None


def test_google_credentials_expiry_preserves_naive_timestamp():
    assert _credentials_expiry("2026-08-28T10:00:00") == datetime(2026, 8, 28, 10, 0, 0)
    assert _credentials_expiry(None) is None


def test_account_store_encrypts_tokens_at_rest(tmp_path):
    path = tmp_path / "accounts.enc"
    key = Fernet.generate_key().decode("ascii")
    store = EncryptedAccountStore(path, key)
    record = {
        "id": "account-1", "email": "user@example.com", "name": "User",
        "access_token": "secret-access-token", "refresh_token": "secret-refresh-token",
    }
    store.put(record)

    raw = path.read_bytes()
    assert b"secret-access-token" not in raw
    assert b"secret-refresh-token" not in raw
    assert store.get("account-1")["refresh_token"] == "secret-refresh-token"
    assert "refresh_token" not in store.list_public()[0]


def test_account_store_rejects_wrong_encryption_key(tmp_path):
    path = tmp_path / "accounts.enc"
    EncryptedAccountStore(path, Fernet.generate_key().decode()).put({"id": "one"})
    with pytest.raises(InvalidToken):
        EncryptedAccountStore(path, Fernet.generate_key().decode()).list_public()


def test_gmail_multipart_prefers_plain_text():
    encode = lambda value: __import__("base64").urlsafe_b64encode(value.encode()).decode().rstrip("=")
    payload = {
        "headers": [{"name": "Subject", "value": "Progress"}],
        "parts": [
            {"mimeType": "text/html", "body": {"data": encode("<p>HTML body</p>")}},
            {"mimeType": "text/plain", "body": {"data": encode("Plain body")}},
        ],
    }
    assert _gmail_body(payload) == "Plain body"
    assert _headers(payload)["subject"] == "Progress"


def test_import_names_and_account_ids_are_stable():
    assert _safe_name("../Tender: Final?.pdf") == "Tender_ Final_.pdf"
    assert _account_id(" User@Example.com ") == _account_id("user@example.com")


def test_registered_routes_build_openapi_schema(registry):
    async def require_account():  # pragma: no cover - schema build only
        raise AssertionError("routes are not called in this test")

    namespace = {
        "app": FastAPI(),
        "ingest_document": lambda *_: {"page_count": 0},
        "embed_query": lambda *_: None,
        "vl_generate": lambda *_args, **_kwargs: "{}",
        "require_account": require_account,
    }
    register_kaggle_routes(namespace)
    register_google_workspace_routes(namespace)

    schema = namespace["app"].openapi()
    assert "/api/projects/{project_id}/documents" in schema["paths"]
    assert "/api/google/oauth/code" in schema["paths"]
