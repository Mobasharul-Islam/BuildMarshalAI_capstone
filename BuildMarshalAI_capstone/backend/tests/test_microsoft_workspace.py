"""Microsoft 365 (Graph) integration: helpers, wiring, and account scoping."""

import base64
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.microsoft_workspace import (
    MICROSOFT_SCOPES,
    _addresses,
    _message_body,
    _pkce_pair,
    _plain_text,
    _recipients,
    register_microsoft_workspace_routes,
)
from backend.oauth_tokens import EncryptedAccountStore, account_identifier, safe_name


# ── helpers ───────────────────────────────────────────────────────────────────

def test_recipient_lists_accept_commas_and_semicolons():
    assert _addresses("a@x.com, b@y.com; c@z.com") == [
        {"emailAddress": {"address": "a@x.com"}},
        {"emailAddress": {"address": "b@y.com"}},
        {"emailAddress": {"address": "c@z.com"}},
    ]
    assert _addresses("   ") == []


def test_html_mail_bodies_are_reduced_to_readable_text():
    html = "<style>p{color:red}</style><p>Pour is <b>Friday</b>.</p><p>Bring the &amp; forms.</p>"
    assert _plain_text(html) == "Pour is Friday .\n\nBring the & forms."


def test_message_body_prefers_content_and_falls_back_to_preview():
    assert _message_body({"body": {"contentType": "html", "content": "<p>Hello</p>"}}) == "Hello"
    assert _message_body({"body": {"contentType": "text", "content": " Plain "}}) == "Plain"
    assert _message_body({"body": {"contentType": "text", "content": ""},
                          "bodyPreview": "Preview only"}) == "Preview only"


def test_recipients_are_flattened_to_addresses():
    message = {"toRecipients": [
        {"emailAddress": {"address": "one@x.com"}},
        {"emailAddress": {"address": "two@x.com"}},
    ]}
    assert _recipients(message, "toRecipients") == "one@x.com, two@x.com"
    assert _recipients({}, "toRecipients") == ""


def test_pkce_challenge_is_the_s256_of_the_verifier():
    verifier, challenge = _pkce_pair()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    assert challenge == expected
    assert "=" not in verifier and "=" not in challenge
    # A second call must not repeat the verifier.
    assert _pkce_pair()[0] != verifier


def test_offline_access_is_requested_so_links_survive_the_hour():
    assert "offline_access" in MICROSOFT_SCOPES
    assert {"Files.Read", "Mail.Read", "Mail.Send", "Calendars.ReadWrite"} <= set(MICROSOFT_SCOPES)


# ── route wiring ──────────────────────────────────────────────────────────────

def build_app(make_account, monkeypatch, configured=True):
    if configured:
        monkeypatch.setenv("MICROSOFT_CLIENT_ID", "client-id")
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "client-secret")
        monkeypatch.setenv("MICROSOFT_TENANT_ID", "common")
        monkeypatch.setenv("MICROSOFT_ALLOWED_ORIGINS", "http://localhost:5500")
        monkeypatch.setenv(
            "MICROSOFT_TOKEN_ENCRYPTION_KEY",
            base64.urlsafe_b64encode(b"0" * 32).decode("ascii"),
        )
    else:
        for name in ("MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET",
                     "MICROSOFT_ALLOWED_ORIGINS", "MICROSOFT_TOKEN_ENCRYPTION_KEY",
                     "GOOGLE_TOKEN_ENCRYPTION_KEY", "GOOGLE_ALLOWED_ORIGINS"):
            monkeypatch.delenv(name, raising=False)

    context = make_account("owner@example.com")
    app = FastAPI()

    async def require_account():
        return context

    namespace = {
        "app": app,
        "ingest_document": lambda *args, **kwargs: {"page_count": 0},
        "require_account": require_account,
        "vl_generate": lambda *args, **kwargs: '{"subject": "S", "body": "B"}',
    }
    service = register_microsoft_workspace_routes(namespace)
    return TestClient(app), context, service


def test_registered_routes_cover_files_mail_and_calendar(make_account, monkeypatch):
    client, _, service = build_app(make_account, monkeypatch)
    paths = client.app.openapi()["paths"]
    for path in (
        "/api/microsoft/config",
        "/api/microsoft/oauth/start",
        "/api/microsoft/oauth/code",
        "/api/microsoft/accounts",
        "/api/microsoft/drive/files",
        "/api/microsoft/drive/import",
        "/api/microsoft/mail/messages",
        "/api/microsoft/mail/import",
        "/api/microsoft/mail/send",
        "/api/microsoft/calendar/events",
        "/api/microsoft/assistant/interpret",
    ):
        assert path in paths, f"{path} was not registered"
    assert service["configured"] is True


