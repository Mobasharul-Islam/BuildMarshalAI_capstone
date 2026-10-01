"""The demonstration's PostgreSQL database, shared by the demo scripts.

Never the application's own database: ``BUILDMARSHAL_DEMO_DATABASE_URL``, or the
one ``SETUP-DATABASE.ps1`` recorded in ``secrets/runtime-secrets.json``.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "backend"))

from database import Database  # noqa: E402  (imported as backend.accounts imports it)


def demo_database_url() -> str:
    url = os.environ.get("BUILDMARSHAL_DEMO_DATABASE_URL", "").strip()
    if not url:
        secrets_file = REPO.parent / "secrets" / "runtime-secrets.json"
        if secrets_file.exists():
            url = str(json.loads(secrets_file.read_text(encoding="utf-8-sig"))
                      .get("BUILDMARSHAL_DEMO_DATABASE_URL") or "").strip()
    return url


def demo_database() -> Database:
    return Database(demo_database_url())


__all__ = ["demo_database", "demo_database_url"]
