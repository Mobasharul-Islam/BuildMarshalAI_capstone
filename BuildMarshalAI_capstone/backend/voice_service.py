"""The local Whisper voice service.

A small FastAPI app, separate from the document backend so Whisper never shares
a process with ColPali. The backend is its only client: the chat microphone
posts to ``POST /api/voice/transcribe`` on the backend, which forwards the
recording here, and uploaded audio documents are transcribed the same way.
It listens on the loopback interface only (``scripts/run_voice_service.py``,
started by ``START-BUILDMARSHAL.ps1``), so it needs no CORS and no tunnel.

Routes:

* ``GET /api/health`` -- model, device, and the recording limit.
* ``POST /api/transcribe`` -- multipart ``file`` plus optional ``language``;
  returns ``text``, ``language``, ``duration_seconds``, ``processing_seconds``,
  ``segments`` and ``model``. Recordings are capped at 60 seconds and 20 MB, and
  one transcription runs at a time.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

LOGGER = logging.getLogger("BuildMarshalVoice")

MODEL_NAME = "base"           # multilingual, compact, and good on short chat queries
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_AUDIO_SECONDS = 60
SAMPLE_RATE = 16_000
ALLOWED_EXTENSIONS = frozenset({
    ".webm", ".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".flac", ".aac",
})

#: ``(path, language) -> result`` -- what the transcribe route calls.
Transcriber = Callable[[str, Optional[str]], dict]


def whisper_transcriber(model_dir: Path, model_name: str = MODEL_NAME,
                        device: str | None = None) -> tuple[Transcriber, dict[str, Any]]:
    """Load Whisper once and return the transcriber plus what health reports."""
    import torch
    import whisper

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    LOGGER.info("Loading OpenAI Whisper %s on %s...", model_name, device)
    model = whisper.load_model(model_name, device=device, download_root=str(model_dir))
    LOGGER.info("Whisper model ready")
    label = f"openai-whisper-{model_name}"

    def transcribe(path: str, language: Optional[str]) -> dict[str, Any]:
        started = time.perf_counter()
        audio = whisper.load_audio(path)
        duration = len(audio) / SAMPLE_RATE
        if duration > MAX_AUDIO_SECONDS + 1:
            raise ValueError(f"Audio is {duration:.1f}s; maximum is {MAX_AUDIO_SECONDS}s")
        result = model.transcribe(
            audio, language=language or None, task="transcribe",
            fp16=(device == "cuda"), temperature=0,
            condition_on_previous_text=False, verbose=False,
        )
        segments = [
            {"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2),
             "text": s["text"].strip()}
            for s in result.get("segments", []) if s.get("text", "").strip()
        ]
        return {
            "text": result.get("text", "").strip(),
            "language": result.get("language"),
            "duration_seconds": round(duration, 2),
            "processing_seconds": round(time.perf_counter() - started, 2),
            "segments": segments,
            "model": label,
        }

    info = {"model": label, "device": device, "cuda_available": torch.cuda.is_available()}
    return transcribe, info


def create_app(transcribe: Transcriber, info: dict[str, Any] | None = None) -> FastAPI:
    """The voice service around one transcriber (Whisper, or a stand-in in tests)."""
    info = dict(info or {})
    lock = asyncio.Lock()
    app = FastAPI(title="BuildMarshalAI Voice Service", version="2.0.0")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": "BuildMarshalAI Voice", "docs": "/docs", "health": "/api/health"}

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "healthy", "service": "voice-transcription", **info,
                "max_audio_seconds": MAX_AUDIO_SECONDS}

    @app.post("/api/transcribe")
    async def transcribe_audio(file: UploadFile = File(...),
                               language: Optional[str] = Form(None)) -> dict[str, Any]:
        suffix = Path(file.filename or "voice.webm").suffix.lower() or ".webm"
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(415, detail=f"Unsupported audio type: {suffix}")
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
                temp_path = temp.name
                total = 0
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, detail="Audio file exceeds the 20 MB limit")
                    temp.write(chunk)
            if total == 0:
                raise HTTPException(400, detail="The uploaded audio file is empty")
            async with lock:
                try:
                    return await asyncio.to_thread(transcribe, temp_path, language)
                except ValueError as error:
                    raise HTTPException(400, detail=str(error)) from error
                except Exception as error:
                    LOGGER.exception("Transcription failed")
                    raise HTTPException(500, detail=f"Transcription failed: {error}") from error
        finally:
            await file.close()
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

    return app


__all__ = ["ALLOWED_EXTENSIONS", "MAX_AUDIO_SECONDS", "MAX_UPLOAD_BYTES", "create_app",
           "whisper_transcriber"]
