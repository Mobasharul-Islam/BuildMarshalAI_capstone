"""PostgreSQL storage for BuildMarshalAI.

Every record the application keeps -- accounts, users, sessions, and each
account's projects, tasks, procurement, documents, catalogues, roles,
conversations, onboarding drafts, generated-document register, evidence
feedback, settings, company profile, and encrypted OAuth tokens -- lives in
PostgreSQL.  Uploaded files, rendered pages, generated PDFs and caches stay on
disk under the account's workspace directory, and the page-vector index stays
in ChromaDB; the database holds the records that point at them.

Design
------

* **Tables per entity.**  Each kind of record has its own table, keyed by the
  owning ``account_id`` (a foreign key to ``accounts`` with ``ON DELETE
  CASCADE``, so deleting an account removes everything it owns in one
  statement) plus the record's own id.  The columns the application filters or
  joins on -- a task's project, parent and status, a document's digest, a
  user's email -- are real, indexed columns; the full record is kept beside
  them as ``jsonb`` so a field added in code needs no migration.

* **Whole-store saves are diffed.**  The feature modules read a store, change
  it, and save it back (``load_tasks`` / ``save_tasks``).  A save compares the
  new rows with the stored ones inside one transaction -- under an advisory lock
  per (table, account), so two saves of the same store cannot interleave -- and
  writes only rows that were added, changed or removed.

* **Atomic units of work.**  :meth:`Database.atomic` binds one connection to
  the current thread; every save inside it joins that transaction, so a
  multi-store operation such as an onboarding commit either lands completely
  or not at all.

* **Schema migrations** are numbered and recorded in ``schema_migrations``;
  :meth:`Database.migrate` applies whatever is missing, so a fresh database and
  an old one converge on the same schema at start-up.

Configuration: ``BUILDMARSHAL_DATABASE_URL`` (a libpq URL such as
``postgresql://buildmarshal:...@localhost:5432/buildmarshal``).  There is no
silent fallback to files: without a database the backend refuses to start and
says why.
"""

from __future__ import annotations

import contextvars
import json
import math
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping, Sequence

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

DATABASE_URL_ENV = "BUILDMARSHAL_DATABASE_URL"


class DatabaseNotConfigured(RuntimeError):
    """No database URL was supplied."""


class DatabaseUnavailable(RuntimeError):
    """The database could not be reached or is unusable."""


# -- values ---------------------------------------------------------------------

