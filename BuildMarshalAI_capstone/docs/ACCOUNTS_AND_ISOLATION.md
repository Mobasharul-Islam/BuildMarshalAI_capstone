# Accounts and data isolation

BuildMarshalAI is multi-tenant. This document describes the account model, how
isolation is enforced, and what happens to data that predates the change.

## Model

- An **account** is an isolated workspace. It owns every resource the product
  stores.
- A **user** is a login that belongs to exactly one account. The user created by
  `POST /api/auth/register` is the account **owner**.
- Owners and users whose role is `Head (Super Admin)` or `Head (System Admin)` are
  account administrators. They manage members through the existing **User**
  page; only the owner can delete the workspace.
- Members of an account share that account's documents, index, projects,
  settings, conversations, and integrations. They can see nothing outside it.
- An account may link **Google Workspace and Microsoft 365 accounts at the same
  time**, and several of each. See
  [MICROSOFT_365_INTEGRATION.md](MICROSOFT_365_INTEGRATION.md).

## What each account owns

**Records** live in PostgreSQL, in rows keyed by the account's id — see
[DATABASE.md](DATABASE.md) for every table: documents and pages, catalogues
(trades, external companies, contacts, task and project types), projects, tasks,
procurement, roles, settings, company profile, conversations, onboarding drafts,
the generated-document register, relevance feedback, and the encrypted Google
and Microsoft 365 OAuth tokens. Accounts, users and sessions are rows too.

**Files** live under `BASE_DIR/accounts/<account_id>/`:

| Path | Contents |
| --- | --- |
| `documents/` | Uploaded and imported source files |
| `pages/` | Rendered page images and other served assets |
| `chroma_db/` | The account's own ChromaDB `document_pages` collection |
| `colpali_v1_2_multivectors/` | Cached ColPali page multi-vectors |
| `generated_documents/` | Generated PDFs |
| `google_imports/` | Scratch space for Drive/Gmail imports |
| `document_generation_vision_cache/` | Downscaled tiles for the composer |

`BASE_DIR` itself holds only account-independent files: the shared Hugging Face
model cache in `hf_models/`, and `.database-binding.json`, which pairs the
directory with its database.

The ColPali model and processor are shared because they are stateless. The
vector **index** is not shared: each account gets its own `PersistentClient`, so
a query cannot reach another account's vectors even if a metadata filter were
ever omitted.

## How isolation is enforced

1. Every route except `/api/health`, `/api/cliproxy/status`, `/api/auth/login`,
   and `/api/auth/register` declares `Depends(require_account)`.
2. `require_account` resolves the bearer token to an `AccountContext` holding the
   user, the account, and its `AccountWorkspace`.
3. Handlers never touch a module-level path, collection or query. They read and
   write through `context.workspace`, which builds every path beneath its own
   root and scopes every database query to its own `account_id`.
4. Client-supplied ids are constrained to `[A-Za-z0-9._-]` before they reach the
   filesystem, so a document id cannot escape the workspace directory.
5. `workspace.resolve_page_path()` returns a path only when it resolves inside
   that workspace; a stored absolute path pointing elsewhere resolves to `""`.
6. An id that belongs to another account returns **404**, not 403, so ids cannot
   be enumerated.

## Authentication

- Passwords are PBKDF2-HMAC-SHA256, 600,000 iterations (OWASP's current
  figure), with a 16-byte per-user salt. Any weaker stored hash -- a bare
  SHA-256 digest from before per-user salting, or PBKDF2 at a lower iteration
  count from an earlier build -- still authenticates and is re-hashed
  transparently on the next successful login, without signing other devices out.
- Sessions are 32-byte random bearer tokens. Only their SHA-256 digest is
  stored, alongside an absolute expiry (12 h) and an idle expiry (4 h).
- A user id is not a credential. Logging out, changing a password, or being
  deactivated revokes the relevant sessions immediately.
- Login answers identically for an unknown email and a wrong password, and
  spends the same time on both: an unknown email is checked against one
  dummy hash built at start-up, so each path costs exactly one key derivation.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register` | Create an account and its owner; returns a session |
| POST | `/api/auth/login` | Exchange credentials for a session token |
| POST | `/api/auth/logout` | Revoke the current session |
| GET | `/api/auth/me` | Current user, account, and settings |
| PUT | `/api/auth/profile` | Update your own profile |
| PUT | `/api/auth/password` | Change password; re-issues your session |
| GET | `/api/account` | Account summary and usage counts |
| PUT | `/api/account` | Rename the account (administrators) |
| DELETE | `/api/account` | Delete the account and all its data (owner) |
| GET/PUT | `/api/account/settings` | Per-account configuration |
| GET/PUT | `/api/conversations` | Chat history for the account |
| DELETE | `/api/conversations/{id}` | Delete one conversation |
| GET/POST/PUT/DELETE | `/api/users[/{id}]` | Members of the caller's account |

All pre-existing endpoints keep their paths, payloads, and status codes; they
now require a bearer token and act on the caller's workspace.

## Migration of pre-isolation data

On first start after the upgrade, `migrate_legacy_workspace` moves the shipped
single-tenant data into one account named **Legacy Workspace**:

- Existing logins in the legacy `users.json` are adopted as members of that account; the
  `Head (Super Admin)` becomes its owner, so `admin@buildmarshal.com` / `admin123`
  keeps working and is upgraded to PBKDF2 on first use.
- `documents/`, `pages/`, `chroma_db/`, the multi-vector cache, generated
  documents, imports, and the vision cache are moved into the account.
- The legacy JSON stores (document metadata, catalogues, the generated-document
  register, relevance feedback, Google tokens) go into the database.
- Absolute page paths recorded in the document metadata, the generated-document
  register, and the Chroma index are rewritten to the new location. Embeddings
  are preserved during the rewrite.
- `BASE_DIR/.account_migration_complete` marks it done, so it never runs twice.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BUILDMARSHAL_ALLOWED_ORIGINS` | `http://localhost:5500,http://127.0.0.1:5500,http://localhost:3000,http://127.0.0.1:3000` | Browser origins allowed to call the API |
| `BUILDMARSHAL_MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Server-side upload ceiling |
| `BUILDMARSHAL_DATABASE_URL` | — (required) | The PostgreSQL database holding every record; see [DATABASE.md](DATABASE.md) |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | — | Fernet key protecting OAuth tokens at rest, server-wide |

## Frontend

`frontend/app.js` gates the whole application behind `#authGate`. Nothing is
fetched or rendered until `/api/auth/me` confirms a stored token. `apiReq`
attaches the bearer token to every call and drops back to the gate on `401`.
Browser-cached conversation state is keyed by account id, and signing out clears
all in-memory and cached account state, so two accounts used from the same
browser never see each other's data.

Page images, audio, and video come from account-scoped endpoints, and a browser
will not attach an `Authorization` header to an `<img>`, `<audio>`, or `<video>`
`src`. Those elements therefore carry `data-authsrc`; `hydrateAuthedMedia()`
fetches the bytes through `apiReq` and swaps in an object URL, which is revoked
when the modal closes or the user signs out. Never put a session token in a URL
to work around this.
