# PostgreSQL storage

Every **record** BuildMarshalAI keeps lives in PostgreSQL: accounts, users,
sessions, and each account's projects, tasks, procurement, documents and pages,
catalogues, roles, conversations, onboarding drafts, the generated-document
register, relevance feedback, settings, company profile, and the encrypted
Google / Microsoft OAuth tokens.

**Files** stay on disk, under `BASE_DIR/accounts/<account_id>/`: original
uploads, rendered page images, the ColPali multi-vector cache, vision tiles,
generated PDFs, and the ChromaDB page-vector index. The records point at them.

| | |
| --- | --- |
| Module | [`backend/database.py`](../backend/database.py) — pool, schema, migrations, row sync |
| Workspace API | [`backend/accounts.py`](../backend/accounts.py) — `AccountWorkspace.load_*/save_*`, `AccountRegistry` |
| JSON import | [`backend/json_storage_import.py`](../backend/json_storage_import.py) |
| Setup | `SETUP-DATABASE.ps1` → [`scripts/setup_database.py`](../scripts/setup_database.py) |
| Check | [`scripts/check_database.py`](../scripts/check_database.py) |
| Import tool | [`scripts/import_json_storage.py`](../scripts/import_json_storage.py) |
| Tests | [`backend/tests/test_database.py`](../backend/tests/test_database.py), and every other test runs on it |

## Set up

PostgreSQL 14 or newer running locally (developed on 18). From the handover
folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\SETUP-DATABASE.ps1
```

It asks for the PostgreSQL superuser's password (never stored), then creates:

* a login role **`buildmarshal`** — the only identity the application uses; it
  owns its databases but is not a superuser;
* **`buildmarshal`** (the application), **`buildmarshal_test`** (the test
  suite) and **`buildmarshal_demo`** (the demonstration kit), UTF-8.

It applies the schema and records `BUILDMARSHAL_DATABASE_URL`,
`BUILDMARSHAL_TEST_DATABASE_URL` and `BUILDMARSHAL_DEMO_DATABASE_URL` in
`secrets/runtime-secrets.json`, which `PREPARE-TEAMMATE-PC.ps1` exports.
`START-BUILDMARSHAL.ps1` runs the setup itself when no database is recorded,
and refuses to start the backend when the database does not answer.

There is no fallback to files. Without `BUILDMARSHAL_DATABASE_URL` the backend
stops at start-up and says what to set.

## Schema

Migrations are numbered in `database.MIGRATIONS` and recorded in
`schema_migrations`; every start applies what is missing (under an advisory
lock, so two processes cannot migrate at once). `/api/health` reports
`database.connected` and `schema_version`.

| Version | What it does |
| --- | --- |
| 1 | Creates every table: records move from JSON files to PostgreSQL |
| 2 | Renames the built-in roles in every stored user (*Super Admin* → *Head (Super Admin)*, *System Admin* → *Head (System Admin)*); removes the per-account voice URL from settings; gives every document a `project_ids` list; links each project manager and task assignee that was a name to the one user it names (a name matching nobody, or several people, is left as it was) |

| Table | Key | Typed, indexed columns | Holds |
| --- | --- | --- | --- |
| `accounts` | `id` | `name`, `status`, `owner_user_id`, `created_at` | Workspaces |
| `users` | `id` | `account_id` → accounts, `email` (+ unique `lower(email)`), `role`, `status`, `is_owner` | Logins (PBKDF2 hashes) |
| `sessions` | `token_hash` | `user_id` → users, `account_id`, `created_at`, `last_seen`, `expires_at` | Sessions (SHA-256 of the token only) |
| `projects` | `(account_id, id)` | `name`, `project_code`, `status` | Projects, their members and costs |
| `tasks` | `(account_id, project_id, id)` | `parent_id`, `name`, `status`, `archived` | Tasks and subtasks, in order |
| `procurement_items` | `(account_id, project_id, id)` | `name`, `status` | Procurement lines |
| `documents` | `(account_id, id)` | `name`, `project_id`, `digest`, `status` | Documents and their pages' text. `data.project_ids` is the list of projects a document is linked to; the `project_id` column is the first of them |
| `catalog_entries` | `(account_id, kind, id)` | `name` | Trades, external companies, contacts, task and project types |
| `roles` | `(account_id, id)` | `name` | Roles and their permissions |
| `conversations` | `(account_id, id)` | `title` | Chat history |
| `onboarding_drafts` | `(account_id, id)` | `status` | Onboarding drafts |
| `generated_documents` | `(account_id, id)` | `project_id`, `doc_kind` | Generated PDFs and reports |
| `evidence_feedback` | `(account_id, id)` | `doc_id`, `rating` | Relevance feedback (newest 5,000) |
| `account_state` | `(account_id, key)` | — | Settings, company profile, catalogue and document extras |
| `oauth_token_stores` | `(account_id, provider)` | — | Fernet ciphertext of linked accounts' tokens |
| `app_meta` | `key` | — | Data-directory binding, JSON-import record |

Every per-account table references `accounts(id) ON DELETE CASCADE`, so deleting
an account removes everything it owns in one statement, then its files. Beside
the typed columns each row keeps the full record as `jsonb`, so a field added in
code needs no migration. The database only ever sees OAuth **ciphertext**; the
Fernet key stays in the process environment.

## How it behaves

* **The feature modules did not change shape.** They still `load_tasks()`,
  change the result, and `save_tasks()`. A save compares the new rows with the
  stored ones in one transaction — under an advisory lock per (table, account),
  so two saves of one store cannot interleave — and writes only rows that were
  added, changed or removed.
* **Order is kept** (a `position` column), including a store's empty groups
  (a project with no tasks yet).
* **Values PostgreSQL rejects are cleaned on the way in:** NUL characters (from
  PDF text) are dropped and NaN / Infinity (from spreadsheets) become null.
* **Atomic units of work.** `workspace.atomic()` makes every save inside it one
  transaction; an onboarding commit — projects, tasks, costs, catalogues, roles
  and new users — lands completely or not at all.
* **The database enforces what code only checked before:** unique emails
  (case-insensitive), users and sessions belonging to real accounts, and the
  cascade on deletion.
* **Hot paths are single-row queries.** Resolving a session, finding a user by
  email and the per-request permission check no longer read whole stores.

## The data directory belongs to one database

Records point at files, so a database served with another installation's data
directory would answer with documents whose files are missing. On first start a
random id is written to `BASE_DIR/.database-binding.json` and to
`app_meta.data_dir_binding`; afterwards they must match, or the backend refuses
to start and says why. Move the two together (copy the directory, restore the
database). `BUILDMARSHAL_ALLOW_REBIND=1` re-pairs them deliberately.

## Upgrading an installation that used JSON files

The first start against a new database imports the JSON stores automatically
(`json_storage_import.import_json_storage`): accounts, users (password hashes
and all, so every login keeps working), live sessions, and every account's
stores and token files — in **one transaction**, so an interrupted import changes
nothing and simply runs again. The files are then moved, not deleted, to
`BASE_DIR/json-storage-backup/<time>/`, and `app_meta.json_storage_import`
records what came across. To preview or run it without the models:

```powershell
.\BuildMarshalAI_capstone\.venv-gpu\Scripts\python.exe .\BuildMarshalAI_capstone\scripts\import_json_storage.py --dry-run
.\BuildMarshalAI_capstone\.venv-gpu\Scripts\python.exe .\BuildMarshalAI_capstone\scripts\import_json_storage.py
```

Pre-isolation (single-tenant) data is migrated into a *Legacy Workspace* account
first, as before; its records go straight into the database.

## Back up and restore

A complete backup is the database **and** the data directory, taken together:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" --format=custom --file buildmarshal.dump $env:BUILDMARSHAL_DATABASE_URL
Compress-Archive .\BuildMarshalAI_capstone\.buildmarshal_runtime\buildmarshal\accounts buildmarshal-files.zip
```

