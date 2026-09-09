"""Encrypted OAuth token storage shared by the connected-account providers.

Google Workspace and Microsoft 365 both hold refresh tokens for accounts a user
has linked.  Those tokens are the most sensitive thing the product stores, so
they live encrypted at rest in the workspace of the BuildMarshal account that
linked them and are never returned by an API response.

The store is provider-agnostic; each provider passes its own file path, so one
account's Google tokens and Microsoft tokens sit in separate files and neither
is reachable from another BuildMarshal account.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


# Fields safe to hand back to a browser.  Everything else in a record --
# access_token, refresh_token, scopes -- stays server-side.
PUBLIC_ACCOUNT_FIELDS = ("id", "email", "name", "picture", "connected_at", "provider")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat()


def safe_name(name: str, fallback: str = "external-document") -> str:
    """Reduce an external file name to something safe to write to disk."""
    name = Path(name or fallback).name
    name = re.sub(r"[^A-Za-z0-9._() -]+", "_", name).strip(" .")
    return name[:180] or fallback


def account_identifier(email: str, length: int = 32) -> str:
    """Stable id for a linked account, derived from its address.

    ``length`` exists because the Google integration shipped 20-character ids
    and already has accounts stored under them; shortening the shared default
    would orphan those records.
    """
    return hashlib.sha256(str(email or "").strip().lower().encode("utf-8")).hexdigest()[:length]


class EncryptedAccountStore:
    """A Fernet-encrypted JSON map of linked external accounts."""

    def __init__(self, path: Path, key: str):
        from cryptography.fernet import Fernet

        if not key:
            raise RuntimeError("The OAuth token encryption key is not configured")
        try:
            self.fernet = Fernet(key.encode("ascii"))
        except Exception as exc:
            raise RuntimeError(
                "The OAuth token encryption key must be a Fernet key; generate one with "
                "Fernet.generate_key().decode()"
            ) from exc
        self.path = Path(path)
        self.lock = threading.RLock()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        encrypted = self.path.read_bytes()
        if not encrypted:
            return {}
        return json.loads(self.fernet.decrypt(encrypted).decode("utf-8"))

    def _save(self, records: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_bytes(self.fernet.encrypt(json.dumps(records).encode("utf-8")))
        temp.replace(self.path)

    def list_public(self) -> list[dict[str, Any]]:
        with self.lock:
            records = self._load()
        return [
            {key: record.get(key) for key in PUBLIC_ACCOUNT_FIELDS}
            for record in records.values()
        ]

    def public(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return {key: record.get(key) for key in PUBLIC_ACCOUNT_FIELDS}

    def get(self, account_id: str) -> dict[str, Any]:
        with self.lock:
            record = self._load().get(account_id)
        if not record:
            raise KeyError(account_id)
        return record

    def put(self, record: Mapping[str, Any]) -> None:
        with self.lock:
            records = self._load()
            records[str(record["id"])] = dict(record)
            self._save(records)

    def delete(self, account_id: str) -> dict[str, Any] | None:
        with self.lock:
            records = self._load()
            record = records.pop(account_id, None)
            self._save(records)
        return record


__all__ = [
    "EncryptedAccountStore", "PUBLIC_ACCOUNT_FIELDS", "account_identifier",
    "iso", "safe_name", "utcnow",
]
