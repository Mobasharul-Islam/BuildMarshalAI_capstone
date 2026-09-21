"""PDF-grounded project document generation for BuildMarshalAI.

The module is intentionally independent from the Kaggle notebook globals.  The
core service can be tested locally with fake retrieval/composition callbacks,
while ``register_kaggle_routes`` adapts it to the notebook's ColPali,
ChromaDB, Qwen2.5-VL, metadata, and FastAPI objects.
"""

import asyncio
import gc
import html
import inspect
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


RetrieveCallback = Callable[[str, str, int, Any], Sequence[Mapping[str, Any]]]
ComposeCallback = Callable[[str, Sequence[Mapping[str, Any]]], str | Awaitable[str]]

DOCGEN_MAX_TOKENS = min(
    4096,
    max(2048, int(os.environ.get("BUILDMARSHAL_DOCGEN_MAX_TOKENS", "3072"))),
)


class GenerateDocumentRequest(BaseModel):
    doc_kind: str = "tender_summary"
    title: str | None = None
    instructions: str = ""
    top_k_per_section: int = Field(default=6, ge=1, le=12)


@dataclass(frozen=True)
class SectionSpec:
    key: str
    heading: str
    query: str
    instruction: str


@dataclass(frozen=True)
class DocumentTemplate:
    kind: str
    label: str
    description: str
    sections: tuple[SectionSpec, ...]


@dataclass
class SectionResult:
    key: str
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    table_columns: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    warning: str | None = None


DOCUMENT_TEMPLATES: dict[str, DocumentTemplate] = {
    "tender_summary": DocumentTemplate(
        kind="tender_summary",
        label="Tender Summary",
        description="Consolidated tender requirements, scope, dates, revisions, and clarifications.",
        sections=(
            SectionSpec(
                "project_overview",
                "Project Overview",
                "project name location owner tender purpose modernization overview",
                "Identify the project, location, purpose, client, and tender context.",
            ),
            SectionSpec(
                "submission_requirements",
                "Submission Requirements",
                "tender submission closing deadline proposal requirements mandatory documents",
                "Summarize deadlines, delivery method, mandatory submission content, and proponent obligations.",
            ),
            SectionSpec(
                "scope",
                "Scope of Services",
                "construction management scope services preconstruction construction responsibilities exclusions",
                "Summarize the requested services and material scope boundaries without inventing missing work.",
            ),
            SectionSpec(
                "schedule",
                "Schedule and Milestones",
                "preliminary project schedule dates milestones tender award construction completion procurement",
                "List important dates and milestones. Preserve the exact dates shown in the evidence.",
            ),
            SectionSpec(
                "addenda",
                "Addenda and Revisions",
                "tender addendum revision supersede extension change allowance revised drawings",
                "Describe revisions in date/version order. Later addenda take precedence over original tender information.",
            ),
            SectionSpec(
                "clarifications",
                "Questions and Clarifications",
                "tender RFI question response clarification bidder question answer",
                "Summarize issued questions and responses, including allowances or conditions stated in the answers.",
            ),
            SectionSpec(
                "risks",
                "Risks, Gaps, and Follow-up",
                "risk unclear not specified bidder responsibility coordination conflict tender documents",
                "Identify only evidence-backed ambiguities, missing information, coordination needs, and follow-up items.",
            ),
        ),
    ),
    "project_brief": DocumentTemplate(
        kind="project_brief",
        label="Project Brief",
        description="High-level project purpose, scope, schedule, stakeholders, and constraints.",
        sections=(
            SectionSpec("overview", "Project Overview", "project overview name location owner purpose", "Explain what the project is and why it is being undertaken."),
            SectionSpec("scope", "Scope Summary", "project scope work services renovation areas", "Summarize the main work areas, services, and boundaries."),
            SectionSpec("schedule", "Schedule Summary", "project schedule milestones start finish construction tender", "Summarize the baseline timeline and major milestones."),
            SectionSpec("constraints", "Constraints and Logistics", "site logistics access storage phasing occupied hotel constraints", "Describe access, logistics, phasing, operational, and site constraints."),
            SectionSpec("decisions", "Key Requirements and Decisions", "mandatory requirement allowance decision approval responsibility", "List important requirements, allowances, approvals, and decisions."),
        ),
    ),
    "schedule_summary": DocumentTemplate(
        kind="schedule_summary",
        label="Schedule Summary",
        description="Narrative and tabular summary of the project baseline schedule.",
        sections=(
            SectionSpec("overall", "Overall Timeline", "overall project schedule start finish duration", "State the overall date range and duration."),
            SectionSpec("milestones", "Major Milestones", "project schedule milestone zero days tender award construction start completion", "Extract major milestones and exact dates."),
            SectionSpec("phases", "Principal Phases", "schedule design procurement tender construction mobilization closeout phases", "Summarize principal phases in chronological order."),
            SectionSpec("dependencies", "Dependencies and Constraints", "schedule dependency predecessor procurement lead time shutdown holiday constraint", "Identify visible schedule dependencies and constraints only when evidenced."),
        ),
    ),
    "addendum_summary": DocumentTemplate(
        kind="addendum_summary",
        label="Addendum Summary",
        description="Chronological register of tender changes and clarifications.",
        sections=(
            SectionSpec("register", "Addendum Register", "addendum number date issued tender", "List each addendum number, date, and purpose."),
            SectionSpec("deadlines", "Revised Deadlines", "addendum revised extension deadline tender closing questions", "List revised deadlines, favoring the latest dated revision."),
            SectionSpec("scope_changes", "Scope and Commercial Changes", "addendum scope revision allowance price include exclude", "Summarize scope, allowance, and commercial changes."),
            SectionSpec("q_and_a", "Questions and Responses", "addendum RFI question response bidder", "Summarize questions and their issued responses."),
            SectionSpec("superseded", "Superseded Information", "addendum supersede original replaced revised drawing", "State what earlier information is explicitly superseded or replaced."),
        ),
    ),
}


