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

import hashlib
import hmac
import json
import os
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
        BUILTIN_ROLES, PERMISSION_KEYS, SUPER_ADMIN_ROLE, SYSTEM_ADMIN_ROLE,
        clean_permissions, is_builtin_admin, is_super_admin, resolve_permissions,
        role_names,
    )
except ModuleNotFoundError:  # imported as backend.accounts
    from backend.permissions import (
        BUILTIN_ROLES, PERMISSION_KEYS, SUPER_ADMIN_ROLE, SYSTEM_ADMIN_ROLE,
        clean_permissions, is_builtin_admin, is_super_admin, resolve_permissions,
        role_names,
    )

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 240_000
SESSION_TTL_HOURS = 12
SESSION_IDLE_HOURS = 4
MAX_SESSIONS_PER_USER = 12
MIN_PASSWORD_LENGTH = 8

# Roles that administer the account itself. These are system-level and stay
# separate from what someone does day to day.
# The only roles that exist without being created. Everything else is made by
# a Super Admin on the User Roles page and is exactly the permissions it was
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
    "voice_api_url": "",
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

    Returns ``(is_valid, needs_rehash)``.  Accounts created before per-user
    salting used a bare SHA-256 digest; those still authenticate once and are
    transparently upgraded to PBKDF2 by the caller.
    """
    stored = str(stored or "")
    if stored.startswith(PBKDF2_ALGORITHM + "$"):
        try:
            _, iterations, salt_hex, digest_hex = stored.split("$", 3)
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac(
                "sha256", plain.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
            )
        except (ValueError, TypeError):
            return False, False
        return hmac.compare_digest(expected, actual), False
    if len(stored) == 64:
        legacy = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, stored), True
    return False, False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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

class AccountWorkspace:
    """Every file and index owned by a single account.

    Nothing in this class accepts an absolute path from a request.  Callers pass
    ids; the workspace turns them into paths beneath its own root, so a request
    handled for one account can never name a file belonging to another.
    """

    def __init__(self, root: Path, account_id: str, chroma_factory: Callable[[Path], Any]):
        self.account_id = account_id
        self.root = Path(root).resolve()
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

        self.metadata_file = self.root / "metadata.json"
        self.mgmt_file = self.root / "management.json"
        self.projects_file = self.root / "projects.json"
        self.tasks_file = self.root / "tasks.json"
        self.procurement_file = self.root / "procurement.json"
        self.settings_file = self.root / "settings.json"
        self.company_file = self.root / "company.json"
        self.roles_file = self.root / "user_roles.json"
        self.conversations_file = self.root / "conversations.json"
        self.onboarding_file = self.root / "onboarding.json"
        self.evidence_file = self.root / "evidence_feedback.json"
        self.generated_registry = self.root / "generated_documents.json"
        self.google_store_file = self.root / "google_workspace_accounts.enc"

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

    # -- JSON stores -----------------------------------------------------

    def load_metadata(self) -> dict[str, Any]:
        data = read_json(self.metadata_file, {"documents": {}})
        if not isinstance(data, dict) or not isinstance(data.get("documents"), dict):
            return {"documents": {}}
        return data

    def save_metadata(self, meta: Mapping[str, Any]) -> None:
        write_json(self.metadata_file, meta)

    def load_mgmt(self) -> dict[str, Any]:
        data = read_json(self.mgmt_file, None)
        if not isinstance(data, dict):
            data = json.loads(json.dumps(DEFAULT_MANAGEMENT))
            write_json(self.mgmt_file, data)
        for key, default in DEFAULT_MANAGEMENT.items():
            data.setdefault(key, json.loads(json.dumps(default)))
        return data

    def save_mgmt(self, data: Mapping[str, Any]) -> None:
        write_json(self.mgmt_file, data)

    def load_projects(self) -> dict[str, dict[str, Any]]:
        data = read_json(self.projects_file, {})
        return data if isinstance(data, dict) else {}

    def save_projects(self, data: Mapping[str, Any]) -> None:
        write_json(self.projects_file, data)

    def load_tasks(self) -> dict[str, list[dict[str, Any]]]:
        data = read_json(self.tasks_file, {})
        return data if isinstance(data, dict) else {}

    def save_tasks(self, data: Mapping[str, Any]) -> None:
        write_json(self.tasks_file, data)

    def load_procurement(self) -> dict[str, list[dict[str, Any]]]:
        data = read_json(self.procurement_file, {})
        return data if isinstance(data, dict) else {}

    def save_procurement(self, data: Mapping[str, Any]) -> None:
        write_json(self.procurement_file, data)

    def load_settings(self) -> dict[str, Any]:
        data = read_json(self.settings_file, {})
        merged = dict(DEFAULT_SETTINGS)
        if isinstance(data, dict):
            merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        return merged

    def save_settings(self, data: Mapping[str, Any]) -> dict[str, Any]:
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        write_json(self.settings_file, merged)
        return merged

    def load_roles(self) -> list[dict[str, Any]]:
        data = read_json(self.roles_file, [])
        return data if isinstance(data, list) else []

    def save_roles(self, data: Sequence[Mapping[str, Any]]) -> None:
        write_json(self.roles_file, list(data))

    def load_company(self) -> dict[str, Any]:
        data = read_json(self.company_file, {})
        return data if isinstance(data, dict) else {}

    def save_company(self, data: Mapping[str, Any]) -> None:
        write_json(self.company_file, data)

    def load_conversations(self) -> dict[str, Any]:
        data = read_json(self.conversations_file, {})
        return data if isinstance(data, dict) else {}

    def save_conversations(self, data: Mapping[str, Any]) -> None:
        write_json(self.conversations_file, data)

    def load_onboarding(self) -> dict[str, Any]:
        """Onboarding drafts, keyed by draft id."""
        data = read_json(self.onboarding_file, {})
        return data if isinstance(data, dict) else {}

    def save_onboarding(self, data: Mapping[str, Any]) -> None:
        write_json(self.onboarding_file, data)

    def delete(self) -> None:
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
        return bool(self.user.get("is_owner")) or self.user.get("role") in ADMIN_ROLES

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
            raise HTTPException(403, "This action requires a Super Admin")

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

        Tasks carry the assignee's display name, so match on that first and
        fall back to the email for members whose name was never filled in.
        """
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