def _clean(value: Any) -> Any:
    """Make a Python value storable as jsonb.

    PostgreSQL's jsonb rejects the NUL character and NaN/Infinity, both of which
    real inputs produce (text extracted from PDFs; empty spreadsheet cells read
    through pandas).  NUL is dropped and non-finite numbers become null, which is
    also how the browser's JSON would have seen them.
    """
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {(_clean(k) if isinstance(k, str) else str(k)): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def normalise(value: Any) -> Any:
    """The value exactly as it will read back from jsonb.

    Saving and comparing both go through this, so a record that has not changed
    compares equal to its stored copy and is not rewritten.
    """
    return json.loads(json.dumps(_clean(value), default=str, ensure_ascii=False))


def as_jsonb(value: Any) -> Jsonb:
    return Jsonb(normalise(value))


# -- schema ---------------------------------------------------------------------

def _account_table(name: str, keys: str, columns: str = "", extra_indexes: Sequence[str] = ()) -> str:
    """DDL for a per-account table: account_id + keys, position, typed columns, data."""
    key_cols = ", ".join(part.split()[0] for part in keys.split(","))
    ddl = f"""
CREATE TABLE IF NOT EXISTS {name} (
    account_id  text    NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    {keys},
    position    integer NOT NULL DEFAULT 0,
    {columns + ',' if columns else ''}
    data        jsonb   NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, {key_cols})
);
CREATE INDEX IF NOT EXISTS {name}_order ON {name} (account_id, position);
"""
    for index in extra_indexes:
        ddl += index + "\n"
    return ddl


MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "records move from JSON files to PostgreSQL", """
CREATE TABLE IF NOT EXISTS app_meta (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accounts (
    id            text PRIMARY KEY,
    name          text NOT NULL,
    status        text NOT NULL DEFAULT 'Active',
    owner_user_id text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    data          jsonb NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id          text PRIMARY KEY,
    account_id  text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    email       text NOT NULL,
    email_key   text GENERATED ALWAYS AS (lower(email)) STORED,
    name        text NOT NULL DEFAULT '',
    role        text NOT NULL DEFAULT '',
    status      text NOT NULL DEFAULT 'Active',
    is_owner    boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    data        jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users (email_key);
CREATE INDEX IF NOT EXISTS users_account ON users (account_id);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  text PRIMARY KEY,
    user_id     text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id  text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL,
    last_seen   timestamptz NOT NULL,
    expires_at  timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id, created_at);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions (expires_at);
""" + _account_table(
        "projects", "id text NOT NULL",
        "name text NOT NULL DEFAULT '', project_code text NOT NULL DEFAULT '', status text NOT NULL DEFAULT ''",
        ["CREATE INDEX IF NOT EXISTS projects_code ON projects (account_id, lower(project_code));"],
    ) + _account_table(
        "tasks", "project_id text NOT NULL, id text NOT NULL",
        "parent_id text, name text NOT NULL DEFAULT '', status text NOT NULL DEFAULT '', archived boolean NOT NULL DEFAULT false",
        ["CREATE INDEX IF NOT EXISTS tasks_project ON tasks (account_id, project_id, position);",
         "CREATE INDEX IF NOT EXISTS tasks_parent ON tasks (account_id, parent_id);"],
    ) + _account_table(
        "procurement_items", "project_id text NOT NULL, id text NOT NULL",
        "name text NOT NULL DEFAULT '', status text NOT NULL DEFAULT ''",
        ["CREATE INDEX IF NOT EXISTS procurement_project ON procurement_items (account_id, project_id, position);"],
    ) + _account_table(
        "documents", "id text NOT NULL",
        "name text NOT NULL DEFAULT '', project_id text, digest text, status text NOT NULL DEFAULT ''",
        ["CREATE INDEX IF NOT EXISTS documents_digest ON documents (account_id, digest);",
         "CREATE INDEX IF NOT EXISTS documents_project ON documents (account_id, project_id);"],
    ) + _account_table(
        "catalog_entries", "kind text NOT NULL, id text NOT NULL",
        "name text NOT NULL DEFAULT ''",
        ["CREATE INDEX IF NOT EXISTS catalog_kind ON catalog_entries (account_id, kind, position);"],
    ) + _account_table(
        "roles", "id text NOT NULL", "name text NOT NULL DEFAULT ''",
    ) + _account_table(
        "conversations", "id text NOT NULL", "title text NOT NULL DEFAULT ''",
    ) + _account_table(
        "onboarding_drafts", "id text NOT NULL", "status text NOT NULL DEFAULT ''",
    ) + _account_table(
        "generated_documents", "id text NOT NULL",
        "project_id text, doc_kind text NOT NULL DEFAULT ''",
        ["CREATE INDEX IF NOT EXISTS generated_project ON generated_documents (account_id, project_id);"],
    ) + _account_table(
        "evidence_feedback", "id text NOT NULL",
        "doc_id text NOT NULL DEFAULT '', rating text NOT NULL DEFAULT ''",
        ["CREATE INDEX IF NOT EXISTS evidence_doc ON evidence_feedback (account_id, doc_id);"],
    ) + """
CREATE TABLE IF NOT EXISTS account_state (
    account_id  text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    key         text NOT NULL,
    data        jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, key)
);

CREATE TABLE IF NOT EXISTS oauth_token_stores (
    account_id  text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    provider    text NOT NULL,
    ciphertext  bytea NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, provider)
);
"""),
    (2, "renamed built-in roles, people by id, documents in several projects", """
-- The built-in roles were renamed; every stored label follows.
UPDATE users
   SET role = CASE coalesce(data->>'role', role)
                  WHEN 'Super Admin' THEN 'Head (Super Admin)'
                  ELSE 'Head (System Admin)' END,
       data = jsonb_set(data, '{role}', to_jsonb(CASE coalesce(data->>'role', role)
                  WHEN 'Super Admin' THEN 'Head (Super Admin)'
                  ELSE 'Head (System Admin)' END::text)),
       updated_at = now()
 WHERE coalesce(data->>'role', role) IN ('Super Admin', 'System Admin');

-- Voice goes to the local service only; the per-account URL is gone.
UPDATE account_state SET data = data - 'voice_api_url', updated_at = now()
 WHERE key = 'settings' AND data ? 'voice_api_url';

-- A document belongs to a list of projects rather than to one.
UPDATE documents
   SET data = data || jsonb_build_object('project_ids',
              CASE WHEN coalesce(data->>'project_id', '') = '' THEN '[]'::jsonb
                   ELSE jsonb_build_array(data->>'project_id') END),
       updated_at = now()
 WHERE NOT data ? 'project_ids';

-- Managers and assignees were names; link each to the one user it names, if
-- exactly one does.  A name matching nobody, or several people, stays as it
-- was and is shown as unlinked until someone is chosen.
UPDATE projects p
   SET data = p.data || jsonb_build_object('manager_id', m.id), updated_at = now()
  FROM (SELECT account_id, lower(btrim(name)) AS key, min(id) AS id, count(*) AS n
          FROM users WHERE btrim(name) <> '' GROUP BY account_id, lower(btrim(name))) m
 WHERE m.account_id = p.account_id AND m.n = 1
   AND m.key = lower(btrim(p.data->>'manager'))
   AND coalesce(p.data->>'manager_id', '') = '';

UPDATE tasks t
   SET data = t.data || jsonb_build_object('assignee_id', m.id), updated_at = now()
  FROM (SELECT account_id, lower(btrim(name)) AS key, min(id) AS id, count(*) AS n
          FROM users WHERE btrim(name) <> '' GROUP BY account_id, lower(btrim(name))) m
 WHERE m.account_id = t.account_id AND m.n = 1
   AND m.key = lower(btrim(t.data->>'assignee'))
   AND coalesce(t.data->>'assignee_id', '') = '';
"""),
)

