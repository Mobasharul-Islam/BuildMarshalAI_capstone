"""Turning an uploaded file into pages: one rendered image and its text per page.

This is the format half of ingestion -- everything before a page is embedded.
It needs no GPU, so it lives outside the notebook, where it can be tested; the
notebook's ``ingest_document`` calls into it and then embeds each page image
with ColPali.

Every ``process_*`` function returns a list of page dicts:

    {"page_num": 1, "image_path": "<png or None>", "text_content": "..."}

A page with no image is kept for its text (lexical retrieval still finds it)
but gets no vector.

Two things here are more than rendering:

* **Audio is transcribed.** A recording is sent to the local Whisper voice
  service (``backend/voice_service.py``) and its transcript becomes ordinary
  text pages, so what was said is retrievable like anything written. The
  recording itself stays where the upload put it and is served for playback by
  the document-media route. When the service is not running, or refuses the
  file (it caps recordings at 60 seconds and 20 MB), the document is kept with
  its file name and the reason, and says so rather than pretending to be indexed.
* **Duplicates are found by content.** :func:`find_duplicate` is the single
  rule every ingestion path uses to recognise bytes it has already indexed.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import shutil
from pathlib import Path
from typing import Any, Callable, Mapping

from matplotlib.figure import Figure
from PIL import Image

LOGGER = logging.getLogger("BuildMarshalAI.ingestion")

PAGE_MAX_EDGE = 1024          # longest side of a stored page image, pixels
PDF_RENDER_DPI = 150
PDF_TEXT_LIMIT = 12_000       # characters of text layer kept per PDF page
SHEET_IMAGE_ROWS = 50         # rows drawn into a spreadsheet page image
SHEET_TEXT_ROWS = 100         # rows kept as the spreadsheet page's text
DOCX_PAGE_CHARS = 2_000
TEXT_PAGE_CHARS = 3_000

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".wma", ".opus"})
SHEET_EXTENSIONS = frozenset({".xlsx", ".xls", ".csv"})
WORD_EXTENSIONS = frozenset({".doc", ".docx"})
TEXT_EXTENSIONS = frozenset({
    ".txt", ".json", ".xml", ".html", ".css", ".js", ".py",
    ".java", ".c", ".cpp", ".md", ".rtf",
})

#: Every file type an upload may carry, whichever route it arrives by: the
#: Documents page, the chat, or a project's Project Documents.
UPLOAD_EXTENSIONS = frozenset({
    # Documents
    ".pdf", ".xlsx", ".xls", ".csv", ".doc", ".docx", ".pptx", ".ppt",
    ".txt", ".rtf", ".odt", ".ods",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff",
    # Audio
    ".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".wma", ".opus",
    # Video
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
    # Archives & code
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".json", ".xml", ".html", ".css", ".js", ".py", ".java", ".c", ".cpp", ".md",
})

Page = dict[str, Any]
Transcriber = Callable[[Path], Mapping[str, Any]]


# -- content identity -----------------------------------------------------------

def file_digest(path: str | Path, chunk: int = 1024 * 1024) -> str:
    """SHA-256 of a file, read in chunks so a large upload never sits in memory.

    Matches ``document_storage.digest_of``.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def find_duplicate(documents: Mapping[str, Mapping[str, Any]], digest: str,
                   doc_id: str, project_id: str | None = None) -> dict[str, Any] | None:
    """An already-indexed document with the same bytes, anywhere in the account.

    The same bytes are indexed once, whichever path they arrive by and whichever
    project they are filed under: a document can belong to several projects, so
    filing it under a second one links the copy already indexed instead of
    storing and embedding it again (the caller adds the link). ``project_id`` is
    the scope being filed into; a copy already in that scope is preferred when
    there are several. The document being (re-)ingested under its own id is
    never its own duplicate.
    """
    if not digest:
        return None
    matches = [(stored_id, stored) for stored_id, stored in documents.items()
               if stored_id != doc_id and stored.get("digest") == digest]
    if not matches:
        return None

    def in_scope(stored: Mapping[str, Any]) -> bool:
        linked = stored.get("project_ids")
        ids = list(linked) if isinstance(linked, (list, tuple)) else [stored.get("project_id")]
        return bool(project_id) and project_id in ids

    stored_id, stored = next(((i, s) for i, s in matches if in_scope(s)), matches[0])
    return {**stored, "id": stored_id}


