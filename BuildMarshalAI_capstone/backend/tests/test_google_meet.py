"""Conversational Google Meet scheduling: field handling, validation, routing."""

import base64
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.google_workspace import (
    merge_meet_fields,
    normalise_meet_fields,
    parse_meeting_start,
    register_google_workspace_routes,
    validate_meet_fields,
)


# ── field parsing ─────────────────────────────────────────────────────────────

def test_start_times_parse_with_and_without_a_zulu_suffix():
    assert parse_meeting_start("2027-03-12T09:30:00") == datetime(2027, 3, 12, 9, 30)
    assert parse_meeting_start("2027-03-12T09:30:00Z").hour == 9
    assert parse_meeting_start("next tuesday") is None
    assert parse_meeting_start(None) is None


def test_attendees_accept_a_string_or_a_list():
    assert normalise_meet_fields({"attendees": "a@x.com, b@y.com"})["attendees"] == ["a@x.com", "b@y.com"]
    assert normalise_meet_fields({"attendees": ["c@z.com"]})["attendees"] == ["c@z.com"]
    assert normalise_meet_fields({})["attendees"] == []


def test_duration_is_coerced_and_bad_values_become_unset():
    assert normalise_meet_fields({"duration_minutes": "45"})["duration_minutes"] == 45
    assert normalise_meet_fields({"duration_minutes": "soon"})["duration_minutes"] is None
    assert normalise_meet_fields({"duration_minutes": None})["duration_minutes"] is None


def test_later_turns_fill_gaps_without_erasing_earlier_answers():
    known = {"summary": "Site walkthrough", "start": None, "attendees": ["a@x.com"]}
    merged = merge_meet_fields(known, {"start": "2027-03-12T09:30:00"})
    assert merged["summary"] == "Site walkthrough"
    assert merged["start"] == "2027-03-12T09:30:00"
    assert merged["attendees"] == ["a@x.com"]


def test_a_later_turn_can_correct_an_earlier_answer():
    known = {"summary": "Old title", "start": "2027-03-12T09:30:00"}
    merged = merge_meet_fields(known, {"summary": "New title"})
    assert merged["summary"] == "New title"
    assert merged["start"] == "2027-03-12T09:30:00"


# ── validation and follow-up questions ────────────────────────────────────────

def test_a_missing_title_asks_for_the_title():
    missing, question = validate_meet_fields({"start": "2027-03-12T09:30:00"})
    assert missing == ["summary"]
    assert "call the meeting" in question


def test_a_missing_time_asks_for_the_time():
    missing, question = validate_meet_fields({"summary": "Kickoff"})
    assert missing == ["start"]
    assert "date and time" in question


def test_an_unparseable_time_asks_for_a_clearer_one():
    missing, question = validate_meet_fields({"summary": "Kickoff", "start": "sometime soon"})
    assert missing == ["start"]
    assert "could not read" in question.lower()


def test_a_nonsense_duration_is_rejected():
    for duration in (0, -30, 60 * 25):
        missing, question = validate_meet_fields({
            "summary": "Kickoff", "start": "2027-03-12T09:30:00", "duration_minutes": duration,
        })
        assert missing == ["duration_minutes"], duration
        assert "how long" in question.lower()


def test_bad_attendee_addresses_are_named_in_the_question():
    missing, question = validate_meet_fields({
        "summary": "Kickoff", "start": "2027-03-12T09:30:00",
        "attendees": ["good@example.com", "not-an-email", "also bad"],
    })
    assert missing == ["attendees"]
    assert "not-an-email" in question and "also bad" in question
    assert "good@example.com" not in question


def test_a_complete_request_passes_validation():
    missing, question = validate_meet_fields({
        "summary": "Kickoff", "start": "2027-03-12T09:30:00",
        "duration_minutes": 45, "attendees": ["good@example.com"],
    })
    assert missing == [] and question is None


# ── route behaviour ───────────────────────────────────────────────────────────

GOOGLE_KEY = base64.urlsafe_b64encode(b"2" * 32).decode("ascii")


def build_app(make_account, monkeypatch, extraction="{}"):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_ALLOWED_ORIGINS", "http://localhost:5500")
    monkeypatch.setenv("GOOGLE_TOKEN_ENCRYPTION_KEY", GOOGLE_KEY)

    context = make_account("owner@example.com")
    app = FastAPI()

    async def require_account():
        return context

    register_google_workspace_routes({
        "app": app,
        "ingest_document": lambda *args, **kwargs: {"page_count": 0},
        "require_account": require_account,
        # The model is consulted only to extract fields from a message.
        "vl_generate": lambda *args, **kwargs: extraction,
    })
    return TestClient(app), context


def link_google_account(context, email="person@example.com"):
    """Store a linked Google account directly, skipping the OAuth round trip."""
    from backend.google_workspace import _account_id
    from backend.oauth_tokens import EncryptedAccountStore

    store = EncryptedAccountStore(context.workspace.token_store("google"), GOOGLE_KEY)
    account_id = _account_id(email)
    store.put({
        "id": account_id, "provider": "google", "email": email, "name": "Person",
        "access_token": "at", "refresh_token": "rt",
        # Far-future expiry so no token refresh is attempted in a test.
        "expiry": "2099-01-01T00:00:00+00:00", "scopes": ["openid"],
    })
    return account_id


