import asyncio
import json
import re
import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader

from backend.document_generation import (
    DOCUMENT_TEMPLATES,
    DocumentGenerationService,
    classify_source_document,
    extract_pdf_page_texts,
    parse_section_response,
)



SAMPLE_ROOT = Path(r"D:\Capstone Project\Sample project pdfs")
SCHEDULE_PDF = SAMPLE_ROOT / "Exhibit D - Preliminary Schedule" / "2025.10.06 - Preliminary Project Schedule.r1.pdf"
ADDENDUM_PDF = SAMPLE_ROOT / "Tender Addendum 02 - 2025.10.29" / "Tender Addendum 02 FINAL.pdf"


def test_source_document_classification():
    assert classify_source_document("Tender Addendum 02 FINAL.pdf") == "tender_addendum"
    assert classify_source_document("Preliminary Project Schedule.r1.pdf") == "schedule"
    assert classify_source_document("CCDC5B.pdf") == "contract"
    assert classify_source_document("M1.00.PDF") == "drawing"


def test_section_parser_rejects_nonexistent_source_numbers():
    spec = DOCUMENT_TEMPLATES["schedule_summary"].sections[0]
    pages = [{"doc_id": "one", "doc_name": "schedule.pdf", "page": 1, "score": 0.9}]
    result = parse_section_response(
        json.dumps({
            "paragraphs": ["The schedule establishes the overall timeline."],
            "bullets": [],
            "table": {"columns": [], "rows": []},
            "used_sources": [1, 99],
        }),
        spec,
        pages,
    )
    assert len(result.sources) == 1
    assert result.sources[0]["doc_name"] == "schedule.pdf"


def test_section_parser_recovers_narrative_from_malformed_json():
    spec = DOCUMENT_TEMPLATES["tender_summary"].sections[0]
    pages = [{"doc_id": "one", "doc_name": "addendum.pdf", "page": 2, "score": 0.8}]
    malformed = '''```json
    {"paragraphs": ["A clean evidence-backed overview."],
     "bullets": ["A recovered requirement."],
     "table": {"columns": ["Item"], "rows": [["One"], // invalid model comment
     ["Two"]]}, "used_sources": [1]}
    ```'''
    result = parse_section_response(malformed, spec, pages)
    assert result.paragraphs == ["A clean evidence-backed overview."]
    assert result.bullets == ["A recovered requirement."]
    assert result.sources[0]["doc_name"] == "addendum.pdf"
    assert "malformed" in result.warning


def test_section_parser_recovers_truncated_json_string():
    spec = DOCUMENT_TEMPLATES["tender_summary"].sections[3]
    pages = [{"doc_id": "one", "doc_name": "schedule.pdf", "page": 1, "score": 0.7}]
    truncated = '```json\n{"paragraphs": ["Task 85 starts Tuesday and the schedule continues with Task 86.\\nTask 87 follows'
    result = parse_section_response(truncated, spec, pages)
    assert result.paragraphs == ["Task 85 starts Tuesday and the schedule continues with Task 86. Task 87 follows"]
    assert result.sources[0]["doc_name"] == "schedule.pdf"
    assert "truncated" in result.warning


@pytest.mark.skipif(not (SCHEDULE_PDF.exists() and ADDENDUM_PDF.exists()), reason="sample project PDFs are unavailable")
def test_two_pdf_project_document_generation(tmp_path, make_workspace):
    upload_dir = tmp_path / "uploaded" / "sample-project"
    upload_dir.mkdir(parents=True)
    uploaded_files = []
    for source in (SCHEDULE_PDF, ADDENDUM_PDF):
        destination = upload_dir / source.name
        shutil.copy2(source, destination)
        uploaded_files.append(destination)

    pages = []
    for doc_index, path in enumerate(uploaded_files, 1):
        for page_number, text in enumerate(extract_pdf_page_texts(path), 1):
            pages.append({
                "doc_id": f"doc-{doc_index}",
                "doc_name": path.name,
                "page": page_number,
                "text_content": text,
                "image_path": "",
                "source_type": classify_source_document(path.name),
            })

    def retrieve(query, project_id, top_k, workspace):
        assert project_id == "sample-project"
        terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        ranked = []
        for page in pages:
            haystack = page["text_content"].lower()
            score = sum(haystack.count(term) for term in terms if len(term) > 3)
            ranked.append((score, page))
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = []
        for score, page in ranked[:top_k]:
            selected.append({**page, "score": min(0.99, 0.45 + score / 100.0)})
        return selected

    def compose(prompt, context_pages):
        heading = re.search(r'Create the section "([^"]+)"', prompt).group(1)
        first_text = " ".join(context_pages[0].get("text_content", "").split())
        return json.dumps({
            "paragraphs": [f"{heading} was compiled from the linked project PDFs. {first_text[:420]}"],
            "bullets": ["Only evidence from the selected project sources was used."],
            "table": {"columns": [], "rows": []},
            "used_sources": [1],
            "warning": None,
        })

    service = DocumentGenerationService(retrieve=retrieve, compose=compose)
    workspace = make_workspace("docgen@example.com")
    record = asyncio.run(service.generate(
        workspace=workspace,
        project_id="sample-project",
        doc_kind="tender_summary",
        project={"id": "sample-project", "name": "Pan Pacific Village Centre Whistler", "project_code": "PPVC"},
        top_k_per_section=4,
    ))

    pdf_path = Path(record["file_path"])
    assert pdf_path.exists() and pdf_path.stat().st_size > 10_000
    assert record["status"] == "ready"
    assert record["section_count"] == len(DOCUMENT_TEMPLATES["tender_summary"].sections)
    assert record["source_page_count"] >= 1
    assert service.get_record(workspace, record["id"])["project_id"] == "sample-project"

    reader = PdfReader(str(pdf_path))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) >= 3
    assert "Tender Summary" in extracted
    assert "Pan Pacific Village Centre Whistler" in extracted
    assert SCHEDULE_PDF.name in extracted or ADDENDUM_PDF.name in extracted