# -- rendering helpers ----------------------------------------------------------

def _save_page_image(image: Image.Image, path: Path) -> Image.Image:
    image = image.convert("RGB")
    image.thumbnail((PAGE_MAX_EDGE, PAGE_MAX_EDGE))
    image.save(path, "PNG")
    return image


def render_text_pages(text: str, doc_id: str, pages_dir: Path, title: str,
                      chars_per_page: int = TEXT_PAGE_CHARS, font_size: int = 8) -> list[Page]:
    """Split text into pages and draw each as an image.

    The image is what ColPali embeds; the chunk is what lexical retrieval and
    the evidence viewer read. A page whose drawing fails keeps its text.
    """
    chunks = [text[i:i + chars_per_page] for i in range(0, max(len(text), 1), chars_per_page)]
    pages: list[Page] = []
    for index, chunk in enumerate(chunks, start=1):
        path = Path(pages_dir) / f"{doc_id}_page_{index}.png"
        try:
            figure = Figure(figsize=(10, 14))
            axes = figure.subplots()
            axes.axis("off")
            axes.text(0.05, 0.95, chunk, transform=axes.transAxes, fontsize=font_size,
                      verticalalignment="top", fontfamily="monospace", wrap=True)
            axes.set_title(f"{title} — Page {index}")
            figure.savefig(str(path), dpi=120, bbox_inches="tight", facecolor="white")
            image_path: str | None = str(path)
        except Exception as error:
            LOGGER.warning("Text page render failed for %s page %d: %s", doc_id, index, error)
            image_path = None
        pages.append({"page_num": index, "image_path": image_path, "text_content": chunk})
    return pages


def _table_image(frame: Any, title: str, path: Path) -> None:
    data = frame.head(SHEET_IMAGE_ROWS).fillna("").astype(str)
    figure = Figure(figsize=(min(20, len(frame.columns) * 1.5 + 1), min(20, len(frame) * 0.4 + 1)))
    axes = figure.subplots()
    axes.axis("off")
    table = axes.table(cellText=data.values, colLabels=data.columns, cellLoc="left", loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.3)
    for (row, _), cell in table.get_celld().items():
        if row == 0:
            cell.set_facecolor("#4472C4")
            cell.set_text_props(color="white", fontweight="bold")
        else:
            cell.set_facecolor("#f0f0f0" if row % 2 == 0 else "white")
    axes.set_title(title, fontsize=10, fontweight="bold")
    figure.tight_layout()
    figure.savefig(str(path), dpi=120, bbox_inches="tight", facecolor="white")


# -- formats ----------------------------------------------------------------------

def process_pdf(file_path: Path, doc_id: str, pages_dir: Path) -> list[Page]:
    """Render PDF pages with PyMuPDF (no external Poppler) and keep the text layer."""
    import fitz

    pages: list[Page] = []
    matrix = fitz.Matrix(PDF_RENDER_DPI / 72, PDF_RENDER_DPI / 72)
    with fitz.open(file_path) as document:
        for index, pdf_page in enumerate(document, start=1):
            pixmap = pdf_page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            path = Path(pages_dir) / f"{doc_id}_page_{index}.png"
            image = _save_page_image(image, path)
            pages.append({
                "page_num": index, "image_path": str(path),
                "width": image.width, "height": image.height,
                "text_content": pdf_page.get_text("text")[:PDF_TEXT_LIMIT],
            })
    return pages