Restore into an empty database created by `SETUP-DATABASE.ps1`:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --clean --if-exists --no-owner --dbname $env:BUILDMARSHAL_DATABASE_URL buildmarshal.dump
```

Keep `.database-binding.json` with the restored files, or start once with
`BUILDMARSHAL_ALLOW_REBIND=1`.

## Kaggle

A Kaggle notebook cannot reach PostgreSQL on your PC. Give it a reachable server
(a managed PostgreSQL) as the Kaggle secret `BUILDMARSHAL_DATABASE_URL`; the
integration cell installs `psycopg` and reads it.

## Tests

The suite runs on real PostgreSQL. Each test gets its own schema in
`buildmarshal_test`, created the first time the test touches the database and
dropped afterwards, so tests are isolated from one another and a test that never
stores anything costs nothing. `test_database.py` covers the layer itself:
round trips, order and empty groups, NUL and NaN, change-only writes, atomic
rollback, concurrent saves, cascading deletion, database-enforced email
uniqueness, session expiry, data-directory binding, the JSON import (and its
rollback), and that a full workflow writes no JSON record files.

## What stays outside the database

The page-vector index stays in ChromaDB, one collection per account. Moving it
to PostgreSQL needs the `pgvector` extension, which on Windows must be compiled
and installed into the PostgreSQL directory with administrator rights; until
then ChromaDB holds the vectors and PostgreSQL everything else.