def test_config_reports_disabled_without_credentials(make_account, monkeypatch):
    client, _, service = build_app(make_account, monkeypatch, configured=False)
    assert service["configured"] is False
    body = client.get("/api/microsoft/config").json()
    assert body["enabled"] is False
    # An unconfigured backend lists nothing rather than failing the page.
    assert client.get("/api/microsoft/accounts").json() == {"accounts": []}


def test_oauth_start_rejects_unlisted_redirect_origins(make_account, monkeypatch):
    client, _, _ = build_app(make_account, monkeypatch)
    denied = client.post("/api/microsoft/oauth/start",
                         json={"redirect_uri": "http://evil.example/oauth-callback.html"})
    assert denied.status_code == 403

    allowed = client.post("/api/microsoft/oauth/start",
                          json={"redirect_uri": "http://localhost:5500/oauth-callback.html"})
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["state"]
    assert "code_challenge=" in payload["authorize_url"]
    assert "code_challenge_method=S256" in payload["authorize_url"]
    assert "offline_access" in payload["authorize_url"]
    # The client secret must never be handed to the browser.
    assert "client-secret" not in payload["authorize_url"]


def test_oauth_code_requires_a_state_this_backend_issued(make_account, monkeypatch):
    client, _, _ = build_app(make_account, monkeypatch)
    response = client.post("/api/microsoft/oauth/code", json={
        "code": "abc", "state": "never-issued",
        "redirect_uri": "http://localhost:5500/oauth-callback.html",
    })
    assert response.status_code == 400
    assert "expired" in response.json()["detail"].lower()


def test_oauth_state_is_single_use(make_account, monkeypatch):
    client, _, _ = build_app(make_account, monkeypatch)
    state = client.post("/api/microsoft/oauth/start", json={
        "redirect_uri": "http://localhost:5500/oauth-callback.html",
    }).json()["state"]

    body = {"code": "abc", "state": state,
            "redirect_uri": "http://localhost:5500/oauth-callback.html"}
    # The first attempt consumes the state and then fails at the token endpoint
    # (no network here); the second must be refused as replay.
    try:
        client.post("/api/microsoft/oauth/code", json=body)
    except Exception:
        pass
    replay = client.post("/api/microsoft/oauth/code", json=body)
    assert replay.status_code == 400


def test_unknown_microsoft_account_is_not_found(make_account, monkeypatch):
    client, _, _ = build_app(make_account, monkeypatch)
    assert client.delete("/api/microsoft/accounts/does-not-exist").status_code == 404


# ── per-account token isolation ───────────────────────────────────────────────

def test_linked_accounts_are_stored_per_buildmarshal_account(make_account):
    key = base64.urlsafe_b64encode(b"1" * 32).decode("ascii")
    first = make_account("first@example.com").workspace
    second = make_account("second@example.com", name="Second").workspace

    store_one = EncryptedAccountStore(first.token_store("microsoft"), key)
    store_two = EncryptedAccountStore(second.token_store("microsoft"), key)

    account_id = account_identifier("person@contoso.com")
    store_one.put({
        "id": account_id, "provider": "microsoft", "email": "person@contoso.com",
        "name": "Person", "refresh_token": "super-secret", "access_token": "at",
    })

    assert [a["email"] for a in store_one.list_public()] == ["person@contoso.com"]
    assert store_two.list_public() == []
    with pytest.raises(KeyError):
        store_two.get(account_id)

    # Tokens are neither returned by list_public nor readable in the database.
    assert "refresh_token" not in store_one.list_public()[0]
    assert b"super-secret" not in first.token_store("microsoft").read()


def test_external_file_names_are_made_safe():
    assert safe_name("../../Tender: Final?.docx") == "Tender_ Final_.docx"
    assert safe_name("") == "external-document"


# ── calendar event editing ────────────────────────────────────────────────────

def test_outlook_event_updates_are_gated_and_validated(make_account, monkeypatch):
    client, _, _ = build_app(make_account, monkeypatch)

    empty = client.patch("/api/microsoft/calendar/events/evt-1", json={"account_id": "a"})
    assert empty.status_code == 422 and "Nothing to change" in empty.json()["detail"]

    blank = client.patch("/api/microsoft/calendar/events/evt-1", json={
        "account_id": "a", "summary": " "})
    assert blank.status_code == 422

    backwards = client.patch("/api/microsoft/calendar/events/evt-1", json={
        "account_id": "a", "start": "2027-03-02T10:00:00", "end": "2027-03-01T10:00:00"})
    assert backwards.status_code == 422

    proposed = client.patch("/api/microsoft/calendar/events/evt-1", json={
        "account_id": "a", "summary": "Renamed", "location": "Site office"})
    assert proposed.status_code == 200
    body = proposed.json()
    assert body["confirmation_required"] is True
    # Graph field names, not the Google ones the frontend sends.
    assert body["event"]["subject"] == "Renamed"
    assert body["event"]["location"]["displayName"] == "Site office"