class AccountRegistry:
    """Accounts, users, and sessions, plus the workspace cache."""

    def __init__(self, base_dir: Path, chroma_factory: Callable[[Path], Any], logger: Any = None):
        self.base_dir = Path(base_dir)
        self.accounts_root = self.base_dir / "accounts"
        self.accounts_file = self.base_dir / "accounts.json"
        self.users_file = self.base_dir / "users.json"
        self.sessions_file = self.base_dir / "sessions.json"
        self._chroma_factory = chroma_factory
        self._logger = logger
        self._lock = threading.RLock()
        self._workspaces: dict[str, AccountWorkspace] = {}
        self.accounts_root.mkdir(parents=True, exist_ok=True)

    # -- storage ---------------------------------------------------------

    def _accounts(self) -> dict[str, dict[str, Any]]:
        data = read_json(self.accounts_file, {})
        return data if isinstance(data, dict) else {}

    def _users(self) -> dict[str, dict[str, Any]]:
        data = read_json(self.users_file, {})
        if isinstance(data, list):
            data = {u["id"]: u for u in data if isinstance(u, dict) and "id" in u}
        return data if isinstance(data, dict) else {}

    def _sessions(self) -> dict[str, dict[str, Any]]:
        data = read_json(self.sessions_file, {})
        return data if isinstance(data, dict) else {}

    # -- workspaces ------------------------------------------------------

    def workspace(self, account_id: str) -> AccountWorkspace:
        with self._lock:
            workspace = self._workspaces.get(account_id)
            if workspace is None:
                workspace = AccountWorkspace(
                    self.accounts_root / account_id, account_id, self._chroma_factory
                ).ensure()
                self._workspaces[account_id] = workspace
                needs_role_seed = not workspace.load_roles()
            else:
                needs_role_seed = False
        if needs_role_seed:
            # Outside the lock: seeding reads the user list, which takes it.
            self._seed_roles(account_id, workspace)
        return workspace

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

    def list_accounts(self) -> list[dict[str, Any]]:
        return list(self._accounts().values())

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        return self._accounts().get(account_id)

    def create_account(self, name: str, *, account_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            accounts = self._accounts()
            new_id = account_id or uuid.uuid4().hex
            account = {
                "id": new_id,
                "name": name.strip() or "Workspace",
                "status": "Active",
                "owner_user_id": None,
                "created_at": iso(),
            }
            accounts[new_id] = account
            write_json(self.accounts_file, accounts)
        self.workspace(new_id)
        return account

    def update_account(self, account_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            accounts = self._accounts()
            account = accounts.get(account_id)
            if not account:
                raise HTTPException(404, "Account not found")
            for field in ("name", "status", "owner_user_id"):
                if field in changes and changes[field] is not None:
                    account[field] = changes[field]
            accounts[account_id] = account
            write_json(self.accounts_file, accounts)
            return account

    def delete_account(self, account_id: str) -> None:
        with self._lock:
            accounts = self._accounts()
            accounts.pop(account_id, None)
            write_json(self.accounts_file, accounts)

            users = self._users()
            removed = [uid for uid, user in users.items() if user.get("account_id") == account_id]
            for uid in removed:
                users.pop(uid, None)
            write_json(self.users_file, users)

            sessions = {
                token: session for token, session in self._sessions().items()
                if session.get("account_id") != account_id
            }
            write_json(self.sessions_file, sessions)

            workspace = self._workspaces.pop(account_id, None)
            workspace = workspace or AccountWorkspace(
                self.accounts_root / account_id, account_id, self._chroma_factory
            )
        # Outside the registry lock: removing a populated workspace can take a
        # moment and must not block other accounts' requests.
        workspace.delete()

    # -- users -----------------------------------------------------------

    def users_for_account(self, account_id: str) -> list[dict[str, Any]]:
        return [u for u in self._users().values() if u.get("account_id") == account_id]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self._users().get(user_id)

    def find_by_email(self, email: str) -> dict[str, Any] | None:
        target = str(email or "").strip().lower()
        if not target:
            return None
        for user in self._users().values():
            if str(user.get("email", "")).lower() == target:
                return user
        return None

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
        with self._lock:
            users = self._users()
            for user in users.values():
                if str(user.get("email", "")).lower() == email.lower():
                    raise HTTPException(409, "An account with this email already exists")
            user = {
                "id": str(uuid.uuid4()),
                "account_id": account_id,
                "name": name.strip(),
                "email": email,
                "password_hash": hash_password(password),
                "phone": str(profile.get("phone", "") or ""),
                "address": str(profile.get("address", "") or ""),
                "role": str(role or "").strip(),
                "department": str(profile.get("department", "") or ""),
                "designation": str(profile.get("designation", "") or ""),
                "company": str(profile.get("company", "") or ""),
                "time_zone": str(profile.get("time_zone", "UTC") or "UTC"),
                "status": str(profile.get("status", "Active") or "Active"),
                "is_owner": bool(is_owner),
                "created_at": iso(),
            }
            users[user["id"]] = user
            write_json(self.users_file, users)
        return user

    def update_user(self, user_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            users = self._users()
            user = users.get(user_id)
            if not user:
                raise HTTPException(404, "User not found")
            if "email" in changes and changes["email"]:
                candidate = str(changes["email"]).strip()
                for other_id, other in users.items():
                    if other_id != user_id and str(other.get("email", "")).lower() == candidate.lower():
                        raise HTTPException(409, "Email already in use")
            for field in (
                "name", "email", "phone", "address", "role", "department",
                "designation", "company", "time_zone", "status",
            ):
                if field in changes and changes[field] is not None:
                    user[field] = changes[field]
            if changes.get("password"):
                user["password_hash"] = hash_password(str(changes["password"]))
            users[user_id] = user
            write_json(self.users_file, users)
        if changes.get("password") or str(changes.get("status", "")).lower() == "inactive":
            self.revoke_user_sessions(user_id)
        return user

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            users = self._users()
            users.pop(user_id, None)
            write_json(self.users_file, users)
        self.revoke_user_sessions(user_id)

    # -- sessions --------------------------------------------------------

    def _prune(self, sessions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        now = utcnow()
        alive: dict[str, dict[str, Any]] = {}
        for key, session in sessions.items():
            expires = parse_iso(session.get("expires_at"))
            last_seen = parse_iso(session.get("last_seen")) or parse_iso(session.get("created_at"))
            if expires and expires <= now:
                continue
            if last_seen and now - last_seen > timedelta(hours=SESSION_IDLE_HOURS):
                continue
            alive[key] = session
        return alive

    def issue_session(self, user: Mapping[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            sessions = self._prune(self._sessions())
            owned = sorted(
                (k for k, s in sessions.items() if s.get("user_id") == user["id"]),
                key=lambda k: str(sessions[k].get("created_at", "")),
            )
            for stale in owned[: max(0, len(owned) - MAX_SESSIONS_PER_USER + 1)]:
                sessions.pop(stale, None)
            sessions[hash_token(token)] = {
                "user_id": str(user["id"]),
                "account_id": str(user["account_id"]),
                "created_at": iso(),
                "last_seen": iso(),
                "expires_at": iso(utcnow() + timedelta(hours=SESSION_TTL_HOURS)),
            }
            write_json(self.sessions_file, sessions)
        return token

    def resolve_session(self, token: str) -> dict[str, Any] | None:
        digest = hash_token(token)
        now = utcnow()
        with self._lock:
            sessions = self._sessions()
            session = sessions.get(digest)
            if session is None:
                return None
            expires = parse_iso(session.get("expires_at"))
            last_seen = parse_iso(session.get("last_seen")) or parse_iso(session.get("created_at"))
            if (expires and expires <= now) or (
                last_seen and now - last_seen > timedelta(hours=SESSION_IDLE_HOURS)
            ):
                write_json(self.sessions_file, self._prune(sessions))
                return None
            # Rewriting the store on every request would be a disk write per API
            # call; the idle window is hours, so a coarse heartbeat is enough.
            if not last_seen or now - last_seen > timedelta(minutes=1):
                session["last_seen"] = iso(now)
                sessions[digest] = session
                write_json(self.sessions_file, self._prune(sessions))
        return session

    def revoke_session(self, token: str) -> None:
        digest = hash_token(token)
        with self._lock:
            sessions = self._sessions()
            sessions.pop(digest, None)
            write_json(self.sessions_file, sessions)

    def revoke_user_sessions(self, user_id: str) -> None:
        with self._lock:
            sessions = {
                key: session for key, session in self._sessions().items()
                if session.get("user_id") != user_id
            }
            write_json(self.sessions_file, sessions)

    # -- registration ----------------------------------------------------

    def migrate_account_roles(self, account_id: str) -> list[dict[str, Any]]:
        """Give an account a role record for every role its users already hold.

        Before custom roles, a member's abilities came from a hardcoded list.
        Seeding a role for each label actually in use -- with the permissions
        that label carried -- means nobody silently loses access the moment
        roles become data. Runs once; after that the file is the source of
        truth and a Super Admin edits it on the User Roles page.
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
    from ``users.json``.  Absolute page paths recorded in ``metadata.json``, the
    generated-document registry, and the Chroma index are rewritten to the new
    location.  A marker file makes the migration run exactly once.
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
    legacy_files = [
        base_dir / name for name in
        ("metadata.json", "management.json", "generated_documents.json",
         "evidence_feedback.json", "google_workspace_accounts.enc")
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
    owner_id: str | None = None
    if legacy_users:
        users = registry._users()
        preferred = next(
            (u for u in legacy_users if str(u.get("role", "")).lower().startswith("super")),
            legacy_users[0],
        )
        for user in legacy_users:
            record = dict(user)
            record["account_id"] = account_id
            record["is_owner"] = record["id"] == preferred["id"]
            record.setdefault("status", "Active")
            record.setdefault("created_at", iso())
            users[str(record["id"])] = record
        owner_id = str(preferred["id"])
        write_json(registry.users_file, users)
        registry.update_account(account_id, {"owner_user_id": owner_id})
        log(f"Adopted {len(legacy_users)} existing login(s) into the migrated account")

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

    # Move flat JSON stores.
    file_targets = {
        "metadata.json": workspace.metadata_file,
        "management.json": workspace.mgmt_file,
        "generated_documents.json": workspace.generated_registry,
        "evidence_feedback.json": workspace.evidence_file,
        "google_workspace_accounts.enc": workspace.google_store_file,
    }
    for name, destination in file_targets.items():
        source = base_dir / name
        if source.exists() and not destination.exists():
            shutil.move(str(source), str(destination))
    for path in legacy_files:
        if path.exists():
            path.unlink(missing_ok=True)

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

    registry_data = read_json(workspace.generated_registry, {})
    if isinstance(registry_data, dict):
        for record in registry_data.values():
            stored = (record or {}).get("file_path")
            if not stored:
                continue
            relocated = workspace.generated_dir / Path(stored).name
            if relocated.exists():
                record["file_path"] = str(relocated)
        write_json(workspace.generated_registry, registry_data)

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
    voice_api_url: str | None = Field(default=None, max_length=500)
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

    app = namespace["app"]
    base_dir = Path(namespace["BASE_DIR"])
    logger = namespace.get("logger")

    registry = AccountRegistry(base_dir, namespace["build_account_collection"], logger)
    migrate_legacy_workspace(registry, base_dir, logger)

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
        # account and a wrong password take the same time to answer.
        stored = str(user.get("password_hash", "")) if user else hash_password(secrets.token_hex(8))
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
            registry.update_user(user["id"], {"password": body.password})
            user = registry.get_user(user["id"]) or user
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
        wanted = str(value or "").strip()
        if not wanted:
            # A new workspace has no roles until a Super Admin makes one, and
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
