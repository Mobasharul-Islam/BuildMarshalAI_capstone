"""Ingestion: every format becomes pages, audio becomes its transcript, and the
same bytes are indexed once per scope whichever path they arrive by.

The format functions are tested directly.  ``ingest_document`` and the media
route live in the notebook (they need ColPali), so they are lifted out of the
exported server with ``ast`` and run against a real account workspace with a
stand-in embedder -- the code under test is the code that ships.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import tempfile
import os
import wave
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.testclient import TestClient
from PIL import Image

from backend import ingestion_formats as formats
from backend.external_imports import ExternalImporter
from backend.ingestion_formats import (
    AUDIO_EXTENSIONS, START_VOICE_HINT, TranscriptionError, VoiceServiceUnavailable, file_digest,
    find_duplicate, process_audio, process_docx, process_excel, process_image, process_pdf,
    process_text, split_pages, transcribe_with_voice_service, voice_service_health,
)
from backend.document_links import ORIGIN_LABELS, link_document, set_document_projects

SERVER = Path(__file__).resolve().parents[1] / "run_backend.py"


# -- fixtures ---------------------------------------------------------------------

def make_pdf(path: Path, lines: list[str]) -> Path:
    import fitz

    document = fitz.open()
    for line in lines:
        page = document.new_page()
        page.insert_text((72, 72), line, fontsize=14)
    document.save(path)
    document.close()
    return path


def make_wav(path: Path, seconds: float = 0.5) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * int(8000 * seconds))
    return path


@pytest.fixture
def pages_dir(tmp_path):
    folder = tmp_path / "pages"
    folder.mkdir()
    return folder


# -- formats ----------------------------------------------------------------------

def test_a_pdf_keeps_its_text_layer_and_a_bounded_page_image(tmp_path, pages_dir):
    pdf = make_pdf(tmp_path / "spec.pdf", ["RFI response within 7 working days", "Slabs 3500 psi"])
    pages = process_pdf(pdf, "d1", pages_dir)
    assert [page["page_num"] for page in pages] == [1, 2]
    assert "7 working days" in pages[0]["text_content"]
    assert "3500 psi" in pages[1]["text_content"]
    with Image.open(pages[0]["image_path"]) as image:
        assert max(image.size) <= formats.PAGE_MAX_EDGE


def test_an_image_is_downscaled_not_stored_as_it_is(tmp_path, pages_dir):
    source = tmp_path / "drawing.png"
    Image.new("RGB", (3000, 1500), "white").save(source)
    [page] = process_image(source, "d2", pages_dir)
    with Image.open(page["image_path"]) as image:
        assert image.size == (1024, 512)
    assert page["text_content"] == ""


def test_long_text_is_split_into_drawn_pages_that_keep_every_character(tmp_path, pages_dir):
    body = "".join(f"line {n:04d} of the site diary\n" for n in range(400))
    source = tmp_path / "diary.txt"
    source.write_text(body, encoding="utf-8")
    pages = process_text(source, "d3", pages_dir)
    assert len(pages) == -(-len(body) // formats.TEXT_PAGE_CHARS)
    assert "".join(page["text_content"] for page in pages) == body
    assert all(Path(page["image_path"]).exists() for page in pages)


def test_a_spreadsheet_page_is_a_table_image_plus_its_rows_as_text(tmp_path, pages_dir):
    source = tmp_path / "cost.csv"
    source.write_text("Element,Amount\nPiling,21400000\nLifts,9800000\n", encoding="utf-8")
    [page] = process_excel(source, "d4", pages_dir)
    assert "Piling" in page["text_content"] and "9800000" in page["text_content"]
    assert Path(page["image_path"]).exists()


def test_a_word_file_becomes_text_pages(tmp_path, pages_dir):
    from docx import Document

    source = tmp_path / "si.docx"
    document = Document()
    document.add_paragraph("Site instruction SI-014: relocate the main entrance.")
    document.save(source)
    [page] = process_docx(source, "d5", pages_dir)
    assert "relocate the main entrance" in page["text_content"]
    assert Path(page["image_path"]).exists()


# -- audio ------------------------------------------------------------------------

def test_a_recording_becomes_its_transcript(tmp_path, pages_dir):
    recording = make_wav(tmp_path / "walk.wav")
    heard = []

    def transcribe(path):
        heard.append(path)
        return {"text": "The level two slab pour moves to Thursday.", "language": "en",
                "duration_seconds": 0.5, "model": "openai-whisper-base"}

    pages, info = process_audio(recording, "a1", pages_dir, transcribe)
    assert heard == [recording]
    assert info["status"] == "transcribed" and info["language"] == "en"
    assert "slab pour moves to Thursday" in pages[0]["text_content"]
    assert Path(pages[0]["image_path"]).exists()          # so ColPali can embed it
    # The recording is not copied; the original upload is what plays back.
    assert not any(path.suffix == ".wav" for path in pages_dir.iterdir())


def test_without_a_voice_service_a_recording_says_why_it_is_not_searchable(tmp_path, pages_dir):
    pages, info = process_audio(make_wav(tmp_path / "memo.wav"), "a2", pages_dir, None)
    assert info["status"] == "unavailable"
    assert pages[0]["image_path"] is None
    assert "Not transcribed" in pages[0]["text_content"]


def test_a_refused_recording_keeps_the_services_reason(tmp_path, pages_dir):
    def refuse(_path):
        raise TranscriptionError("Recording is longer than the 60 second limit")

    pages, info = process_audio(make_wav(tmp_path / "long.wav"), "a3", pages_dir, refuse)
    assert info == {"status": "failed", "reason": "Recording is longer than the 60 second limit"}
    assert "60 second limit" in pages[0]["text_content"]


def test_silence_is_reported_as_no_speech(tmp_path, pages_dir):
    pages, info = process_audio(make_wav(tmp_path / "quiet.wav"), "a4", pages_dir,
                                lambda _path: {"text": "  "})
    assert info["status"] == "empty"
    assert "No speech" in pages[0]["text_content"]


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def post(self, url, files=None, headers=None, timeout=None):
        self.calls.append((url, files["file"][0], headers))
        if self.error:
            raise self.error
        return self.response

    def get(self, url, timeout=None):
        self.calls.append((url, None, None))
        if self.error:
            raise self.error
        return self.response


def test_the_local_voice_service_is_called_directly_with_no_tunnel_headers(tmp_path):
    session = FakeSession(FakeResponse(200, {"text": " Pour at 9 ", "language": "en",
                                             "duration_seconds": 1.2, "model": "m"}))
    result = transcribe_with_voice_service(make_wav(tmp_path / "q.wav"), "http://127.0.0.1:8903/",
                                           session=session)
    assert result["text"] == "Pour at 9"
    url, name, headers = session.calls[0]
    assert url == "http://127.0.0.1:8903/api/transcribe" and name == "q.wav"
    assert headers is None          # no ngrok header: nothing between here and the service


def test_a_voice_service_refusal_or_outage_is_a_transcription_error(tmp_path):
    recording = make_wav(tmp_path / "q.wav")
    with pytest.raises(TranscriptionError, match="20 MB"):
        transcribe_with_voice_service(recording, "http://voice.test", session=FakeSession(
            FakeResponse(413, {"detail": "Audio file exceeds the 20 MB limit"})))
    with pytest.raises(VoiceServiceUnavailable, match="not running"):
        transcribe_with_voice_service(recording, "http://voice.test",
                                      session=FakeSession(error=ConnectionError("refused")))


def test_a_service_that_is_down_says_how_to_start_it(tmp_path):
    recording = make_wav(tmp_path / "q.wav")
    for session in (FakeSession(error=ConnectionError("refused")),
                    FakeSession(FakeResponse(404, ValueError("not JSON"))),
                    FakeSession(FakeResponse(200, ValueError("not JSON")))):
        with pytest.raises(VoiceServiceUnavailable) as down:
            transcribe_with_voice_service(recording, "http://127.0.0.1:8903", session=session)
        assert START_VOICE_HINT in str(down.value)
    # A reason from the service itself is a refusal of the recording, not an outage.
    with pytest.raises(TranscriptionError, match="60s") as refused:
        transcribe_with_voice_service(recording, "http://voice.test", session=FakeSession(
            FakeResponse(400, {"detail": "Audio is 75.0s; maximum is 60s"})))
    assert not isinstance(refused.value, VoiceServiceUnavailable)


def test_the_health_probe_reports_the_local_service(tmp_path):
    up = voice_service_health("http://127.0.0.1:8903", session=FakeSession(
        FakeResponse(200, {"status": "healthy", "model": "openai-whisper-base", "device": "cuda"})))
    assert up["available"] is True and up["model"] == "openai-whisper-base"
    down = voice_service_health("http://127.0.0.1:8903", session=FakeSession(error=ConnectionError()))
    assert down["available"] is False and START_VOICE_HINT in down["detail"]


def test_every_audio_extension_is_routed_to_transcription(tmp_path, pages_dir):
    for ext in sorted(AUDIO_EXTENSIONS):
        source = tmp_path / f"clip{ext}"
        source.write_bytes(b"not really audio")
        _, info = split_pages(source, f"x{ext[1:]}", pages_dir, None)
        assert info and info["status"] == "unavailable", ext


# -- the duplicate rule -----------------------------------------------------------

def test_the_same_bytes_are_a_duplicate_anywhere_in_the_account():
    documents = {
        "general": {"digest": "abc", "name": "Spec.pdf", "project_ids": []},
        "in_a": {"digest": "abc", "name": "Spec.pdf", "project_ids": ["A"]},
        "legacy_b": {"digest": "def", "name": "Old.pdf", "project_id": "B"},
    }
    # A copy already in the scope is preferred; otherwise any copy will do,
    # because the caller links it rather than indexing the bytes again.
    assert find_duplicate(documents, "abc", "new", "A")["id"] == "in_a"
    assert find_duplicate(documents, "abc", "new", None)["id"] in {"general", "in_a"}
    assert find_duplicate(documents, "abc", "new", "C")["id"] in {"general", "in_a"}
    assert find_duplicate(documents, "def", "new", "B")["id"] == "legacy_b"
    assert find_duplicate(documents, "zzz", "new", None) is None
    # Re-ingesting a document under its own id is not a duplicate of itself.
    assert find_duplicate({"same": {"digest": "abc"}}, "abc", "same", None) is None
    assert find_duplicate(documents, "", "new", None) is None


# -- ingest_document and the media route, as the server defines them ---------------

def lift(names: set[str], namespace: dict) -> dict:
    """Compile the named top-level definitions of run_backend.py into namespace."""
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    wanted = [node for node in tree.body
              if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names)
              or (isinstance(node, ast.Assign)
                  and any(getattr(target, "id", None) in names for target in node.targets))]
    assert {getattr(node, "name", None) or node.targets[0].id for node in wanted} == names
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace


LOCAL_VOICE = "http://127.0.0.1:8903"


@pytest.fixture
def server(make_account):
    """ingest_document, audio_transcriber, the voice and media routes over a real workspace."""
    context = make_account("owner@example.com")
    transcribed = []
    state = {"up": True}      # whether the stand-in local voice service is running

    def fake_service(path, url):
        if not state["up"]:
            raise VoiceServiceUnavailable(f"The voice service is not running at {url}. {START_VOICE_HINT}")
        transcribed.append((Path(path).name, url))
        return {"text": "Crane lift of the level four precast units is on Monday.", "language": "en"}

    app = FastAPI()

    async def require_account():
        return context

    namespace = {
        "Path": Path, "os": os, "Dict": dict, "datetime": datetime, "re": __import__("re"),
        "uuid": __import__("uuid"), "logger": logging.getLogger("test.ingest"),
        "torch": SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)),
        "embed_image": lambda path, workspace=None: np.ones(4, dtype=np.float32),
        "_file_digest": file_digest, "find_duplicate": find_duplicate, "split_pages": split_pages,
        "AUDIO_EXTENSIONS": AUDIO_EXTENSIONS, "transcribe_with_voice_service": fake_service,
        "VOICE_SERVICE_URL": LOCAL_VOICE, "app": app, "Depends": Depends, "HTTPException": HTTPException,
        "require_account": require_account,
        "TranscriptionError": TranscriptionError, "VoiceServiceUnavailable": VoiceServiceUnavailable,
        "UploadFile": UploadFile, "File": File, "tempfile": tempfile, "asyncio": asyncio,
        "ORIGIN_LABELS": ORIGIN_LABELS, "link_document": link_document,
        "set_document_projects": set_document_projects,
    }
    lift({"ingest_document", "audio_transcriber", "MEDIA_TYPES",
          "sanitize_doc_id", "get_document_media", "VOICE_UPLOAD_LIMIT", "VOICE_EXTENSIONS",
          "transcribe_voice"}, namespace)
    return SimpleNamespace(ingest=namespace["ingest_document"], workspace=context.workspace,
                           client=TestClient(app), transcribed=transcribed, state=state,
                           namespace=namespace)


def stored_upload(workspace, doc_id: str, source: Path) -> Path:
    """Put a file where an upload route puts it: docs/<doc_id><ext>."""
    target = Path(workspace.docs_dir) / f"{doc_id}{source.suffix}"
    target.write_bytes(source.read_bytes())
    return target


def test_the_same_pdf_uploaded_twice_is_indexed_once(server, tmp_path):
    pdf = make_pdf(tmp_path / "tender.pdf", ["Tender specification"])
    first = server.ingest(stored_upload(server.workspace, "first", pdf), "first", server.workspace,
                          display_name="Tender.pdf")
    vectors = server.workspace.collection.count()
    again = stored_upload(server.workspace, "second", pdf)
    second = server.ingest(again, "second", server.workspace, display_name="Tender (copy).pdf")

    assert first["status"] == "indexed"
    assert second["status"] == "duplicate" and second["id"] == "first"
    assert not again.exists()                          # the redundant copy is gone
    assert set(server.workspace.load_metadata()["documents"]) == {"first"}
    assert server.workspace.collection.count() == vectors


def test_the_same_pdf_filed_under_two_projects_is_indexed_once_and_linked_to_both(server, tmp_path):
    pdf = make_pdf(tmp_path / "tender.pdf", ["Tender specification"])
    a = server.ingest(stored_upload(server.workspace, "for_a", pdf), "for_a", server.workspace,
                      project_id="A")
    vectors = server.workspace.collection.count()
    again = stored_upload(server.workspace, "for_b", pdf)
    b = server.ingest(again, "for_b", server.workspace, project_id="B")

    assert a["status"] == "indexed"
    assert b["status"] == "duplicate" and b["id"] == "for_a" and b["linked"] is True
    assert not again.exists()                          # no second file on disk
    assert server.workspace.collection.count() == vectors      # nor second set of vectors
    documents = server.workspace.load_metadata()["documents"]
    assert set(documents) == {"for_a"}
    assert documents["for_a"]["project_ids"] == ["A", "B"]
    # Filing it under A again changes nothing.
    repeat = server.ingest(stored_upload(server.workspace, "again_a", pdf), "again_a",
                           server.workspace, project_id="A")
    assert repeat["status"] == "duplicate" and repeat["linked"] is False
    assert server.workspace.load_metadata()["documents"]["for_a"]["project_ids"] == ["A", "B"]


def test_ingestion_records_where_a_document_came_from(server, tmp_path):
    pdf = make_pdf(tmp_path / "chat.pdf", ["Asked about in chat"])
    meta = server.ingest(stored_upload(server.workspace, "c1", pdf), "c1", server.workspace,
                         origin="chat")
    assert meta["origin"] == "chat" and meta["project_ids"] == [] and meta["project_id"] is None
    other = make_pdf(tmp_path / "odd.pdf", ["Somewhere else"])
    meta = server.ingest(stored_upload(server.workspace, "c2", other), "c2", server.workspace,
                         origin="not-a-place")
    assert "origin" not in meta


def test_an_uploaded_recording_is_transcribed_embedded_and_playable(server, tmp_path):
    recording = stored_upload(server.workspace, "rec1", make_wav(tmp_path / "site-walk.wav"))
    meta = server.ingest(recording, "rec1", server.workspace, display_name="site-walk.wav")

    assert server.transcribed == [("rec1.wav", LOCAL_VOICE)]
    assert meta["transcription"]["status"] == "transcribed"
    assert "precast units is on Monday" in meta["pages"][0]["text_content"]
    # The transcript names the file that was uploaded, not the stored id.
    assert "Transcript of site-walk.wav" in meta["pages"][0]["text_content"]
    assert server.workspace.collection.count() == len(meta["pages"])    # its words are indexed

    response = server.client.get("/api/documents/rec1/media")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == recording.read_bytes()


def test_a_recording_with_no_voice_service_is_kept_and_says_so(server, tmp_path):
    server.namespace["VOICE_SERVICE_URL"] = ""
    recording = stored_upload(server.workspace, "rec2", make_wav(tmp_path / "memo.wav"))
    meta = server.ingest(recording, "rec2", server.workspace, display_name="memo.wav")
    assert meta["transcription"]["status"] == "unavailable"
    assert server.transcribed == [] and server.workspace.collection.count() == 0
    assert server.client.get("/api/documents/rec2/media").status_code == 200


def test_a_recording_while_the_service_is_down_keeps_the_reason(server, tmp_path):
    server.state["up"] = False
    recording = stored_upload(server.workspace, "rec3", make_wav(tmp_path / "memo.wav"))
    meta = server.ingest(recording, "rec3", server.workspace, display_name="memo.wav")
    assert meta["transcription"]["status"] == "failed"
    assert "run_voice_service.py" in meta["transcription"]["reason"]


def test_the_media_route_serves_only_media_and_only_known_documents(server, tmp_path):
    pdf = make_pdf(tmp_path / "brief.pdf", ["Project brief"])
    server.ingest(stored_upload(server.workspace, "brief", pdf), "brief", server.workspace)
    assert server.client.get("/api/documents/brief/media").status_code == 404
    assert server.client.get("/api/documents/nobody/media").status_code == 404


def test_an_import_of_bytes_already_indexed_reports_the_existing_document(make_account, tmp_path):
    context = make_account("importer@example.com")
    calls = []

    def ingest(path, doc_id, workspace, display_name=None, project_id=None, origin=None):
        calls.append((project_id, origin))
        Path(path).unlink()
        return {"id": "existing", "name": "Spec.pdf", "page_count": 3, "status": "duplicate"}

    download = tmp_path / "Spec.pdf"
    download.write_bytes(b"%PDF-1.4 fake")
    result = ExternalImporter(ingest, "google").ingest_path(
        context.workspace, download, "Spec.pdf", None, "google_drive", {"item_id": "x"})
    assert calls == [(None, "google")]
    assert result["status"] == "duplicate" and result["id"] == "existing" and result["pages"] == 3


# -- the chat microphone's route ---------------------------------------------------

def post_voice(server, name="voice-message.webm", data=b"webm bytes"):
    return server.client.post("/api/voice/transcribe", files={"file": (name, data, "audio/webm")})


def test_a_spoken_message_is_transcribed_by_the_local_service(server):
    response = post_voice(server)
    assert response.status_code == 200
    assert "precast units" in response.json()["text"]
    assert server.transcribed == [("voice-message.webm", LOCAL_VOICE)]


def test_an_old_per_account_voice_url_is_ignored(server):
    # Settings no longer holds a voice URL at all; an old value cannot redirect it.
    server.workspace.save_settings({"voice_api_url": "https://gone.ngrok-free.dev"})
    assert "voice_api_url" not in server.workspace.load_settings()
    assert post_voice(server).status_code == 200
    assert server.transcribed == [("voice-message.webm", LOCAL_VOICE)]


def test_when_the_local_service_is_down_the_reason_reaches_the_user(server):
    server.state["up"] = False
    response = post_voice(server)
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "not running" in detail and "run_voice_service.py" in detail


def test_the_voice_route_refuses_what_the_service_would(server):
    assert post_voice(server, name="notes.txt").status_code == 415
    assert post_voice(server, data=b"").status_code == 400
    limit = server.namespace["VOICE_UPLOAD_LIMIT"]
    assert post_voice(server, data=b"x" * (limit + 1)).status_code == 413
    assert server.transcribed == []
