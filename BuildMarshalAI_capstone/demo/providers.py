"""Simulated Google Workspace and Microsoft 365, for the demonstration only.

The real integrations need OAuth applications, consented accounts and live
tokens, none of which belong in a walkthrough. These routes answer with the same
shapes the real ones do, from a fixed set of files, messages and events, so the
Drive indexing, mail composition and calendar features can be shown end to end
without anybody signing in to anything.

**Nothing here talks to Google or Microsoft.** Every account, file, message and
meeting link below is invented. A reply that would normally come from a model is
written out in full instead. The routes say so themselves: each response carries
`"simulated": True`, and the demonstration deck says so on the slide.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from fastapi import Depends, HTTPException, Request

BN = "৳"


def _day(offset: int, hour: int = 10, minute: int = 0) -> str:
    moment = datetime.combine(date.today() + timedelta(days=offset),
                              datetime.min.time()).replace(hour=hour, minute=minute)
    return moment.isoformat()


ACCOUNTS: dict[str, list[dict[str, Any]]] = {
    "google": [{
        "id": "gws-rafiqul", "email": "rafiqul.islam@purbachalcon.example",
        "name": "Md. Rafiqul Islam", "picture": "",
        "scopes": ["drive.readonly", "gmail.readonly", "gmail.compose", "calendar.events"],
        "connected_at": "2026-02-11T09:20:00+00:00",
    }],
    "microsoft": [{
        "id": "m365-rafiqul", "email": "rafiqul.islam@purbachalcon.example",
        "name": "Md. Rafiqul Islam", "picture": "",
        "scopes": ["Files.Read", "Mail.Read", "Mail.Send", "Calendars.ReadWrite"],
        "connected_at": "2026-02-11T09:34:00+00:00",
    }],
}

DRIVE_FILES: dict[str, list[dict[str, Any]]] = {
    "google": [
        {"id": "gd-01", "name": "PVH-2026 Project Files",
         "mimeType": "application/vnd.google-apps.folder", "is_folder": True,
         "modifiedTime": _day(-42), "webViewLink": ""},
        {"id": "gd-02", "name": "RAJUK Approved Drawings.pdf",
         "mimeType": "application/pdf", "is_folder": False,
         "modifiedTime": _day(-34), "webViewLink": "https://drive.example/gd-02"},
        {"id": "gd-03", "name": "Soil Test Report - Uttara Sector 11.pdf",
         "mimeType": "application/pdf", "is_folder": False,
         "modifiedTime": _day(-198), "webViewLink": "https://drive.example/gd-03"},
        {"id": "gd-04", "name": "Monthly Progress - August 2026.xlsx",
         "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "is_folder": False, "modifiedTime": _day(-19), "webViewLink": "https://drive.example/gd-04"},
        {"id": "gd-05", "name": "Fire Service NOC Application.pdf",
         "mimeType": "application/pdf", "is_folder": False,
         "modifiedTime": _day(-27), "webViewLink": "https://drive.example/gd-05"},
        {"id": "gd-06", "name": "Site Photos - Level 3 Slab Casting",
         "mimeType": "application/vnd.google-apps.folder", "is_folder": True,
         "modifiedTime": _day(-4), "webViewLink": ""},
        {"id": "gd-07", "name": "Glazing Sample Panel - Submittal Rev B.pdf",
         "mimeType": "application/pdf", "is_folder": False,
         "modifiedTime": _day(-15), "webViewLink": "https://drive.example/gd-07"},
    ],
    "microsoft": [
        {"id": "od-01", "name": "PVH-2026 Contract Documents",
         "mimeType": "application/vnd.google-apps.folder", "is_folder": True,
         "modifiedTime": _day(-220), "webViewLink": ""},
        {"id": "od-02", "name": "Signed Contract - PVH-2026.pdf",
         "mimeType": "application/pdf", "is_folder": False,
         "modifiedTime": _day(-226), "webViewLink": "https://onedrive.example/od-02"},
        {"id": "od-03", "name": "Bill of Quantities Rev C.xlsx",
         "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "is_folder": False, "modifiedTime": _day(-31), "webViewLink": "https://onedrive.example/od-03"},
        {"id": "od-04", "name": "Insurance and Bank Guarantee.pdf",
         "mimeType": "application/pdf", "is_folder": False,
         "modifiedTime": _day(-210), "webViewLink": "https://onedrive.example/od-04"},
        {"id": "od-05", "name": "Consultant Meeting Minutes 12.docx",
         "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "is_folder": False, "modifiedTime": _day(-8), "webViewLink": "https://onedrive.example/od-05"},
    ],
}

MESSAGES: dict[str, list[dict[str, Any]]] = {
    "google": [
        {"id": "gm-01",
         "subject": "Glazing sample panel - approval needed",
         "from": "Imtiaz Rahman <imtiaz.rahman@sthapatyasangsad.example>",
         "date": _day(-11, 11, 20)[:16].replace("T", " "),
         "snippet": "The sample panel has still not been erected on site. The 12-week "
                    "lead time starts only after written approval."},
        {"id": "gm-02",
         "subject": "Level 3 slab casting - cube test results",
         "from": "Kamrul Hasan <kamrul.hasan@bhittieng.example>",
         "date": _day(-6, 16, 5)[:16].replace("T", " "),
         "snippet": "7-day results attached. All three cylinders above 2,450 psi, so the "
                    "28-day results should comfortably exceed the specified grade."},
        {"id": "gm-03",
         "subject": "Lift letter of credit - urgent",
         "from": "Rumana Parveen <rumana.parveen@hisabcons.example>",
         "date": _day(-3, 9, 45)[:16].replace("T", " "),
         "snippet": "16-week import lead time against a March 2027 need date - the "
                    "order-by date has already passed."},
        {"id": "gm-04",
         "subject": "Weekly site meeting - minutes",
         "from": "Nusrat Jahan <nusrat.jahan@purbachalcon.example>",
         "date": _day(-2, 18, 10)[:16].replace("T", " "),
         "snippet": "Minutes of the weekly site meeting. Level 3 casting is delayed; work "
                    "stopped for 2 days because of monsoon rain."},
    ],
    "microsoft": [
        {"id": "mm-01",
         "subject": "RAJUK occupancy certificate - application timeline",
         "from": "Dr. Anisur Rahman <anisur.rahman@meghnahealth.example>",
         "date": _day(-9, 14, 0)[:16].replace("T", " "),
         "snippet": "The application must be submitted 8 weeks before handover. Please "
                    "confirm the document list."},
        {"id": "mm-02",
         "subject": "Chiller units - factory acceptance test date",
         "from": "Surma Air Systems <orders@surmaair.example>",
         "date": _day(-5, 12, 30)[:16].replace("T", " "),
         "snippet": "Two 400TR chillers ready for FAT. Please confirm the inspection date."},
        {"id": "mm-03",
         "subject": "Interim payment certificate - IPC-08",
         "from": "Rumana Parveen <rumana.parveen@hisabcons.example>",
         "date": _day(-1, 17, 15)[:16].replace("T", " "),
         "snippet": f"Interim payment certificate 08 - {BN}4,18,60,000 gross, 10% "
                    f"retention deducted."},
    ],
}


def _event(event_id: str, summary: str, offset: int, hour: int,
           minutes: int = 60, link: str = "", where: str = "") -> dict[str, Any]:
    start = datetime.fromisoformat(_day(offset, hour))
    end = start + timedelta(minutes=minutes)
    return {
        "id": event_id, "summary": summary,
        "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()},
        "location": where, "description": "", "hangoutLink": link,
        "onlineMeetingUrl": link, "htmlLink": f"https://calendar.example/{event_id}",
    }


def events_for(provider: str) -> list[dict[str, Any]]:
    if provider == "google":
        return [
            _event("gcal-01", "Weekly site meeting",
                   1, 10, 90, "https://meet.example/pvh-weekly", "Site office, Uttara"),
            _event("gcal-02", "Glazing sample review",
                   3, 15, 60, "https://meet.example/pvh-glazing"),
            _event("gcal-03", "Level 4 pour planning", 7, 11, 60, ""),
            _event("gcal-04", "Monthly progress review",
                   11, 14, 120, "https://meet.example/pvh-monthly"),
        ]
    return [
        _event("mcal-01", "IPC-08 valuation review",
               2, 12, 60, "https://teams.example/pvh-ipc08"),
        _event("mcal-02", "Fire Service inspection",
               6, 10, 180, "", "Site, Sector 11"),
        _event("mcal-03", "Chiller factory acceptance test - witness",
               9, 16, 90, "https://teams.example/pvh-fat"),
    ]


#: What the assistant writes when asked to compose an email. A real deployment
#: generates this; the demonstration backend has no model, so it is written out.
DRAFTS = {
    "glazing": {
        "subject": "Glazing sample panel approval - urgent",
        "body": (
            "Dear Sir,\n\n"
            "The aluminium glazing sample panel is still awaiting approval. Under clause "
            "3.2 of the tender specification, manufacture takes 12 weeks from written "
            "approval of the panel.\n\n"
            "This task is currently Blocked and 15 days past its planned date, and the "
            "envelope phase cannot start behind it. Could we please review the panel at "
            "the site meeting and issue approval in writing?\n\n"
            "Regards,\nMd. Rafiqul Islam\nProject Director"),
    },
    "default": {
        "subject": "Project progress update",
        "body": (
            "Dear Sir,\n\n"
            "An update on the Padma View Hospital Extension:\n\n"
            "- Level 1 and Level 2 slab casting complete\n"
            "- Level 3 casting in progress\n"
            "- Glazing sample approval still blocked\n\n"
            "Full figures are in the attached progress report.\n\n"
            "Regards,\nMd. Rafiqul Islam"),
    },
}


def register_simulated_providers(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register stand-in Google and Microsoft routes on the demonstration app."""
    app = namespace["app"]
    require_account = namespace["require_account"]

    def make(provider: str) -> None:
        mail = "gmail" if provider == "google" else "mail"
        conference = "Google Meet" if provider == "google" else "Teams"
        base = f"/api/{provider}"

        @app.get(f"{base}/config", name=f"{provider}_config")
        async def config() -> dict:
            # The frontend reads "enabled"; "configured" alone leaves the
            # not-configured warning on screen.
            return {"enabled": True, "configured": True, "simulated": True,
                    "client_id": f"simulated-{provider}-client",
                    "redirect_uri": "http://127.0.0.1:8000/oauth-callback.html",
                    "detail": "Simulated for the demonstration; nothing leaves this machine."}

        @app.get(f"{base}/accounts", name=f"{provider}_accounts")
        async def accounts(context=Depends(require_account)) -> dict:
            return {"accounts": ACCOUNTS[provider], "connected": True, "simulated": True}

        @app.delete(f"{base}/accounts/{{account_id}}", name=f"{provider}_disconnect")
        async def disconnect(account_id: str, context=Depends(require_account)) -> dict:
            return {"status": "disconnected", "simulated": True}

        @app.get(f"{base}/drive/files", name=f"{provider}_files")
        async def files(account_id: str = "", q: str = "",
                        context=Depends(require_account)) -> dict:
            found = DRIVE_FILES[provider]
            if q:
                needle = q.casefold()
                found = [row for row in found if needle in row["name"].casefold()]
            return {"files": found, "simulated": True}

        @app.get(f"{base}/{mail}/messages", name=f"{provider}_messages")
        async def messages(account_id: str = "", q: str = "",
                           context=Depends(require_account)) -> dict:
            found = MESSAGES[provider]
            if q:
                needle = q.casefold()
                found = [row for row in found
                         if needle in (row["subject"] + row["from"] + row["snippet"]).casefold()]
            return {"messages": found, "simulated": True}

        @app.get(f"{base}/calendar/events", name=f"{provider}_events")
        async def calendar(account_id: str = "", max_results: int = 50,
                           context=Depends(require_account)) -> dict:
            return {"events": events_for(provider)[:max_results], "simulated": True}

        @app.post(f"{base}/drive/import", name=f"{provider}_import_files")
        async def import_files(request: Request, context=Depends(require_account)) -> dict:
            body = await request.json()
            wanted = list(body.get("file_ids") or body.get("files") or [])
            names = {row["id"]: row["name"] for row in DRIVE_FILES[provider]}
            indexed = _index_stubs(context, [names.get(fid, fid) for fid in wanted],
                                   body.get("project_id", ""), provider)
            return {"status": "indexed", "imported": len(indexed),
                    "documents": indexed, "simulated": True}

        @app.post(f"{base}/{mail}/import", name=f"{provider}_import_mail")
        async def import_mail(request: Request, context=Depends(require_account)) -> dict:
            body = await request.json()
            wanted = list(body.get("message_ids") or body.get("messages") or [])
            subjects = {row["id"]: row["subject"] for row in MESSAGES[provider]}
            indexed = _index_stubs(context, [subjects.get(mid, mid) for mid in wanted],
                                   body.get("project_id", ""), provider, suffix=".eml")
            return {"status": "indexed", "imported": len(indexed),
                    "documents": indexed, "simulated": True}

        @app.post(f"{base}/{mail}/generate", name=f"{provider}_generate")
        async def generate(request: Request, context=Depends(require_account)) -> dict:
            body = await request.json()
            instruction = str(body.get("instruction", "")).casefold()
            key = "glazing" if "glaz" in instruction else "default"
            return {**DRAFTS[key], "simulated": True}

        @app.post(f"{base}/{mail}/draft", name=f"{provider}_draft")
        async def draft(request: Request, context=Depends(require_account)) -> dict:
            body = await request.json()
            return {"status": "draft_saved", "id": uuid.uuid4().hex[:12],
                    "subject": body.get("subject", ""), "simulated": True}

        @app.post(f"{base}/{mail}/send", name=f"{provider}_send")
        async def send(request: Request, context=Depends(require_account)) -> dict:
            body = await request.json()
            if not body.get("confirm"):
                raise HTTPException(400, "Sending needs an explicit confirmation")
            return {"status": "sent", "id": uuid.uuid4().hex[:12],
                    "to": body.get("to", ""), "subject": body.get("subject", ""),
                    "simulated": True}

        @app.post(f"{base}/calendar/events", name=f"{provider}_create_event")
        async def create_event(request: Request, context=Depends(require_account)) -> dict:
            body = await request.json()
            link = (f"https://meet.example/{uuid.uuid4().hex[:10]}" if provider == "google"
                    else f"https://teams.example/{uuid.uuid4().hex[:10]}")
            return {"id": uuid.uuid4().hex[:12], "summary": body.get("summary", ""),
                    "start": {"dateTime": body.get("start")},
                    "end": {"dateTime": body.get("end")},
                    "meet_link": link, "hangoutLink": link, "onlineMeetingUrl": link,
                    "htmlLink": "https://calendar.example/new", "simulated": True}

        @app.patch(f"{base}/calendar/events/{{event_id}}", name=f"{provider}_patch_event")
        async def patch_event(event_id: str, request: Request,
                              context=Depends(require_account)) -> dict:
            body = await request.json()
            return {"id": event_id, **body, "status": "updated", "simulated": True}

        @app.get(f"{base}/calendar/events/{{event_id}}", name=f"{provider}_get_event")
        async def get_event(event_id: str, context=Depends(require_account)) -> dict:
            found = next((row for row in events_for(provider) if row["id"] == event_id), None)
            if not found:
                raise HTTPException(404, "Event not found")
            return found

        @app.post(f"{base}/assistant/interpret", name=f"{provider}_interpret")
        async def interpret(request: Request, context=Depends(require_account)) -> dict:
            body = await request.json()
            return {"supported": True, "simulated": True,
                    "proposal": _read_event(str(body.get("query", "")), conference)}

        meeting_path = "meet/schedule" if provider == "google" else "meeting/schedule"

        @app.post(f"{base}/{meeting_path}", name=f"{provider}_schedule_meeting")
        async def schedule(request: Request, context=Depends(require_account)) -> dict:
            """One turn of the conversational scheduler.

            The statuses and the proposal shape mirror the real route exactly:
            the frontend formats `proposal` on both `confirm` and `created`, and
            invents nothing of its own.
            """
            body = await request.json()
            timezone = str(body.get("timezone") or "Asia/Dhaka")
            known = dict(body.get("known") or {})
            read = _read_event(str(body.get("query", "")), conference)
            fields = {**read, **{k: v for k, v in known.items() if v}}

            missing = [name for name in ("summary", "start") if not fields.get(name)]
            if missing:
                question = ("What should I call the meeting?" if missing[0] == "summary"
                            else "What date and time should it start? "
                                 "For example \"next Tuesday at 2pm\".")
                return {"status": "needs_input", "missing": missing,
                        "question": question, "known": fields, "simulated": True}

            start_at = datetime.fromisoformat(fields["start"])
            duration = int(fields.get("duration_minutes") or 60)
            proposal = {
                "summary": fields["summary"],
                "description": fields.get("description", ""),
                "start": start_at.isoformat(),
                "end": (start_at + timedelta(minutes=duration)).isoformat(),
                "duration_minutes": duration,
                "attendees": list(fields.get("attendees", [])),
                "timezone": timezone,
            }

            if not body.get("confirm"):
                return {"status": "confirm", "confirmation_required": True,
                        "action": f"schedule_{provider}_meeting",
                        "proposal": proposal, "known": fields, "simulated": True}

            link = (f"https://meet.example/{uuid.uuid4().hex[:10]}" if provider == "google"
                    else f"https://teams.example/{uuid.uuid4().hex[:10]}")
            return {
                "status": "created", "created": True,
                "meet_link": link, "meet_unavailable": False,
                "proposal": proposal,
                "event": {
                    "id": uuid.uuid4().hex[:12], "summary": proposal["summary"],
                    "start": proposal["start"], "end": proposal["end"],
                    "html_link": "https://calendar.example/new",
                    "attendees": proposal["attendees"],
                },
                "simulated": True,
            }

        @app.post(f"{base}/oauth/code", name=f"{provider}_oauth_code")
        async def oauth_code(request: Request, context=Depends(require_account)) -> dict:
            return {"status": "connected", "account": ACCOUNTS[provider][0], "simulated": True}

    for provider in ("google", "microsoft"):
        make(provider)
    return {"simulated": True, "providers": ["google", "microsoft"]}


