# BuildMarshalAI Google Workspace integration

## What was added

The main Kaggle backend now supports multiple Google accounts through OAuth 2.0. The frontend has a **Google Workspace** page with three areas:

- **Drive:** list/search files, select files, optionally assign them to a BuildMarshal project, and index them through the existing ColPali/ChromaDB pipeline.
- **Gmail:** list/search messages, select only the messages that should be indexed, and compose, draft, or send an email with Marshal.
- **Calendar:** read upcoming events, create a reviewed event, or copy a BuildMarshal project task into an event.

Marshal Chat also uses the selected Google account:

- Calendar questions retrieve live upcoming events and add them to the Qwen answer context.
- “Write/compose an email” generates a reviewable email.
- “Send an email” requires a browser confirmation before Gmail is called.
- “Add/create a calendar event” is interpreted by Qwen, shown for confirmation, and only then created.

Imported Drive files and Gmail messages become normal BuildMarshal documents. If a project is selected, their Chroma metadata contains that `project_id`, so they also appear in the project source list and participate in project-scoped retrieval/document generation.

## 1. Configure Google Cloud

1. Open Google Cloud Console and create or select a project.
2. Enable **Google Drive API**, **Gmail API**, and **Google Calendar API**.
3. Configure the OAuth consent screen. For development, use **External → Testing** and add every Google account that will test BuildMarshal as a test user.
4. Add these scopes:
   - `openid`, `email`, `profile`
   - `https://www.googleapis.com/auth/drive.readonly`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.compose`
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
5. Create an OAuth client of type **Web application**.
6. Under **Authorized JavaScript origins**, add the exact frontend origins you will use, for example:
   - `http://localhost:5500`
   - `https://your-buildmarshal-site.example`

Do not open `frontend/index.html` through `file://`. Google Identity Services requires an HTTP/HTTPS origin, and the popup authorization-code flow uses that origin during the server-side code exchange.

## 2. Add Kaggle Secrets

Add these four secrets to the main backend notebook:

| Secret | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | Web OAuth client ID from Google Cloud |
| `GOOGLE_CLIENT_SECRET` | Web OAuth client secret from Google Cloud |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | One stable Fernet encryption key |
| `GOOGLE_ALLOWED_ORIGINS` | Comma-separated exact origins, e.g. `http://localhost:5500,https://your-site.example` |

Generate the encryption key once on your own computer:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep this key stable. Changing it makes previously stored Google refresh tokens unreadable and users must reconnect. Never print or hardcode any of the four secrets in the notebook.

## 3. Keep Google accounts across Kaggle restarts

Linked accounts' credentials are stored encrypted in the PostgreSQL database
(`oauth_token_stores`, one Fernet-encrypted blob per BuildMarshal account and
provider), so they survive a Kaggle restart as long as the notebook points at the
same database: set the Kaggle secret `BUILDMARSHAL_DATABASE_URL` to a reachable
PostgreSQL server (see [DATABASE.md](DATABASE.md)). The database holds only
ciphertext; the key is `GOOGLE_TOKEN_ENCRYPTION_KEY`, and access and refresh
tokens are never returned to the frontend. Uploaded files and page images still
live under `BASE_DIR`, so keep **Persistence** on **Files only** (or **Variables
and Files**) as well.

Each Drive/Gmail import request accepts at most 25 selected items. Very large PDFs still consume one ColPali embedding pass per page and are limited by the Kaggle session's disk, memory, runtime, and Google API quotas. Start with one or two modest documents when validating a new deployment.

## 4. Run the updated backend

The integration cell in `Dual_t4_Working_with_Document_Generation.ipynb` installs the Google client libraries, reads the Kaggle Secrets, downloads `google_workspace.py`, and registers its routes before ngrok starts.

Because the notebook downloads modules from the `docgen-pipeline` GitHub branch, push `backend/google_workspace.py` and the updated notebook to that branch before running a fresh Kaggle session.

After the backend starts, verify:

```text
GET {BACKEND_URL}/api/google/config
```

Expected:

```json
{"enabled": true, "client_id": "...", "scopes": ["..."], "requires_served_frontend": true}
```

The API must not return the client secret, encryption key, access token, or refresh token.

## 5. Serve the frontend

From the repository root:

```powershell
python -m http.server 5500 --directory frontend
```

Open `http://localhost:5500`, set the main Kaggle/ngrok backend URL in **Settings**, then open **Google Workspace → Add account**.

The browser origin must exactly match both `GOOGLE_ALLOWED_ORIGINS` and the Google Cloud Authorized JavaScript origin. A changing backend ngrok URL does not need to be registered because OAuth starts from the stable frontend origin.

## Scheduling a Google Meet from chat

Ask Marshal in the chat panel, for example:

> Schedule a Google Meet called Foundation review next Tuesday at 2pm for 45
> minutes with sam@example.com

Marshal collects the title, date/time, duration, and attendees over as many
turns as it takes, shows the meeting for confirmation, then creates the Calendar
event with a Meet link and posts the details back into the chat.

`POST /api/google/meet/schedule` drives one turn at a time and answers with one
of three shapes:

| `status` | Meaning | Fields |
| --- | --- | --- |
| `needs_input` | Something is missing or invalid | `missing`, `question`, `known` |
| `confirm` | Everything is present; nothing created yet | `proposal`, `known` |
| `created` | The meeting exists | `meet_link`, `event`, `proposal` |

Request fields: `account_id`, `query` (what the user just typed), `timezone`,
`known` (the fields settled in earlier turns), and `confirm`.

Rules:

- **Nothing is created without `confirm: true`.** The proposal step always comes
  first, and validation runs again on the confirming call, so an invalid
  attendee stops the booking even then.
- **Required:** a title and a start time. Duration defaults to 60 minutes and is
  shown in the proposal so it can be corrected. Attendees are optional but must
  be valid email addresses.
- **The model never invents values.** The extractor is told to return null for
  anything the user did not state, so a missing time becomes a question rather
  than a guess.
- **Meet links** are requested with a `hangoutsMeet` conference and
  `conferenceDataVersion=1`. If the Google account is not permitted to create
  conferences, the event is still created and the reply says the link could not
  be added rather than reporting success.
- **Errors are specific.** Calendar `401`/`403` become "this account is not
  allowed…", `429` becomes a rate-limit message, anything else surfaces the
  Google error text.
- **Isolation.** The Calendar account is resolved through the caller's own
  workspace, so a Google account id linked by another BuildMarshal account
  reads as 404.

The Calendar tab also has an **Add a Google Meet link** checkbox on the event
form, which sets `add_meet` on `POST /api/google/calendar/events`.

## Account scope

Connected Google accounts belong to the BuildMarshal account that added them.
Each workspace holds its own encrypted token file, so an `account_id` from one
workspace is unknown in another and Drive, Gmail, and Calendar calls made with it
return 404. Every `/api/google/*` route requires a session token. See
[ACCOUNTS_AND_ISOLATION.md](ACCOUNTS_AND_ISOLATION.md).

## Security and behavior guarantees

- OAuth uses the Google Identity Services popup authorization-code flow; the backend exchanges the one-time code.
- Refresh tokens are encrypted at rest with Fernet and never placed in local storage.
- Drive is read-only; BuildMarshal cannot delete or change a Drive file.
- Gmail messages are indexed only when the user checks them and clicks **Index selected**.
- Gmail sending and Calendar creation require `confirm: true` at the API and a visible browser confirmation in the UI.
- Disconnect revokes the Google token when possible and deletes the encrypted local account record. Already-indexed BuildMarshal documents remain until explicitly deleted.
- Do not expose this development backend publicly without application authentication. Google account IDs alone are not an authorization boundary for a multi-user production deployment.

## Validation checklist

1. Connect two test Google accounts and switch between them.
2. Import one normal PDF and one native Google Doc from Drive; confirm both appear in Documents.
3. Import a Drive file under project `sert`; confirm it also appears in that project's source list.
4. Search Gmail, select one harmless test email, index it, and query its content in Marshal Chat.
5. Generate an email, create a Gmail draft, then use a separate test message to verify confirmed sending.
6. Load upcoming Calendar events and ask Marshal, “What meetings do I have this week?”
7. Ask Marshal to add a test event. Cancel once to confirm no write occurs, then approve once and verify it in Google Calendar.
8. Restart Kaggle with file persistence enabled and confirm the account remains connected.
