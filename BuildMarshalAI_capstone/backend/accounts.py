"""Account isolation, authentication, and per-account workspaces for BuildMarshalAI.

The module follows the same integration convention as ``document_generation`` and
``google_workspace``: the notebook builds its globals, then calls
``register_account_routes(globals())``.  Registration injects the pieces the rest
of the backend needs -- ``ACCOUNT_REGISTRY``, ``require_account``, and
``optional_account`` -- back into that namespace.

Model
-----
An **account** is an isolated workspace.  A **user** is a login that belongs to
exactly one account; the user created by ``/api/auth/register`` owns it.  Every
resource the product stores -- uploaded files, rendered pages, the Chroma vector
index, ColPali multi-vector caches, project/task records, company management
data, settings, conversations, generated documents, evidence feedback, and
connected Google Workspace tokens -- lives under
``BASE_DIR/accounts/<account_id>/`` and is only ever reached through the
workspace resolved from the caller's bearer token.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import json
import re
import secrets
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:  # the notebook puts this directory on sys.path
    from permissions import (
        BUILTIN_ROLES, PERMISSION_KEYS, SUPER_ADMIN_ROLE, apply_permission_upgrades,
        canonical_role, is_super_admin, resolve_permissions, role_names,
    )
except ModuleNotFoundError:  # imported as backend.accounts
    from backend.permissions import (
        BUILTIN_ROLES, PERMISSION_KEYS, SUPER_ADMIN_ROLE, apply_permission_upgrades,
        canonical_role, is_super_admin, resolve_permissions, role_names,
    )

try:
    from database import (
        CATALOG, CONVERSATIONS, DOCUMENTS, EVIDENCE, GENERATED, ONBOARDING, PROCUREMENT,
        PROJECTS, ROLES, TASKS, Database, as_jsonb, default_database,
    )
except ModuleNotFoundError:
    from backend.database import (
        CATALOG, CONVERSATIONS, DOCUMENTS, EVIDENCE, GENERATED, ONBOARDING, PROCUREMENT,
        PROJECTS, ROLES, TASKS, Database, as_jsonb, default_database,
    )

import psycopg
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

PBKDF2_ALGORITHM = "pbkdf2_sha256"
# OWASP's current recommendation for PBKDF2-HMAC-SHA256.  Hashes stored with a
# lower count keep working and are upgraded the next time their owner signs in.
PBKDF2_ITERATIONS = 600_000
SESSION_TTL_HOURS = 12
SESSION_IDLE_HOURS = 4
MAX_SESSIONS_PER_USER = 12
MIN_PASSWORD_LENGTH = 8

# Roles that administer the account itself. These are system-level and stay
# separate from what someone does day to day.
# The only roles that exist without being created. Everything else is made by
# a Head (Super Admin) on the User Roles page and is exactly the permissions it was
# given, so no job title is hardcoded here.
SYSTEM_ROLES: tuple[str, ...] = BUILTIN_ROLES
OWNER_ROLE = SUPER_ADMIN_ROLE
ADMIN_ROLES = frozenset(SYSTEM_ROLES)

# Permission sets used only to carry pre-existing users across to the new
# system; see migrate_account_roles. Not a role catalogue.
_MEMBER_BASELINE = tuple(
    key for key in sorted(PERMISSION_KEYS)
    if key.startswith(("task.", "project.create", "project.update", "project.people"))
    and key != "project.cost.task"
)
_COST_KEYS = ("project.cost.base", "project.cost.additional", "project.cost.task")

DEFAULT_SETTINGS: dict[str, Any] = {
    "model": "gemini-3.7-flash-high",
    "top_k": 5,
    "company_name": "",
    "company_email": "",
    "company_phone": "",
    "company_address": "",
    "time_zone": "UTC",
}

DEFAULT_MANAGEMENT: dict[str, Any] = {
    "trades": [
        {"id": "tr-1", "name": "Carpentry", "description": "-", "status": "Active"},
        {"id": "tr-2", "name": "Concrete", "description": "-", "status": "Active"},
        {"id": "tr-3", "name": "Drywall", "description": "-", "status": "Active"},
        {"id": "tr-4", "name": "Electrical", "description": "-", "status": "Active"},
        {"id": "tr-5", "name": "Exterior Works", "description": "-", "status": "Active"},
        {"id": "tr-6", "name": "Flooring / Finishing", "description": "-", "status": "Active"},
        {"id": "tr-7", "name": "HVAC", "description": "-", "status": "Active"},
        {"id": "tr-8", "name": "Insulation", "description": "-", "status": "Active"},
        {"id": "tr-9", "name": "Landscaping", "description": "-", "status": "Active"},
        {"id": "tr-10", "name": "Masonry", "description": "-", "status": "Active"},
        {"id": "tr-11", "name": "Painting", "description": "-", "status": "Active"},
        {"id": "tr-12", "name": "Plumbing", "description": "-", "status": "Active"},
        {"id": "tr-13", "name": "Roofing", "description": "-", "status": "Active"},
    ],
    "vendors": [],
    "team_members": [],
    "task_types": [
        {"id": "tt-1", "name": "Task (workspace default)", "description": "-", "status": "Active"},
        {"id": "tt-2", "name": "Phase", "description": "Groups related tasks", "status": "Active"},
        {"id": "tt-3", "name": "Inspection", "description": "-", "status": "Active"},
        {"id": "tt-4", "name": "Delivery", "description": "-", "status": "Active"},
        {"id": "tt-5", "name": "Milestone", "description": "-", "status": "Active"},
    ],
    "project_types": [
        {"id": "pr-1", "name": "Residential", "description": "-", "status": "Active"},
        {"id": "pr-2", "name": "Commercial", "description": "-", "status": "Active"},
        {"id": "pr-3", "name": "Industrial", "description": "-", "status": "Active"},
        {"id": "pr-4", "name": "Renovation", "description": "-", "status": "Active"},
        {"id": "pr-5", "name": "Infrastructure", "description": "-", "status": "Active"},
        {"id": "pr-6", "name": "Interior", "description": "-", "status": "Active"},
    ],
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def safe_identifier(value: str, *, fallback: str = "", max_length: int = 64) -> str:
    """Return a filesystem- and URL-safe identifier.

    Client-supplied ids reach the filesystem (``documents/<doc_id>.pdf``) and
    Chroma record ids, so anything outside a conservative character set --
    path separators, ``..``, control characters -- is rejected rather than
    escaped.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "", str(value or "")).strip("._-")
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned[:max_length]


def hash_password(plain: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(plain: str, stored: str) -> tuple[bool, bool]:
    """Check ``plain`` against ``stored``.

    Returns ``(is_valid, needs_rehash)``.  ``needs_rehash`` is set for any hash
    weaker than what :func:`hash_password` writes today: a bare SHA-256 digest
    from before per-user salting, or PBKDF2 at fewer than
    :data:`PBKDF2_ITERATIONS`.  Both still authenticate, and the caller
    upgrades them transparently on a successful sign-in.
    """
    stored = str(stored or "")
    if stored.startswith(PBKDF2_ALGORITHM + "$"):
        try:
            _, iterations, salt_hex, digest_hex = stored.split("$", 3)
            rounds = int(iterations)
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac(
                "sha256", plain.encode("utf-8"), bytes.fromhex(salt_hex), rounds
            )
        except (ValueError, TypeError):
            return False, False
        return hmac.compare_digest(expected, actual), rounds < PBKDF2_ITERATIONS
    if len(stored) == 64:
        legacy = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, stored), True
    return False, False


@functools.lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """A hash of a random password, made once per process.

    Login verifies against it when the email is unknown, so a missing account
    costs exactly one key derivation at the current work factor -- the same as
    a wrong password -- and the response time does not reveal which emails are
    registered.  Built once because building it per request would double the
    cost of that path, which is the leak this exists to close.
    """
    return hash_password(secrets.token_hex(16))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# JSON-file helpers.  Records are no longer stored in files; these remain for