def _index_stubs(context: Any, names: list[str], project_id: str,
                 provider: str, suffix: str = "") -> list[dict[str, Any]]:
    """Record an imported file as an indexed document, without indexing it.

    The real import renders and embeds every page. Here the metadata row is
    written so the Documents page and the storage panel show the import having
    happened, and the row says where it came from.
    """
    workspace = context.workspace
    meta = workspace.load_metadata()
    meta.setdefault("documents", {})
    made: list[dict[str, Any]] = []
    for name in names:
        doc_id = uuid.uuid4().hex[:12]
        record = {
            "id": doc_id, "name": f"{name}{suffix}", "project_id": project_id or None,
            "source_type": f"{provider}_import", "status": "indexed", "page_count": 1,
            "size": 148_000, "digest": uuid.uuid4().hex,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "accessed_at": datetime.now(timezone.utc).isoformat(),
            "pages": [], "imported_from": provider, "simulated": True,
        }
        meta["documents"][doc_id] = record
        made.append({"id": doc_id, "name": record["name"]})
    workspace.save_metadata(meta)
    return made


def _read_event(query: str, conference: str) -> dict[str, Any]:
    """A stand-in for the model's reading of a meeting request."""
    import re

    text = str(query or "")
    lowered = text.casefold()

    start = datetime.combine(date.today() + timedelta(days=1),
                             datetime.min.time()).replace(hour=10)
    if "today" in lowered:
        start = start - timedelta(days=1)
    day_match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", lowered)
    if day_match:
        hour = int(day_match.group(1)) % 12 + (12 if day_match.group(2) == "pm" else 0)
        start = start.replace(hour=hour)

    summary = ""
    quoted = re.search(r"[\"“']([^\"”']{3,70})[\"”']", text)
    named = re.search(r"\b(?:about|regarding|on|for|titled|called)\s+([^,.]{3,60})", text, re.I)
    if quoted:
        summary = quoted.group(1).strip()
    elif named:
        summary = named.group(1).strip()
    elif "site" in lowered:
        summary = "Site meeting"

    attendees = re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    return {"summary": summary, "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
            "duration_minutes": 60,
            "attendees": attendees, "description": "",
            "conference": conference}
