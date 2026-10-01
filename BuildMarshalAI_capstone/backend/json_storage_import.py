"""Bring an installation's JSON-file records into PostgreSQL, once.

Before the database, every record lived in JSON files under ``BASE_DIR``:
``accounts.json``, ``users.json`` and ``sessions.json`` at the top, and each
account's stores under ``accounts/<id>/`` (``projects.json``, ``tasks.json``,
``metadata.json`` and the rest, plus the encrypted ``*.enc`` OAuth token files).
:func:`import_json_storage` reads all of them into the database in a single
transaction -- so an interrupted import leaves nothing half-done and simply runs
again -- and then moves the files into ``BASE_DIR/json-storage-backup/<time>/``,
keeping them, but out of the way. ``app_meta.json_storage_import`` records that it
happened and what came across, so it never runs twice.

Uploaded files, page images, caches and the ChromaDB index are not records and
stay exactly where they are.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from accounts import AccountRegistry, iso, read_json
except ModuleNotFoundError:
    from backend.accounts import AccountRegistry, iso, read_json

IMPORT_KEY = "json_storage_import"

# Per-account JSON stores and the workspace method that saves each.
ACCOUNT_STORES = (
    ("metadata.json", "save_metadata"),
    ("management.json", "save_mgmt"),
    ("projects.json", "save_projects"),
    ("tasks.json", "save_tasks"),
    ("procurement.json", "save_procurement"),
    ("settings.json", "save_settings"),
    ("company.json", "save_company"),
    ("user_roles.json", "save_roles"),
    ("conversations.json", "save_conversations"),
    ("onboarding.json", "save_onboarding"),
    ("evidence_feedback.json", "save_evidence"),
    ("generated_documents.json", "save_generated"),
)
TOKEN_FILES = (
    ("google_workspace_accounts.enc", "google"),
    ("microsoft_accounts.enc", "microsoft"),
)
TOP_LEVEL_FILES = ("accounts.json", "users.json", "sessions.json")


def import_json_storage(registry: AccountRegistry, base_dir: Path, logger: Any = None) -> dict[str, Any] | None:
    """Import the JSON stores under ``base_dir``; return what was imported, or
    None when there was nothing to do."""
    database = registry.db
    if database.get_meta(IMPORT_KEY):
        return None
    base = Path(base_dir)
    accounts_file = base / "accounts.json"
    if not accounts_file.exists():
        database.set_meta(IMPORT_KEY, {"status": "nothing to import", "at": iso()})
        return None

    def log(message: str) -> None:
        (logger.info if logger is not None else print)(message)

    accounts = read_json(accounts_file, {})
    accounts = accounts if isinstance(accounts, dict) else {}
    users = read_json(base / "users.json", {})
    if isinstance(users, list):
        users = {str(u["id"]): u for u in users if isinstance(u, dict) and u.get("id")}
    users = users if isinstance(users, dict) else {}
    sessions = read_json(base / "sessions.json", {})
    sessions = sessions if isinstance(sessions, dict) else {}

    report: dict[str, Any] = {"accounts": 0, "users": 0, "users_skipped": [], "sessions": 0,
                              "stores": {}, "token_stores": 0}
    moved: list[Path] = []
    with database.atomic():
        for account_id, account in accounts.items():
            if not isinstance(account, dict):
                continue
            record = {**account, "id": str(account.get("id") or account_id)}
            report["accounts"] += registry.adopt_account(record)
        known_accounts = {str(a.get("id") or key) for key, a in accounts.items() if isinstance(a, dict)}

        for user_id, user in users.items():
            if not isinstance(user, dict):
                continue
            record = {**user, "id": str(user.get("id") or user_id)}
            if str(record.get("account_id") or "") not in known_accounts:
                report["users_skipped"].append({"id": record["id"], "reason": "no such account"})
                continue
            if registry.adopt_user(record):
                report["users"] += 1
            else:
                report["users_skipped"].append({"id": record["id"], "reason": "id or email already taken"})

        for token_hash, session in sessions.items():
            if isinstance(session, dict) and registry.adopt_session(str(token_hash), session):
                report["sessions"] += 1

        for account_id in sorted(known_accounts):
            workspace = registry._open_workspace(account_id)   # no role seeding mid-import
            for filename, method in ACCOUNT_STORES:
                path = workspace.root / filename
                if not path.exists():
                    continue
                data = read_json(path, None)
                if data is not None:
                    getattr(workspace, method)(data)
                    report["stores"][filename] = report["stores"].get(filename, 0) + 1
                moved.append(path)
            for filename, provider in TOKEN_FILES:
                path = workspace.root / filename
                if not path.exists():
                    continue
                if path.stat().st_size:
                    workspace.token_store(provider).write(path.read_bytes())
                    report["token_stores"] += 1
                moved.append(path)

    for name in TOP_LEVEL_FILES:
        if (base / name).exists():
            moved.append(base / name)
    backup = base / "json-storage-backup" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for path in moved:
        target = backup / path.relative_to(base)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    report.update({"status": "imported", "at": iso(), "backup": str(backup), "files": len(moved)})
    database.set_meta(IMPORT_KEY, report)
    log(f"Imported JSON storage into PostgreSQL: {report['accounts']} account(s), "
        f"{report['users']} user(s), {sum(report['stores'].values())} store file(s); "
        f"originals moved to {backup}")
    return report


__all__ = ["IMPORT_KEY", "import_json_storage"]
