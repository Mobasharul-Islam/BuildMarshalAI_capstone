# Microsoft 365 integration (Microsoft Graph)

BuildMarshal links Microsoft 365 accounts alongside Google Workspace accounts.
Both providers can be connected at the same time, in the same BuildMarshal
account, and each linked account belongs to the workspace that linked it.

Capabilities:

| Area | Microsoft | Google |
| --- | --- | --- |
| Files | OneDrive browse, search, import & index | Drive |
| Mail | Outlook Mail read, import & index, AI compose, draft, send | Gmail |
| Calendar | Outlook Calendar read, create, task-to-event | Google Calendar |

## 1. Register the application

In the [Azure portal](https://portal.azure.com) → **Microsoft Entra ID** →
**App registrations** → **New registration**:

1. **Supported account types** — pick what you need. "Accounts in any
   organizational directory and personal Microsoft accounts" corresponds to
   `MICROSOFT_TENANT_ID=common`; a single tenant uses that tenant's GUID.
2. **Redirect URI** — platform **Web**, value
   `http://localhost:5500/oauth-callback.html`. Add one entry per origin you
   serve the frontend from. It must be the **Web** platform, not SPA: the code
   is redeemed server-side with the client secret.
3. After creating it, note the **Application (client) ID**.
4. **Certificates & secrets** → **New client secret** → copy the *value*.
5. **API permissions** → **Microsoft Graph** → **Delegated permissions**, add:
   `offline_access`, `User.Read`, `Files.Read`, `Mail.Read`, `Mail.ReadWrite`,
   `Mail.Send`, `Calendars.ReadWrite`. Grant admin consent if your tenant
   requires it.

`offline_access` is what yields a refresh token. Without it a linked account
stops working after about an hour.

## 2. Configure the backend

Add to `secrets/runtime-secrets.json` (they are exported as environment
variables by `PREPARE-TEAMMATE-PC.ps1`):

```json
{
  "MICROSOFT_CLIENT_ID": "00000000-0000-0000-0000-000000000000",
  "MICROSOFT_CLIENT_SECRET": "the secret value",
  "MICROSOFT_TENANT_ID": "common",
  "MICROSOFT_ALLOWED_ORIGINS": "http://localhost:5500"
}
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `MICROSOFT_CLIENT_ID` | — | Application (client) ID |
| `MICROSOFT_CLIENT_SECRET` | — | Client secret value; server-side only |
| `MICROSOFT_TENANT_ID` | `common` | Tenant GUID, or `common`/`organizations`/`consumers` |
| `MICROSOFT_ALLOWED_ORIGINS` | falls back to `GOOGLE_ALLOWED_ORIGINS` | Origins allowed to start a sign-in |
| `MICROSOFT_TOKEN_ENCRYPTION_KEY` | falls back to `GOOGLE_TOKEN_ENCRYPTION_KEY` | Fernet key protecting refresh tokens at rest |

Until these are set, `/api/microsoft/config` reports `enabled: false`, the
Microsoft 365 page shows a configuration banner, and no route errors.

## 3. Connect an account

**Microsoft 365** in the sidebar → **Continue with Microsoft**. Connect as many
accounts as you like and switch between them with the account selector; Google
accounts stay connected independently.

## OAuth flow

The authorization-code flow runs with **PKCE and the client secret**:

1. The browser asks `POST /api/microsoft/oauth/start` for an authorize URL.
2. The backend mints a `state` and a PKCE verifier, keeps them in memory bound
   to the calling BuildMarshal account, and returns only the URL.
3. A popup completes sign-in and lands on `frontend/oauth-callback.html`, which
   `postMessage`s the code back to its opener at the exact page origin.
4. The browser posts the code and state to `POST /api/microsoft/oauth/code`.
   The backend checks the state was one it issued, that it belongs to the same
   account, and that the redirect URI matches, then redeems the code with the
   verifier and the client secret.

The browser never sees the client secret or a refresh token. `state` is
single-use and expires after 10 minutes.

## Endpoints

All require `Authorization: Bearer <session token>` and act only on the caller's
workspace.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/microsoft/config` | Whether Microsoft is configured, plus scopes |
| POST | `/api/microsoft/oauth/start` | Begin a sign-in; returns the authorize URL |
| POST | `/api/microsoft/oauth/code` | Redeem the authorization code |
| GET | `/api/microsoft/accounts` | Linked Microsoft accounts (no tokens) |
| DELETE | `/api/microsoft/accounts/{id}` | Unlink an account |
| GET | `/api/microsoft/drive/files` | Browse/search OneDrive |
| POST | `/api/microsoft/drive/import` | Import and index selected files |
| GET | `/api/microsoft/mail/messages` | List/search Outlook Mail |
| POST | `/api/microsoft/mail/import` | Import and index selected messages |
| POST | `/api/microsoft/mail/generate` | Draft an email with the model (no send) |
| POST | `/api/microsoft/mail/draft` | Create an Outlook draft (needs `confirm`) |
| POST | `/api/microsoft/mail/send` | Send mail (needs `confirm`) |
| GET | `/api/microsoft/calendar/events` | Read Outlook Calendar |
| POST | `/api/microsoft/calendar/events` | Create an event (needs `confirm`); `add_online_meeting` attaches a Teams meeting |
| POST | `/api/microsoft/meeting/schedule` | Schedule a Teams meeting conversationally, one chat turn at a time |

> **Personal vs work accounts.** `add_online_meeting` sets `isOnlineMeeting` but deliberately does
> not send `onlineMeetingProvider`. Naming `teamsForBusiness` makes Graph refuse the conferencing on a
> personal Microsoft account (`@outlook.com`, `@hotmail.com`) and create a plain event with no join
> link, with no error to explain it. Omitting the field produces a Teams link on personal accounts and
> lets a work tenant apply its own default provider.
| POST | `/api/microsoft/assistant/interpret` | Natural language → event proposal, never creates |
| POST | `/api/microsoft/tasks/{project_id}/{task_id}/calendar` | Schedule a project task |

## Behaviour guarantees

- **Nothing is sent or created without confirmation.** `draft`, `send`, and
  calendar create return `{"confirmation_required": true}` unless the request
  carries `confirm: true`; `assistant/interpret` only ever proposes.
- **Refresh tokens are encrypted at rest** in the linking account's workspace
  (`microsoft_accounts.enc`) and are never in an API response.
- **Account ids do not cross accounts.** A Microsoft account id from one
  BuildMarshal workspace reads as 404 in another.
- **Office documents are converted to PDF on import** by Graph, so OneDrive
  Word/PowerPoint/Excel files get page images and extracted text like any other
  source. Folders cannot be imported.

## Files and Calendar shape

Outlook Calendar responses are reshaped to the Google Calendar payload
(`summary`, `start.dateTime`, `end.dateTime`, `htmlLink`), so the frontend
renders either provider with the same code. The same applies to OneDrive
listings (`name`, `mimeType`, `modifiedTime`, `webViewLink`).

## Shared implementation

- `backend/oauth_tokens.py` — encrypted token store and helpers, used by both
  providers.
- `backend/external_imports.py` — download → ingest → index enrichment, used by
  both providers.
- `backend/microsoft_workspace.py` / `backend/google_workspace.py` — the
  provider-specific routes.
- `frontend/app.js` — one set of renderers and handlers driven by the
  `WORKSPACE_PROVIDERS` descriptor.

See [ACCOUNTS_AND_ISOLATION.md](ACCOUNTS_AND_ISOLATION.md) for the account model.