def test_updating_an_outlook_event_on_an_unknown_account_is_not_found(make_account, monkeypatch):
    client, _, _ = build_app(make_account, monkeypatch)
    response = client.patch("/api/microsoft/calendar/events/evt-1", json={
        "account_id": "never-linked", "summary": "Renamed", "confirm": True})
    assert response.status_code == 404


# ── Teams meetings ────────────────────────────────────────────────────────────

def test_creating_an_event_can_ask_graph_for_a_teams_meeting(make_account, monkeypatch):
    client, _, _ = build_app(make_account, monkeypatch)
    proposed = client.post("/api/microsoft/calendar/events", json={
        "account_id": "a", "summary": "Kickoff", "start": "2027-03-12T09:30:00",
        "end": "2027-03-12T10:30:00", "add_online_meeting": True,
    }).json()
    assert proposed["confirmation_required"] is True
    assert proposed["event"]["add_online_meeting"] is True


def test_an_event_without_the_flag_stays_a_plain_appointment(make_account, monkeypatch):
    client, _, _ = build_app(make_account, monkeypatch)
    proposed = client.post("/api/microsoft/calendar/events", json={
        "account_id": "a", "summary": "Kickoff", "start": "2027-03-12T09:30:00",
        "end": "2027-03-12T10:30:00",
    }).json()
    assert proposed["event"]["add_online_meeting"] is False


def test_the_teams_scheduler_is_registered_and_scoped_to_the_caller(make_account, monkeypatch):
    client, _, _ = build_app(make_account, monkeypatch)
    assert "/api/microsoft/meeting/schedule" in client.app.openapi()["paths"]
    # An account this workspace has not linked must read as missing.
    response = client.post("/api/microsoft/meeting/schedule", json={
        "account_id": "not-linked",
        "known": {"summary": "Kickoff", "start": "2027-03-12T09:30:00"},
    })
    assert response.status_code == 404


# ── Graph query encoding ──────────────────────────────────────────────────────

def test_a_utc_offset_survives_the_query_string():
    """A raw "+" reads back as a space, which Graph rejects as an invalid date."""
    from urllib.parse import parse_qs

    from backend.microsoft_workspace import graph_query

    stamp = "2025-09-01T17:40:49.648633+00:00"
    encoded = graph_query({"startDateTime": stamp})
    assert "%2B" in encoded, "the offset's + must be escaped, not sent literally"
    assert parse_qs(encoded)["startDateTime"][0] == stamp


def test_search_terms_with_url_syntax_are_escaped():
    from urllib.parse import parse_qs

    from backend.microsoft_workspace import graph_query

    encoded = graph_query({"$search": '"pour + forms & rebar"'})
    # An unescaped & would split the term into a second query parameter.
    assert len(parse_qs(encoded)) == 1
    assert parse_qs(encoded)["$search"][0] == '"pour + forms & rebar"'


# ── Teams join links ──────────────────────────────────────────────────────────

def test_a_work_account_join_url_is_read_from_the_online_meeting():
    from backend.microsoft_workspace import teams_join_url

    join = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_ABC%40thread.v2/0"
    assert teams_join_url({"onlineMeeting": {"joinUrl": join}}) == join


def test_the_deprecated_online_meeting_url_is_still_honoured():
    from backend.microsoft_workspace import teams_join_url

    join = "https://teams.microsoft.com/l/meetup-join/19%3aXYZ"
    assert teams_join_url({"onlineMeetingUrl": join}) == join


def test_a_personal_account_link_in_the_body_is_found():
    """Personal accounts get teams.live.com links, often only in the body."""
    from backend.microsoft_workspace import teams_join_url

    event = {"body": {"content": '<a href="https://teams.live.com/meet/93123?p=AbC">Join</a>'}}
    assert teams_join_url(event) == "https://teams.live.com/meet/93123?p=AbC"


def test_html_entities_in_a_body_link_are_decoded():
    from backend.microsoft_workspace import teams_join_url

    event = {"body": {"content": "Join https://teams.live.com/meet/931?p=A&amp;anon=true"}}
    assert teams_join_url(event) == "https://teams.live.com/meet/931?p=A&anon=true"


def test_prose_punctuation_is_not_part_of_the_link():
    from backend.microsoft_workspace import teams_join_url

    assert teams_join_url({"bodyPreview": "Join at https://teams.live.com/meet/93122."}) \
        == "https://teams.live.com/meet/93122"