def list_document_templates() -> list[dict[str, str]]:
    return [
        {"kind": item.kind, "label": item.label, "description": item.description}
        for item in DOCUMENT_TEMPLATES.values()
    ]


def classify_source_document(filename: str) -> str:
    name = filename.lower()
    if "addendum" in name:
        return "tender_addendum"
    if "schedule" in name:
        return "schedule"
    if "scope" in name or "schedule a1" in name:
        return "scope"
    if "storage" in name or "logistic" in name or "laydown" in name:
        return "site_logistics"
    if re.search(r"(^|[\\/_ -])[amse]\d", name) or "drawing" in name or "plan" in name:
        return "drawing"
    if "ccdc" in name or "agreement" in name:
        return "contract"
    if "tender" in name or "rft" in name:
        return "tender"
    return "project_document"


def extract_pdf_page_texts(path: str | Path) -> list[str]:
    """Extract text per page while preserving a stable page-number mapping."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard for Kaggle
        raise RuntimeError("pypdf is required for PDF-grounded generation") from exc

    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def _json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _clean_text(value: Any, limit: int = 6000) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:limit]


def _json_array_field(text: str, field_name: str) -> list[Any]:
    """Recover a valid JSON array field from an otherwise malformed object."""
    match = re.search(rf'"{re.escape(field_name)}"\s*:\s*\[', text)
    if not match:
        return []
    start = match.end() - 1
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start : index + 1])
                    return value if isinstance(value, list) else []
                except json.JSONDecodeError:
                    return []
    return []


def _partial_json_string_field(text: str, field_name: str) -> str:
    """Recover the beginning of a string when generation stops mid-JSON."""
    match = re.search(rf'"{re.escape(field_name)}"\s*:\s*\[\s*"', text)
    if not match:
        return ""
    start = match.end()
    escaped = False
    end = len(text)
    for index in range(start, len(text)):
        character = text[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            end = index
            break
    fragment = text[start:end]
    fragment = re.sub(r"```(?:json)?\s*$", "", fragment, flags=re.IGNORECASE).rstrip()
    if fragment.endswith("\\"):
        fragment = fragment[:-1]
    try:
        recovered = json.loads(f'"{fragment}"')
    except json.JSONDecodeError:
        recovered = fragment.replace(r"\n", " ").replace(r'\"', '"').replace(r"\\", "\\")
    return _clean_text(str(recovered).replace("**", ""))


def _normalise_source(page: Mapping[str, Any], source_number: int) -> dict[str, Any]:
    return {
        "source_number": source_number,
        "doc_id": str(page.get("doc_id", "")),
        "doc_name": str(page.get("doc_name", "Unknown document")),
        "page": int(page.get("page", page.get("page_num", 1)) or 1),
        "score": float(page.get("score", 0.0) or 0.0),
        "source_type": str(page.get("source_type", "project_document")),
    }


def parse_section_response(
    raw: str,
    spec: SectionSpec,
    pages: Sequence[Mapping[str, Any]],
) -> SectionResult:
    parsed = _json_object(raw)
    if parsed is None:
        repaired_paragraphs = _json_array_field(raw, "paragraphs")
        repaired_bullets = _json_array_field(raw, "bullets")
        partial_paragraph = _partial_json_string_field(raw, "paragraphs")
        if not repaired_paragraphs and partial_paragraph:
            repaired_paragraphs = [partial_paragraph]
        if repaired_paragraphs or repaired_bullets:
            parsed = {
                "paragraphs": repaired_paragraphs,
                "bullets": repaired_bullets,
                "used_sources": _json_array_field(raw, "used_sources"),
                "warning": "The model response contained malformed or truncated JSON; valid narrative fields were recovered.",
            }
        else:
            paragraphs = [_clean_text(raw)] if _clean_text(raw) else []
            used = list(range(1, min(3, len(pages)) + 1))
            return SectionResult(
                key=spec.key,
                heading=spec.heading,
                paragraphs=paragraphs or ["No supported information was found in the selected source documents."],
                sources=[_normalise_source(pages[i - 1], i) for i in used],
                warning="The model returned unstructured text; the section was preserved as a paragraph.",
            )

    paragraphs = parsed.get("paragraphs", [])
    if isinstance(paragraphs, str):
        paragraphs = [paragraphs]
    bullets = parsed.get("bullets", [])
    if isinstance(bullets, str):
        bullets = [bullets]

    table = parsed.get("table") if isinstance(parsed.get("table"), dict) else {}
    columns = [_clean_text(x, 120) for x in table.get("columns", [])]
    rows: list[list[str]] = []
    for row in table.get("rows", []):
        if isinstance(row, (list, tuple)):
            rows.append([_clean_text(cell, 500) for cell in row])

    used_sources = parsed.get("used_sources", [])
    valid_numbers: list[int] = []
    for item in used_sources if isinstance(used_sources, list) else []:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= len(pages) and number not in valid_numbers:
            valid_numbers.append(number)
    if not valid_numbers and pages:
        valid_numbers = list(range(1, min(3, len(pages)) + 1))

    clean_paragraphs = [_clean_text(x) for x in paragraphs if _clean_text(x)]
    clean_bullets = [
        re.sub(r"^[\s\-•]+", "", _clean_text(x, 2000))
        for x in bullets if _clean_text(x)
    ]
    if not clean_paragraphs and not clean_bullets and not rows:
        clean_paragraphs = ["No supported information was found in the selected source documents."]

    return SectionResult(
        key=spec.key,
        heading=spec.heading,
        paragraphs=clean_paragraphs,
        bullets=clean_bullets,
        table_columns=columns,
        table_rows=rows,
        sources=[_normalise_source(pages[number - 1], number) for number in valid_numbers],
        warning=_clean_text(parsed.get("warning"), 1000) or None,
    )


def build_section_prompt(
    template: DocumentTemplate,
    spec: SectionSpec,
    project: Mapping[str, Any],
    pages: Sequence[Mapping[str, Any]],
    instructions: str,
) -> str:
    project_name = project.get("name") or project.get("project_code") or project.get("id") or "Selected project"
    evidence: list[str] = []
    for index, page in enumerate(pages, 1):
        # Keep the composed section prompt small enough for Qwen2.5-VL's
        # eager-attention path on a 16 GB T4. Retrieval has already selected
        # the relevant page, so a focused excerpt is preferable to repeating
        # several full pages in every section call.
        text = _clean_text(page.get("text_content", ""), 900)
        evidence.append(
            f"[S{index}] {page.get('doc_name', 'Unknown document')}, "
            f"page {page.get('page', page.get('page_num', 1))}, "
            f"type={page.get('source_type', 'project_document')}\n{text or '[Visual page - inspect the attached image]'}"
        )

    return f"""Create the section \"{spec.heading}\" for a {template.label} about {project_name}.