def process_excel(file_path: Path, doc_id: str, pages_dir: Path) -> list[Page]:
    """One page per sheet: a table image and the sheet's first rows as text."""
    import pandas as pd

    frames = ({"Sheet1": pd.read_csv(str(file_path))}
              if Path(file_path).suffix.lower() == ".csv"
              else pd.read_excel(str(file_path), sheet_name=None))
    pages: list[Page] = []
    for sheet_name, frame in frames.items():
        path = Path(pages_dir) / f"{doc_id}_sheet_{sheet_name}.png"
        try:
            _table_image(frame, f"{Path(file_path).stem} — {sheet_name}", path)
            image_path: str | None = str(path)
        except Exception as error:
            LOGGER.warning("Sheet render failed for %s/%s: %s", doc_id, sheet_name, error)
            image_path = None
        pages.append({
            "page_num": len(pages) + 1, "image_path": image_path, "sheet_name": sheet_name,
            "text_content": frame.head(SHEET_TEXT_ROWS).to_string(),
        })
    return pages


def process_image(file_path: Path, doc_id: str, pages_dir: Path) -> list[Page]:
    with Image.open(str(file_path)) as source:
        path = Path(pages_dir) / f"{doc_id}_img.png"
        image = _save_page_image(source, path)
    return [{"page_num": 1, "image_path": str(path),
             "width": image.width, "height": image.height, "text_content": ""}]


def process_docx(file_path: Path, doc_id: str, pages_dir: Path) -> list[Page]:
    from docx import Document as DocxDocument

    document = DocxDocument(str(file_path))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
    return render_text_pages(text, doc_id, pages_dir, Path(file_path).stem,
                             chars_per_page=DOCX_PAGE_CHARS, font_size=9)


def process_text(file_path: Path, doc_id: str, pages_dir: Path) -> list[Page]:
    """Plain text and code files, drawn as pages."""
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    return render_text_pages(text, doc_id, pages_dir, Path(file_path).stem)


def process_generic(file_path: Path, doc_id: str, pages_dir: Path) -> list[Page]:
    """Fallback -- keep the file and describe it; nothing to render."""
    path = Path(pages_dir) / f"{doc_id}_file{Path(file_path).suffix}"
    shutil.copy2(str(file_path), str(path))
    return [{"page_num": 1, "image_path": str(path),
             "text_content": f"File: {Path(file_path).name} ({Path(file_path).stat().st_size} bytes)"}]


# -- audio --------------------------------------------------------------------------

class TranscriptionError(RuntimeError):
    """The voice service could not transcribe a recording; the message says why."""


#: How to bring the voice service up, for every message that says it is down.
START_VOICE_HINT = ("Start it with START-BUILDMARSHAL.ps1, or run "
                    "python scripts/run_voice_service.py")


class VoiceServiceUnavailable(TranscriptionError):
    """The local voice service is not running, or something else is on its port.

    Unlike a refusal of the recording itself, trying again once the service is
    up will work.
    """


def transcribe_with_voice_service(file_path: Path, url: str, *, timeout: int = 300,
                                  session: Any = None) -> dict[str, Any]:
    """Send one recording to the local Whisper voice service; return its transcript.

    The service is ``backend/voice_service.py`` (``POST /api/transcribe``), the
    same one the chat microphone reaches through the backend. Its refusals --
    too long, too large, unsupported type -- come back as
    :class:`TranscriptionError` with the service's own reason.
    """
    import requests

    endpoint = url.rstrip("/") + "/api/transcribe"
    mime = mimetypes.guess_type(Path(file_path).name)[0] or "application/octet-stream"
    client = session or requests
    try:
        with Path(file_path).open("rb") as handle:
            response = client.post(endpoint, files={"file": (Path(file_path).name, handle, mime)},
                                   timeout=timeout)
    except Exception as error:
        raise VoiceServiceUnavailable(
            f"The voice service is not running at {url.rstrip('/')} ({type(error).__name__}). "
            f"{START_VOICE_HINT}") from error
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = None
        # A 404, or an error page with no reason in it, is not the voice service
        # refusing the recording: something other than it is on that port.
        if response.status_code == 404 or (detail is None and response.status_code >= 500):
            raise VoiceServiceUnavailable(
                f"No voice service at {url.rstrip('/')} (HTTP {response.status_code}). "
                f"{START_VOICE_HINT}")
        raise TranscriptionError(str(detail or f"Voice service returned HTTP {response.status_code}"))
    try:
        data = response.json()
    except Exception as error:
        raise VoiceServiceUnavailable(
            f"No voice service at {url.rstrip('/')} (the reply was not JSON). "
            f"{START_VOICE_HINT}") from error
    return {
        "text": str(data.get("text") or "").strip(),
        "language": data.get("language"),
        "duration_seconds": data.get("duration_seconds"),
        "model": data.get("model"),
    }


