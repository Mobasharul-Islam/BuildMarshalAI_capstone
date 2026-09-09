from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.evidence_viewer import (
    best_evidence_snippet,
    evidence_terms,
    register_evidence_viewer_routes,
)



def test_evidence_terms_remove_chat_filler():
    assert evidence_terms("Tell me very details about Guestroom Carpet Option B") == [
        "details", "guestroom", "carpet", "option", "b"
    ]


def test_best_snippet_finds_matching_specification_late_on_page():
    prefix = "General installation requirement. " * 80
    target = "Guestroom Carpet Option B style IN23277 Infinity with a 36 by 36 repeat."
    snippet = best_evidence_snippet(prefix + target + (" Warranty information. " * 80), target, 320)
    assert "Guestroom Carpet Option B" in snippet
    assert "IN23277" in snippet


def _seed_document(workspace, doc_id: str = "doc-1") -> Path:
    image = workspace.pages_dir / f"{doc_id}_page_2.png"
    image.write_bytes(b"not-a-real-image-but-present")
    workspace.save_metadata({
        "documents": {
            doc_id: {
                "name": "finish-spec.pdf",
                "page_count": 2,
                "project_id": "project-1",
                "source_type": "specification",
                "pages": [
                    {
                        "page_num": 2,
                        "image_path": str(image),
                        "text_content": "Guestroom Carpet Option B style IN23277 Infinity.",
                    }
                ],
            }
        }
    })
    return image


def _client(context) -> TestClient:
    app = FastAPI()

    async def require_account():
        return context

    register_evidence_viewer_routes({"app": app, "require_account": require_account})
    return TestClient(app)


def test_evidence_routes_return_exact_page_and_store_feedback(make_account):
    context = make_account("evidence@example.com")
    _seed_document(context.workspace)
    client = _client(context)

    detail = client.get(
        "/api/evidence/doc-1/2",
        params={"query": "Guestroom Carpet Option B"},
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["page"] == 2
    assert payload["doc_name"] == "finish-spec.pdf"
    assert payload["has_page_image"] is True
    assert "Guestroom Carpet Option B" in payload["evidence_text"]

    feedback = client.post("/api/evidence/feedback", json={
        "doc_id": "doc-1",
        "page": 2,
        "rating": "relevant",
        "query": "Guestroom Carpet Option B",
        "message_id": "message-1",
        "score": 0.91,
    })
    assert feedback.status_code == 200
    assert context.workspace.evidence_file.exists()
    assert client.get("/api/evidence-feedback/stats").json() == {
        "total": 1,
        "relevant": 1,
        "not_relevant": 0,
    }


def test_evidence_of_another_account_is_not_readable(make_account):
    owner = make_account("owner@example.com")
    _seed_document(owner.workspace)
    _client(owner).post("/api/evidence/feedback", json={
        "doc_id": "doc-1", "page": 2, "rating": "relevant", "query": "carpet",
    })

    intruder = make_account("intruder@example.com", name="Intruder")
    intruder_client = _client(intruder)

    # The document id is valid in the other account, and must still read as
    # missing here rather than returning that account's page.
    assert intruder_client.get("/api/evidence/doc-1/2").status_code == 404
    assert intruder_client.post("/api/evidence/feedback", json={
        "doc_id": "doc-1", "page": 2, "rating": "relevant",
    }).status_code == 404
    assert intruder_client.get("/api/evidence-feedback/stats").json()["total"] == 0
    assert _client(owner).get("/api/evidence-feedback/stats").json()["total"] == 1
