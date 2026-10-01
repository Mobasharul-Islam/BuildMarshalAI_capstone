"""Microsoft 365 integration for BuildMarshalAI, via the Microsoft Graph API.

This mirrors ``google_workspace`` so both providers behave the same way, and a
user can keep Google and Microsoft accounts linked at the same time.  Call
``register_microsoft_workspace_routes(globals())`` after the FastAPI app, the
account system, document ingestion, and the generator have been created.

OAuth notes
-----------
The authorization-code flow runs with PKCE **and** the confidential-client
secret.  The backend mints the ``state`` and the code verifier, keeps them in
memory, and hands the browser only an authorize URL; the browser never sees the
client secret and never handles a refresh token.  Refresh tokens are encrypted
at rest in the workspace of the BuildMarshal account that linked them.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlencode

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

try:  # the notebook puts this directory on sys.path
    from meeting_language import (
        MeetScheduleRequest, extraction_prompt, meeting_proposal, merge_meet_fields,
        parse_extraction, validate_meet_fields,
    )
    from external_imports import ExternalImporter
    from oauth_tokens import (
        EncryptedAccountStore,
        account_identifier,
        iso,
        safe_name,
        utcnow,
    )
except ModuleNotFoundError:  # imported as backend.microsoft_workspace
    from backend.meeting_language import (
        MeetScheduleRequest, extraction_prompt, meeting_proposal, merge_meet_fields,
        parse_extraction, validate_meet_fields,
    )
    from backend.external_imports import ExternalImporter
    from backend.oauth_tokens import (
        EncryptedAccountStore,
        account_identifier,
        iso,
        safe_name,
        utcnow,
    )


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"

# offline_access is what yields a refresh token; without it a link would die
# within the hour.  The rest mirror the Google scope set feature for feature.
# A Teams join URL. Work and school accounts get teams.microsoft.com links;
# personal Microsoft accounts get teams.live.com ones, which is why matching
# only the first host missed them.
#: The characters a OneDrive item id is made of ("ABC123!105"). An id becomes
#: part of a Graph path, so anything else -- a slash, a query -- is refused.
ONEDRIVE_ID = re.compile(r"[A-Za-z0-9!._-]{1,200}")

TEAMS_JOIN_URL = re.compile(
    r"https://teams\.(?:microsoft|live)\.com/[^\s\"'<>\\]+",
    re.IGNORECASE,
)


# Outlook wraps the Teams block in a rule of dots or underscores, above and
# below. Everything between them is boilerplate the app already shows properly.
MEETING_BOILERPLATE = re.compile(r"^[ \t]*[._-]{20,}[ \t]*$", re.MULTILINE)

MEETING_ID = re.compile(r"Meeting\s*ID:\s*([\d][\d\s]{6,})", re.IGNORECASE)
MEETING_PASSCODE = re.compile(r"Passcode:\s*(\S+)", re.IGNORECASE)


def event_body_text(item: Mapping[str, Any]) -> str:
    """The event body as readable text.

    Graph returns the body as HTML for anything Outlook or Teams created, and
    handing that to the client showed a wall of markup where the notes should
    be. bodyPreview stands in when there is no body at all.
    """
    body = item.get("body") or {}
    content = str(body.get("content") or "")
    if not content.strip():
        return str(item.get("bodyPreview") or "").strip()
    if str(body.get("contentType") or "").lower() == "html" or "<" in content:
        return _plain_text(content)
    return content.strip()


def strip_meeting_boilerplate(text: str) -> str:
    """Drop the Teams join block, keeping whatever the organiser actually wrote.

    The join link, meeting id, and passcode are surfaced as their own fields,
    so repeating the block verbatim adds nothing but noise.
    """
    parts = MEETING_BOILERPLATE.split(str(text or ""))
    if len(parts) < 3:
        return str(text or "").strip()
    # The organiser's own words are outside the rules: the first part and the
    # last. Anything between them is the generated block.
    kept = [parts[0].strip(), parts[-1].strip()]
    return "\n\n".join(part for part in kept if part).strip()


def teams_meeting_details(item: Mapping[str, Any]) -> dict[str, str]:
    """Join URL, meeting id, and passcode, wherever Graph happened to put them."""
    text = event_body_text(item)
    meeting_id = MEETING_ID.search(text)
    passcode = MEETING_PASSCODE.search(text)
    return {
        "join_url": teams_join_url(item),
        "meeting_id": " ".join(meeting_id.group(1).split()) if meeting_id else "",
        "passcode": passcode.group(1).strip() if passcode else "",
    }


def teams_join_url(item: Mapping[str, Any]) -> str:
    """Pull the join link out of an Outlook event.

    Graph reports it in several places depending on how the meeting was made:
    ``onlineMeeting.joinUrl`` when Graph or Outlook created it, the deprecated
    ``onlineMeetingUrl`` on older events, and for anything created outside
    Outlook -- or on a personal account -- only as a link inside the event
    body. Checking just the first field left those events showing no link at
    all, so fall through the lot.
    """
    direct = str((item.get("onlineMeeting") or {}).get("joinUrl") or "").strip()
    if direct:
        return direct
    legacy = str(item.get("onlineMeetingUrl") or "").strip()
    if legacy:
        return legacy

    import html as html_module

    for blob in (
        (item.get("body") or {}).get("content"),
        item.get("bodyPreview"),
        (item.get("location") or {}).get("displayName"),
    ):
        if not blob:
            continue
        # Body content is HTML, so "&amp;" in a query string has to come back
        # as "&" before the URL is usable.
        match = TEAMS_JOIN_URL.search(html_module.unescape(str(blob)))
        if match:
            # Trailing punctuation from the surrounding prose is not the URL.
            return match.group(0).rstrip(".,;:)]}\'\"")
    return ""


def graph_query(params: Mapping[str, Any]) -> str:
    """Build an encoded Graph query string.

    Values are percent-encoded rather than interpolated straight in. A UTC
    timestamp carries a "+" in its offset, and a raw "+" in a query string is
    read back as a space -- which is why Graph rejected calendarView with
    "The value '...17:40:49.648633 00:00' of parameter 'StartDateTime' is
    invalid". The same applies to any "&" or "+" a user types into a search box.
    """
    return "&".join(f"{key}={quote(str(value), safe='')}" for key, value in params.items())


MICROSOFT_SCOPES = [
    "openid",
    "profile",
    "email",
    "offline_access",
    "User.Read",
    "Files.Read",
    "Mail.Read",
    "Mail.ReadWrite",
    "Mail.Send",
    "Calendars.ReadWrite",
]

# Office formats Graph can convert to PDF on download, so page rendering and
# text extraction work the same way they do for Drive exports.
GRAPH_PDF_CONVERTIBLE = {
    ".doc", ".docx", ".dot", ".dotx", ".epub", ".odp", ".ods", ".odt",
    ".pot", ".potx", ".pps", ".ppsx", ".ppt", ".pptx", ".rtf", ".xls", ".xlsx",
}

# Extensions the ingestion pipeline handles directly.
DIRECT_IMPORT_SUFFIXES = {
    ".pdf", ".txt", ".csv", ".json", ".xml", ".html", ".md",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff",
}

OAUTH_STATE_TTL_SECONDS = 600


class OAuthStartRequest(BaseModel):
    redirect_uri: str = Field(min_length=1, max_length=500)


class OAuthCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=8000)
    state: str = Field(min_length=1, max_length=200)
    redirect_uri: str = Field(min_length=1, max_length=500)


class ImportRequest(BaseModel):
    account_id: str
    item_ids: list[str] = Field(min_length=1, max_length=25)
    project_id: str | None = None


class MailComposeRequest(BaseModel):
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
    # Ask Graph to attach a Teams meeting, the Outlook counterpart of add_meet.
    add_online_meeting: bool = False
    confirm: bool = False


class CalendarEventUpdateRequest(BaseModel):
    """A partial edit of an existing Outlook Calendar event."""

    account_id: str
    summary: str | None = Field(default=None, max_length=1024)
    description: str | None = Field(default=None, max_length=8000)
    location: str | None = Field(default=None, max_length=1024)
    start: str | None = None
    end: str | None = None
    timezone: str = "UTC"
    attendees: list[str] | None = None
    confirm: bool = False


class AssistantRequest(BaseModel):
    account_id: str
    query: str
    timezone: str = "UTC"


def _addresses(value: str) -> list[dict[str, Any]]:
    """Turn a comma/semicolon separated list into Graph recipient objects."""
    parts = [item.strip() for item in re.split(r"[;,]", str(value or "")) if item.strip()]
    return [{"emailAddress": {"address": address}} for address in parts]


def _plain_text(html_body: str) -> str:
    import html as html_module

    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", str(html_body or ""))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6])\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    # Collapse runs of spaces, then trim each line, so the text stored for
    # retrieval has no ragged indentation left over from the HTML.
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _message_body(message: Mapping[str, Any]) -> str:
    body = message.get("body") or {}
    content = str(body.get("content") or "")
    if str(body.get("contentType") or "").lower() == "html":
        return _plain_text(content)
    return content.strip() or str(message.get("bodyPreview") or "")


def _recipients(message: Mapping[str, Any], field: str) -> str:
    return ", ".join(
        str((item.get("emailAddress") or {}).get("address") or "")
        for item in (message.get(field) or [])
    )


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    return verifier, challenge


def register_microsoft_workspace_routes(namespace: Mapping[str, Any]) -> Any:
    """Register Microsoft OAuth, OneDrive, Outlook Mail, and Calendar routes."""
    required = ["app", "ingest_document", "require_account"]
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Microsoft integration is missing: {', '.join(missing)}")

    import requests

    app = namespace["app"]
    require_account = namespace["require_account"]
    vl_generate = namespace.get("vl_generate")
    importer = ExternalImporter(namespace["ingest_document"], "microsoft")

    client_id = os.environ.get("MICROSOFT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("MICROSOFT_CLIENT_SECRET", "").strip()
    tenant = os.environ.get("MICROSOFT_TENANT_ID", "common").strip() or "common"
    encryption_key = os.environ.get(
        "MICROSOFT_TOKEN_ENCRYPTION_KEY",
        os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY", ""),
    ).strip()
    allowed_origins = {
        origin.strip().rstrip("/")
        for origin in os.environ.get(
            "MICROSOFT_ALLOWED_ORIGINS",
            os.environ.get("GOOGLE_ALLOWED_ORIGINS", ""),
        ).split(",")
        if origin.strip()
    }

    authority = f"https://login.microsoftonline.com/{tenant}"
    authorize_endpoint = f"{authority}/oauth2/v2.0/authorize"
    token_endpoint = f"{authority}/oauth2/v2.0/token"

    # Pending authorizations, keyed by the state value we minted.  In memory
    # only: a restart simply invalidates in-flight sign-ins.
    pending: dict[str, dict[str, Any]] = {}
    pending_lock = threading.RLock()

    _stores: dict[str, EncryptedAccountStore] = {}
    _stores_lock = threading.RLock()

    def account_store(workspace: Any) -> EncryptedAccountStore:
        if not encryption_key:
            raise HTTPException(503, "Microsoft OAuth is not configured on this backend")
        with _stores_lock:
            store = _stores.get(workspace.account_id)
            if store is None:
                store = EncryptedAccountStore(workspace.token_store("microsoft"), encryption_key)
                _stores[workspace.account_id] = store
            return store

    def configured() -> bool:
        return bool(client_id and client_secret and encryption_key and allowed_origins)

    def assert_configured() -> None:
        if not configured():
            raise HTTPException(503, "Microsoft OAuth is not configured on this backend")

    def assert_origin(request: Request, redirect_uri: str) -> None:
        origin = request.headers.get("origin", "").rstrip("/")
        redirect = redirect_uri.rstrip("/")
        if redirect in {"", "null", "file://"}:
            raise HTTPException(400, "Microsoft sign-in requires a served HTTPS or localhost frontend")
        if not any(redirect.startswith(allowed) for allowed in allowed_origins):
            raise HTTPException(403, "Redirect URI is not in MICROSOFT_ALLOWED_ORIGINS")
        if origin and origin not in allowed_origins:
            raise HTTPException(403, "Frontend origin is not in MICROSOFT_ALLOWED_ORIGINS")

    def prune_pending() -> None:
        cutoff = time.monotonic() - OAUTH_STATE_TTL_SECONDS
        with pending_lock:
            for key in [k for k, v in pending.items() if v["created"] < cutoff]:
                pending.pop(key, None)

    # -- token handling --------------------------------------------------

    def token_request(payload: dict[str, str]) -> dict[str, Any]:
        response = requests.post(
            token_endpoint,
            data={"client_id": client_id, "client_secret": client_secret, **payload},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if not response.ok:
            detail = ""
            try:
                body = response.json()
                detail = str(body.get("error_description") or body.get("error") or "")
            except ValueError:
                detail = response.text[:200]
            # Never echo the raw response: it can carry request ids and tokens.
            raise HTTPException(400, f"Microsoft token request failed: {detail[:200]}")
        return response.json()

    def store_tokens(store: EncryptedAccountStore, token: Mapping[str, Any]) -> dict[str, Any]:
        access_token = str(token.get("access_token") or "")
        if not access_token:
            raise HTTPException(400, "Microsoft did not return an access token")
        profile = requests.get(
            f"{GRAPH_ROOT}/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if not profile.ok:
            raise HTTPException(400, "The Microsoft account profile could not be read")
        me = profile.json()
        email = str(me.get("mail") or me.get("userPrincipalName") or "").lower()
        if not email:
            raise HTTPException(400, "Microsoft did not return an email address")
        account_id = account_identifier(email)
        try:
            previous = store.get(account_id)
        except KeyError:
            previous = {}
        expires_in = int(token.get("expires_in", 3600))
        record = {
            "id": account_id,
            "provider": "microsoft",
            "email": email,
            "name": me.get("displayName") or email,
            "picture": None,
            "connected_at": previous.get("connected_at") or iso(),
            "access_token": access_token,
            # A refresh response often omits the refresh token; keep the one we
            # already hold so the link does not silently expire.
            "refresh_token": token.get("refresh_token") or previous.get("refresh_token"),
            "expiry": iso(utcnow() + timedelta(seconds=max(expires_in - 60, 60))),
            "scopes": str(token.get("scope") or " ".join(MICROSOFT_SCOPES)).split(),
        }
        store.put(record)
        return record

    def access_token(workspace: Any, account_id: str) -> str:
        assert_configured()
        store = account_store(workspace)
        try:
            record = store.get(account_id)
        except KeyError as exc:
            raise HTTPException(404, "Microsoft account not found") from exc

        expired = True
        if record.get("expiry"):
            try:
                parsed = datetime.fromisoformat(str(record["expiry"]))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                expired = parsed <= utcnow()
            except ValueError:
                expired = True
        if not expired:
            return str(record["access_token"])

        refresh_token = record.get("refresh_token")
        if not refresh_token:
            raise HTTPException(401, "Reconnect this Microsoft account to restore offline access")
        try:
            token = token_request({
                "grant_type": "refresh_token",
                "refresh_token": str(refresh_token),
                "scope": " ".join(MICROSOFT_SCOPES),
            })
        except HTTPException as exc:
            raise HTTPException(401, "Microsoft authorization expired; reconnect this account") from exc
        return str(store_tokens(store, token)["access_token"])

    def graph(workspace: Any, account_id: str, method: str, path: str, **kwargs) -> Any:
        """Call Graph for one linked account and return the decoded response."""
        url = path if path.startswith("http") else f"{GRAPH_ROOT}{path}"
        headers = {"Authorization": f"Bearer {access_token(workspace, account_id)}"}
        headers.update(kwargs.pop("headers", {}))
        response = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        if response.status_code == 401:
            raise HTTPException(401, "Microsoft authorization expired; reconnect this account")
        if not response.ok:
            detail = ""
            try:
                detail = str(((response.json() or {}).get("error") or {}).get("message") or "")
            except ValueError:
                detail = response.text[:200]
            raise HTTPException(response.status_code, f"Microsoft Graph error: {detail[:200]}")
        if response.status_code == 204 or not response.content:
            return {}
        if response.headers.get("Content-Type", "").startswith("application/json"):
            return response.json()
        return response.content

    # -- OneDrive downloads ----------------------------------------------

    def download_drive_item(workspace: Any, account_id: str, item: Mapping[str, Any]) -> tuple[Path, str]:
        name = safe_name(str(item.get("name") or "onedrive-document"))
        suffix = Path(name).suffix.lower()
        item_id = item["id"]
        convert = suffix in GRAPH_PDF_CONVERTIBLE
        if convert:
            path = f"/me/drive/items/{item_id}/content?format=pdf"
            if suffix != ".pdf":
                name = f"{Path(name).stem}.pdf"
        elif suffix in DIRECT_IMPORT_SUFFIXES:
            path = f"/me/drive/items/{item_id}/content"
        else:
            raise ValueError(f"Unsupported OneDrive file type: {suffix or 'unknown'}")

        content = graph(workspace, account_id, "GET", path)
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("OneDrive returned no file content")
        target = Path(workspace.imports_dir) / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target, name

    # -- configuration & OAuth -------------------------------------------

    @app.get("/api/microsoft/config")
    async def microsoft_config(context=Depends(require_account)) -> dict[str, Any]:
        return {
            "enabled": configured(),
            "client_id": client_id,
            "tenant": tenant,
            "scopes": MICROSOFT_SCOPES,
            "requires_served_frontend": True,
        }

    @app.post("/api/microsoft/oauth/start")
    async def microsoft_oauth_start(
        body: OAuthStartRequest, request: Request, context=Depends(require_account)
    ) -> dict[str, Any]:
        assert_configured()
        assert_origin(request, body.redirect_uri)
        prune_pending()
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        with pending_lock:
            pending[state] = {
                "verifier": verifier,
                "redirect_uri": body.redirect_uri,
                # Bind the pending sign-in to the account that started it, so a
                # code cannot be redeemed into a different workspace.
                "account_id": context.account_id,
                "created": time.monotonic(),
            }
        query = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": body.redirect_uri,
            "response_mode": "query",
            "scope": " ".join(MICROSOFT_SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return {"authorize_url": f"{authorize_endpoint}?{urlencode(query)}", "state": state}

    @app.post("/api/microsoft/oauth/code")
    async def microsoft_oauth_code(
        body: OAuthCodeRequest, request: Request, context=Depends(require_account)
    ) -> dict[str, Any]:
        assert_configured()
        assert_origin(request, body.redirect_uri)
        prune_pending()
        with pending_lock:
            record = pending.pop(body.state, None)
        if not record:
            raise HTTPException(400, "This Microsoft sign-in expired or was already used")
        if record["account_id"] != context.account_id:
            raise HTTPException(403, "This Microsoft sign-in belongs to a different account")
        if record["redirect_uri"].rstrip("/") != body.redirect_uri.rstrip("/"):
            raise HTTPException(400, "Redirect URI does not match the one the sign-in started with")

        store = account_store(context.workspace)
        token = token_request({
            "grant_type": "authorization_code",
            "code": body.code,
            "redirect_uri": body.redirect_uri,
            "code_verifier": record["verifier"],
            "scope": " ".join(MICROSOFT_SCOPES),
        })
        saved = store_tokens(store, token)
        return {"account": store.public(saved)}

    @app.get("/api/microsoft/accounts")
    async def microsoft_accounts(context=Depends(require_account)) -> dict[str, Any]:
        if not encryption_key:
            return {"accounts": []}
        return {"accounts": account_store(context.workspace).list_public()}

    @app.delete("/api/microsoft/accounts/{account_id}")
    async def microsoft_disconnect(account_id: str, context=Depends(require_account)) -> dict[str, Any]:
        assert_configured()
        record = account_store(context.workspace).delete(account_id)
        if not record:
            raise HTTPException(404, "Microsoft account not found")
        return {"disconnected": True, "account_id": account_id}

    # -- OneDrive ---------------------------------------------------------

    @app.get("/api/microsoft/drive/files")
    async def microsoft_drive_files(
        account_id: str, q: str = "", page_size: int = 50, page_token: str | None = None,
        folder_id: str = "", context=Depends(require_account),
    ) -> dict[str, Any]:
        """One folder's contents, folders first -- or a search across OneDrive.

        The folder id becomes part of a Graph path, so it is held to the
        characters OneDrive item ids are made of.
        """
        folder = str(folder_id or "").strip()
        if folder and not ONEDRIVE_ID.fullmatch(folder):
            raise HTTPException(422, "Invalid folder id")
        workspace = context.workspace
        size = min(max(page_size, 1), 100)
        if page_token:
            result = graph(workspace, account_id, "GET", page_token)
        elif q.strip():
            escaped = quote(q.replace("'", "''"), safe="")
            result = graph(
                workspace, account_id, "GET",
                f"/me/drive/root/search(q='{escaped}')?" + graph_query({
                    "$top": size,
                    "$select": "id,name,size,file,folder,lastModifiedDateTime,webUrl",
                }),
            )
        else:
            result = graph(
                workspace, account_id, "GET",
                (f"/me/drive/items/{folder}/children?" if folder else "/me/drive/root/children?")
                + graph_query({
                    "$top": size, "$orderby": "lastModifiedDateTime desc",
                    "$select": "id,name,size,file,folder,lastModifiedDateTime,webUrl",
                }),
            )
        files = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "mimeType": ((item.get("file") or {}).get("mimeType")
                             or ("folder" if item.get("folder") else "")),
                "size": item.get("size"),
                "modifiedTime": item.get("lastModifiedDateTime"),
                "webViewLink": item.get("webUrl"),
                "is_folder": bool(item.get("folder")),
            }
            for item in (result.get("value") or [])
        ]
        # Folders first, as Drive does; Graph cannot sort that way itself.
        files.sort(key=lambda row: not row["is_folder"])
        return {"files": files, "next_page_token": result.get("@odata.nextLink"),
                "folder_id": None if q.strip() else (folder or "root")}

    @app.post("/api/microsoft/drive/import")
    async def microsoft_drive_import(
        body: ImportRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        context.require("document.upload", "adding documents")
        workspace = context.workspace
        imported, errors = [], []
        for item_id in body.item_ids:
            try:
                item = graph(workspace, body.account_id, "GET",
                             f"/me/drive/items/{item_id}?$select=id,name,file,folder,size")
                if item.get("folder"):
                    raise ValueError("Folders cannot be imported; select files instead")
                path, display_name = download_drive_item(workspace, body.account_id, item)
                imported.append(importer.ingest_path(
                    workspace, path, display_name, body.project_id, "onedrive_file",
                    {"account_id": body.account_id, "item_id": item_id,
                     "mime_type": (item.get("file") or {}).get("mimeType")},
                ))
                path.unlink(missing_ok=True)
            except HTTPException as exc:
                errors.append({"item_id": item_id, "error": str(exc.detail)})
            except Exception as exc:
                errors.append({"item_id": item_id, "error": str(exc)})
        return {"imported": imported, "errors": errors, "total": len(imported)}

    # -- Outlook Mail ------------------------------------------------------

    @app.get("/api/microsoft/mail/messages")
    async def microsoft_mail_messages(
        account_id: str, q: str = "", page_size: int = 30, page_token: str | None = None,
        context=Depends(require_account),
    ) -> dict[str, Any]:
        workspace = context.workspace
        size = min(max(page_size, 1), 50)
        select = "id,conversationId,subject,from,toRecipients,receivedDateTime,bodyPreview"
        if page_token:
            result = graph(workspace, account_id, "GET", page_token)
        elif q.strip():
            # $search cannot be combined with $orderby in Graph.
            result = graph(
                workspace, account_id, "GET",
                "/me/messages?" + graph_query({
                    "$search": f'"{q.strip()}"', "$top": size, "$select": select,
                }),
                headers={"ConsistencyLevel": "eventual"},
            )
        else:
            result = graph(
                workspace, account_id, "GET",
                "/me/messages?" + graph_query({
                    "$top": size, "$orderby": "receivedDateTime desc", "$select": select,
                }),
            )
        messages = [
            {
                "id": item.get("id"),
                "thread_id": item.get("conversationId"),
                "subject": item.get("subject") or "(no subject)",
                "from": str(((item.get("from") or {}).get("emailAddress") or {}).get("address") or ""),
                "to": _recipients(item, "toRecipients"),
                "date": item.get("receivedDateTime", ""),
                "snippet": item.get("bodyPreview", ""),
            }
            for item in (result.get("value") or [])
        ]
        return {"messages": messages, "next_page_token": result.get("@odata.nextLink")}

    @app.post("/api/microsoft/mail/import")
    async def microsoft_mail_import(
        body: ImportRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        context.require("document.upload", "adding documents")
        workspace = context.workspace
        imported, errors = [], []
        import_dir = Path(workspace.imports_dir)
        import_dir.mkdir(parents=True, exist_ok=True)
        for item_id in body.item_ids:
            try:
                message = graph(workspace, body.account_id, "GET", f"/me/messages/{item_id}")
                subject = message.get("subject") or "No subject"
                text = (
                    f"Subject: {subject}\n"
                    f"From: {str(((message.get('from') or {}).get('emailAddress') or {}).get('address') or '')}\n"
                    f"To: {_recipients(message, 'toRecipients')}\n"
                    f"Date: {message.get('receivedDateTime', '')}\n\n"
                    f"{_message_body(message)}"
                )
                path = import_dir / f"{uuid.uuid4().hex}.txt"
                path.write_text(text, encoding="utf-8")
                imported.append(importer.ingest_path(
                    workspace, path, safe_name(f"Email - {subject}.txt"), body.project_id,
                    "outlook_message",
                    {"account_id": body.account_id, "item_id": item_id,
                     "thread_id": message.get("conversationId")},
                ))
                path.unlink(missing_ok=True)
            except HTTPException as exc:
                errors.append({"item_id": item_id, "error": str(exc.detail)})
            except Exception as exc:
                errors.append({"item_id": item_id, "error": str(exc)})
        return {"imported": imported, "errors": errors, "total": len(imported)}

    async def generate_mail(body: MailComposeRequest) -> dict[str, str]:
        if not vl_generate:
            raise HTTPException(503, "The generator is not loaded")
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

    def message_payload(body: MailComposeRequest) -> dict[str, Any]:
        if not body.to.strip() or not body.subject.strip() or not body.body.strip():
            raise HTTPException(422, "To, subject, and body are required")
        payload: dict[str, Any] = {
            "subject": body.subject.strip(),
            "body": {"contentType": "Text", "content": body.body},
            "toRecipients": _addresses(body.to),
        }
        if body.cc.strip():
            payload["ccRecipients"] = _addresses(body.cc)
        return payload

    @app.post("/api/microsoft/mail/generate")
    async def microsoft_mail_generate(
        body: MailComposeRequest, context=Depends(require_account)
    ) -> dict[str, str]:
        return await generate_mail(body)

    @app.post("/api/microsoft/mail/draft")
    async def microsoft_mail_draft(
        body: MailComposeRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        # Nothing reaches the mailbox until the client echoes an explicit
        # confirmation, matching the Google behaviour.
        if not body.confirm:
            return {"confirmation_required": True, "action": "create_email_draft"}
        result = graph(context.workspace, body.account_id, "POST", "/me/messages",
                       json=message_payload(body))
        return {"created": True, "draft_id": result.get("id"), "message_id": result.get("id")}

    @app.post("/api/microsoft/mail/send")
    async def microsoft_mail_send(
        body: MailComposeRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        if not body.confirm:
            return {"confirmation_required": True, "action": "send_email"}
        graph(context.workspace, body.account_id, "POST", "/me/sendMail",
              json={"message": message_payload(body), "saveToSentItems": True})
        return {"sent": True}

    def send_plain_email(workspace: Any, account_id: str, to: str, subject: str,
                         body: str) -> dict[str, Any]:
        """Send one plain-text email. Published for other modules to reuse."""
        graph(workspace, account_id, "POST", "/me/sendMail", json={
            "message": message_payload(MailComposeRequest(
                account_id=account_id, to=to, subject=subject, body=body, confirm=True)),
            "saveToSentItems": True,
        })
        return {"sent": True}

    namespace.setdefault("MAIL_SENDERS", {})["microsoft"] = send_plain_email

    # -- Outlook Calendar --------------------------------------------------

    def event_payload(body: CalendarEventRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "subject": body.summary,
            "body": {"contentType": "Text", "content": body.description},
            "start": {"dateTime": body.start, "timeZone": body.timezone},
            "end": {"dateTime": body.end, "timeZone": body.timezone},
            "attendees": [
                {"emailAddress": {"address": value.strip()}, "type": "required"}
                for value in body.attendees if value.strip()
            ],
        }
        if body.location.strip():
            payload["location"] = {"displayName": body.location.strip()}
        if body.add_online_meeting:
            # Graph mints the Teams meeting and returns the join URL on the event.
            #
            # onlineMeetingProvider is deliberately left unset. Naming
            # "teamsForBusiness" makes Graph refuse the conferencing on a
            # personal Microsoft account and quietly create a plain event with
            # no join link; omitting it yields a Teams link on personal and
            # work accounts alike, since a work tenant applies its own default.
            payload["isOnlineMeeting"] = True
        return payload

    def shape_event(item: Mapping[str, Any]) -> dict[str, Any]:
        """Present an Outlook event in the Google Calendar shape.

        The frontend renders either provider with the same code, so both must
        agree on the field names.
        """
        meeting = teams_meeting_details(item)
        return {
            "id": item.get("id"),
            "summary": item.get("subject") or "(no title)",
            "description": strip_meeting_boilerplate(event_body_text(item)),
            "start": {"dateTime": (item.get("start") or {}).get("dateTime"),
                      "timeZone": (item.get("start") or {}).get("timeZone")},
            "end": {"dateTime": (item.get("end") or {}).get("dateTime"),
                    "timeZone": (item.get("end") or {}).get("timeZone")},
            "location": (item.get("location") or {}).get("displayName") or "",
            "htmlLink": item.get("webLink"),
            # Named meet_link so one renderer covers Teams and Google Meet alike.
            "meet_link": meeting["join_url"],
            "meeting_id": meeting["meeting_id"],
            "meeting_passcode": meeting["passcode"],
            "online_meeting_provider": item.get("onlineMeetingProvider") or "",
            "organizer": ((item.get("organizer") or {}).get("emailAddress") or {}).get("address", ""),
            "attendees": [
                {"email": str(((a.get("emailAddress") or {}).get("address") or ""))}
                for a in (item.get("attendees") or [])
            ],
        }

    @app.get("/api/microsoft/calendar/events")
    async def microsoft_calendar_events(
        account_id: str, time_min: str | None = None, time_max: str | None = None,
        max_results: int = 100, context=Depends(require_account),
    ) -> dict[str, Any]:
        size = min(max(max_results, 1), 250)
        # body and bodyPreview are selected because a meeting made outside
        # Outlook carries its join link only in the body.
        select = ("id,subject,body,bodyPreview,start,end,location,attendees,organizer,webLink,"
                  "isOnlineMeeting,onlineMeeting,onlineMeetingUrl,onlineMeetingProvider")
        common = {"$top": size, "$orderby": "start/dateTime", "$select": select}
        if time_min == "all":
            path = f"/me/events?{graph_query(common)}"
        else:
            path = "/me/calendarView?" + graph_query({
                "startDateTime": time_min or iso(utcnow() - timedelta(days=365)),
                "endDateTime": time_max or iso(utcnow() + timedelta(days=365)),
                **common,
            })
        result = graph(context.workspace, account_id, "GET", path)
        return {"events": [shape_event(item) for item in (result.get("value") or [])]}

    @app.post("/api/microsoft/calendar/events")
    async def microsoft_calendar_create(
        body: CalendarEventRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        if not body.confirm:
            return {
                "confirmation_required": True,
                "action": "create_calendar_event",
                "event": {"summary": body.summary, "description": body.description,
                          "start": body.start, "end": body.end, "timezone": body.timezone,
                          "location": body.location, "attendees": body.attendees,
                          "add_online_meeting": body.add_online_meeting},
            }
        result = graph(context.workspace, body.account_id, "POST", "/me/events",
                       json=event_payload(body))
        event = shape_event(result)
        return {"created": True, "event": event, "meet_link": event.get("meet_link", "")}

    @app.get("/api/microsoft/calendar/events/{event_id}")
    async def microsoft_calendar_event(
        event_id: str, account_id: str, context=Depends(require_account)
    ) -> dict[str, Any]:
        """One event, read back from Graph so the edit form starts from truth."""
        item = graph(context.workspace, account_id, "GET", f"/me/events/{event_id}")
        return {"event": shape_event(item)}

    @app.patch("/api/microsoft/calendar/events/{event_id}")
    async def microsoft_calendar_update(
        event_id: str, body: CalendarEventUpdateRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        """Edit an event in the user's real Outlook Calendar."""
        patch: dict[str, Any] = {}
        if body.summary is not None:
            summary = body.summary.strip()
            if not summary:
                raise HTTPException(422, "Event title cannot be empty")
            patch["subject"] = summary
        if body.description is not None:
            patch["body"] = {"contentType": "Text", "content": body.description}
        if body.location is not None:
            patch["location"] = {"displayName": body.location}
        if body.start is not None:
            patch["start"] = {"dateTime": body.start, "timeZone": body.timezone}
        if body.end is not None:
            patch["end"] = {"dateTime": body.end, "timeZone": body.timezone}
        if body.attendees is not None:
            patch["attendees"] = [
                {"emailAddress": {"address": value.strip()}, "type": "required"}
                for value in body.attendees if value.strip()
            ]
        if not patch:
            raise HTTPException(422, "Nothing to change")
        if body.start is not None and body.end is not None and body.end < body.start:
            raise HTTPException(422, "The event cannot end before it starts")

        if not body.confirm:
            return {"confirmation_required": True, "action": "update_calendar_event", "event": patch}

        updated = graph(context.workspace, body.account_id, "PATCH",
                        f"/me/events/{event_id}", json=patch)
        return {"updated": True, "event": shape_event(updated)}

    @app.delete("/api/microsoft/calendar/events/{event_id}")
    async def microsoft_calendar_delete(
        event_id: str, account_id: str, confirm: bool = False,
        context=Depends(require_account),
    ) -> dict[str, Any]:
        """Cancel an event in the user's real Outlook calendar.

        The Google route's twin: nothing happens without ``confirm=true``, and
        the first call names the event. Graph tells attendees it was cancelled.
        """
        item = graph(context.workspace, account_id, "GET", f"/me/events/{event_id}")
        summary = shape_event(item)
        if not confirm:
            return {"confirmation_required": True, "action": "delete_calendar_event", "event": summary}
        graph(context.workspace, account_id, "DELETE", f"/me/events/{event_id}")
        return {"deleted": True, "event": summary}

    @app.post("/api/microsoft/assistant/interpret")
    async def microsoft_assistant_interpret(
        body: AssistantRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        """Turn a natural-language request into a reviewable Calendar proposal.

        This route never performs the action; the client must display the
        proposal and call the confirmed Calendar endpoint separately.
        """
        if not vl_generate:
            raise HTTPException(503, "The generator is not loaded")
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
            "Interpret the user's request as an Outlook Calendar event proposal. "
            "Return JSON only with keys intent, summary, description, start, end, attendees. "
            "intent must be create_calendar_event or unsupported. start and end must be ISO-8601 "
            "date-times. If no duration is stated, use one hour. Never claim the event was created.\n"
            f"Current UTC time: {iso()}\nUser timezone: {body.timezone}\n"
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

    async def extract_meeting_fields(query: str, tz: str, known: Mapping[str, Any]) -> dict[str, Any]:
        """Ask the model for whatever meeting details this message supplies."""
        if not vl_generate or not query.strip():
            return {}
        prompt = extraction_prompt(
            query, tz, json.dumps(dict(known), default=str), iso(), "Microsoft Teams")
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        raw = await asyncio.get_running_loop().run_in_executor(
            None, lambda: vl_generate(messages, max_new_tokens=350)
        )
        return parse_extraction(raw)

    @app.post("/api/microsoft/meeting/schedule")
    async def microsoft_meeting_schedule(
        body: MeetScheduleRequest, context=Depends(require_account)
    ) -> dict[str, Any]:
        """Schedule an Outlook meeting conversationally.

        The Teams counterpart of the Google Meet scheduler, and deliberately the
        same shape: each turn returns a follow-up question, a proposal awaiting
        confirmation, or the booked meeting. The Outlook account is resolved
        through the caller's own workspace, so a meeting can only land on an
        account this BuildMarshal account has linked.
        """
        if not vl_generate and body.query.strip():
            raise HTTPException(503, "The generator is not loaded")
        # Fail early and clearly if the account is not linked here.
        access_token(context.workspace, body.account_id)

        extracted = await extract_meeting_fields(body.query, body.timezone, body.known)
        fields = merge_meet_fields(body.known, extracted)

        missing, question = validate_meet_fields(fields)
        if missing:
            return {"status": "needs_input", "missing": missing,
                    "question": question, "known": fields}

        proposal = meeting_proposal(fields, body.timezone)
        if not body.confirm:
            return {"status": "confirm", "confirmation_required": True,
                    "action": "schedule_teams_meeting", "proposal": proposal,
                    "known": fields}

        created = graph(context.workspace, body.account_id, "POST", "/me/events",
                        json=event_payload(CalendarEventRequest(
                            account_id=body.account_id, summary=proposal["summary"],
                            description=proposal["description"], start=proposal["start"],
                            end=proposal["end"], timezone=body.timezone,
                            attendees=proposal["attendees"],
                            add_online_meeting=True, confirm=True,
                        )))
        event = shape_event(created)
        return {"status": "created", "created": True, "event": event,
                "meet_link": event.get("meet_link", ""), "proposal": proposal}

    @app.post("/api/microsoft/tasks/{project_id}/{task_id}/calendar")
    async def microsoft_task_to_calendar(
        project_id: str, task_id: str, body: CalendarEventRequest,
        context=Depends(require_account),
    ) -> dict[str, Any]:
        project_tasks = context.workspace.load_tasks().get(project_id, [])
        task = next((item for item in project_tasks if str(item.get("id")) == task_id), None)
        if not task:
            raise HTTPException(404, "Task not found")
        body.summary = body.summary or str(task.get("name") or task.get("title") or "Project task")
        body.description = body.description or str(task.get("description") or "")
        return await microsoft_calendar_create(body, context)

    return {
        "configured": configured(),
        "account_store": account_store,
        "scopes": MICROSOFT_SCOPES,
        "authority": authority,
    }


__all__ = ["MICROSOFT_SCOPES", "register_microsoft_workspace_routes"]