Section instruction: {spec.instruction}
Additional user instruction: {instructions or 'None'}

Rules:
1. Use only the evidence below and any attached source-page images.
2. Do not invent dates, requirements, parties, costs, status, or scope.
3. Later dated addenda supersede conflicting earlier tender information.
4. If evidence is insufficient, say what is not available.
5. Keep the complete response under 250 words; do not add comments, markdown fences, or extra keys.
6. Return JSON only using this schema:
{{
  "paragraphs": ["one or more concise evidence-backed paragraphs"],
  "bullets": ["optional evidence-backed bullet"],
  "table": {{"columns": ["optional"], "rows": [["optional"]]}},
  "used_sources": [1, 2],
  "warning": null
}}

Evidence:
{chr(10).join(evidence) if evidence else '[No relevant evidence was retrieved]'}
"""


class PdfDocumentRenderer:
    """Render typed document blocks into a polished, cited PDF."""

    def __init__(self) -> None:
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("reportlab is required for PDF rendering") from exc

        candidates = [
            ("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            ("Arial", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        ]
        self.font_name, self.bold_font_name = "Helvetica", "Helvetica-Bold"
        for family, regular, bold in candidates:
            if Path(regular).exists() and Path(bold).exists():
                pdfmetrics.registerFont(TTFont(family, regular))
                pdfmetrics.registerFont(TTFont(f"{family}-Bold", bold))
                self.font_name, self.bold_font_name = family, f"{family}-Bold"
                break

    #: What the cover and footer say a document is grounded in.  A document
    #: generated from source PDFs cites them; a report generated from the
    #: workspace's own records cites those, so callers may say which.
    EVIDENCE_POLICY = "Only project-linked source PDFs; citations identify document and page."
    FOOTER_NOTE = "BuildMarshalAI - evidence-grounded project document"

    def render(
        self,
        output_path: str | Path,
        title: str,
        template: DocumentTemplate,
        project: Mapping[str, Any],
        sections: Sequence[SectionResult],
        generated_at: str,
        evidence_policy: str | None = None,
        footer_note: str | None = None,
    ) -> None:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            LongTable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        styles = getSampleStyleSheet()
        navy, blue, muted, line, panel = colors.HexColor("#17324D"), colors.HexColor("#2F6B9A"), colors.HexColor("#5B6975"), colors.HexColor("#D8E0E7"), colors.HexColor("#F3F6F8")
        title_style = ParagraphStyle("BMTitle", parent=styles["Title"], fontName=self.bold_font_name, fontSize=25, leading=30, textColor=navy, alignment=TA_CENTER, spaceAfter=14)
        subtitle_style = ParagraphStyle("BMSub", parent=styles["Normal"], fontName=self.font_name, fontSize=11, leading=16, textColor=muted, alignment=TA_CENTER, spaceAfter=10)
        h1 = ParagraphStyle("BMH1", parent=styles["Heading1"], fontName=self.bold_font_name, fontSize=15, leading=19, textColor=navy, spaceBefore=13, spaceAfter=7)
        body = ParagraphStyle("BMBody", parent=styles["BodyText"], fontName=self.font_name, fontSize=9.5, leading=14, textColor=colors.HexColor("#24313D"), spaceAfter=7)
        bullet = ParagraphStyle("BMBullet", parent=body, leftIndent=12, firstLineIndent=-7, bulletIndent=2, spaceAfter=4)
        source_style = ParagraphStyle("BMSource", parent=body, fontSize=7.7, leading=10.5, textColor=muted, leftIndent=8, spaceAfter=2)
        warning_style = ParagraphStyle("BMWarn", parent=body, fontSize=8, leading=11, textColor=colors.HexColor("#8A4B08"), backColor=colors.HexColor("#FFF6E5"), borderPadding=6, spaceBefore=4, spaceAfter=7)
        table_header = ParagraphStyle("BMTableHeader", parent=body, fontName=self.bold_font_name, textColor=colors.white, spaceAfter=0)

        page_size = A4
        doc = SimpleDocTemplate(
            str(output_path), pagesize=page_size,
            rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
            title=title, author="BuildMarshalAI",
        )
        story: list[Any] = [Spacer(1, 25 * mm), Paragraph(html.escape(title), title_style)]
        story.append(Paragraph(html.escape(template.description), subtitle_style))
        project_rows = [
            ["Project", str(project.get("name") or project.get("id") or "Not specified")],
            ["Project code", str(project.get("project_code") or "Not specified")],
            ["Generated", generated_at],
            ["Evidence policy", evidence_policy or self.EVIDENCE_POLICY],
        ]
        metadata_table = Table(
            [[Paragraph(f"<b>{html.escape(k)}</b>", body), Paragraph(html.escape(v), body)] for k, v in project_rows],
            colWidths=[37 * mm, 115 * mm],
        )
        metadata_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), panel), ("GRID", (0, 0), (-1, -1), 0.4, line),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.extend([Spacer(1, 7 * mm), metadata_table, PageBreak()])

        all_sources: dict[tuple[str, int], dict[str, Any]] = {}
        for section_number, section in enumerate(sections, 1):
            story.append(Paragraph(f"{section_number}. {html.escape(section.heading)}", h1))
            for paragraph in section.paragraphs:
                story.append(Paragraph(html.escape(paragraph), body))
            for item in section.bullets:
                story.append(Paragraph(f"• {html.escape(item)}", bullet))
            if section.table_columns and section.table_rows:
                width = 164 * mm
                col_count = len(section.table_columns)
                data = [[Paragraph(html.escape(col), table_header) for col in section.table_columns]]
                for row in section.table_rows:
                    fitted = list(row[:col_count]) + [""] * max(0, col_count - len(row))
                    data.append([Paragraph(html.escape(cell), body) for cell in fitted])
                table = LongTable(data, colWidths=[width / col_count] * col_count, repeatRows=1)
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.35, line), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, panel]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.extend([Spacer(1, 3), table, Spacer(1, 5)])
            if section.warning:
                story.append(Paragraph(f"Note: {html.escape(section.warning)}", warning_style))
            if section.sources:
                story.append(Paragraph("<b>Section sources</b>", source_style))
                for source in section.sources:
                    key = (source["doc_id"] or source["doc_name"], source["page"])
                    all_sources[key] = source
                    story.append(Paragraph(
                        f"{html.escape(source['doc_name'])}, page {source['page']} "
                        f"(retrieval score {source['score']:.3f})", source_style,
                    ))
            story.append(Spacer(1, 5))

        story.extend([PageBreak(), Paragraph("Source Register", h1)])
        if all_sources:
            source_rows = [["Document", "Page", "Type"]]
            for source in sorted(all_sources.values(), key=lambda s: (s["doc_name"].lower(), s["page"])):
                source_rows.append([source["doc_name"], str(source["page"]), source["source_type"]])
            source_table = LongTable(
                [[Paragraph(html.escape(cell), table_header) if row_index == 0 else Paragraph(html.escape(cell), body) for cell in row] for row_index, row in enumerate(source_rows)],
                colWidths=[112 * mm, 18 * mm, 34 * mm], repeatRows=1,
            )
            source_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, line), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, panel]),
            ]))
            story.append(source_table)
        else:
            story.append(Paragraph("No source pages were available.", body))

        def footer(canvas: Any, document: Any) -> None:
            canvas.saveState()
            canvas.setStrokeColor(line)
            canvas.line(18 * mm, 12 * mm, page_size[0] - 18 * mm, 12 * mm)
            canvas.setFont(self.font_name, 7.5)
            canvas.setFillColor(muted)
            canvas.drawString(18 * mm, 8 * mm, footer_note or self.FOOTER_NOTE)
            canvas.drawRightString(page_size[0] - 18 * mm, 8 * mm, f"Page {document.page}")
            canvas.restoreState()

        doc.build(story, onFirstPage=footer, onLaterPages=footer)


class DocumentGenerationService:
    def __init__(
        self,
        retrieve: RetrieveCallback,
        compose: ComposeCallback,
        renderer: PdfDocumentRenderer | None = None,
    ) -> None:
        # The service is stateless with respect to storage: the output
        # directory and the registry both come from the workspace of whichever
        # account asked for the document.
        self.retrieve = retrieve
        self.compose = compose
        self.renderer = renderer or PdfDocumentRenderer()

    @staticmethod
    def _load_registry(workspace: Any) -> dict[str, dict[str, Any]]:
        path = Path(workspace.generated_registry)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _save_registry(workspace: Any, registry: Mapping[str, Any]) -> None:
        path = Path(workspace.generated_registry)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def get_record(self, workspace: Any, generated_id: str) -> dict[str, Any] | None:
        return self._load_registry(workspace).get(generated_id)

    async def generate(
        self,
        workspace: Any,
        project_id: str,
        doc_kind: str,
        project: Mapping[str, Any] | None = None,
        title: str | None = None,
        instructions: str = "",
        top_k_per_section: int = 6,
        compose: ComposeCallback | None = None,
    ) -> dict[str, Any]:
        template = DOCUMENT_TEMPLATES.get(doc_kind)
        if template is None:
            raise ValueError(f"Unsupported document kind: {doc_kind}")
        project = dict(project or {"id": project_id, "name": project_id})
        top_k_per_section = max(1, min(int(top_k_per_section), 12))
        sections: list[SectionResult] = []
        for spec in template.sections:
            pages = list(self.retrieve(spec.query, project_id, top_k_per_section, workspace))
            if not pages:
                sections.append(SectionResult(
                    key=spec.key,
                    heading=spec.heading,
                    paragraphs=["No relevant information was found in the project-linked source PDFs."],
                    warning="This section requires additional or better-indexed source documents.",
                ))
                continue
            prompt = build_section_prompt(template, spec, project, pages, instructions)
            # A per-request composer keeps concurrent generations for different
            # accounts from sharing mutable state on the service instance.
            raw = (compose or self.compose)(prompt, pages)
            if inspect.isawaitable(raw):
                raw = await raw
            sections.append(parse_section_response(str(raw), spec, pages))

        generated_id = uuid.uuid4().hex[:16]
        generated_at = datetime.now(timezone.utc).isoformat()
        resolved_title = title or f"{template.label} - {project.get('name') or project_id}"
        output_dir = Path(workspace.generated_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{generated_id}.pdf"
        self.renderer.render(output_path, resolved_title, template, project, sections, generated_at)
        source_count = len({(s["doc_id"], s["page"]) for section in sections for s in section.sources})
        warnings = [section.warning for section in sections if section.warning]
        record = {
            "id": generated_id,
            "account_id": getattr(workspace, "account_id", None),
            "project_id": project_id,
            "doc_kind": doc_kind,
            "format": "pdf",
            "title": resolved_title,
            "status": "ready",
            "created_at": generated_at,
            "file_path": str(output_path),
            "download_url": f"/api/generated-documents/{generated_id}/download",
            "document_path": None,
            "section_count": len(sections),
            "source_page_count": source_count,
            "warnings": warnings,
            "sections": [asdict(section) for section in sections],
        }
        registry = self._load_registry(workspace)
        registry[generated_id] = record
        self._save_registry(workspace, registry)
        return record


def register_kaggle_routes(namespace: Mapping[str, Any]) -> DocumentGenerationService:
    """Register project-source and document-generation routes in the notebook.

    Call this after the notebook has created ``app``, the ColPali embedding
    functions, ``vl_generate``, and the account system, so every route can
    resolve the caller's workspace.
    """
    required = [
        "app", "ingest_document", "embed_query", "vl_generate", "require_account",
    ]
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Notebook integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    ingest_document = namespace["ingest_document"]
    embed_query = namespace["embed_query"]
    hybrid_retrieve = namespace.get("retrieve_context")
    vl_generate = namespace["vl_generate"]
    require_account = namespace["require_account"]
    torch_module = namespace.get("torch")

    def qwen_safe_image(image_path: str, workspace: Any) -> str:
        """Cache a compact visual fallback inside the account's workspace."""
        from PIL import Image

        source = Path(image_path)
        cache_dir = Path(workspace.vision_cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"{source.stem}_512.jpg"
        if not target.exists():
            with Image.open(source) as image:
                image = image.convert("RGB")
                image.thumbnail((512, 512))
                image.save(target, "JPEG", quality=88, optimize=True)
        return str(target)

    def retrieve_project_pages(
        query: str, project_id: str, top_k: int, workspace: Any
    ) -> list[dict[str, Any]]:
        if callable(hybrid_retrieve):
            return list(hybrid_retrieve(
                query, top_k=top_k, project_id=project_id, workspace=workspace
            ))
        collection = workspace.collection
        if collection.count() == 0:
            return []
        vector = embed_query(query)
        if vector is None:
            return []
        try:
            result = collection.query(
                query_embeddings=[vector.tolist()],
                n_results=min(max(top_k, 1), collection.count()),
                where={"project_id": project_id},
                include=["metadatas", "documents", "distances"],
            )
        except Exception:
            return []
        pages: list[dict[str, Any]] = []
        documents = (result.get("documents") or [[]])[0]
        for index, (metadata, distance) in enumerate(zip(result["metadatas"][0], result["distances"][0])):
            pages.append({
                "doc_name": metadata.get("doc_name", "Unknown document"),
                "doc_id": metadata.get("doc_id", ""),
                "page": int(metadata.get("page_num", 1)),
                "image_path": workspace.resolve_page_path(metadata.get("image_path", "")),
                "text_content": documents[index] if index < len(documents) else metadata.get("text_content", ""),
                "source_type": metadata.get("source_type", "project_document"),
                "score": round(1.0 - float(distance), 4),
            })
        return pages

    def compose_factory(workspace: Any) -> ComposeCallback:
        """Bind the composer to one account so cached vision tiles stay separate."""

        async def compose_with_qwen(prompt: str, pages: Sequence[Mapping[str, Any]]) -> str:
            content: list[dict[str, str]] = []
            # Extracted PDF text is already embedded in ``prompt``.  Sending the
            # same textual pages as images wastes thousands of vision tokens and
            # can exhaust a T4 during attention.  Keep multimodal support for
            # scanned/drawing pages, but attach only the first page that has no
            # usable text.
            visual_pages = [page for page in pages if not _clean_text(page.get("text_content", ""), 80)]
            for page in visual_pages[:1]:
                image_path = str(page.get("image_path", ""))
                if image_path and os.path.exists(image_path):
                    content.append({"type": "image", "image": qwen_safe_image(image_path, workspace)})
            content.append({"type": "text", "text": prompt})
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are BuildMarshalAI's evidence-grounded construction document composer. "
                        "Use only supplied sources, obey source precedence, and return valid JSON only."
                    ),
                },
                {"role": "user", "content": content},
            ]
            loop = asyncio.get_running_loop()
            try:
                return await loop.run_in_executor(
                    None,
                    lambda: vl_generate(messages, max_new_tokens=DOCGEN_MAX_TOKENS),
                )
            finally:
                if torch_module is not None and getattr(torch_module, "cuda", None) is not None:
                    gc.collect()
                    torch_module.cuda.empty_cache()

        return compose_with_qwen

    async def compose_for_request(prompt: str, pages: Sequence[Mapping[str, Any]]) -> str:
        raise RuntimeError("Document composition must be bound to an account workspace")

    service = DocumentGenerationService(
        retrieve=retrieve_project_pages,
        compose=compose_for_request,
    )

    def project_or_404(workspace: Any, project_id: str) -> dict[str, Any]:
        project = workspace.load_projects().get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @app.get("/api/document-templates")
    async def document_templates(context=Depends(require_account)) -> dict[str, Any]:
        return {"templates": list_document_templates()}

    @app.post("/api/projects/{project_id}/source-documents")
    async def upload_project_source(
        project_id: str,
        file: UploadFile = File(...),
        doc_id: str | None = Form(None),
        context=Depends(require_account),
    ) -> dict[str, Any]:
        workspace = context.workspace
        project_or_404(workspace, project_id)
        safe_name = Path(file.filename or "source.pdf").name
        if Path(safe_name).suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Project document generation currently accepts PDF sources only")
        doc_id = re.sub(r"[^A-Za-z0-9._-]+", "", str(doc_id or "")).strip("._-")[:64] or uuid.uuid4().hex[:12]
        save_path = Path(workspace.docs_dir) / f"{doc_id}.pdf"
        with save_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                destination.write(chunk)
        doc_meta = ingest_document(save_path, doc_id, workspace)
        texts = extract_pdf_page_texts(save_path)
        source_type = classify_source_document(safe_name)
        metadata = workspace.load_metadata()
        stored = metadata["documents"][doc_id]
        stored.update({"name": safe_name, "project_id": project_id, "source_type": source_type})
        chroma_ids: list[str] = []
        chroma_metadata: list[dict[str, Any]] = []
        chroma_documents: list[str] = []
        for index, page in enumerate(stored.get("pages", [])):
            page_text = texts[index] if index < len(texts) else ""
            page["text_content"] = page_text
            page_number = int(page.get("page_num", index + 1))
            chroma_ids.append(f"{doc_id}_p{page_number}")
            chroma_metadata.append({
                "doc_id": doc_id, "doc_name": safe_name, "page_num": page_number,
                "image_path": page.get("image_path", ""), "text_content": page_text[:1000],
                "project_id": project_id, "source_type": source_type,
            })
            chroma_documents.append(page_text[:8000])
        workspace.save_metadata(metadata)
        if chroma_ids:
            # Chroma tries to invoke the collection embedding function whenever
            # documents are updated without embeddings.  This collection uses a
            # deliberate no-op embedding function because ColPali created the
            # vectors during ``ingest_document``.  Preserve those vectors while
            # enriching the records with project scope and extracted PDF text.
            collection = workspace.collection
            existing = collection.get(ids=chroma_ids, include=["embeddings"])
            vectors_by_id = {
                item_id: vector.tolist() if hasattr(vector, "tolist") else vector
                for item_id, vector in zip(existing.get("ids", []), existing.get("embeddings", []))
            }
            indexes = [index for index, item_id in enumerate(chroma_ids) if item_id in vectors_by_id]
            if indexes:
                collection.update(
                    ids=[chroma_ids[index] for index in indexes],
                    embeddings=[vectors_by_id[chroma_ids[index]] for index in indexes],
                    metadatas=[chroma_metadata[index] for index in indexes],
                    documents=[chroma_documents[index] for index in indexes],
                )
        return {
            "id": doc_id, "project_id": project_id, "name": safe_name,
            "source_type": source_type, "pages": doc_meta.get("page_count", len(texts)),
            "status": "indexed",
        }

    @app.get("/api/projects/{project_id}/source-documents")
    async def list_project_sources(project_id: str, context=Depends(require_account)) -> dict[str, Any]:
        documents = context.workspace.load_metadata().get("documents", {})
        selected = [document for document in documents.values() if document.get("project_id") == project_id]
        return {"documents": selected, "total": len(selected)}

    @app.post("/api/projects/{project_id}/documents", status_code=201)
    async def generate_project_document(
        project_id: str, request: GenerateDocumentRequest, context=Depends(require_account),
    ) -> dict[str, Any]:
        workspace = context.workspace
        project = project_or_404(workspace, project_id)
        if request.doc_kind not in DOCUMENT_TEMPLATES:
            raise HTTPException(status_code=422, detail=f"Unsupported document kind: {request.doc_kind}")
        try:
            record = await service.generate(
                workspace=workspace, project_id=project_id, doc_kind=request.doc_kind,
                project=project, title=request.title, instructions=request.instructions,
                top_k_per_section=request.top_k_per_section,
                compose=compose_factory(workspace),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Document generation failed: {exc}") from exc
        return {key: value for key, value in record.items() if key not in {"file_path", "sections"}}

    def owned_record(context: Any, generated_id: str) -> dict[str, Any]:
        record = service.get_record(context.workspace, generated_id)
        if not record:
            raise HTTPException(status_code=404, detail="Generated document not found")
        return record

    @app.get("/api/generated-documents/{generated_id}")
    async def generated_document_metadata(
        generated_id: str, context=Depends(require_account),
    ) -> dict[str, Any]:
        record = owned_record(context, generated_id)
        return {key: value for key, value in record.items() if key != "file_path"}

    @app.get("/api/generated-documents/{generated_id}/download")
    async def download_generated_document(
        generated_id: str, context=Depends(require_account),
    ) -> FileResponse:
        record = owned_record(context, generated_id)
        stored = Path(record.get("file_path", ""))
        # The registry is per-account, but re-check containment so a hand-edited
        # record can never turn into an arbitrary file read.
        if not context.workspace.contains(stored) or not stored.exists():
            raise HTTPException(status_code=404, detail="Generated document file not found")
        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", record["title"]).strip("_") + ".pdf"
        return FileResponse(str(stored), media_type="application/pdf", filename=filename)

    return service


__all__ = [
    "DOCUMENT_TEMPLATES", "DocumentGenerationService", "PdfDocumentRenderer",
    "build_section_prompt", "classify_source_document", "extract_pdf_page_texts",
    "list_document_templates", "parse_section_response", "register_kaggle_routes",
]