def test_the_direct_field_wins_over_the_body():
    from backend.microsoft_workspace import teams_join_url

    event = {
        "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/meetup-join/REAL"},
        "body": {"content": "Old link https://teams.live.com/meet/STALE"},
    }
    assert teams_join_url(event).endswith("REAL")


def test_an_event_with_no_meeting_reports_no_link():
    from backend.microsoft_workspace import teams_join_url

    assert teams_join_url({"body": {"content": "<p>Bring the drawings.</p>"}}) == ""
    assert teams_join_url({}) == ""


def test_the_calendar_selection_asks_for_the_fields_the_link_can_hide_in():
    """body and onlineMeetingUrl must be selected or the link cannot be found."""
    import inspect

    from backend import microsoft_workspace

    source = inspect.getsource(microsoft_workspace.register_microsoft_workspace_routes)
    select = source[source.index('select = ("id,subject'):]
    select = select[:select.index(")") + 1]
    for field in ("body", "bodyPreview", "onlineMeeting", "onlineMeetingUrl", "location"):
        assert field in select, f"{field} is not selected from Graph"


# ── Outlook event bodies ──────────────────────────────────────────────────────

TEAMS_BODY = (
    '<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
    '<style><!-- .EmailQuote { margin-left: 1pt; } --></style></head><body>'
    '<div class="PlainText">Bring the level 2 drawings.<br>'
    '....................................................................<br>'
    'Join Teams Meeting<br><br>'
    '<a href="https://teams.live.com/meet/934623249649?p=57XsOU31L5Cm386jcR">'
    'https://teams.live.com/meet/934623249649?p=57XsOU31L5Cm386jcR</a><br>'
    'Meeting ID: 934 623 249 649<br>Passcode: Xt3Xq2<br><br>'
    'If you need a local number, get one here.<br>'
    'Learn More <a href="https://aka.ms/JoinTeamsFreeMeeting">https://aka.ms/JoinTeamsFreeMeeting</a><br>'
    '....................................................................<br>'
    '</div></body></html>'
)


def teams_event():
    return {"body": {"contentType": "html", "content": TEAMS_BODY},
            "location": {"displayName": "Microsoft Teams Meeting"}}


def test_an_html_body_is_rendered_as_text_not_markup():
    """The popover showed a wall of markup where the notes should be."""
    from backend.microsoft_workspace import event_body_text

    text = event_body_text(teams_event())
    assert "<html>" not in text and "<div" not in text and "EmailQuote" not in text
    assert "Bring the level 2 drawings." in text


def test_the_teams_block_is_stripped_leaving_the_organisers_words():
    from backend.microsoft_workspace import event_body_text, strip_meeting_boilerplate

    notes = strip_meeting_boilerplate(event_body_text(teams_event()))
    assert notes == "Bring the level 2 drawings."
    for noise in ("Join Teams Meeting", "Meeting ID", "Passcode", "Learn More", "dial-in"):
        assert noise not in notes, f"{noise} survived the strip"


def test_an_event_with_only_a_teams_block_has_empty_notes():
    from backend.microsoft_workspace import event_body_text, strip_meeting_boilerplate

    body = TEAMS_BODY.replace("Bring the level 2 drawings.<br>", "")
    event = {"body": {"contentType": "html", "content": body}}
    assert strip_meeting_boilerplate(event_body_text(event)) == ""


def test_the_meeting_id_and_passcode_are_lifted_into_their_own_fields():
    from backend.microsoft_workspace import teams_meeting_details

    details = teams_meeting_details(teams_event())
    assert details["meeting_id"] == "934 623 249 649"
    assert details["passcode"] == "Xt3Xq2"
    assert details["join_url"] == "https://teams.live.com/meet/934623249649?p=57XsOU31L5Cm386jcR"


def test_a_plain_text_body_is_left_alone():
    from backend.microsoft_workspace import event_body_text, strip_meeting_boilerplate

    event = {"body": {"contentType": "text", "content": "  Bring the drawings.  "}}
    assert strip_meeting_boilerplate(event_body_text(event)) == "Bring the drawings."


def test_body_preview_stands_in_when_there_is_no_body():
    from backend.microsoft_workspace import event_body_text

    assert event_body_text({"body": {"content": ""}, "bodyPreview": "Preview text"}) == "Preview text"
    assert event_body_text({}) == ""


def test_an_event_without_a_meeting_reports_no_details():
    from backend.microsoft_workspace import teams_meeting_details

    details = teams_meeting_details({"body": {"contentType": "text", "content": "Notes only"}})
    assert details == {"join_url": "", "meeting_id": "", "passcode": ""}
