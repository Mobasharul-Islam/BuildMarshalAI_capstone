"""Google Workspace integration for the BuildMarshalAI Kaggle backend.

The module is deliberately separate from the large notebook.  Call
``register_google_workspace_routes(globals())`` after the FastAPI app, document
ingestion functions, projects, tasks, and Qwen generator have been created.

OAuth refresh tokens are encrypted before they are written to Kaggle's
persistent working directory.  They are never returned by an API response.
"""

from __future__ import annotations

import asyncio
import base64
import html
import io
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping, Sequence

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

try:  # the notebook puts this directory on sys.path
    from meeting_language import (
        EMAIL_PATTERN, MEET_FIELD_QUESTIONS, MeetScheduleRequest, extraction_prompt,
        meeting_proposal, merge_meet_fields, normalise_meet_fields, parse_extraction,
        parse_meeting_start, validate_meet_fields,
    )
    from external_imports import ExternalImporter
    from oauth_tokens import EncryptedAccountStore, account_identifier, safe_name
    from oauth_tokens import iso as _iso
    from oauth_tokens import utcnow as _utcnow
except ModuleNotFoundError:  # imported as backend.google_workspace
    from backend.meeting_language import (
        EMAIL_PATTERN, MEET_FIELD_QUESTIONS, MeetScheduleRequest, extraction_prompt,
        meeting_proposal, merge_meet_fields, normalise_meet_fields, parse_extraction,
        parse_meeting_start, validate_meet_fields,
    )
    from backend.external_imports import ExternalImporter
    from backend.oauth_tokens import EncryptedAccountStore, account_identifier, safe_name
    from backend.oauth_tokens import iso as _iso
    from backend.oauth_tokens import utcnow as _utcnow


def _safe_name(name: str, fallback: str = "google-document") -> str:
    return safe_name(name, fallback)


def _account_id(email: str) -> str:
    # Existing linked accounts are stored under a 20-character id.
    return account_identifier(email, length=20)


GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]

GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
}

MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/json": ".json",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


class OAuthCodeRequest(BaseModel):
    code: str
    redirect_uri: str


class ImportRequest(BaseModel):
    account_id: str
    item_ids: list[str] = Field(min_length=1, max_length=25)
    project_id: str | None = None


class EmailComposeRequest(BaseModel):
    account_id: str
    to: str = ""
    cc: str = ""
    subject: str = ""
    body: str = ""
    instruction: str = ""
    confirm: bool = False


class CalendarEventRequest(BaseModel):
    account_id: str
    summary: str
    description: str = ""
    start: str
    end: str
    timezone: str = "UTC"
    location: str = ""
    attendees: list[str] = Field(default_factory=list)
    add_meet: bool = False
    confirm: bool = False


class CalendarEventUpdateRequest(BaseModel):
    """A partial edit of an existing Calendar event.

    Only the fields present are changed, so the client can send just a new time
    without having to echo the whole event back.
    """

    account_id: str
    summary: str | None = Field(default=None, max_length=1024)
    description: str | None = Field(default=None, max_length=8000)
    location: str | None = Field(default=None, max_length=1024)
    start: str | None = None
    end: str | None = None
    timezone: str = "UTC"
    attendees: list[str] | None = None
    confirm: bool = False


class WorkspaceAssistantRequest(BaseModel):
    account_id: str
    query: str
    timezone: str = "UTC"


def _credentials_expiry(value: str | None) -> datetime | None:
    """Return the naive UTC expiry expected by google-auth.

    OAuth records are stored as timezone-aware ISO timestamps, while
    google-auth currently compares credential expiry against a naive UTC
    clock.  Normalizing at the boundary avoids an aware/naive comparison
    failure before the first Workspace API request.
    """
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _strip_html(value: str) -> str:
    value = re.sub(r"<style[\s\S]*?</style>|<script[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", value, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _decode_b64url(value: str) -> str:
    if not value:
        return ""
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8", errors="replace")


def _gmail_body(payload: Mapping[str, Any]) -> str:
    plain: list[str] = []
    rich: list[str] = []

    def walk(part: Mapping[str, Any]) -> None:
        mime = str(part.get("mimeType", ""))
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode_b64url(data))
        elif data and mime == "text/html":
            rich.append(_strip_html(_decode_b64url(data)))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return "\n\n".join(plain or rich).strip()


