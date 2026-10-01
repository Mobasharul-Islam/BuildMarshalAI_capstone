"""Create BuildMarshalAI's PostgreSQL role and databases, and apply the schema.

Run once per machine (``SETUP-DATABASE.ps1`` does it for you). Idempotent: an
existing role or database is kept, and the schema is only brought up to date.

What it creates, connecting as a PostgreSQL superuser:

* a login role ``buildmarshal`` -- the only identity the application uses; it
  owns its databases but is not a superuser;
* ``buildmarshal`` (the application), ``buildmarshal_test`` (the automated test
  suite; each test works in its own schema) and ``buildmarshal_demo`` (the
  demonstration kit).

The superuser password is taken from ``PGPASSWORD`` or asked for, and is never
written anywhere. The application role's password is generated here and stored,
inside the database URLs, in ``secrets/runtime-secrets.json`` -- the handover's
existing uncommitted secrets file -- as ``BUILDMARSHAL_DATABASE_URL``,
``BUILDMARSHAL_TEST_DATABASE_URL`` and ``BUILDMARSHAL_DEMO_DATABASE_URL``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
from database import Database, redact  # noqa: E402

DATABASES = {
    "BUILDMARSHAL_DATABASE_URL": "buildmarshal",
    "BUILDMARSHAL_TEST_DATABASE_URL": "buildmarshal_test",
    "BUILDMARSHAL_DEMO_DATABASE_URL": "buildmarshal_demo",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--admin-user", default="postgres")
    parser.add_argument("--role", default="buildmarshal")
    parser.add_argument("--secrets", type=Path, default=REPO.parent / "secrets" / "runtime-secrets.json",
                        help="JSON secrets file to record the database URLs in")
    parser.add_argument("--extra-database", action="append", default=[],
                        help="also create this database (e.g. an isolated verification copy)")
    options = parser.parse_args()

    admin_password = os.environ.get("PGPASSWORD") or getpass.getpass(
        f"Password for PostgreSQL superuser '{options.admin_user}': ")
    admin = psycopg.connect(host=options.host, port=options.port, user=options.admin_user,
                            password=admin_password, dbname="postgres", autocommit=True)

    existing_secrets: dict = {}
    if options.secrets.exists():
        existing_secrets = json.loads(options.secrets.read_text(encoding="utf-8-sig"))
    # Keep the role's password stable across runs if it was already recorded.
    password = _recorded_password(existing_secrets, options.role) or secrets.token_urlsafe(24)

    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (options.role,))
        if cur.fetchone():
            # Utility statements take no bound parameters; Literal quotes it safely.
            cur.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                sql.Identifier(options.role), sql.Literal(password)))
            print(f"role {options.role}: exists (password refreshed)")
        else:
            cur.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE")
                        .format(sql.Identifier(options.role), sql.Literal(password)))
            print(f"role {options.role}: created")
        names = list(DATABASES.values()) + list(options.extra_database)
        for name in names:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cur.fetchone():
                print(f"database {name}: exists")
            else:
                cur.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0")
                            .format(sql.Identifier(name), sql.Identifier(options.role)))
                print(f"database {name}: created")
    admin.close()

    def url(name: str) -> str:
        return (f"postgresql://{quote(options.role)}:{quote(password, safe='')}"
                f"@{options.host}:{options.port}/{name}")

    for name in list(DATABASES.values()) + list(options.extra_database):
        database = Database(url(name), min_size=1, max_size=1)
        applied = database.migrate()
        print(f"schema {name}: version {database.schema_version()}"
              + (f" (applied {applied})" if applied else " (up to date)"))
        database.close()

    existing_secrets.update({key: url(name) for key, name in DATABASES.items()})
    options.secrets.parent.mkdir(parents=True, exist_ok=True)
    options.secrets.write_text(json.dumps(existing_secrets, indent=2), encoding="utf-8")
    print(f"recorded {', '.join(DATABASES)} in {options.secrets}")
    print(f"application database: {redact(url(DATABASES['BUILDMARSHAL_DATABASE_URL']))}")
    return 0


def _recorded_password(values: dict, role: str) -> str | None:
    from urllib.parse import unquote, urlparse

    recorded = values.get("BUILDMARSHAL_DATABASE_URL") or ""
    parsed = urlparse(recorded)
    if parsed.username == role and parsed.password:
        return unquote(parsed.password)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