APP_TABLES = (
    "oauth_token_stores", "account_state", "evidence_feedback", "generated_documents",
    "onboarding_drafts", "conversations", "roles", "catalog_entries", "documents",
    "procurement_items", "tasks", "projects", "sessions", "users", "accounts", "app_meta",
    "schema_migrations",
)


# -- per-account row tables ----------------------------------------------------------

@dataclass(frozen=True)
class RowTable:
    """A per-account table whose rows mirror one in-memory store."""

    name: str
    keys: tuple[str, ...]              # key columns after account_id
    columns: tuple[str, ...] = ()      # typed columns, written from each row


PROJECTS = RowTable("projects", ("id",), ("name", "project_code", "status"))
TASKS = RowTable("tasks", ("project_id", "id"), ("parent_id", "name", "status", "archived"))
PROCUREMENT = RowTable("procurement_items", ("project_id", "id"), ("name", "status"))
DOCUMENTS = RowTable("documents", ("id",), ("name", "project_id", "digest", "status"))
CATALOG = RowTable("catalog_entries", ("kind", "id"), ("name",))
ROLES = RowTable("roles", ("id",), ("name",))
CONVERSATIONS = RowTable("conversations", ("id",), ("title",))
ONBOARDING = RowTable("onboarding_drafts", ("id",), ("status",))
GENERATED = RowTable("generated_documents", ("id",), ("project_id", "doc_kind"))
EVIDENCE = RowTable("evidence_feedback", ("id",), ("doc_id", "rating"))


# -- the database ---------------------------------------------------------------