def voice_service_health(url: str, *, timeout: float = 1.5, session: Any = None) -> dict[str, Any]:
    """Whether the local voice service answers, for the backend's health report."""
    import requests

    client = session or requests
    try:
        response = client.get(url.rstrip("/") + "/api/health", timeout=timeout)
        data = response.json() if response.status_code == 200 else {}
    except Exception:
        data = {}
    if data.get("status") == "healthy":
        return {"available": True, "url": url, "model": data.get("model"), "device": data.get("device")}
    return {"available": False, "url": url, "detail": f"not running. {START_VOICE_HINT}"}


def process_audio(file_path: Path, doc_id: str, pages_dir: Path,
                  transcribe: Transcriber | None = None,
                  display_name: str | None = None) -> tuple[list[Page], dict[str, Any]]:
    """Transcribe a recording into text pages.

    Returns the pages and a ``transcription`` record for the document's
    metadata. The recording is not copied: the original upload is what the
    document-media route plays back.
    """
    # The stored file is named after its id; the transcript names what was uploaded.
    name = Path(display_name).name if display_name else Path(file_path).name
    if transcribe is None:
        reason = f"the voice service is not configured. {START_VOICE_HINT}"
        return ([{"page_num": 1, "image_path": None,
                  "text_content": f"Audio file: {name}. Not transcribed: {reason}."}],
                {"status": "unavailable", "reason": reason})
    try:
        result = dict(transcribe(Path(file_path)))
    except Exception as error:
        reason = str(error)[:300] or error.__class__.__name__
        LOGGER.warning("Audio transcription failed for %s: %s", doc_id, reason)
        return ([{"page_num": 1, "image_path": None,
                  "text_content": f"Audio file: {name}. Not transcribed: {reason}."}],
                {"status": "failed", "reason": reason})
    text = str(result.get("text") or "").strip()
    info = {key: result.get(key) for key in ("language", "duration_seconds", "model")
            if result.get(key) is not None}
    if not text:
        return ([{"page_num": 1, "image_path": None,
                  "text_content": f"Audio file: {name}. No speech was recognised."}],
                {"status": "empty", **info})
    pages = render_text_pages(f"Transcript of {name}\n\n{text}", doc_id, pages_dir,
                              f"{Path(name).stem} (transcript)")
    return pages, {"status": "transcribed", "characters": len(text), **info}


def split_pages(file_path: Path, doc_id: str, pages_dir: Path,
                transcribe: Transcriber | None = None,
                display_name: str | None = None) -> tuple[list[Page], dict[str, Any] | None]:
    """Dispatch on the file extension. Returns the pages and, for audio, the
    transcription record (``None`` for every other format)."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return process_pdf(file_path, doc_id, pages_dir), None
    if ext in SHEET_EXTENSIONS:
        return process_excel(file_path, doc_id, pages_dir), None
    if ext in IMAGE_EXTENSIONS:
        return process_image(file_path, doc_id, pages_dir), None
    if ext in WORD_EXTENSIONS:
        return process_docx(file_path, doc_id, pages_dir), None
    if ext in AUDIO_EXTENSIONS:
        return process_audio(file_path, doc_id, pages_dir, transcribe, display_name)
    if ext in TEXT_EXTENSIONS:
        return process_text(file_path, doc_id, pages_dir), None
    return process_generic(file_path, doc_id, pages_dir), None


__all__ = [
    "AUDIO_EXTENSIONS", "IMAGE_EXTENSIONS", "START_VOICE_HINT", "TranscriptionError",
    "UPLOAD_EXTENSIONS", "VoiceServiceUnavailable",
    "file_digest",
    "find_duplicate", "process_audio", "process_docx", "process_excel", "process_generic",
    "process_image", "process_pdf", "process_text", "render_text_pages", "split_pages",
    "transcribe_with_voice_service", "voice_service_health",
]