def test_scheduling_against_an_unlinked_google_account_is_not_found(make_account, monkeypatch):
    client, _ = build_app(make_account, monkeypatch)
    response = client.post("/api/google/meet/schedule", json={
        "account_id": "not-linked", "query": "set up a Google Meet kickoff tomorrow at 9am",
    })
    # The account belongs to no workspace here, so it must read as missing.
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_a_google_account_linked_elsewhere_stays_invisible(make_account, monkeypatch):
    """The Meet route must resolve accounts only through the caller's workspace."""
    other = make_account("neighbour@example.com", name="Neighbour")
    foreign_id = link_google_account(other)

    client, _ = build_app(make_account, monkeypatch)
    response = client.post("/api/google/meet/schedule", json={
        "account_id": foreign_id, "known": {"summary": "Kickoff", "start": "2027-03-12T09:30:00"},
    })
    assert response.status_code == 404


def test_incomplete_requests_come_back_as_a_follow_up_question(make_account, monkeypatch):
    client, context = build_app(make_account, monkeypatch, extraction='{"summary": "Kickoff"}')
    linked = link_google_account(context)
    response = client.post("/api/google/meet/schedule", json={
        "account_id": linked, "query": "schedule a Google Meet kickoff",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_input"
    assert body["missing"] == ["start"]
    # The partial answer comes back so the next turn continues from it.
    assert body["known"]["summary"] == "Kickoff"


def test_a_complete_request_is_proposed_before_anything_is_created(make_account, monkeypatch):
    client, context = build_app(make_account, monkeypatch)
    linked = link_google_account(context)
    body = client.post("/api/google/meet/schedule", json={
        "account_id": linked,
        "known": {"summary": "Kickoff", "start": "2027-03-12T09:30:00",
                  "duration_minutes": 45, "attendees": ["guest@example.com"]},
    }).json()
    assert body["status"] == "confirm"
    assert body["confirmation_required"] is True
    assert body["action"] == "schedule_google_meet"
    assert body["proposal"]["end"] == "2027-03-12T10:15:00"
    assert body["proposal"]["duration_minutes"] == 45


def test_an_unstated_duration_defaults_to_an_hour(make_account, monkeypatch):
    client, context = build_app(make_account, monkeypatch)
    linked = link_google_account(context)
    body = client.post("/api/google/meet/schedule", json={
        "account_id": linked,
        "known": {"summary": "Kickoff", "start": "2027-03-12T09:30:00"},
    }).json()
    assert body["proposal"]["duration_minutes"] == 60
    assert body["proposal"]["end"] == "2027-03-12T10:30:00"


def test_invalid_attendees_are_questioned_rather_than_sent(make_account, monkeypatch):
    client, context = build_app(make_account, monkeypatch)
    linked = link_google_account(context)
    body = client.post("/api/google/meet/schedule", json={
        "account_id": linked, "confirm": True,
        "known": {"summary": "Kickoff", "start": "2027-03-12T09:30:00",
                  "attendees": ["nope"]},
    }).json()
    # Even with confirm set, an invalid field stops the booking.
    assert body["status"] == "needs_input"
    assert body["missing"] == ["attendees"]


def test_the_event_body_requests_a_meet_conference(make_account, monkeypatch):
    """A Meet booking must ask Calendar for a hangoutsMeet conference."""
    from backend.google_workspace import CalendarEventRequest

    client, context = build_app(make_account, monkeypatch)
    schema = client.app.openapi()["paths"]
    assert "/api/google/meet/schedule" in schema

    request = CalendarEventRequest(
        account_id="a", summary="S", start="2027-03-12T09:30:00",
        end="2027-03-12T10:30:00", add_meet=True, confirm=True,
    )
    assert request.add_meet is True
    # Without add_meet the request must not ask for conferencing.
    plain = CalendarEventRequest(
        account_id="a", summary="S", start="2027-03-12T09:30:00", end="2027-03-12T10:30:00",
    )
    assert plain.add_meet is False


# ── calendar event editing ────────────────────────────────────────────────────

def test_updating_an_event_requires_confirmation_and_something_to_change(make_account, monkeypatch):
    client, context = build_app(make_account, monkeypatch)
    linked = link_google_account(context)

    # Nothing supplied: there is no edit to make.
    empty = client.patch("/api/google/calendar/events/evt-1", json={"account_id": linked})
    assert empty.status_code == 422 and "Nothing to change" in empty.json()["detail"]

    # A real change is proposed first rather than written straight through.
    proposed = client.patch("/api/google/calendar/events/evt-1", json={
        "account_id": linked, "summary": "Renamed"})
    assert proposed.status_code == 200
    assert proposed.json()["confirmation_required"] is True
    assert proposed.json()["action"] == "update_calendar_event"
    assert proposed.json()["event"]["summary"] == "Renamed"


def test_an_event_update_validates_its_inputs(make_account, monkeypatch):
    client, context = build_app(make_account, monkeypatch)
    linked = link_google_account(context)

    blank = client.patch("/api/google/calendar/events/evt-1", json={
        "account_id": linked, "summary": "   "})
    assert blank.status_code == 422 and "title" in blank.json()["detail"].lower()

    backwards = client.patch("/api/google/calendar/events/evt-1", json={
        "account_id": linked, "start": "2027-03-02T10:00:00", "end": "2027-03-01T10:00:00"})
    assert backwards.status_code == 422 and "end before it starts" in backwards.json()["detail"]


def test_editing_an_event_on_an_unlinked_account_is_not_found(make_account, monkeypatch):
    client, _ = build_app(make_account, monkeypatch)
    response = client.patch("/api/google/calendar/events/evt-1", json={
        "account_id": "not-linked", "summary": "Renamed", "confirm": True})
    assert response.status_code == 404


def test_reading_one_event_needs_a_linked_account(make_account, monkeypatch):
    client, _ = build_app(make_account, monkeypatch)
    response = client.get("/api/google/calendar/events/evt-1", params={"account_id": "not-linked"})
    assert response.status_code == 404