class Database:
    """A connection pool plus the application's storage operations."""

    def __init__(self, url: str, *, schema: str | None = None,
                 min_size: int = 1, max_size: int = 10, timeout: float = 15.0):
        if not url:
            raise DatabaseNotConfigured(
                f"No database configured. Set {DATABASE_URL_ENV} to a PostgreSQL URL, "
                "for example postgresql://buildmarshal:PASSWORD@localhost:5432/buildmarshal "
                "(run SETUP-DATABASE.ps1 to create one)."
            )
        self.url = url
        self.schema = schema
        kwargs: dict[str, Any] = {"row_factory": dict_row, "autocommit": False}
        if schema:
            kwargs["options"] = f"-c search_path={schema},public"
        self.pool = ConnectionPool(url, min_size=min_size, max_size=max_size,
                                   kwargs=kwargs, open=False, timeout=timeout,
                                   name=f"buildmarshal{('-' + schema) if schema else ''}")
        try:
            self.pool.open(wait=True, timeout=timeout)
        except Exception as error:
            self.pool.close()
            raise DatabaseUnavailable(
                f"Could not connect to PostgreSQL at {redact(url)}: {error}"
            ) from error
        # The connection of the atomic block this context is inside, if any.  A
        # ContextVar, not a thread-local: async request handlers share a thread,
        # and each must see only its own transaction.
        self._atomic: contextvars.ContextVar = contextvars.ContextVar(
            f"buildmarshal_atomic_{id(self)}", default=None)

    # -- plumbing ----------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Cursor]:
        """A cursor inside a transaction; joins the thread's atomic block if any."""
        outer = self._atomic.get()
        if outer is not None:
            with outer.transaction():          # a savepoint within the atomic block
                with outer.cursor() as cursor:
                    yield cursor
            return
        with self.pool.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    yield cursor

    @contextmanager
    def atomic(self) -> Iterator["Database"]:
        """Make every storage call in this context one transaction until exit."""
        if self._atomic.get() is not None:
            yield self                          # already inside one; nest into it
            return
        with self.pool.connection() as connection:
            token = self._atomic.set(connection)
            try:
                with connection.transaction():
                    yield self
            finally:
                self._atomic.reset(token)

    def close(self) -> None:
        self.pool.close()

    # -- schema -----------------------------------------------------------

    def migrate(self) -> list[int]:
        """Apply every migration not yet recorded; return the versions applied."""
        applied: list[int] = []
        with self.transaction() as cur:
            # One process migrates at a time; the others wait, then find nothing to do.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('buildmarshal.migrate'))")
            cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                               version integer PRIMARY KEY,
                               description text NOT NULL,
                               applied_at timestamptz NOT NULL DEFAULT now())""")
            cur.execute("SELECT version FROM schema_migrations")
            done = {row["version"] for row in cur.fetchall()}
            for version, description, statements in MIGRATIONS:
                if version in done:
                    continue
                cur.execute(statements)
                cur.execute("INSERT INTO schema_migrations (version, description) VALUES (%s, %s)",
                            (version, description))
                applied.append(version)
        return applied

    def schema_version(self) -> int:
        with self.transaction() as cur:
            cur.execute("SELECT coalesce(max(version), 0) AS v FROM schema_migrations")
            return int(cur.fetchone()["v"])

    def drop_all(self) -> None:
        """Remove every application table (demo reset and tests only)."""
        with self.transaction() as cur:
            for table in APP_TABLES:
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table)))

    # -- app metadata -------------------------------------------------------

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self.transaction() as cur:
            cur.execute("SELECT value FROM app_meta WHERE key = %s", (key,))
            row = cur.fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: Any) -> None:
        with self.transaction() as cur:
            cur.execute("""INSERT INTO app_meta (key, value) VALUES (%s, %s)
                           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
                        (key, as_jsonb(value)))

    # -- per-account rows ------------------------------------------------------

    def load_rows(self, table: RowTable, account_id: str) -> list[dict[str, Any]]:
        """Rows of one store, in the order they were saved."""
        columns = sql.SQL(", ").join(sql.Identifier(col) for col in (*table.keys, "data"))
        query = sql.SQL("SELECT {} FROM {} WHERE account_id = %s ORDER BY position").format(
            columns, sql.Identifier(table.name))
        with self.transaction() as cur:
            cur.execute(query, (account_id,))
            return cur.fetchall()

    def sync_rows(self, table: RowTable, account_id: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        """Make the stored rows equal ``rows``, writing only what differs.

        Each row gives its key columns, typed columns, and ``data``; ``position``
        is its index.  Returns how many rows were inserted, updated and deleted.
        """
        key_ids = [sql.Identifier(col) for col in table.keys]
        wanted: dict[tuple, dict[str, Any]] = {}
        for position, row in enumerate(rows):
            key = tuple(str(row[col]) for col in table.keys)
            wanted[key] = {**{col: row.get(col) for col in table.columns},
                           "position": position, "data": normalise(row["data"])}

        counts = {"inserted": 0, "updated": 0, "deleted": 0}
        with self.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{table.name}:{account_id}",))
            cur.execute(sql.SQL("SELECT {}, position, data FROM {} WHERE account_id = %s").format(
                sql.SQL(", ").join(key_ids), sql.Identifier(table.name)), (account_id,))
            existing = {tuple(row[col] for col in table.keys): row for row in cur.fetchall()}

            gone = [key for key in existing if key not in wanted]
            if gone:
                condition = sql.SQL(" AND ").join(
                    sql.SQL("{} = %s").format(ident) for ident in key_ids)
                cur.executemany(
                    sql.SQL("DELETE FROM {} WHERE account_id = %s AND ").format(
                        sql.Identifier(table.name)) + condition,
                    [(account_id, *key) for key in gone])
                counts["deleted"] = len(gone)

            changed = []
            for key, row in wanted.items():
                before = existing.get(key)
                if before is not None and before["data"] == row["data"] and before["position"] == row["position"]:
                    continue
                counts["updated" if before is not None else "inserted"] += 1
                changed.append((key, row))
            if changed:
                cols = ["account_id", *table.keys, "position", *table.columns, "data"]
                updates = [col for col in ("position", *table.columns, "data")]
                statement = sql.SQL(
                    "INSERT INTO {table} ({cols}) VALUES ({vals}) "
                    "ON CONFLICT (account_id, {keys}) DO UPDATE SET {sets}, updated_at = now()"
                ).format(
                    table=sql.Identifier(table.name),
                    cols=sql.SQL(", ").join(sql.Identifier(col) for col in cols),
                    vals=sql.SQL(", ").join(sql.Placeholder() for _ in cols),
                    keys=sql.SQL(", ").join(key_ids),
                    sets=sql.SQL(", ").join(
                        sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(col)) for col in updates),
                )
                cur.executemany(statement, [
                    (account_id, *key, row["position"],
                     *[row[col] for col in table.columns], Jsonb(row["data"]))
                    for key, row in changed])
        return counts

    def count_rows(self, table: RowTable, account_id: str) -> int:
        with self.transaction() as cur:
            cur.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE account_id = %s").format(
                sql.Identifier(table.name)), (account_id,))
            return int(cur.fetchone()["n"])

    # -- per-account key/value state --------------------------------------------

    def get_state(self, account_id: str, key: str) -> Any:
        with self.transaction() as cur:
            cur.execute("SELECT data FROM account_state WHERE account_id = %s AND key = %s",
                        (account_id, key))
            row = cur.fetchone()
        return row["data"] if row else None

    def set_state(self, account_id: str, key: str, value: Any) -> None:
        with self.transaction() as cur:
            cur.execute("""INSERT INTO account_state (account_id, key, data) VALUES (%s, %s, %s)
                           ON CONFLICT (account_id, key)
                           DO UPDATE SET data = EXCLUDED.data, updated_at = now()""",
                        (account_id, key, as_jsonb(value)))

    # -- encrypted OAuth token stores ------------------------------------------

    def get_token_store(self, account_id: str, provider: str) -> bytes | None:
        with self.transaction() as cur:
            cur.execute("SELECT ciphertext FROM oauth_token_stores WHERE account_id = %s AND provider = %s",
                        (account_id, provider))
            row = cur.fetchone()
        return bytes(row["ciphertext"]) if row else None

    def put_token_store(self, account_id: str, provider: str, ciphertext: bytes) -> None:
        with self.transaction() as cur:
            cur.execute("""INSERT INTO oauth_token_stores (account_id, provider, ciphertext)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (account_id, provider)
                           DO UPDATE SET ciphertext = EXCLUDED.ciphertext, updated_at = now()""",
                        (account_id, provider, ciphertext))


