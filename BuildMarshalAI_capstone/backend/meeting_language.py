"""Turning a chat message into a meeting proposal.

Shared by the Google Meet and Microsoft Teams schedulers so both read a request
the same way and ask the same follow-up questions. Nothing here talks to a
provider: it parses, merges across turns, and validates, and the provider
modules do the booking.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Mapping

from pydantic import BaseModel, Field


class MeetScheduleRequest(BaseModel):
    """One turn of a conversational meeting scheduler.

    ``query`` is what the user just typed. ``known`` carries the fields already
    settled in earlier turns, so a follow-up answer only has to supply what was
    missing.
    """

    account_id: str
    query: str = Field(default="", max_length=4000)
    timezone: str = "UTC"
    known: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MEET_FIELD_QUESTIONS = {
    "summary": "What should I call the meeting?",
    "start": "What date and time should the meeting start? For example \"next Tuesday at 2pm\".",
}


def parse_meeting_start(value: Any) -> datetime | None:
    """Parse an ISO-8601 start time, tolerating a trailing Z."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalise_meet_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the fields the scheduler understands, lightly cleaned."""
    attendees = raw.get("attendees") or []
    if isinstance(attendees, str):
        attendees = re.split(r"[;,\s]+", attendees)
    duration = raw.get("duration_minutes")
    try:
        duration = int(duration) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration = None
    return {
        "summary": (str(raw.get("summary")).strip() if raw.get("summary") else None),
        "start": (str(raw.get("start")).strip() if raw.get("start") else None),
        "duration_minutes": duration,
        "attendees": [str(item).strip() for item in attendees if str(item).strip()],
        "description": (str(raw.get("description")).strip() if raw.get("description") else ""),
    }


def merge_meet_fields(known: Mapping[str, Any], extracted: Mapping[str, Any]) -> dict[str, Any]:
    """Later turns fill gaps and may correct earlier answers."""
    merged = dict(normalise_meet_fields(known))
    for key, value in normalise_meet_fields(extracted).items():
        if key == "attendees":
            if value:
                merged["attendees"] = value
        elif key == "description":
            if value:
                merged["description"] = value
        elif value not in (None, ""):
            merged[key] = value
    return merged


def validate_meet_fields(fields: Mapping[str, Any]) -> tuple[list[str], str | None]:
    """Return the missing/invalid field names and one clear follow-up question."""
    for name in ("summary", "start"):
        if not fields.get(name):
            return [name], MEET_FIELD_QUESTIONS[name]

    start = parse_meeting_start(fields.get("start"))
    if start is None:
        return ["start"], (
            "I could not read that date and time. Could you give it as a day and a clock "
            "time, for example \"12 March at 09:30\"?"
        )

    duration = fields.get("duration_minutes")
    if duration is not None and (duration <= 0 or duration > 24 * 60):
        return ["duration_minutes"], (
            "How long should the meeting run? Give a length between 1 minute and 24 hours."
        )

    invalid = [a for a in fields.get("attendees", []) if not EMAIL_PATTERN.match(a)]
    if invalid:
        return ["attendees"], (
            f"These do not look like email addresses: {', '.join(invalid)}. "
            "Could you give the attendees' full email addresses?"
        )
    return [], None


def meeting_proposal(fields: Mapping[str, Any], timezone: str) -> dict[str, Any]:
    """Build the reviewable proposal for a validated set of fields."""
    start = parse_meeting_start(fields["start"])
    duration = fields.get("duration_minutes") or 60
    return {
        "summary": fields["summary"],
        "description": fields.get("description", ""),
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=duration)).isoformat(),
        "duration_minutes": duration,
        "attendees": list(fields.get("attendees", [])),
        "timezone": timezone,
    }


def extraction_prompt(query: str, timezone: str, known: str, now: str,
                      product: str = "meeting") -> str:
    """The instruction that pulls meeting details out of one chat message."""
    return (
        f"Extract {product} scheduling details from the user's message. "
        "Return JSON only with keys summary, start, duration_minutes, attendees, description. "
        "start must be an ISO-8601 local date-time with no timezone suffix. "
        "attendees is an array: use the email address when the user gives one, and "
        "otherwise copy exactly the word they used to name the person, so it can be "
        "queried back rather than silently dropped. Never invent or complete an "
        "email address. "
        "Use null for anything the user did not state; never invent a title or a time.\n"
        f"Current local time: {now} (user timezone {timezone})\n"
        f"Already known: {known}\n"
        f"User message: {query}"
    )


def parse_extraction(raw: Any) -> dict[str, Any]:
    """Read the model's JSON reply, treating anything unusable as \"nothing new\"."""
    match = re.search(r"\{[\s\S]*\}", str(raw))
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


__all__ = [
    "EMAIL_PATTERN", "MEET_FIELD_QUESTIONS", "MeetScheduleRequest",
    "extraction_prompt", "meeting_proposal", "merge_meet_fields", "parse_extraction",
    "normalise_meet_fields", "parse_meeting_start", "validate_meet_fields",
]
