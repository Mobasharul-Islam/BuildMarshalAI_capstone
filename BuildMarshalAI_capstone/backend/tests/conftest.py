"""Shared fixtures for the integration-module tests.

The modules under test resolve every store through an ``AccountWorkspace`` and
an ``AccountContext``.  These helpers build real ones over a temporary
directory, backed by an in-memory stand-in for the Chroma collection, so route
tests can assert isolation without loading ColPali or starting ChromaDB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.accounts import AccountContext, AccountRegistry, AccountWorkspace


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
