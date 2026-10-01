"""Move a JSON-era BuildMarshalAI data directory's records into PostgreSQL.

The backend does this by itself on its first start against a new database;
this runs the same steps without loading the models, and can preview them.

    python scripts/import_json_storage.py [--data-dir DIR] [--dry-run]

``--dry-run`` reads the JSON files and reports what would be imported, touching
nothing. Otherwise: pre-isolation data is migrated into an account first (as at
start-up), then every JSON store goes into the database in one transaction and
the files are moved to ``<data-dir>/json-storage-backup/<time>/``.
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


def chroma_collection(chroma_dir: Path):
    """The account's ChromaDB collection, opened as the backend opens it."""
    import chromadb

    class NoEmbedding(chromadb.EmbeddingFunction):
        def __init__(self):
            pass

        def __call__(self, input):  # pragma: no cover - never called
            raise RuntimeError("vectors are supplied by ColPali")

    client = chromadb.PersistentClient(path=str(chroma_dir))
    try:
        collection = client.get_collection(name="document_pages", embedding_function=NoEmbedding())
    except Exception:
        collection = client.create_collection(name="document_pages", embedding_function=NoEmbedding(),
                                              metadata={"hnsw:space": "cosine"})
    return client, collection


def preview(base: Path) -> dict:
    from json_storage_import import ACCOUNT_STORES, TOKEN_FILES

    def load(path: Path):
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    accounts = load(base / "accounts.json") or {}
    users = load(base / "users.json") or {}
    report = {"accounts": len(accounts), "users": len(users),
              "sessions": len(load(base / "sessions.json") or {}), "per_account": {}}
    for account_id, account in accounts.items():
        root = base / "accounts" / account_id
        report["per_account"][account.get("name", account_id)] = {
            "stores": [name for name, _ in ACCOUNT_STORES if (root / name).exists()],
            "token_files": [name for name, _ in TOKEN_FILES if (root / name).exists()],
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get(
        "BUILDMARSHAL_DATA_DIR", REPO / ".buildmarshal_runtime" / "buildmarshal")))
    parser.add_argument("--secrets", type=Path, default=REPO.parent / "secrets" / "runtime-secrets.json")
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args()
    base = options.data_dir.resolve()

    if options.dry_run:
        print(json.dumps(preview(base), indent=2))
        return 0

    url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not url and options.secrets.exists():
        url = str(json.loads(options.secrets.read_text(encoding="utf-8-sig")).get(DATABASE_URL_ENV) or "")
    database = Database(url)
    database.migrate()
    print(f"database: {redact(url)}")
    print(f"data dir: {base}")

    from accounts import AccountRegistry, migrate_legacy_workspace
    from json_storage_import import import_json_storage

    registry = AccountRegistry(base, chroma_collection, database=database)
    migrated = migrate_legacy_workspace(registry, base)
    if migrated:
        print(f"pre-isolation data migrated into account {migrated}")
    report = import_json_storage(registry, base)
    print(json.dumps(report, indent=2, default=str) if report else "nothing to import (already done)")
    database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