# reading the files a pre-database installation left behind (see
# ``json_storage_import`` and :func:`migrate_legacy_workspace`).

def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default() if callable(default) else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default() if callable(default) else default


def write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` atomically so a crash cannot truncate a store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    temporary.replace(path)


# --------------------------------------------------------------------------
# Workspace
# --------------------------------------------------------------------------

def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _optional(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _keyed(items: Sequence[Any]) -> list[tuple[str, Any]]:
    """Give each list item a row key: its own id, or its position if it has none.

    A list store may hold items without an id, or (in old data) two with the
    same one; each still needs a distinct row, and the item itself is stored
    unchanged, so what reads back is exactly what was saved.
    """
    seen: set[str] = set()
    keyed: list[tuple[str, Any]] = []
    for index, item in enumerate(items):
        key = _text(item.get("id")) if isinstance(item, Mapping) else ""
        key = key or f"#{index}"
        while key in seen:
            key = f"{key}#{index}"
        seen.add(key)
        keyed.append((key, item))
    return keyed


def _field(record: Any, name: str) -> Any:
    return record.get(name) if isinstance(record, Mapping) else None


class TokenStorage:
    """One encrypted OAuth token blob, kept in the database for one account."""

    def __init__(self, database: Database, account_id: str, provider: str):
        self.database, self.account_id, self.provider = database, account_id, provider

    def read(self) -> bytes | None:
        return self.database.get_token_store(self.account_id, self.provider)

    def write(self, ciphertext: bytes) -> None:
        self.database.put_token_store(self.account_id, self.provider, ciphertext)


class AccountWorkspace:
    """Every record, file and index owned by a single account.

    Records -- projects, tasks, documents, catalogues, roles and the rest --
    live in PostgreSQL, in rows keyed by this account's id; the load/save pairs
    below read and write them.  Files -- uploads, page images, caches,
    generated PDFs -- live under ``root``.  Nothing in this class accepts an
    absolute path or an account id from a request: callers pass record ids, and
    the workspace scopes every query and every path to its own account.
    """

    def __init__(self, root: Path, account_id: str, chroma_factory: Callable[[Path], Any],
                 database: Database | None = None):
        self.account_id = account_id
        self.root = Path(root).resolve()
        self.db = database or default_database()
        self._chroma_factory = chroma_factory
        self._client: Any = None
        self._collection: Any = None
        self._lock = threading.RLock()

        self.docs_dir = self.root / "documents"
        self.pages_dir = self.root / "pages"
        self.chroma_dir = self.root / "chroma_db"
        self.multivector_dir = self.root / "colpali_v1_2_multivectors"
        self.generated_dir = self.root / "generated_documents"
        self.imports_dir = self.root / "google_imports"
        self.vision_cache_dir = self.root / "document_generation_vision_cache"

    # -- filesystem ------------------------------------------------------

    def ensure(self) -> "AccountWorkspace":
        for directory in (
            self.root, self.docs_dir, self.pages_dir, self.chroma_dir,
            self.multivector_dir, self.generated_dir, self.imports_dir,
            self.vision_cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def contains(self, candidate: str | Path | None) -> bool:
        """True when ``candidate`` resolves inside this workspace."""
        if not candidate:
            return False
        try:
            return Path(candidate).resolve().is_relative_to(self.root)
        except (OSError, ValueError):
            return False

    def resolve_page_path(self, stored: str | Path | None) -> str:
        """Resolve a stored page path against this workspace.

        Page paths are recorded absolutely.  When a workspace is migrated or the
        runtime directory moves, the recorded prefix goes stale, so fall back to
        the file of the same name inside this workspace's ``pages/``.  A path
        that belongs to a different account is never returned.
        """
        if not stored:
            return ""
        candidate = Path(stored)
        if self.contains(candidate) and candidate.exists():
            return str(candidate)
        local = self.pages_dir / candidate.name
        return str(local) if local.exists() else ""

    # -- vector index ----------------------------------------------------

    @property
    def collection(self) -> Any:
        with self._lock:
            if self._collection is None:
                self.chroma_dir.mkdir(parents=True, exist_ok=True)
                self._client, self._collection = self._chroma_factory(self.chroma_dir)
            return self._collection

    def close_index(self) -> None:
        """Release the vector index.

        ChromaDB keeps its SQLite file open for the lifetime of the client, and
        an open file cannot be removed on Windows.  Closing also drops the entry
        from Chroma's process-wide client cache, so a directory recreated at the
        same path gets a fresh client rather than a stopped one.
        """
        with self._lock:
            client, self._client, self._collection = self._client, None, None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    # -- records -----------------------------------------------------------

    def atomic(self):
        """One transaction around several saves: all of them land, or none."""
        return self.db.atomic()

    def _rows(self, table) -> list[dict[str, Any]]:
        return self.db.load_rows(table, self.account_id)

    def _sync(self, table, rows: list[dict[str, Any]]) -> None:
        self.db.sync_rows(table, self.account_id, rows)

    def _load_map(self, table) -> dict[str, Any]:
        return {row["id"]: row["data"] for row in self._rows(table)}

    def _save_map(self, table, data: Mapping[str, Any], columns: Callable[[Any], dict]) -> None:
        self._sync(table, [{"id": str(key), **columns(record), "data": record}
                           for key, record in data.items()])

    def _load_grouped(self, table, groups_key: str) -> dict[str, list[dict[str, Any]]]:
        # Group order, including groups that are currently empty lists.
        grouped: dict[str, list[dict[str, Any]]] = {
            str(group): [] for group in (self.db.get_state(self.account_id, groups_key) or [])}
        for row in self._rows(table):
            grouped.setdefault(row["project_id"], []).append(row["data"])
        return grouped

    def _save_grouped(self, table, groups_key: str, data: Mapping[str, Any],
                      columns: Callable[[Any], dict]) -> None:
        rows = []
        for group, items in data.items():
            for key, item in _keyed(list(items or [])):
                rows.append({"project_id": str(group), "id": key, **columns(item), "data": item})
        with self.db.atomic():
            self._sync(table, rows)
            self.db.set_state(self.account_id, groups_key, [str(group) for group in data])

    def load_metadata(self) -> dict[str, Any]:
        """Documents and their pages, plus any other metadata the account keeps."""
        extras = self.db.get_state(self.account_id, "metadata") or {}
        return {**{k: v for k, v in extras.items() if k != "documents"},
                "documents": self._load_map(DOCUMENTS)}

    def save_metadata(self, meta: Mapping[str, Any]) -> None:
        documents = meta.get("documents") if isinstance(meta.get("documents"), Mapping) else {}
        with self.db.atomic():
            self._save_map(DOCUMENTS, documents, lambda doc: {
                "name": _text(_field(doc, "name")),
                "project_id": _optional(_field(doc, "project_id")),
                "digest": _optional(_field(doc, "digest")),
                "status": _text(_field(doc, "status")),
            })
            self.db.set_state(self.account_id, "metadata",
                              {k: v for k, v in meta.items() if k != "documents"})

    def load_mgmt(self) -> dict[str, Any]:
        """Trades, external companies, contacts, task and project types, and
        the other account-wide catalogues; seeded with the defaults on first use."""
        state = self.db.get_state(self.account_id, "management")
        if state is None:
            data = json.loads(json.dumps(DEFAULT_MANAGEMENT))
            self.save_mgmt(data)
        else:
            kinds = list(state.get("kinds") or [])
            extras = dict(state.get("extras") or {})
            catalogues: dict[str, list[Any]] = {kind: [] for kind in kinds}
            for row in self._rows(CATALOG):
                catalogues.setdefault(row["kind"], []).append(row["data"])
            data = {}
            for key in state.get("order") or [*kinds, *extras]:
                if key in catalogues:
                    data[key] = catalogues[key]
                elif key in extras:
                    data[key] = extras[key]
        for key, default in DEFAULT_MANAGEMENT.items():
            data.setdefault(key, json.loads(json.dumps(default)))
        return data

    def save_mgmt(self, data: Mapping[str, Any]) -> None:
        kinds = [key for key, value in data.items() if isinstance(value, list)]
        rows = []
        for kind in kinds:
            for key, item in _keyed(data[kind]):
                rows.append({"kind": kind, "id": key, "name": _text(_field(item, "name")), "data": item})
        with self.db.atomic():
            self._sync(CATALOG, rows)
            self.db.set_state(self.account_id, "management", {
                "order": list(data.keys()), "kinds": kinds,
                "extras": {key: value for key, value in data.items() if key not in kinds},
            })

    def load_projects(self) -> dict[str, dict[str, Any]]:
        return self._load_map(PROJECTS)

    def save_projects(self, data: Mapping[str, Any]) -> None:
        self._save_map(PROJECTS, data, lambda project: {
            "name": _text(_field(project, "name")),
            "project_code": _text(_field(project, "project_code")),
            "status": _text(_field(project, "status")),
        })

    def load_tasks(self) -> dict[str, list[dict[str, Any]]]:
        """Tasks by project id, each project's in its saved order."""
        return self._load_grouped(TASKS, "tasks.groups")

    def save_tasks(self, data: Mapping[str, Any]) -> None:
        self._save_grouped(TASKS, "tasks.groups", data, lambda task: {
            "parent_id": _optional(_field(task, "parent_id")),
            "name": _text(_field(task, "name")),
            "status": _text(_field(task, "status")),
            "archived": bool(_field(task, "archived")),
        })

    def load_procurement(self) -> dict[str, list[dict[str, Any]]]:
        return self._load_grouped(PROCUREMENT, "procurement.groups")

    def save_procurement(self, data: Mapping[str, Any]) -> None:
        self._save_grouped(PROCUREMENT, "procurement.groups", data, lambda item: {
            "name": _text(_field(item, "name")),
            "status": _text(_field(item, "status")),
        })

    def load_settings(self) -> dict[str, Any]:
        data = self.db.get_state(self.account_id, "settings") or {}
        merged = dict(DEFAULT_SETTINGS)
        if isinstance(data, dict):
            merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        return merged

    def save_settings(self, data: Mapping[str, Any]) -> dict[str, Any]:
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        self.db.set_state(self.account_id, "settings", merged)
        return merged

    def load_roles(self) -> list[dict[str, Any]]:
        return [row["data"] for row in self._rows(ROLES)]

    def save_roles(self, data: Sequence[Mapping[str, Any]]) -> None:
        self._sync(ROLES, [{"id": key, "name": _text(_field(role, "name")), "data": role}
                           for key, role in _keyed(list(data))])

    def load_company(self) -> dict[str, Any]:
        data = self.db.get_state(self.account_id, "company")
        return data if isinstance(data, dict) else {}

    def save_company(self, data: Mapping[str, Any]) -> None:
        self.db.set_state(self.account_id, "company", dict(data))

    def load_conversations(self) -> dict[str, Any]:
        return self._load_map(CONVERSATIONS)

    def save_conversations(self, data: Mapping[str, Any]) -> None:
        self._save_map(CONVERSATIONS, data, lambda chat: {"title": _text(_field(chat, "title"))})

    def load_onboarding(self) -> dict[str, Any]:
        """Onboarding drafts, keyed by draft id."""
        return self._load_map(ONBOARDING)

    def save_onboarding(self, data: Mapping[str, Any]) -> None:
        self._save_map(ONBOARDING, data, lambda draft: {"status": _text(_field(draft, "status"))})

    def load_generated(self) -> dict[str, dict[str, Any]]:
        """The generated-document register: generated PDFs and reports, by id."""
        return self._load_map(GENERATED)

    def save_generated(self, data: Mapping[str, Any]) -> None:
        self._save_map(GENERATED, data, lambda record: {
            "project_id": _optional(_field(record, "project_id")),
            "doc_kind": _text(_field(record, "doc_kind")),
        })

    def load_evidence(self) -> list[dict[str, Any]]:
        """Relevance feedback on cited pages, oldest first."""
        return [row["data"] for row in self._rows(EVIDENCE)]

    def save_evidence(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._sync(EVIDENCE, [{"id": key, "doc_id": _text(_field(record, "doc_id")),
                               "rating": _text(_field(record, "rating")), "data": record}
                              for key, record in _keyed(list(records))])

    def add_evidence(self, record: Mapping[str, Any], keep: int = 5000) -> None:
        """Append one feedback record and trim the log to its newest ``keep``.

        An insert, not a rewrite: the log is append-mostly and can be thousands
        of rows long.
        """
        with self.db.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"evidence_feedback:{self.account_id}",))
            cur.execute("""INSERT INTO evidence_feedback (account_id, id, position, doc_id, rating, data)
                           VALUES (%s, %s,
                                   (SELECT coalesce(max(position) + 1, 0) FROM evidence_feedback
                                     WHERE account_id = %s),
                                   %s, %s, %s)
                           ON CONFLICT (account_id, id) DO UPDATE SET data = EXCLUDED.data""",
                        (self.account_id, _text(record.get("id")) or uuid.uuid4().hex, self.account_id,
                         _text(record.get("doc_id")), _text(record.get("rating")), as_jsonb(record)))
            cur.execute("""DELETE FROM evidence_feedback WHERE account_id = %s AND position <
                               (SELECT position FROM evidence_feedback WHERE account_id = %s
                                 ORDER BY position DESC OFFSET %s LIMIT 1)""",
                        (self.account_id, self.account_id, max(keep, 1) - 1))

    def token_store(self, provider: str) -> TokenStorage:
        """Where a provider's encrypted OAuth tokens for this account are kept."""
        return TokenStorage(self.db, self.account_id, provider)

    def delete(self) -> None:
        """Remove this account's files.  Its rows go with the account's own row
        (every table cascades from ``accounts``); see ``AccountRegistry.delete_account``."""
        self.close_index()
        # A file handle can linger for a moment after close on Windows, so give
        # the removal a few attempts before reporting what is left behind.
        for attempt in range(5):
            shutil.rmtree(self.root, ignore_errors=attempt < 4)
            if not self.root.exists():
                return
            time.sleep(0.2 * (attempt + 1))
        raise OSError(f"Workspace directory could not be removed: {self.root}")


@dataclass
class AccountContext:
    """The authenticated caller and the workspace every handler must use."""

    user: dict[str, Any]
    account: dict[str, Any]
    workspace: AccountWorkspace
    token: str

    @property
    def account_id(self) -> str:
        return str(self.account["id"])

    @property
    def user_id(self) -> str:
        return str(self.user["id"])

    @property
    def is_admin(self) -> bool:
        return bool(self.user.get("is_owner")) or canonical_role(self.user.get("role")) in ADMIN_ROLES

    def require_admin(self) -> None:
        if not self.is_admin:
            raise HTTPException(403, "This action requires an account administrator")

    @property
    def is_super_admin(self) -> bool:
        """Managing roles and permissions is theirs alone, by design.

        This is deliberately not a permission: an authority that could be
        ticked on a custom role would be an authority that could be given away.
        """
        return is_super_admin(self.user)

    def require_super_admin(self) -> None:
        if not self.is_super_admin:
            raise HTTPException(403, "This action requires a Head (Super Admin)")

    @property
    def permissions(self) -> frozenset[str]:
        """What this user may do, resolved from their role each time it is asked.

        Reading it fresh means a permission taken off a role applies to that
        user's very next request, rather than whenever they next sign in.
        """
        return resolve_permissions(self.user, self.workspace.load_roles())

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str, action: str) -> None:
        if not self.can(permission):
            raise HTTPException(403, f"Your role does not allow {action}")

    @property
    def can_edit_project_cost(self) -> bool:
        """Whether this user may set a project's baseline or additional costs."""
        return self.can("project.cost.base") or self.can("project.cost.additional")

    def require_project_cost_editor(self, permission: str = "project.cost.additional") -> None:
        self.require(permission, "changing this project's costs")

    def is_assigned(self, task: Mapping[str, Any]) -> bool:
        """Whether this user is the person a task is assigned to.

        A task names its assignee by user id. Older tasks carry only the
        display name, so those match on the name, falling back to the email for
        members whose name was never filled in.
        """
        if str(task.get("assignee_id") or "").strip():
            return str(task.get("assignee_id")).strip() == str(self.user.get("id") or "")
        assignee = str(task.get("assignee") or "").strip().casefold()
        if not assignee:
            return False
        return assignee in {
            str(self.user.get("name") or "").strip().casefold(),
            str(self.user.get("email") or "").strip().casefold(),
        } - {""}

    def can_edit_task_cost(self, task: Mapping[str, Any]) -> bool:
        """A task's cost is the assignee's to maintain, or a cost-holder's."""
        return self.can("project.cost.task") or self.is_assigned(task)

    def require_task_cost_editor(self, task: Mapping[str, Any]) -> None:
        if not self.can_edit_task_cost(task):
            raise HTTPException(
                403,
                "Only the assigned user, or a role allowed to set project costs, "
                "can change this task's cost",
            )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

class DataDirectoryMismatch(RuntimeError):
    """The data directory and the database belong to different installations."""


BINDING_FILE = ".database-binding.json"


class AccountRegistry:
    """Accounts, users, and sessions -- rows in PostgreSQL -- plus the workspace cache."""

    def __init__(self, base_dir: Path, chroma_factory: Callable[[Path], Any], logger: Any = None,
                 database: Database | None = None):
        self.base_dir = Path(base_dir)
        self.accounts_root = self.base_dir / "accounts"
        self.db = database or default_database()
        self.db.migrate()
        self._chroma_factory = chroma_factory
        self._logger = logger
        self._lock = threading.RLock()
        self._workspaces: dict[str, AccountWorkspace] = {}
        self.accounts_root.mkdir(parents=True, exist_ok=True)
        self._bind_data_dir()

    # -- the data directory belongs to this database --------------------

    def _bind_data_dir(self) -> None:
        """Pair the data directory (files) with the database (records), once.

        Records point at files -- page images, uploads, generated PDFs -- so a
        database served with some other installation's data directory would
        answer with documents whose files are missing.  A random id is recorded
        in both on first start and must match afterwards; the pair can move to
        another machine together (copy the directory, restore the database).
        ``BUILDMARSHAL_ALLOW_REBIND=1`` deliberately re-pairs them.
        """
        import os

        marker = self.base_dir / BINDING_FILE
        local = read_json(marker, None)
        local_id = local.get("id") if isinstance(local, dict) else None
        recorded = self.db.get_meta("data_dir_binding")
        recorded_id = recorded.get("id") if isinstance(recorded, dict) else None
        if local_id and local_id == recorded_id:
            return
        with self.db.transaction() as cur:
            cur.execute("SELECT count(*) AS n FROM accounts")
            database_empty = cur.fetchone()["n"] == 0
        rebind = os.environ.get("BUILDMARSHAL_ALLOW_REBIND", "").strip() == "1"
        if recorded_id and not database_empty and not rebind:
            raise DataDirectoryMismatch(
                f"The database already belongs to another data directory, and {self.base_dir} "
                + ("belongs to a different database." if local_id else "is not the one it was paired with.")
                + " Point BUILDMARSHAL_DATA_DIR at the matching directory, use a different database, "
                  "or set BUILDMARSHAL_ALLOW_REBIND=1 to re-pair them deliberately."
            )
        binding = {"id": local_id or uuid.uuid4().hex, "bound_at": iso()}
        write_json(marker, binding)
        self.db.set_meta("data_dir_binding", {**binding, "path": str(self.base_dir.resolve())})

    # -- workspaces ------------------------------------------------------

    def _open_workspace(self, account_id: str) -> AccountWorkspace:
        return AccountWorkspace(self.accounts_root / account_id, account_id,
                                self._chroma_factory, self.db).ensure()

    def workspace(self, account_id: str) -> AccountWorkspace:
        with self._lock:
            workspace = self._workspaces.get(account_id)
            if workspace is None:
                workspace = self._open_workspace(account_id)
                self._workspaces[account_id] = workspace
                first_load = True
                needs_role_seed = not workspace.load_roles()
            else:
                first_load = needs_role_seed = False
        if needs_role_seed:
            # Outside the lock: seeding reads the user list, which takes it.
            self._seed_roles(account_id, workspace)
        if first_load:
            self._upgrade_roles(workspace)
        return workspace

    @staticmethod
    def _upgrade_roles(workspace: "AccountWorkspace") -> None:
        """Give existing roles the permissions added since they were made, once.

        Each new permission guards something any member could do before it, so
        a role that already existed is granted it and its people lose nothing.
        See ``permissions.PERMISSION_UPGRADES``.
        """
        roles = workspace.load_roles()
        if roles and apply_permission_upgrades(roles):
            workspace.save_roles(roles)

    def _seed_roles(self, account_id: str, workspace: AccountWorkspace) -> None:
        """Carry pre-existing role labels into the new role records, once."""
        seeded: list[dict[str, Any]] = []
        seen: set[str] = {name.casefold() for name in SYSTEM_ROLES}
        for user in self.users_for_account(account_id):
            name = str(user.get("role") or "").strip()
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            granted = list(_MEMBER_BASELINE)
            if name.casefold() == "project manager":
                granted += list(_COST_KEYS)
            seeded.append({
                "id": f"role-{uuid.uuid4().hex[:8]}",
                "name": name,
                "description": "Carried over when roles became configurable.",
                "permissions": sorted(set(granted)),
                "created_at": iso(),
                "updated_at": iso(),
            })
        if seeded:
            workspace.save_roles(seeded)

    # -- accounts --------------------------------------------------------

    @staticmethod
    def _account_params(account: Mapping[str, Any]) -> tuple:
        return (str(account["id"]), _text(account.get("name")) or "Workspace",
                _text(account.get("status")) or "Active", _optional(account.get("owner_user_id")),
                parse_iso(account.get("created_at")) or utcnow(), as_json(account))

    def list_accounts(self) -> list[dict[str, Any]]:
        with self.db.transaction() as cur:
            cur.execute("SELECT data FROM accounts ORDER BY created_at, id")
            return [row["data"] for row in cur.fetchall()]

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        with self.db.transaction() as cur:
            cur.execute("SELECT data FROM accounts WHERE id = %s", (str(account_id),))
            row = cur.fetchone()
        return row["data"] if row else None

    def adopt_account(self, account: Mapping[str, Any]) -> bool:
        """Insert an account record as it is (imports); False if it already exists."""
        with self.db.transaction() as cur:
            cur.execute("""INSERT INTO accounts (id, name, status, owner_user_id, created_at, data)
                           VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
                        self._account_params(account))
            return cur.rowcount == 1

    def create_account(self, name: str, *, account_id: str | None = None) -> dict[str, Any]:
        account = {
            "id": account_id or uuid.uuid4().hex,
            "name": name.strip() or "Workspace",
            "status": "Active",
            "owner_user_id": None,
            "created_at": iso(),
        }
        if not self.adopt_account(account):
            raise HTTPException(409, "An account with this id already exists")
        self.workspace(account["id"])
        return account

    def update_account(self, account_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        with self.db.transaction() as cur:
            cur.execute("SELECT data FROM accounts WHERE id = %s FOR UPDATE", (str(account_id),))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Account not found")
            account = dict(row["data"])
            for field in ("name", "status", "owner_user_id"):
                if field in changes and changes[field] is not None:
                    account[field] = changes[field]
            _, name, status, owner, _, data = self._account_params(account)
            cur.execute("""UPDATE accounts SET name = %s, status = %s, owner_user_id = %s,
                                  data = %s, updated_at = now() WHERE id = %s""",
                        (name, status, owner, data, str(account_id)))
        return account

    def delete_account(self, account_id: str) -> None:
        """Delete an account: its row, and with it (by cascade) every user,
        session and record it owns, in one statement; then its files."""
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM accounts WHERE id = %s", (str(account_id),))
        with self._lock:
            workspace = self._workspaces.pop(account_id, None)
            workspace = workspace or AccountWorkspace(
                self.accounts_root / account_id, account_id, self._chroma_factory, self.db
            )
        # Outside the registry lock: removing a populated workspace can take a
        # moment and must not block other accounts' requests.
        workspace.delete()

    # -- users -----------------------------------------------------------

    @staticmethod
    def _user_params(user: Mapping[str, Any]) -> tuple:
        # Every write stores the built-ins under their current names, whatever
        # label an older client or an import carried.
        user = {**user, "role": canonical_role(user.get("role"))}
        return (str(user["id"]), str(user["account_id"]), _text(user.get("email")),
                _text(user.get("name")), _text(user.get("role")),
                _text(user.get("status")) or "Active", bool(user.get("is_owner")),
                parse_iso(user.get("created_at")) or utcnow(), as_json(user))

    def users_for_account(self, account_id: str) -> list[dict[str, Any]]:
        with self.db.transaction() as cur:
            cur.execute("SELECT data FROM users WHERE account_id = %s ORDER BY created_at, id",
                        (str(account_id),))
            return [row["data"] for row in cur.fetchall()]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.db.transaction() as cur:
            cur.execute("SELECT data FROM users WHERE id = %s", (str(user_id),))
            row = cur.fetchone()
        return row["data"] if row else None

    def find_by_email(self, email: str) -> dict[str, Any] | None:
        target = str(email or "").strip().lower()
        if not target:
            return None
        with self.db.transaction() as cur:
            cur.execute("SELECT data FROM users WHERE email_key = %s", (target,))
            row = cur.fetchone()
        return row["data"] if row else None

    def adopt_user(self, user: Mapping[str, Any]) -> bool:
        """Insert a user record as it is -- password hash and all (imports,
        legacy migration).  False when the id or the email is already taken."""
        try:
            with self.db.transaction() as cur:
                cur.execute("""INSERT INTO users (id, account_id, email, name, role, status,
                                                  is_owner, created_at, data)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT (id) DO NOTHING""", self._user_params(user))
                return cur.rowcount == 1
        except psycopg.errors.UniqueViolation:
            return False

    def create_user(
        self,
        *,
        account_id: str,
        name: str,
        email: str,
        password: str,
        role: str = "User",
        is_owner: bool = False,
        **profile: Any,
    ) -> dict[str, Any]:
        email = email.strip()
        user = {
            "id": str(uuid.uuid4()),
            "account_id": account_id,
            "name": name.strip(),
            "email": email,
            "password_hash": hash_password(password),
            "phone": str(profile.get("phone", "") or ""),
            "address": str(profile.get("address", "") or ""),
            "role": canonical_role(role),
            "department": str(profile.get("department", "") or ""),
            "designation": str(profile.get("designation", "") or ""),
            "company": str(profile.get("company", "") or ""),
            "time_zone": str(profile.get("time_zone", "UTC") or "UTC"),
            "status": str(profile.get("status", "Active") or "Active"),
            "is_owner": bool(is_owner),
            "created_at": iso(),
        }
        try:
            with self.db.transaction() as cur:
                cur.execute("""INSERT INTO users (id, account_id, email, name, role, status,
                                                  is_owner, created_at, data)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""", self._user_params(user))
        except psycopg.errors.UniqueViolation:
            # The unique index on lower(email) is the rule; two requests racing
            # to register the same address cannot both succeed.
            raise HTTPException(409, "An account with this email already exists") from None
        except psycopg.errors.ForeignKeyViolation:
            raise HTTPException(404, "Account not found") from None
        return user

    def _write_user(self, cur: Any, user: Mapping[str, Any]) -> None:
        _, account_id, email, name, role, status, is_owner, _, data = self._user_params(user)
        cur.execute("""UPDATE users SET account_id = %s, email = %s, name = %s, role = %s,
                              status = %s, is_owner = %s, data = %s, updated_at = now()
                       WHERE id = %s""",
                    (account_id, email, name, role, status, is_owner, data, str(user["id"])))

    def update_user(self, user_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        try:
            with self.db.transaction() as cur:
                cur.execute("SELECT data FROM users WHERE id = %s FOR UPDATE", (str(user_id),))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(404, "User not found")
                user = dict(row["data"])
                for field in (
                    "name", "email", "phone", "address", "role", "department",
                    "designation", "company", "time_zone", "status",
                ):
                    if field in changes and changes[field] is not None:
                        user[field] = changes[field]
                if changes.get("password"):
                    user["password_hash"] = hash_password(str(changes["password"]))
                self._write_user(cur, user)
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "Email already in use") from None
        if changes.get("password") or str(changes.get("status", "")).lower() == "inactive":
            self.revoke_user_sessions(user_id)
        return user

    def rehash_password(self, user_id: str, plain: str) -> dict[str, Any] | None:
        """Store the same password under the current hash parameters.

        Unlike a password change this revokes nothing: the credential has not
        changed, only how strongly it is stored.
        """
        with self.db.transaction() as cur:
            cur.execute("SELECT data FROM users WHERE id = %s FOR UPDATE", (str(user_id),))
            row = cur.fetchone()
            if not row:
                return None
            user = dict(row["data"])
            user["password_hash"] = hash_password(plain)
            self._write_user(cur, user)
        return user

    def delete_user(self, user_id: str) -> None:
        # Sessions go with the user (ON DELETE CASCADE).
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (str(user_id),))

    # -- sessions --------------------------------------------------------

    @staticmethod
    def _session_record(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "user_id": row["user_id"], "account_id": row["account_id"],
            "created_at": iso(row["created_at"]), "last_seen": iso(row["last_seen"]),
            "expires_at": iso(row["expires_at"]),
        }

    @staticmethod
    def _prune(cur: Any, now: datetime) -> None:
        cur.execute("DELETE FROM sessions WHERE expires_at <= %s OR last_seen < %s",
                    (now, now - timedelta(hours=SESSION_IDLE_HOURS)))

    def adopt_session(self, token_hash: str, session: Mapping[str, Any]) -> bool:
        """Insert a session as it is (imports); skipped when expired or orphaned."""
        now = utcnow()
        created = parse_iso(session.get("created_at")) or now
        last_seen = parse_iso(session.get("last_seen")) or created
        expires = parse_iso(session.get("expires_at"))
        if not expires or expires <= now or now - last_seen > timedelta(hours=SESSION_IDLE_HOURS):
            return False
        try:
            with self.db.transaction() as cur:
                cur.execute("""INSERT INTO sessions (token_hash, user_id, account_id, created_at,
                                                     last_seen, expires_at)
                               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                            (token_hash, str(session.get("user_id")), str(session.get("account_id")),
                             created, last_seen, expires))
                return cur.rowcount == 1
        except psycopg.errors.ForeignKeyViolation:
            return False

    def issue_session(self, user: Mapping[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        now = utcnow()
        with self.db.transaction() as cur:
            self._prune(cur, now)
            cur.execute("SELECT token_hash FROM sessions WHERE user_id = %s ORDER BY created_at",
                        (str(user["id"]),))
            owned = [row["token_hash"] for row in cur.fetchall()]
            stale = owned[: max(0, len(owned) - MAX_SESSIONS_PER_USER + 1)]
            if stale:
                cur.execute("DELETE FROM sessions WHERE token_hash = ANY(%s)", (stale,))
            cur.execute("""INSERT INTO sessions (token_hash, user_id, account_id, created_at,
                                                 last_seen, expires_at)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (hash_token(token), str(user["id"]), str(user["account_id"]), now, now,
                         now + timedelta(hours=SESSION_TTL_HOURS)))
        return token

    def resolve_session(self, token: str) -> dict[str, Any] | None:
        digest = hash_token(token)
        now = utcnow()
        with self.db.transaction() as cur:
            cur.execute("SELECT * FROM sessions WHERE token_hash = %s", (digest,))
            row = cur.fetchone()
            if row is None:
                return None
            if row["expires_at"] <= now or now - row["last_seen"] > timedelta(hours=SESSION_IDLE_HOURS):
                cur.execute("DELETE FROM sessions WHERE token_hash = %s", (digest,))
                return None
            # A coarse heartbeat: the idle window is hours, so writing on every
            # request would be a write per API call for nothing.
            if now - row["last_seen"] > timedelta(minutes=1):
                cur.execute("UPDATE sessions SET last_seen = %s WHERE token_hash = %s", (now, digest))
                row = {**row, "last_seen": now}
        return self._session_record(row)

    def revoke_session(self, token: str) -> None:
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM sessions WHERE token_hash = %s", (hash_token(token),))

    def revoke_user_sessions(self, user_id: str) -> None:
        with self.db.transaction() as cur:
            cur.execute("DELETE FROM sessions WHERE user_id = %s", (str(user_id),))

    # -- registration ----------------------------------------------------

    def migrate_account_roles(self, account_id: str) -> list[dict[str, Any]]:
        """Give an account a role record for every role its users already hold.

        Before custom roles, a member's abilities came from a hardcoded list.
        Seeding a role for each label actually in use -- with the permissions
        that label carried -- means nobody silently loses access the moment
        roles become data. Runs once; after that the stored roles are the source
        of truth and a Head (Super Admin) edits them on the User Roles page.
        """
        workspace = self.workspace(account_id)
        if not workspace.load_roles():
            self._seed_roles(account_id, workspace)
        return workspace.load_roles()

    def register_account(
        self, *, account_name: str, name: str, email: str, password: str, **profile: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.find_by_email(email):
            raise HTTPException(409, "An account with this email already exists")
        account = self.create_account(account_name)
        try:
            owner = self.create_user(
                account_id=account["id"], name=name, email=email, password=password,
                role=OWNER_ROLE, is_owner=True, **profile,
            )
        except Exception:
            self.delete_account(account["id"])
            raise
        account = self.update_account(account["id"], {"owner_user_id": owner["id"]})
        workspace = self.workspace(account["id"])
        workspace.save_mgmt(json.loads(json.dumps(DEFAULT_MANAGEMENT)))
        workspace.save_settings({
            **DEFAULT_SETTINGS,
            "company_name": str(profile.get("company", "") or account["name"]),
            "company_email": email,
            "time_zone": str(profile.get("time_zone", "UTC") or "UTC"),
        })
        return account, owner


def as_json(value: Any):
    """A record as a jsonb parameter (NUL and non-finite numbers removed)."""
    return as_jsonb(value)


def public_user(user: Mapping[str, Any]) -> dict[str, Any]:
    """A user record with the credential material removed."""
    return {key: value for key, value in user.items() if key != "password_hash"}


# --------------------------------------------------------------------------
# Legacy migration
# --------------------------------------------------------------------------

def migrate_legacy_workspace(registry: AccountRegistry, base_dir: Path, logger: Any = None) -> str | None:
    """Move pre-isolation single-tenant data into one owned account.

    The handover ships a populated ``BASE_DIR`` that predates account
    isolation.  Everything there belongs to whoever was using the machine, so it
    is moved wholesale into a single account owned by the existing administrator
    from ``users.json``: the logins and the JSON stores go into the database,
    the directories of files into the account's workspace.  Absolute page paths
    recorded in the document metadata, the generated-document register, and the
    Chroma index are rewritten to the new location.  A marker file makes the
    migration run exactly once.
    """
    base_dir = Path(base_dir)
    marker = base_dir / ".account_migration_complete"
    if marker.exists():
        return None

    legacy_metadata = base_dir / "metadata.json"
    legacy_users_raw = read_json(base_dir / "users.json", {})
    legacy_users = [
        user for user in (legacy_users_raw.values() if isinstance(legacy_users_raw, dict) else legacy_users_raw or [])
        if isinstance(user, dict) and user.get("id") and not user.get("account_id")
    ]
    legacy_dirs = [
        base_dir / name for name in
        ("documents", "pages", "chroma_db", "colpali_v1_2_multivectors",
         "generated_documents", "google_imports", "document_generation_vision_cache")
    ]
    has_legacy = (
        legacy_metadata.exists()
        or legacy_users
        or any(path.exists() and any(path.iterdir()) for path in legacy_dirs if path.is_dir())
    )
    if not has_legacy:
        marker.write_text(iso(), encoding="utf-8")
        return None

    def log(message: str) -> None:
        if logger is not None:
            logger.info(message)
        else:
            print(message)

    account = registry.create_account("Legacy Workspace")
    account_id = account["id"]
    workspace = registry.workspace(account_id)

    # Adopt the existing logins so the shipped credentials keep working.
    if legacy_users:
        preferred = next(
            (u for u in legacy_users if str(u.get("role", "")).lower().startswith("super")),
            legacy_users[0],
        )
        adopted = 0
        for user in legacy_users:
            record = dict(user)
            record["account_id"] = account_id
            record["is_owner"] = record["id"] == preferred["id"]
            record.setdefault("status", "Active")
            record.setdefault("created_at", iso())
            adopted += registry.adopt_user(record)
        registry.update_account(account_id, {"owner_user_id": str(preferred["id"])})
        log(f"Adopted {adopted} existing login(s) into the migrated account")
        # A pre-isolation installation had no stored roles; give its labels some.
        registry.migrate_account_roles(account_id)

    # Move directories.
    targets = {
        "documents": workspace.docs_dir,
        "pages": workspace.pages_dir,
        "chroma_db": workspace.chroma_dir,
        "colpali_v1_2_multivectors": workspace.multivector_dir,
        "generated_documents": workspace.generated_dir,
        "google_imports": workspace.imports_dir,
        "document_generation_vision_cache": workspace.vision_cache_dir,
    }
    for name, destination in targets.items():
        source = base_dir / name
        if not source.is_dir():
            continue
        destination.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            target = destination / item.name
            if target.exists():
                continue
            shutil.move(str(item), str(target))
        shutil.rmtree(source, ignore_errors=True)

    # The flat JSON stores go into the database.
    stores = {
        "metadata.json": workspace.save_metadata,
        "management.json": workspace.save_mgmt,
        "generated_documents.json": workspace.save_generated,
        "evidence_feedback.json": workspace.save_evidence,
    }
    for name, save in stores.items():
        source = base_dir / name
        data = read_json(source, None)
        if data is not None:
            save(data)
        source.unlink(missing_ok=True)
    tokens = base_dir / "google_workspace_accounts.enc"
    if tokens.exists():
        if tokens.stat().st_size:
            workspace.token_store("google").write(tokens.read_bytes())
        tokens.unlink(missing_ok=True)
    (base_dir / "users.json").unlink(missing_ok=True)

    # Rewrite absolute page paths recorded before the move.
    metadata = workspace.load_metadata()
    rewritten = 0
    for document in metadata.get("documents", {}).values():
        for page in document.get("pages") or []:
            stored = page.get("image_path")
            if not stored:
                continue
            relocated = workspace.pages_dir / Path(stored).name
            if relocated.exists() and str(relocated) != stored:
                page["image_path"] = str(relocated)
                rewritten += 1
    workspace.save_metadata(metadata)

    generated = workspace.load_generated()
    for record in generated.values():
        stored = (record or {}).get("file_path")
        if not stored:
            continue
        relocated = workspace.generated_dir / Path(stored).name
        if relocated.exists():
            record["file_path"] = str(relocated)
    workspace.save_generated(generated)

    # Rewrite the same paths inside the vector index, preserving embeddings.
    try:
        collection = workspace.collection
        if collection.count():
            existing = collection.get(include=["metadatas", "documents", "embeddings"])
            ids = existing.get("ids") or []
            metadatas = existing.get("metadatas") or []
            documents = existing.get("documents") or []
            embeddings = existing.get("embeddings") or []
            changed_ids, changed_meta, changed_docs, changed_vectors = [], [], [], []
            for index, item_id in enumerate(ids):
                record = dict(metadatas[index] or {}) if index < len(metadatas) else {}
                stored = str(record.get("image_path") or "")
                if not stored:
                    continue
                relocated = workspace.pages_dir / Path(stored).name
                if not relocated.exists() or str(relocated) == stored:
                    continue
                record["image_path"] = str(relocated)
                vector = embeddings[index] if index < len(embeddings) else None
                if vector is None:
                    continue
                changed_ids.append(item_id)
                changed_meta.append(record)
                changed_docs.append(documents[index] if index < len(documents) else "")
                changed_vectors.append(vector.tolist() if hasattr(vector, "tolist") else list(vector))
            if changed_ids:
                collection.update(
                    ids=changed_ids, embeddings=changed_vectors,
                    metadatas=changed_meta, documents=changed_docs,
                )
                log(f"Rewrote {len(changed_ids)} vector-index page paths")
    except Exception as exc:  # a stale index must not block startup
        log(f"Vector index path rewrite skipped: {exc}")

    marker.write_text(iso(), encoding="utf-8")
    log(
        f"Migrated legacy workspace into account {account_id} "
        f"({len(metadata.get('documents', {}))} documents, {rewritten} page paths rewritten)"
    )
    return account_id


# --------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    account_name: str = Field(default="", max_length=160)
    phone: str = Field(default="", max_length=60)
    address: str = Field(default="", max_length=300)
    department: str = Field(default="", max_length=120)
    designation: str = Field(default="", max_length=120)
    company: str = Field(default="", max_length=160)
    time_zone: str = Field(default="UTC", max_length=60)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


class ProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=120)
    designation: str | None = Field(default=None, max_length=120)
    company: str | None = Field(default=None, max_length=160)
    time_zone: str | None = Field(default=None, max_length=60)


class AccountUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class SettingsRequest(BaseModel):
    model: str | None = Field(default=None, max_length=120)
    top_k: int | None = Field(default=None, ge=1, le=20)
    company_name: str | None = Field(default=None, max_length=160)
    company_email: str | None = Field(default=None, max_length=200)
    company_phone: str | None = Field(default=None, max_length=60)
    company_address: str | None = Field(default=None, max_length=300)
    time_zone: str | None = Field(default=None, max_length=60)


class ConversationsRequest(BaseModel):
    conversations: dict[str, Any] = Field(default_factory=dict)


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(value: str) -> str:
    email = str(value or "").strip()
    if not EMAIL_PATTERN.match(email):
        raise HTTPException(422, "A valid email address is required")
    return email


def validate_password(value: str) -> str:
    password = str(value or "")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(422, f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    return password


# --------------------------------------------------------------------------
# Route registration
# --------------------------------------------------------------------------

def register_account_routes(namespace: dict[str, Any]) -> dict[str, Any]:
    """Register authentication, account, user, settings, and conversation routes.

    Injects ``ACCOUNT_REGISTRY``, ``require_account``, and ``optional_account``
    into ``namespace`` so the remaining cells and integration modules can depend
    on a resolved :class:`AccountContext` instead of module-level globals.
    """
    required = ("app", "BASE_DIR", "build_account_collection")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Account integration is missing: {', '.join(missing)}")

    # Build the unknown-email comparison hash now, so the first failed login
    # does not pay for it (and stand out by taking longer).
    dummy_password_hash()

    app = namespace["app"]
    base_dir = Path(namespace["BASE_DIR"])
    logger = namespace.get("logger")

    registry = AccountRegistry(base_dir, namespace["build_account_collection"], logger,
                               database=namespace.get("DATABASE"))
    namespace["DATABASE"] = registry.db
    migrate_legacy_workspace(registry, base_dir, logger)
    # An installation from before the database keeps its records in JSON files;
    # bring them in once.  See json_storage_import.
    try:
        from json_storage_import import import_json_storage
    except ModuleNotFoundError:
        from backend.json_storage_import import import_json_storage
    import_json_storage(registry, base_dir, logger)

    def bearer_token(request: Request) -> str:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[7:].strip()
        return ""

    def context_for(token: str) -> AccountContext | None:
        if not token:
            return None
        session = registry.resolve_session(token)
        if not session:
            return None
        user = registry.get_user(str(session.get("user_id", "")))
        if not user or str(user.get("status", "Active")).lower() != "active":
            return None
        account = registry.get_account(str(user.get("account_id", "")))
        if not account or str(account.get("status", "Active")).lower() != "active":
            return None
        return AccountContext(
            user=user, account=account,
            workspace=registry.workspace(str(account["id"])), token=token,
        )

    async def require_account(request: Request) -> AccountContext:
        context = context_for(bearer_token(request))
        if context is None:
            raise HTTPException(401, "Sign in to continue")
        return context

    async def optional_account(request: Request) -> AccountContext | None:
        return context_for(bearer_token(request))

    def session_payload(user: Mapping[str, Any], account: Mapping[str, Any], token: str) -> dict[str, Any]:
        workspace = registry.workspace(str(account["id"]))
        return {
            "token": token,
            "user": public_user(user),
            "account": {
                "id": account["id"], "name": account["name"],
                "status": account.get("status", "Active"),
                "created_at": account.get("created_at"),
                "owner_user_id": account.get("owner_user_id"),
            },
            "settings": workspace.load_settings(),
        }

    # -- authentication --------------------------------------------------

    @app.post("/api/auth/register")
    async def auth_register(body: RegisterRequest) -> dict[str, Any]:
        email = validate_email(body.email)
        password = validate_password(body.password)
        account_name = body.account_name.strip() or body.company.strip() or f"{body.name.strip()}'s workspace"
        account, owner = registry.register_account(
            account_name=account_name, name=body.name, email=email, password=password,
            phone=body.phone, address=body.address, department=body.department,
            designation=body.designation, company=body.company, time_zone=body.time_zone,
        )
        token = registry.issue_session(owner)
        payload = session_payload(owner, account, token)
        payload["message"] = "Account created successfully"
        return payload

    @app.post("/api/auth/login")
    async def auth_login(body: LoginRequest) -> dict[str, Any]:
        user = registry.find_by_email(body.email)
        # Compare against a dummy hash when the email is unknown so a missing
        # account and a wrong password take the same time to answer: one key
        # derivation each.
        stored = str(user.get("password_hash", "")) if user else dummy_password_hash()
        valid, needs_rehash = verify_password(body.password, stored)
        if not user or not valid:
            raise HTTPException(401, "Invalid email or password")
        if str(user.get("status", "Active")).lower() != "active":
            raise HTTPException(403, "Account is deactivated. Contact your administrator.")
        account = registry.get_account(str(user.get("account_id", "")))
        if not account:
            raise HTTPException(403, "This login is not attached to an active workspace")
        if str(account.get("status", "Active")).lower() != "active":
            raise HTTPException(403, "This workspace has been deactivated")
        if needs_rehash:
            # Same password, stronger hash: other devices stay signed in.
            user = registry.rehash_password(user["id"], body.password) or user
        token = registry.issue_session(user)
        payload = session_payload(user, account, token)
        payload["message"] = "Login successful"
        return payload

    @app.post("/api/auth/logout")
    async def auth_logout(context: AccountContext = Depends(require_account)) -> dict[str, Any]:
        registry.revoke_session(context.token)
        return {"message": "Signed out"}

    @app.get("/api/auth/me")
    async def auth_me(context: AccountContext = Depends(require_account)) -> dict[str, Any]:
        return session_payload(context.user, context.account, context.token)

    @app.put("/api/auth/profile")
    async def auth_profile(
        body: ProfileUpdateRequest, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        changes = {k: v for k, v in body.model_dump().items() if v is not None}
        user = registry.update_user(context.user_id, changes)
        return {"user": public_user(user)}

    @app.put("/api/auth/password")
    async def auth_password(
        body: PasswordChangeRequest, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        valid, _ = verify_password(body.current_password, str(context.user.get("password_hash", "")))
        if not valid:
            raise HTTPException(403, "Current password is incorrect")
        registry.update_user(context.user_id, {"password": validate_password(body.new_password)})
        token = registry.issue_session(registry.get_user(context.user_id) or context.user)
        return {"message": "Password updated", "token": token}

    # -- account ---------------------------------------------------------

    @app.get("/api/account")
    async def get_account(context: AccountContext = Depends(require_account)) -> dict[str, Any]:
        workspace = context.workspace
        metadata = workspace.load_metadata()
        return {
            "account": {
                "id": context.account["id"], "name": context.account["name"],
                "status": context.account.get("status", "Active"),
                "created_at": context.account.get("created_at"),
                "owner_user_id": context.account.get("owner_user_id"),
            },
            "usage": {
                "documents": len(metadata.get("documents", {})),
                "indexed_pages": workspace.collection.count(),
                "members": len(registry.users_for_account(context.account_id)),
                "projects": len(workspace.load_projects()),
                "conversations": len(workspace.load_conversations()),
            },
        }

    @app.put("/api/account")
    async def rename_account(
        body: AccountUpdateRequest, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        context.require_admin()
        return {"account": registry.update_account(context.account_id, {"name": body.name})}

    @app.delete("/api/account")
    async def remove_account(context: AccountContext = Depends(require_account)) -> dict[str, Any]:
        if not context.user.get("is_owner"):
            raise HTTPException(403, "Only the account owner can delete this workspace")
        registry.delete_account(context.account_id)
        return {"message": "Account and all of its data were deleted"}

    @app.get("/api/account/settings")
    async def get_settings(context: AccountContext = Depends(require_account)) -> dict[str, Any]:
        return {"settings": context.workspace.load_settings()}

    @app.put("/api/account/settings")
    async def put_settings(
        body: SettingsRequest, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        current = context.workspace.load_settings()
        current.update({k: v for k, v in body.model_dump().items() if v is not None})
        return {"settings": context.workspace.save_settings(current)}

    # -- conversations ---------------------------------------------------

    @app.get("/api/conversations")
    async def list_conversations(context: AccountContext = Depends(require_account)) -> dict[str, Any]:
        return {"conversations": context.workspace.load_conversations()}

    @app.put("/api/conversations")
    async def replace_conversations(
        body: ConversationsRequest, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        conversations = {
            str(key): value for key, value in body.conversations.items()
            if isinstance(value, dict)
        }
        context.workspace.save_conversations(conversations)
        return {"saved": len(conversations)}

    @app.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(
        conversation_id: str, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        conversations = context.workspace.load_conversations()
        if conversation_id not in conversations:
            raise HTTPException(404, "Conversation not found")
        conversations.pop(conversation_id)
        context.workspace.save_conversations(conversations)
        return {"message": "Conversation deleted", "id": conversation_id}

    # -- members ---------------------------------------------------------

    @app.get("/api/users")
    async def list_users(
        name: str = "", email: str = "", status: str = "", role: str = "",
        department: str = "", context: AccountContext = Depends(require_account),
    ) -> dict[str, Any]:
        users = [public_user(u) for u in registry.users_for_account(context.account_id)]
        if name and len(name) >= 3:
            users = [u for u in users if name.lower() in str(u.get("name", "")).lower()]
        if email and len(email) >= 3:
            users = [u for u in users if email.lower() in str(u.get("email", "")).lower()]
        if status:
            users = [u for u in users if u.get("status") == status]
        if role:
            users = [u for u in users if u.get("role") == role]
        if department:
            users = [u for u in users if u.get("department", "") == department]
        return {"users": users, "total": len(users)}

    def member_or_404(user_id: str, context: AccountContext) -> dict[str, Any]:
        user = registry.get_user(user_id)
        if not user or str(user.get("account_id")) != context.account_id:
            # A member of another account must be indistinguishable from one
            # that does not exist, otherwise ids become an enumeration oracle.
            raise HTTPException(404, "User not found")
        return user

    @app.get("/api/users/{user_id}")
    async def get_user_route(
        user_id: str, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        return public_user(member_or_404(user_id, context))

    def assert_known_role(context: AccountContext, value: Any) -> str:
        """A role must be one this account actually has.

        Without this a direct PUT could store any string, and a user holding an
        unknown role would resolve to no permissions at all -- failing closed,
        but confusingly.
        """
        wanted = canonical_role(value)
        if not wanted:
            # A new workspace has no roles until a Head (Super Admin) makes one, and
            # none are shipped. Someone can therefore be added before a role
            # exists for them; with no role they hold no permissions, so this
            # fails closed rather than granting anything by default.
            return ""
        known = role_names(context.workspace.load_roles())
        for name in known:
            if name.casefold() == wanted.casefold():
                return name
        raise HTTPException(422, f"Unknown role: {wanted}")

    @app.post("/api/users")
    async def create_user_route(
        request: Request, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        context.require_admin()
        data = await request.json()
        name = str(data.get("name", "")).strip()
        if not name:
            raise HTTPException(422, "Name is required")
        email = validate_email(data.get("email", ""))
        password = validate_password(data.get("password", ""))
        role = assert_known_role(context, data.get("role") or "")
        user = registry.create_user(
            account_id=context.account_id, name=name, email=email, password=password,
            role=role,
            phone=data.get("phone", ""), address=data.get("address", ""),
            department=data.get("department", ""), designation=data.get("designation", ""),
            company=data.get("company", ""), time_zone=data.get("time_zone", "UTC"),
            status=data.get("status", "Active"),
        )
        return public_user(user)

    # Fields that grant authority.  Editing your own record is self-service and
    # must not become a way to promote yourself.
    PRIVILEGED_FIELDS = ("role", "status")

    @app.put("/api/users/{user_id}")
    async def update_user_route(
        user_id: str, request: Request, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        member = member_or_404(user_id, context)
        data = await request.json()
        if user_id != context.user_id:
            context.require_admin()
        elif not context.is_admin:
            for field in PRIVILEGED_FIELDS:
                if field in data and data[field] != member.get(field):
                    raise HTTPException(403, f"Only an administrator can change a user's {field}")
        if member.get("is_owner") and str(data.get("status", "Active")).lower() == "inactive":
            raise HTTPException(409, "The account owner cannot be deactivated")
        if "role" in data:
            data["role"] = assert_known_role(context, data["role"])
        if "email" in data and data["email"]:
            data["email"] = validate_email(data["email"])
        if data.get("password"):
            data["password"] = validate_password(data["password"])
        return public_user(registry.update_user(user_id, data))

    @app.delete("/api/users/{user_id}")
    async def delete_user_route(
        user_id: str, context: AccountContext = Depends(require_account)
    ) -> dict[str, Any]:
        member = member_or_404(user_id, context)
        context.require_admin()
        if member.get("is_owner"):
            raise HTTPException(409, "The account owner cannot be deactivated")
        registry.update_user(user_id, {"status": "Inactive"})
        return {"message": "User deactivated"}

    # The FastAPI cell defines thin ``require_account``/``optional_account``
    # wrappers before this module is importable, and its routes already captured
    # them through ``Depends``.  Publish the real resolver for those wrappers to
    # delegate to rather than rebinding names the routes no longer look up.
    namespace["ACCOUNT_REGISTRY"] = registry
    namespace["ACCOUNT_RESOLVER"] = context_for
    namespace["AccountContext"] = AccountContext
    namespace.setdefault("require_account", require_account)
    namespace.setdefault("optional_account", optional_account)
    return {
        "registry": registry,
        "require_account": require_account,
        "optional_account": optional_account,
        "accounts": len(registry.list_accounts()),
    }


__all__ = [
    "AccountContext", "AccountRegistry", "AccountWorkspace", "DEFAULT_MANAGEMENT",
    "DEFAULT_SETTINGS", "hash_password", "migrate_legacy_workspace", "public_user",
    "register_account_routes", "safe_identifier", "verify_password",
]
