"""The local voice service (backend/voice_service.py), around a stand-in model."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.voice_service import MAX_UPLOAD_BYTES, create_app

INFO = {"model": "openai-whisper-base", "device": "cpu", "cuda_available": False}


def client(transcribe):
    return TestClient(create_app(transcribe, INFO))


def test_health_reports_the_model_and_the_limit():
    body = client(lambda path, language: {}).get("/api/health").json()
    assert body["status"] == "healthy" and body["model"] == "openai-whisper-base"
    assert body["max_audio_seconds"] == 60


def test_a_recording_is_transcribed_and_its_file_removed_afterwards():
    seen = []

    def transcribe(path, language):
        seen.append((path, language))
        return {"text": "Pour at nine", "language": "en"}

    reply = client(transcribe).post("/api/transcribe", files={"file": ("q.webm", b"bytes", "audio/webm")},
                                    data={"language": "en"})
    assert reply.status_code == 200 and reply.json()["text"] == "Pour at nine"
    from pathlib import Path
    assert seen[0][1] == "en" and not Path(seen[0][0]).exists()


def test_what_the_service_refuses():
    app = client(lambda path, language: {"text": "x"})
    assert app.post("/api/transcribe", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 415
    assert app.post("/api/transcribe", files={"file": ("a.wav", b"", "audio/wav")}).status_code == 400
    big = b"x" * (MAX_UPLOAD_BYTES + 1)
    assert app.post("/api/transcribe", files={"file": ("a.wav", big, "audio/wav")}).status_code == 413


def test_a_recording_over_the_limit_is_a_refusal_with_the_reason():
    def too_long(path, language):
        raise ValueError("Audio is 75.0s; maximum is 60s")

    reply = client(too_long).post("/api/transcribe", files={"file": ("a.wav", b"x", "audio/wav")})
    assert reply.status_code == 400 and "maximum is 60s" in reply.json()["detail"]


def test_the_service_has_no_cors_because_no_browser_calls_it():
    app = create_app(lambda path, language: {}, INFO)
    assert not any(getattr(m.cls, "__name__", "") == "CORSMiddleware" for m in app.user_middleware)