def redact(url: str) -> str:
    """A database URL with its password hidden, for messages and logs."""
    try:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        parts = conninfo_to_dict(url)
        if parts.get("password"):
            parts["password"] = "***"
        return make_conninfo(**parts)
    except Exception:
        return "<database url>"


# -- the process-wide default ------------------------------------------------------

_default: Database | None = None
_default_factory: Callable[[], Database] | None = None
_default_lock = threading.Lock()


def default_database() -> Database:
    """The process-wide database, opened and migrated on first use.

    Normally the one named by ``BUILDMARSHAL_DATABASE_URL``; a factory set with
    :func:`set_default_database` takes its place (the test suite gives each test
    its own schema this way, created only if the test touches the database).
    """
    global _default
    with _default_lock:
        if _default is None:
            if _default_factory is not None:
                database = _default_factory()
            else:
                database = Database(os.environ.get(DATABASE_URL_ENV, "").strip())
            database.migrate()
            _default = database
        return _default


def set_default_database(database: "Database | Callable[[], Database] | None") -> None:
    """Replace the process-wide database, or give a factory for it."""
    global _default, _default_factory
    with _default_lock:
        if database is None or isinstance(database, Database):
            _default, _default_factory = database, None
        else:
            _default, _default_factory = None, database


__all__ = [
    "CATALOG", "CONVERSATIONS", "DATABASE_URL_ENV", "DOCUMENTS", "Database",
    "DatabaseNotConfigured", "DatabaseUnavailable", "EVIDENCE", "GENERATED", "MIGRATIONS",
    "ONBOARDING", "PROCUREMENT", "PROJECTS", "ROLES", "RowTable", "TASKS",
    "as_jsonb", "default_database", "normalise", "redact", "set_default_database",
]
