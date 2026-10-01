"""Check that BuildMarshalAI's PostgreSQL database is reachable and up to date.

Prints the schema version and what is stored, never a password. Exit status 0
when the database answers, 1 when it does not (with the reason), 2 when no
database is configured at all.

    python scripts/check_database.py [--secrets PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
from database import DATABASE_URL_ENV, Database, redact  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--secrets", type=Path, default=REPO.parent / "secrets" / "runtime-secrets.json")
    options = parser.parse_args()

    url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not url and options.secrets.exists():
        url = str(json.loads(options.secrets.read_text(encoding="utf-8-sig")).get(DATABASE_URL_ENV) or "")
    if not url:
        print(f"No database configured ({DATABASE_URL_ENV}). Run SETUP-DATABASE.ps1.")
        return 2
    try:
        database = Database(url, min_size=1, max_size=1, timeout=8)
        applied = database.migrate()
        with database.transaction() as cur:
            counts = {}
            for table in ("accounts", "users", "projects", "tasks", "documents", "oauth_token_stores"):
                cur.execute(f"SELECT count(*) AS n FROM {table}")
                counts[table] = cur.fetchone()["n"]
            cur.execute("SELECT version() AS v")
            server = cur.fetchone()["v"].split(",")[0]
        version = database.schema_version()
        database.close()
    except Exception as error:
        print(f"Database unreachable at {redact(url)}: {error}")
        return 1
    print(f"Database OK: {redact(url)}")
    print(f"  {server}; schema version {version}" + (f" (just applied {applied})" if applied else ""))
    print("  " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    if not counts["oauth_token_stores"]:
        print("  No Google or Microsoft account linked yet -- connect one from the app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
