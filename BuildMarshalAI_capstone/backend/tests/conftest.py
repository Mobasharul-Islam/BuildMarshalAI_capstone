"""Shared fixtures for the integration-module tests.

The modules under test resolve every store through an ``AccountWorkspace`` and
an ``AccountContext``.  These helpers build real ones over a temporary
directory and a real PostgreSQL database, backed by an in-memory stand-in for
the Chroma collection, so route tests can assert isolation without loading
ColPali or starting ChromaDB.

Each test gets its own schema in the test database, created the first time the
test touches the database and dropped afterwards, so tests cannot see each
other's rows and a test that never stores anything costs nothing.  The test
database is ``BUILDMARSHAL_TEST_DATABASE_URL``, or the one ``SETUP-DATABASE.ps1``
recorded in ``secrets/runtime-secrets.json``.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest

from backend.accounts import AccountContext, AccountRegistry, AccountWorkspace
from backend.database import Database, set_default_database


def _test_database_url() -> str:
    url = os.environ.get("BUILDMARSHAL_TEST_DATABASE_URL", "").strip()
    if url:
        return url
    secrets_file = Path(__file__).resolve().parents[3] / "secrets" / "runtime-secrets.json"
    if secrets_file.exists():
        recorded = json.loads(secrets_file.read_text(encoding="utf-8-sig"))
        url = str(recorded.get("BUILDMARSHAL_TEST_DATABASE_URL") or "").strip()
    if not url:
        pytest.exit("No test database: set BUILDMARSHAL_TEST_DATABASE_URL or run SETUP-DATABASE.ps1",
                    returncode=2)
    return url


TEST_DATABASE_URL = _test_database_url()


@pytest.fixture(autouse=True)
def database():
    """A fresh schema for this test, made on first use and dropped after."""
    opened: dict[str, Any] = {}

    def create() -> Database:
        schema = f"t_{uuid.uuid4().hex[:16]}"
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
            admin.execute(f'CREATE SCHEMA "{schema}"')
        opened["schema"] = schema
        opened["db"] = Database(TEST_DATABASE_URL, schema=schema, min_size=1, max_size=4)
        return opened["db"]

    set_default_database(create)
    yield lambda: opened.get("db")
    set_default_database(None)
    if "db" in opened:
        opened["db"].close()
    if "schema" in opened:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA "{opened["schema"]}" CASCADE')


class FakeCollection:
    """Minimal in-memory stand-in for a Chroma collection."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def count(self) -> int:
        return len(self.records)

    def add(self, ids, embeddings=None, metadatas=None, documents=None):
        for index, item_id in enumerate(ids):
            self.records[item_id] = {
                "embedding": (embeddings or [None] * len(ids))[index],
                "metadata": (metadatas or [{}] * len(ids))[index],
                "document": (documents or [""] * len(ids))[index],
            }

    update = add

    def get(self, ids=None, include=None):
        selected = list(self.records) if ids is None else [i for i in ids if i in self.records]
        return {
            "ids": selected,
            "embeddings": [self.records[i]["embedding"] for i in selected],
            "metadatas": [self.records[i]["metadata"] for i in selected],
            "documents": [self.records[i]["document"] for i in selected],
        }

    def delete(self, ids=None, where=None):
        if ids:
            for item_id in ids:
                self.records.pop(item_id, None)
        if where:
            for item_id, record in list(self.records.items()):
                if all(record["metadata"].get(k) == v for k, v in where.items()):
                    self.records.pop(item_id, None)

    def peek(self, limit=5):
        return self.get(list(self.records)[:limit])

    def query(self, **kwargs):
        return {"ids": [[]], "metadatas": [[]], "documents": [[]], "distances": [[]]}


class FakeClient:
    """Stands in for a Chroma PersistentClient, including its close()."""

    def __init__(self) -> None:
        self.collection = FakeCollection()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def build_collection(_chroma_dir: Path):
    client = FakeClient()
    return client, client.collection


@pytest.fixture
def registry(tmp_path: Path) -> AccountRegistry:
    return AccountRegistry(tmp_path / "data", build_collection)


@pytest.fixture
def make_account(registry: AccountRegistry):
    """Factory returning an authenticated context for a freshly created account."""

    def factory(email: str, *, name: str = "Owner") -> AccountContext:
        account, owner = registry.register_account(
            account_name=f"{name} workspace", name=name, email=email,
            password="Passw0rd!123",
        )
        return AccountContext(
            user=owner, account=account,
            workspace=registry.workspace(account["id"]), token=f"token-{email}",
        )

    return factory


@pytest.fixture
def make_workspace(make_account):
    def factory(email: str) -> AccountWorkspace:
        return make_account(email).workspace

    return factory
