"""Exact-page evidence inspection and relevance feedback for BuildMarshalAI."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field


EVIDENCE_STOPWORDS = {
    "a", "about", "an", "and", "are", "for", "from", "give", "i", "in",
    "is", "me", "of", "on", "please", "show", "tell", "the", "this", "to",
    "very", "what", "with", "you",
}


def evidence_terms(query: str) -> list[str]:
    """Return stable, useful query terms for evidence highlighting."""
    return list(dict.fromkeys(
        token for token in re.findall(r"[a-z0-9]+", str(query).casefold())
        if token not in EVIDENCE_STOPWORDS
    ))


def best_evidence_snippet(text: str, query: str, max_chars: int = 1400) -> str:
    """Select the densest query-matching window from a page's extracted text."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= max_chars:
        return clean
    terms = evidence_terms(query)
    if not terms:
        return clean[:max_chars].rstrip() + "…"

    lowered = clean.casefold()
    candidates: list[int] = []
    for term in terms:
        candidates.extend(match.start() for match in re.finditer(rf"\b{re.escape(term)}\b", lowered))
    if not candidates:
        return clean[:max_chars].rstrip() + "…"

    best_start, best_score = 0, -1
    half = max_chars // 2
    for position in candidates:
        start = max(0, min(position - half, len(clean) - max_chars))
        window = lowered[start:start + max_chars]
        score = sum(len(re.findall(rf"\b{re.escape(term)}\b", window)) for term in terms)
        if score > best_score:
            best_start, best_score = start, score

    if best_start:
        boundary = clean.find(" ", best_start)
        if 0 <= boundary < best_start + 80:
            best_start = boundary + 1
    snippet = clean[best_start:best_start + max_chars].strip()
    return ("…" if best_start else "") + snippet + ("…" if best_start + max_chars < len(clean) else "")


class EvidenceFeedbackRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=1)
    rating: str = Field(pattern=r"^(relevant|not_relevant)$")
    query: str = Field(default="", max_length=4000)
    message_id: str | None = Field(default=None, max_length=200)
    score: float | None = Field(default=None, ge=0.0, le=1.0)


def register_evidence_viewer_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register evidence-detail and relevance-feedback routes on the notebook app.

    Both the document lookup and the feedback log resolve through the caller's
    account workspace, so a document id from another account reads as missing
    rather than as someone else's page.
    """
    required = ("app", "require_account")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Evidence viewer integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]

    def find_page(workspace: Any, doc_id: str, page_num: int) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        document = workspace.load_metadata().get("documents", {}).get(doc_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        for page in document.get("pages", []):
            if int(page.get("page_num", 0)) == page_num:
                return document, page
        raise HTTPException(status_code=404, detail="Document page not found")

    def read_feedback(workspace: Any) -> list[dict[str, Any]]:
        return workspace.load_evidence()

    @app.get("/api/evidence/{doc_id}/{page_num}")
    async def evidence_detail(
        doc_id: str, page_num: int, query: str = "", context=Depends(require_account),
    ) -> dict[str, Any]:
        workspace = context.workspace
        document, page = find_page(workspace, doc_id, page_num)
        text = str(page.get("text_content", ""))
        return {
            "doc_id": doc_id,
            "doc_name": document.get("name", doc_id),
            "page": page_num,
            "page_count": int(document.get("page_count", len(document.get("pages", [])))),
            "project_id": document.get("project_id"),
            "source_type": document.get("source_type", "project_document"),
            "text_content": text,
            "evidence_text": best_evidence_snippet(text, query),
            "matched_terms": evidence_terms(query),
            "has_page_image": bool(workspace.resolve_page_path(page.get("image_path"))),
            "image_endpoint": f"/api/pages/{doc_id}/{page_num}",
        }

    @app.post("/api/evidence/feedback")
    async def evidence_feedback(
        body: EvidenceFeedbackRequest, context=Depends(require_account),
    ) -> dict[str, Any]:
        workspace = context.workspace
        document, _ = find_page(workspace, body.doc_id, body.page)
        record = {
            "id": uuid.uuid4().hex,
            "doc_id": body.doc_id,
            "doc_name": document.get("name", body.doc_id),
            "page": body.page,
            "rating": body.rating,
            "query": body.query,
            "message_id": body.message_id,
            "score": body.score,
            "user_id": context.user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # One row, and the log trimmed to its newest 5,000, in one transaction.
        workspace.add_evidence(record, keep=5000)
        return {"status": "saved", "feedback_id": record["id"]}

    @app.get("/api/evidence-feedback/stats")
    async def evidence_feedback_stats(context=Depends(require_account)) -> dict[str, Any]:
        records = read_feedback(context.workspace)
        relevant = sum(item.get("rating") == "relevant" for item in records)
        not_relevant = sum(item.get("rating") == "not_relevant" for item in records)
        return {"total": len(records), "relevant": relevant, "not_relevant": not_relevant}

    return {"scoped": "per-account"}


__all__ = [
    "EvidenceFeedbackRequest", "best_evidence_snippet", "evidence_terms",
    "register_evidence_viewer_routes",
]