def _headers(payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in payload.get("headers") or []
    }


def register_google_workspace_routes(namespace: Mapping[str, Any]) -> Any:
    """Register Google OAuth, Drive, Gmail, Calendar, and assistant routes."""
    required = ["app", "ingest_document", "require_account"]
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Google Workspace integration is missing: {', '.join(missing)}")

    import requests
    from cryptography.fernet import Fernet
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    app = namespace["app"]
    ingest_document = namespace["ingest_document"]
    require_account = namespace["require_account"]
    vl_generate = namespace.get("vl_generate")

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    encryption_key = os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY", "").strip()
    allowed_origins = {
        origin.strip().rstrip("/")
        for origin in os.environ.get("GOOGLE_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    }
    # Connected Google accounts are per BuildMarshal account: each workspace
    # holds its own encrypted token file, so an account_id from one workspace is
    # simply unknown in another.  The Fernet key is server-wide because it
    # protects tokens at rest, not between tenants.
    _stores: dict[str, EncryptedAccountStore] = {}
    _stores_lock = threading.RLock()

    def account_store(workspace: Any) -> EncryptedAccountStore:
        if not encryption_key:
            raise HTTPException(503, "Google OAuth is not configured on this backend")
        with _stores_lock:
            store = _stores.get(workspace.account_id)
            if store is None:
                store = EncryptedAccountStore(Path(workspace.google_store_file), encryption_key)
                _stores[workspace.account_id] = store
            return store

    def assert_configured() -> None:
        if not client_id or not client_secret or not encryption_key or not allowed_origins:
            raise HTTPException(503, "Google OAuth is not configured on this backend")

    def assert_oauth_request(request: Request, redirect_uri: str) -> None:
        requested_with = request.headers.get("x-requested-with", "")
        origin = request.headers.get("origin", "").rstrip("/")
        redirect_origin = redirect_uri.rstrip("/")
        if requested_with.lower() != "xmlhttprequest":
            raise HTTPException(400, "Missing X-Requested-With OAuth protection header")
        if redirect_origin in {"", "null", "file://"}:
            raise HTTPException(400, "Google sign-in requires a served HTTPS or localhost frontend")
        if allowed_origins and (origin not in allowed_origins or redirect_origin not in allowed_origins):
            raise HTTPException(403, "Frontend origin is not in GOOGLE_ALLOWED_ORIGINS")
        if origin and origin != redirect_origin:
            raise HTTPException(403, "OAuth redirect origin does not match the requesting origin")

    def credentials(workspace: Any, account_id: str) -> Credentials:
        assert_configured()
        store = account_store(workspace)
        try:
            record = store.get(account_id)
        except KeyError as exc:
            raise HTTPException(404, "Google account not found") from exc
        expiry = record.get("expiry")
        creds = Credentials(
            token=record.get("access_token"),
            refresh_token=record.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=record.get("scopes") or GOOGLE_SCOPES,
            expiry=_credentials_expiry(expiry),
        )
        if not creds.valid:
            if not creds.refresh_token:
                raise HTTPException(401, "Reconnect this Google account to restore offline access")
            try:
                creds.refresh(GoogleAuthRequest())
            except Exception as exc:
                raise HTTPException(401, "Google authorization expired; reconnect this account") from exc
            record["access_token"] = creds.token
            record["expiry"] = creds.expiry.isoformat() if creds.expiry else None
            store.put(record)
        return creds

    def service(workspace: Any, account_id: str, api: str, version: str):
        return build(
            api, version, credentials=credentials(workspace, account_id), cache_discovery=False
        )

    importer = ExternalImporter(ingest_document, "google")

    def ingest_path(workspace: Any, path: Path, display_name: str, project_id: str | None,
                    source_type: str, external: Mapping[str, Any]) -> dict[str, Any]:
        return importer.ingest_path(
            workspace, path, display_name, project_id, source_type, external
        )

    def download_drive_file(workspace: Any, drive, item: Mapping[str, Any]) -> tuple[Path, str]:
        name = _safe_name(str(item.get("name") or "drive-document"))
        mime_type = str(item.get("mimeType") or "application/octet-stream")
        if mime_type in GOOGLE_EXPORTS:
            export_mime, extension = GOOGLE_EXPORTS[mime_type]
            request = drive.files().export_media(fileId=item["id"], mimeType=export_mime)
            if not name.lower().endswith(extension):
                name += extension
        elif not mime_type.startswith("application/vnd.google-apps"):
            extension = Path(name).suffix or MIME_EXTENSIONS.get(mime_type, ".bin")
            if extension == ".bin":
                raise ValueError(f"Unsupported Drive file type: {mime_type}")
            if not Path(name).suffix:
                name += extension
            request = drive.files().get_media(fileId=item["id"])
        else:
            raise ValueError(f"Google file type cannot be exported: {mime_type}")
        target = Path(workspace.imports_dir) / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request, chunksize=4 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=3)
        return target, name

    @app.get("/api/google/config")
    async def google_config(context=Depends(require_account)) -> dict[str, Any]:
        return {
            "enabled": bool(client_id and client_secret and encryption_key and allowed_origins),
            "client_id": client_id,
            "scopes": GOOGLE_SCOPES,
            "requires_served_frontend": True,
        }

    @app.post("/api/google/oauth/code")
    async def google_oauth_code(
        body: OAuthCodeRequest, request: Request, context=Depends(require_account),
    ) -> dict[str, Any]:
        assert_configured()
        store = account_store(context.workspace)
        assert_oauth_request(request, body.redirect_uri)
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": body.code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": body.redirect_uri.rstrip("/"),
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        if not token_response.ok:
            raise HTTPException(400, f"Google token exchange failed ({token_response.status_code})")
        token = token_response.json()
        profile_response = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token['access_token']}"}, timeout=20,
        )
        if not profile_response.ok:
            raise HTTPException(400, "Google account profile could not be read")
        profile = profile_response.json()
        email_address = str(profile.get("email") or "").lower()
        if not email_address:
            raise HTTPException(400, "Google did not return an email address")
        account_id = _account_id(email_address)
        try:
            previous = store.get(account_id)
        except KeyError:
            previous = {}
        expires_in = int(token.get("expires_in", 3600))
        record = {
            "id": account_id,
            "provider": "google",
            "email": email_address,
            "name": profile.get("name") or email_address,
            "picture": profile.get("picture"),
            "connected_at": previous.get("connected_at") or _iso(),
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token") or previous.get("refresh_token"),
            "expiry": _iso(_utcnow() + timedelta(seconds=max(expires_in - 30, 60))),
            "scopes": str(token.get("scope") or " ".join(GOOGLE_SCOPES)).split(),
        }
        store.put(record)
        return {"account": store.public(record)}

    @app.get("/api/google/accounts")
    async def google_accounts(context=Depends(require_account)) -> dict[str, Any]:
        if not encryption_key:
            return {"accounts": []}
        return {"accounts": account_store(context.workspace).list_public()}

    @app.delete("/api/google/accounts/{account_id}")
    async def google_disconnect(account_id: str, context=Depends(require_account)) -> dict[str, Any]:
        assert_configured()
        record = account_store(context.workspace).delete(account_id)
        if not record:
            raise HTTPException(404, "Google account not found")
        token = record.get("refresh_token") or record.get("access_token")
        if token:
            try:
                requests.post("https://oauth2.googleapis.com/revoke", params={"token": token}, timeout=10)
            except Exception:
                pass
        return {"disconnected": True, "account_id": account_id}

    @app.get("/api/google/drive/files")
    async def google_drive_files(account_id: str, q: str = "", page_size: int = 50,
                                 page_token: str | None = None,
                                 context=Depends(require_account)) -> dict[str, Any]:
        drive = service(context.workspace, account_id, "drive", "v3")
        query = "trashed = false and mimeType != 'application/vnd.google-apps.folder'"
        if q.strip():
            clean = q.replace("'", "\\'")
            query += f" and name contains '{clean}'"
        result = drive.files().list(
            q=query, pageSize=min(max(page_size, 1), 100), pageToken=page_token,
            orderBy="modifiedTime desc",
            fields="nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink,iconLink)",
        ).execute()
        return {"files": result.get("files", []), "next_page_token": result.get("nextPageToken")}

    @app.post("/api/google/drive/import")
    async def google_drive_import(
        body: ImportRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        workspace = context.workspace
        drive = service(workspace, body.account_id, "drive", "v3")
        imported, errors = [], []
        for item_id in body.item_ids:
            try:
                item = drive.files().get(fileId=item_id, fields="id,name,mimeType,modifiedTime").execute()
                path, display_name = download_drive_file(workspace, drive, item)
                imported.append(ingest_path(
                    workspace, path, display_name, body.project_id, "google_drive",
                    {"account_id": body.account_id, "item_id": item_id, "mime_type": item.get("mimeType")},
                ))
                path.unlink(missing_ok=True)
            except Exception as exc:
                errors.append({"item_id": item_id, "error": str(exc)})
        return {"imported": imported, "errors": errors, "total": len(imported)}

    @app.get("/api/google/gmail/messages")
    async def google_gmail_messages(account_id: str, q: str = "", page_size: int = 30,
                                    page_token: str | None = None,
                                    context=Depends(require_account)) -> dict[str, Any]:
        gmail = service(context.workspace, account_id, "gmail", "v1")
        result = gmail.users().messages().list(
            userId="me", q=q or None, maxResults=min(max(page_size, 1), 50), pageToken=page_token,
        ).execute()
        messages = []
        for item in result.get("messages", []):
            message = gmail.users().messages().get(
                userId="me", id=item["id"], format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            ).execute()
            headers = _headers(message.get("payload") or {})
            messages.append({
                "id": message["id"], "thread_id": message.get("threadId"),
                "subject": headers.get("subject", "(no subject)"),
                "from": headers.get("from", ""), "to": headers.get("to", ""),
                "date": headers.get("date", ""), "snippet": message.get("snippet", ""),
            })
        return {"messages": messages, "next_page_token": result.get("nextPageToken")}

    @app.post("/api/google/gmail/import")
    async def google_gmail_import(
        body: ImportRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        workspace = context.workspace
        gmail = service(workspace, body.account_id, "gmail", "v1")
        imported, errors = [], []
        import_dir = Path(workspace.imports_dir)
        import_dir.mkdir(parents=True, exist_ok=True)
        for item_id in body.item_ids:
            try:
                message = gmail.users().messages().get(userId="me", id=item_id, format="full").execute()
                payload = message.get("payload") or {}
                headers = _headers(payload)
                subject = headers.get("subject", "No subject")
                text = (
                    f"Subject: {subject}\nFrom: {headers.get('from', '')}\n"
                    f"To: {headers.get('to', '')}\nDate: {headers.get('date', '')}\n\n"
                    f"{_gmail_body(payload) or message.get('snippet', '')}"
                )
                path = import_dir / f"{uuid.uuid4().hex}.txt"
                path.write_text(text, encoding="utf-8")
                imported.append(ingest_path(
                    workspace, path, _safe_name(f"Email - {subject}.txt"), body.project_id, "gmail_message",
                    {"account_id": body.account_id, "item_id": item_id, "thread_id": message.get("threadId")},
                ))
                path.unlink(missing_ok=True)
            except Exception as exc:
                errors.append({"item_id": item_id, "error": str(exc)})
        return {"imported": imported, "errors": errors, "total": len(imported)}

    async def generate_email(body: EmailComposeRequest) -> dict[str, str]:
        if not vl_generate:
            raise HTTPException(503, "The Qwen generator is not loaded")
        prompt = (
            "Write a professional construction-project email. Return JSON only with keys subject and body.\n"
            f"Recipient: {body.to or 'not specified'}\nExisting subject: {body.subject}\n"
            f"Existing body: {body.body}\nInstruction: {body.instruction}"
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        raw = await asyncio.get_running_loop().run_in_executor(
            None, lambda: vl_generate(messages, max_new_tokens=450)
        )
        match = re.search(r"\{[\s\S]*\}", str(raw))
        if match:
            try:
                data = json.loads(match.group(0))
                return {"subject": str(data.get("subject", "")), "body": str(data.get("body", ""))}
            except json.JSONDecodeError:
                pass
        return {"subject": body.subject or "Project update", "body": str(raw).strip()}

    def raw_email(body: EmailComposeRequest) -> str:
        if not body.to.strip() or not body.subject.strip() or not body.body.strip():
            raise HTTPException(422, "To, subject, and body are required")
        message = EmailMessage()
        message["To"] = body.to.strip()
        if body.cc.strip():
            message["Cc"] = body.cc.strip()
        message["Subject"] = body.subject.strip()
        message.set_content(body.body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    @app.post("/api/google/gmail/generate")
    async def google_gmail_generate(
        body: EmailComposeRequest, context=Depends(require_account)
    ) -> dict[str, str]:
        return await generate_email(body)

    @app.post("/api/google/gmail/draft")
    async def google_gmail_draft(
        body: EmailComposeRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        if not body.confirm:
            return {"confirmation_required": True, "action": "create_email_draft"}
        gmail = service(context.workspace, body.account_id, "gmail", "v1")
        result = gmail.users().drafts().create(
            userId="me", body={"message": {"raw": raw_email(body)}}
        ).execute()
        return {"created": True, "draft_id": result.get("id"), "message_id": (result.get("message") or {}).get("id")}

    @app.post("/api/google/gmail/send")
    async def google_gmail_send(
        body: EmailComposeRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        if not body.confirm:
            return {"confirmation_required": True, "action": "send_email"}
        gmail = service(context.workspace, body.account_id, "gmail", "v1")
        result = gmail.users().messages().send(userId="me", body={"raw": raw_email(body)}).execute()
        return {"sent": True, "message_id": result.get("id"), "thread_id": result.get("threadId")}

    def send_plain_email(workspace: Any, account_id: str, to: str, subject: str,
                         body: str) -> dict[str, Any]:
        """Send one plain-text email. Published for other modules to reuse.

        Anything that needs to mail on the user's behalf goes through here
        rather than building its own Gmail client.
        """
        gmail = service(workspace, account_id, "gmail", "v1")
        raw = raw_email(EmailComposeRequest(
            account_id=account_id, to=to, subject=subject, body=body, confirm=True))
        result = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"sent": True, "message_id": result.get("id")}

    namespace.setdefault("MAIL_SENDERS", {})["google"] = send_plain_email

    @app.get("/api/google/calendar/events")
    async def google_calendar_events(account_id: str, time_min: str | None = None,
                                     time_max: str | None = None, max_results: int = 100,
                                     context=Depends(require_account)) -> dict[str, Any]:
        calendar = service(context.workspace, account_id, "calendar", "v3")
        list_kwargs: dict[str, Any] = {
            "calendarId": "primary",
            "maxResults": min(max(max_results, 1), 250),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min == "all":
            # Don't apply time bounds if explicitly asking for all events
            pass
        else:
            list_kwargs["timeMin"] = time_min if time_min else _iso(_utcnow() - timedelta(days=365))
            list_kwargs["timeMax"] = time_max if time_max else _iso(_utcnow() + timedelta(days=365))
        result = calendar.events().list(**list_kwargs).execute()
        events = [dict(item, meet_link=meet_link(item)) for item in result.get("items", [])]
        return {"events": events}

    def event_body(body: CalendarEventRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "summary": body.summary,
            "description": body.description,
            "start": {"dateTime": body.start, "timeZone": body.timezone},
            "end": {"dateTime": body.end, "timeZone": body.timezone},
            "attendees": [{"email": value} for value in body.attendees if value.strip()],
        }
        if body.location.strip():
            payload["location"] = body.location.strip()
        if body.add_meet:
            payload["conferenceData"] = {
                "createRequest": {
                    # Google requires a caller-supplied id it can use to make
                    # the conference creation idempotent.
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        return payload

    def run_calendar(request: Any, action: str) -> Any:
        """Execute a Calendar request, turning Google failures into clear messages."""
        from googleapiclient.errors import HttpError

        try:
            return request.execute()
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", 502) or 502
            detail = "Google Calendar rejected the request"
            try:
                detail = str(
                    ((json.loads(exc.content.decode("utf-8")) or {}).get("error") or {}).get("message")
                    or detail
                )
            except Exception:
                pass
            if status == 404:
                raise HTTPException(404, "That event no longer exists in this Google Calendar") from exc
            if status in (401, 403):
                raise HTTPException(
                    403, f"This Google account is not allowed to {action} the event: {detail}"
                ) from exc
            if status == 429:
                raise HTTPException(
                    429, "Google Calendar is rate limiting this account; try again shortly"
                ) from exc
            raise HTTPException(502, f"Google Calendar error: {detail}") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"Google Calendar could not be reached: {exc}") from exc

    def insert_event(workspace: Any, account_id: str, payload: Mapping[str, Any],
                     with_conference: bool) -> dict[str, Any]:
        calendar = service(workspace, account_id, "calendar", "v3")
        return run_calendar(calendar.events().insert(
            calendarId="primary", body=dict(payload), sendUpdates="all",
            # Without conferenceDataVersion=1 Calendar silently drops the
            # conference request and no Meet link is created.
            conferenceDataVersion=1 if with_conference else 0,
        ), "create")

    def meet_link(event: Mapping[str, Any]) -> str:
        """Pull the Meet URL out of a created event, if one was provisioned."""
        if event.get("hangoutLink"):
            return str(event["hangoutLink"])
        for entry in ((event.get("conferenceData") or {}).get("entryPoints") or []):
            if entry.get("entryPointType") == "video" and entry.get("uri"):
                return str(entry["uri"])
        return ""

    @app.post("/api/google/calendar/events")
    async def google_calendar_create(
        body: CalendarEventRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        if not body.confirm:
            return {"confirmation_required": True, "action": "create_calendar_event", "event": event_body(body)}
        result = insert_event(context.workspace, body.account_id, event_body(body), body.add_meet)
        return {"created": True, "event": result, "meet_link": meet_link(result)}

    @app.get("/api/google/calendar/events/{event_id}")
    async def google_calendar_event(
        event_id: str, account_id: str, context=Depends(require_account)
    ) -> dict[str, Any]:
        """One event, read back from Google so the edit form starts from truth."""
        calendar = service(context.workspace, account_id, "calendar", "v3")
        event = run_calendar(
            calendar.events().get(calendarId="primary", eventId=event_id), "read")
        return {"event": dict(event, meet_link=meet_link(event)), "meet_link": meet_link(event)}

    @app.patch("/api/google/calendar/events/{event_id}")
    async def google_calendar_update(
        event_id: str, body: CalendarEventUpdateRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        """Edit an event in the user's real Google Calendar.

        Only the supplied fields are sent, so an unspecified field keeps
        whatever Google already has.
        """
        patch: dict[str, Any] = {}
        if body.summary is not None:
            summary = body.summary.strip()
            if not summary:
                raise HTTPException(422, "Event title cannot be empty")
            patch["summary"] = summary
        if body.description is not None:
            patch["description"] = body.description
        if body.location is not None:
            patch["location"] = body.location
        if body.start is not None:
            patch["start"] = {"dateTime": body.start, "timeZone": body.timezone}
        if body.end is not None:
            patch["end"] = {"dateTime": body.end, "timeZone": body.timezone}
        if body.attendees is not None:
            patch["attendees"] = [{"email": value.strip()} for value in body.attendees if value.strip()]
        if not patch:
            raise HTTPException(422, "Nothing to change")
        if body.start is not None and body.end is not None and body.end < body.start:
            raise HTTPException(422, "The event cannot end before it starts")

        if not body.confirm:
            return {"confirmation_required": True, "action": "update_calendar_event", "event": patch}

        calendar = service(context.workspace, body.account_id, "calendar", "v3")
        updated = run_calendar(calendar.events().patch(
            calendarId="primary", eventId=event_id, body=patch, sendUpdates="all",
        ), "update")
        return {"updated": True, "event": updated, "meet_link": meet_link(updated)}

    @app.post("/api/google/assistant/interpret")
    async def google_assistant_interpret(
        body: WorkspaceAssistantRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        """Turn a natural-language Calendar request into a reviewable proposal.

        This route never performs the action.  The client must display the
        proposal and call the confirmed Calendar endpoint separately.
        """
        if not vl_generate:
            raise HTTPException(503, "The Qwen generator is not loaded")
        task_rows = []
        for project_id, project_tasks in context.workspace.load_tasks().items():
            for task in project_tasks:
                task_rows.append({
                    "project_id": project_id, "task_id": task.get("id"),
                    "name": task.get("name") or task.get("title"),
                    "due_date": task.get("due_date"),
                    "description": task.get("description", ""),
                })
        prompt = (
            "Interpret the user's request as a Google Calendar event proposal. "
            "Return JSON only with keys intent, summary, description, start, end, attendees. "
            "intent must be create_calendar_event or unsupported. start and end must be ISO-8601 "
            "date-times. If no duration is stated, use one hour. Never claim the event was created.\n"
            f"Current UTC time: {_iso()}\nUser timezone: {body.timezone}\n"
            f"Available project tasks: {json.dumps(task_rows[:100], default=str)}\n"
            f"User request: {body.query}"
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        raw = await asyncio.get_running_loop().run_in_executor(
            None, lambda: vl_generate(messages, max_new_tokens=350)
        )
        match = re.search(r"\{[\s\S]*\}", str(raw))
        if not match:
            raise HTTPException(422, "Marshal could not interpret the calendar request")
        try:
            proposal = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise HTTPException(422, "Marshal returned an invalid calendar proposal") from exc
        if proposal.get("intent") != "create_calendar_event":
            return {"supported": False, "proposal": proposal}
        return {"supported": True, "proposal": proposal, "confirmation_required": True}

    async def extract_meet_fields(query: str, timezone: str, known: Mapping[str, Any]) -> dict[str, Any]:
        """Ask the model for whatever meeting details this message supplies."""
        if not vl_generate or not query.strip():
            return {}
        prompt = extraction_prompt(
            query, timezone, json.dumps(dict(known), default=str), _iso(), "Google Meet")
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        raw = await asyncio.get_running_loop().run_in_executor(
            None, lambda: vl_generate(messages, max_new_tokens=350)
        )
        return parse_extraction(raw)

    @app.post("/api/google/meet/schedule")
    async def google_meet_schedule(
        body: MeetScheduleRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        """Schedule a Google Meet conversationally.

        One turn at a time: the response is either a follow-up question, a
        proposal awaiting confirmation, or the created meeting with its Meet
        link. The Calendar account is always resolved through the caller's own
        workspace, so a meeting can only ever be created on a Google account
        this BuildMarshal account has linked.
        """
        if not vl_generate and body.query.strip():
            raise HTTPException(503, "The generator is not loaded")
        # Fail early and clearly if the account is not linked here.
        credentials(context.workspace, body.account_id)

        extracted = await extract_meet_fields(body.query, body.timezone, body.known)
        fields = merge_meet_fields(body.known, extracted)

        missing, question = validate_meet_fields(fields)
        if missing:
            return {
                "status": "needs_input",
                "missing": missing,
                "question": question,
                "known": fields,
            }

        proposal = meeting_proposal(fields, body.timezone)

        if not body.confirm:
            return {
                "status": "confirm",
                "confirmation_required": True,
                "action": "schedule_google_meet",
                "proposal": proposal,
                "known": fields,
            }

        payload = event_body(CalendarEventRequest(
            account_id=body.account_id, summary=proposal["summary"],
            description=proposal["description"], start=proposal["start"],
            end=proposal["end"], timezone=body.timezone,
            attendees=proposal["attendees"], add_meet=True, confirm=True,
        ))
        event = insert_event(context.workspace, body.account_id, payload, True)
        link = meet_link(event)
        return {
            "status": "created",
            "created": True,
            "meet_link": link,
            # Google can refuse to attach a conference (for example when the
            # Workspace policy disables Meet); say so rather than pretending.
            "meet_unavailable": not link,
            "event": {
                "id": event.get("id"),
                "summary": event.get("summary"),
                "start": (event.get("start") or {}).get("dateTime"),
                "end": (event.get("end") or {}).get("dateTime"),
                "html_link": event.get("htmlLink"),
                "attendees": [a.get("email") for a in (event.get("attendees") or [])],
            },
            "proposal": proposal,
        }

    @app.post("/api/google/tasks/{project_id}/{task_id}/calendar")
    async def google_task_to_calendar(
        project_id: str, task_id: str, body: CalendarEventRequest,
        context=Depends(require_account),
    ) -> dict[str, Any]:
        project_tasks = context.workspace.load_tasks().get(project_id, [])
        task = next((item for item in project_tasks if str(item.get("id")) == task_id), None)
        if not task:
            raise HTTPException(404, "Task not found")
        body.summary = body.summary or str(task.get("name") or task.get("title") or "Project task")
        body.description = body.description or str(task.get("description") or "")
        return await google_calendar_create(body, context)

    return {
        "configured": bool(client_id and client_secret and encryption_key and allowed_origins),
        "account_store": account_store,
        "scopes": GOOGLE_SCOPES,
        "generate_encryption_key": lambda: Fernet.generate_key().decode("ascii"),
    }


__all__ = [
    "GOOGLE_SCOPES", "MeetScheduleRequest", "merge_meet_fields",
    "normalise_meet_fields", "parse_meeting_start",
    "register_google_workspace_routes", "validate_meet_fields",
]
