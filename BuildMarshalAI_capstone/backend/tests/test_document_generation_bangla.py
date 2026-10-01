"""Generated documents with Bangla in them: extracted, quoted, written and drawn properly.

The documents that prompted this came out with every Bangla word as blank
space -- the project name in the title included -- and with sections written in
whichever language the evidence happened to be in, built from the first few
hundred characters of each page.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

from backend.document_generation import (
    DOCUMENT_TEMPLATES,
    DocumentGenerationService,
    PdfDocumentRenderer,
    SectionResult,
    best_excerpt,
    build_section_prompt,
    extract_pdf_page_texts,
)

PACK = Path(__file__).resolve().parents[2] / "demo" / "project-pack"
BRIEF_BN = PACK / "01_Prokolpo-Bibaroni_Project-Brief.pdf"
PROJECT_BN = {"id": "p-bn", "name": "পদ্মা ভিউ স্পেশালাইজড হাসপাতাল সম্প্রসারণ", "project_code": "PVH1-2026"}


def _fonts_in(pdf_path: Path) -> set[str]:
    import fitz

    with fitz.open(str(pdf_path)) as document:
        return {font[3] for page in document for font in page.get_fonts()}


# ── extraction ────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not BRIEF_BN.exists(), reason="demo pack not present")
def test_bangla_pdf_text_is_extracted_in_reading_order():
    text = extract_pdf_page_texts(BRIEF_BN)[0]
    # Reading order: the vowel sign follows its consonant, as a reader types it.
    assert "বিবরণী" in text and "পরিচিতি" in text
    # pypdf's visual order put it first ("িববরণী"), which reads as nonsense.
    assert "িববরণী" not in text


# ── evidence ──────────────────────────────────────────────────────────────────

def test_a_short_page_is_quoted_whole():
    assert best_excerpt("Line one\nLine two", "anything", 4000) == "Line one Line two"


def test_a_long_page_is_quoted_by_the_passages_that_matter():
    filler = [f"Row {n}: general preliminaries item {n}" for n in range(400)]
    rows = filler[:200] + ["Structural frame completion milestone 2027-03-14"] + filler[200:]
    excerpt = best_excerpt("Works Programme Rev C\n" + "\n".join(rows), "milestone completion", 1500)
    assert len(excerpt) <= 1500
    assert "Works Programme Rev C" in excerpt                 # the page's own title stays
    assert "Structural frame completion milestone 2027-03-14" in excerpt
    assert "…" in excerpt                                       # and the gap is marked


def test_bangla_query_terms_find_bangla_passages():
    rows = [f"সারি {n}: সাধারণ কাজ" for n in range(300)] + ["হস্তান্তর তারিখ ৩০ জুন ২০২৭"]
    excerpt = best_excerpt("\n".join(rows), "সমাপ্তি হস্তান্তর", 800)
    assert "হস্তান্তর তারিখ ৩০ জুন ২০২৭" in excerpt


def test_the_prompt_quotes_far_more_than_the_first_900_characters():
    page = {"doc_name": "Works.xlsx", "page": 1, "text_content": ("x" * 50 + "\n") * 200}
    template = DOCUMENT_TEMPLATES["project_brief"]
    prompt = build_section_prompt(template, template.sections[2], PROJECT_BN, [page], "")
    assert prompt.count("x" * 50) > 30


# ── language ─────────────────────────────────────────────────────────────────

def test_one_language_for_the_whole_document():
    template = DOCUMENT_TEMPLATES["tender_summary"]
    english = build_section_prompt(template, template.sections[0], PROJECT_BN, [], "")
    bangla = build_section_prompt(template, template.sections[0], PROJECT_BN, [], "", "Bangla")
    assert "in English" in english and "translate it faithfully" in english
    assert "in Bangla" in bangla
    # Anything else is treated as the default rather than passed to the model.
    assert "in English" in build_section_prompt(template, template.sections[0], PROJECT_BN, [], "", "Klingon")


def test_generation_refuses_an_unknown_language(make_workspace):
    service = DocumentGenerationService(retrieve=lambda *a: [], compose=lambda *a: "{}")
    with pytest.raises(ValueError, match="Unsupported language"):
        asyncio.run(service.generate(make_workspace("lang@example.com"), "p", "project_brief", language="French"))


# ── rendering ─────────────────────────────────────────────────────────────────

renderer = PdfDocumentRenderer()
needs_font = pytest.mark.skipif(not renderer.bengali_font, reason="no Bangla font on this machine")


def test_markup_sets_whole_bangla_words_in_the_bangla_font():
    if not renderer.bengali_font:
        assert renderer.markup("পদ্মা <x>") == "পদ্মা &lt;x&gt;"
        return
    marked = renderer.markup("Project: পদ্মা ভিউ, <PVH1>")
    assert f'<font face="{renderer.bengali_font}">পদ্মা</font>' in marked
    # Punctuation touching a Bangla word goes with it: HarfBuzz shapes a word in one font.
    assert f'<font face="{renderer.bengali_font}">ভিউ,</font>' in marked
    assert marked.startswith("Project: <font") and marked.endswith(" &lt;PVH1&gt;")
    assert renderer.bengali_bold_font in renderer.markup("শিরোনাম", bold=True)
    assert renderer.markup("Plain English") == "Plain English"


@needs_font
def test_a_bangla_title_and_section_are_drawn_with_a_bangla_font(tmp_path):
    out = tmp_path / "bn.pdf"
    section = SectionResult(key="overview", heading="Project Overview",
                            paragraphs=["প্রকল্পটি একটি হাসপাতাল সম্প্রসারণ, মোট চুক্তিমূল্য ৳৬০,০০,০০,০০০।"],
                            bullets=["Contract value: BDT 60,00,00,000"],
                            table_columns=["তলা", "Scope"], table_rows=[["নিচতলা", "Emergency entrance"]],
                            sources=[{"doc_id": "d1", "doc_name": "01_Prokolpo-Bibaroni_Project-Brief.pdf",
                                      "page": 1, "score": 0.0, "source_type": "project_document"}])
    renderer.render(out, f"Project Brief - {PROJECT_BN['name']}", DOCUMENT_TEMPLATES["project_brief"],
                    PROJECT_BN, [section], "2026-09-30T04:32:00+00:00")
    fonts = _fonts_in(out)
    assert any(renderer.bengali_font.split("-")[0].lower() in font.lower().replace(" ", "")
               or "nirmala" in font.lower() or "bengali" in font.lower() for font in fonts), fonts
    import fitz

    with fitz.open(str(out)) as document:
        text = "\n".join(page.get_text() for page in document)
    assert "retrieval score" not in text          # a normalised 0.000 misleads; it is not printed
    assert "01_Prokolpo-Bibaroni_Project-Brief.pdf, page 1" in text


@needs_font
def test_bangla_is_shaped_when_harfbuzz_is_available():
    pytest.importorskip("uharfbuzz")
    assert renderer.shaping is True


def test_the_language_reaches_the_record(make_workspace):
    pages = [{"doc_id": "d", "doc_name": "Brief.pdf", "page": 1, "text_content": "Scope text", "score": 0.9}]
    prompts = []

    def compose(prompt, _pages):
        prompts.append(prompt)
        return json.dumps({"paragraphs": ["বাংলা অনুচ্ছেদ"], "used_sources": [1]})

    service = DocumentGenerationService(retrieve=lambda *a: pages, compose=compose)
    record = asyncio.run(service.generate(make_workspace("record@example.com"), "p-bn", "project_brief",
                                          project=PROJECT_BN, language="Bangla"))
    assert record["language"] == "Bangla"
    assert all("in Bangla" in prompt for prompt in prompts)
    assert re.search(r"Project Brief - পদ্মা", record["title"])


@needs_font
def test_a_pdf_drawn_before_bangla_worked_is_redrawn_from_its_own_text(make_workspace):
    """No retrieval and no model call: the stored sections are drawn again, once."""
    pages = [{"doc_id": "d", "doc_name": "Brief.pdf", "page": 1, "text_content": "x", "score": 0.9}]
    calls = []

    def compose(prompt, _pages):
        calls.append(prompt)
        return json.dumps({"paragraphs": ["পদ্মা ভিউ একটি হাসপাতাল সম্প্রসারণ প্রকল্প।"], "used_sources": [1]})

    workspace = make_workspace("redraw@example.com")
    service = DocumentGenerationService(retrieve=lambda *a: pages, compose=compose)
    record = asyncio.run(service.generate(workspace, "p-bn", "project_brief", project=PROJECT_BN))
    # Pretend it was made by the old renderer: Arial only, no render_version.
    registry = workspace.load_generated()
    old = {k: v for k, v in registry[record["id"]].items() if k != "render_version"}
    registry[record["id"]] = old
    workspace.save_generated(registry)
    Path(old["file_path"]).write_bytes(b"%PDF-1.4 old")
    made = len(calls)

    refreshed = service.refresh_rendering(workspace, record["id"])
    assert refreshed["render_version"] == renderer.render_version and "rerendered_at" in refreshed
    assert len(calls) == made                                    # the model was not asked again
    assert Path(old["file_path"]).stat().st_size > 10_000
    assert any("nirmala" in font.lower() or "bengali" in font.lower() for font in _fonts_in(Path(old["file_path"])))
    again = service.refresh_rendering(workspace, record["id"])
    assert again["rerendered_at"] == refreshed["rerendered_at"]  # drawn once, not on every download


def test_the_renderer_says_why_bangla_cannot_be_drawn():
    status = renderer.bangla_status()
    assert set(status) == {"ready", "font", "detail"}
    if not status["ready"]:
        assert "uharfbuzz" in status["detail"] or "font" in status["detail"]
