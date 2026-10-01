# PDF-Grounded Document Generation

BuildMarshalAI can generate a new cited project document from PDFs linked to a project. This is different from chat Q&A: every document section has its own retrieval query, the Qwen model returns structured section content, and the backend renders and stores a reusable PDF.

## Runtime flow

```text
Project PDF upload
  -> PDF pages rendered and text extracted
  -> ColPali v1.2 embeds each page image on GPU 0
  -> ChromaDB stores the page vectors for project-filtered retrieval
  -> user selects a document template
  -> each template section runs project-filtered retrieval
  -> Qwen2.5-VL composes JSON from page images/text on GPU 1
  -> invalid source numbers and malformed JSON are handled
  -> ReportLab creates a cited PDF and source register
  -> generated document metadata and download URL are returned
```

## Supported templates

- `tender_summary`
- `project_brief`
- `schedule_summary`
- `addendum_summary`

The templates and service are implemented in `backend/document_generation.py`.

## API

All routes below require `Authorization: Bearer <session token>` and act on the
caller's account only. Sources, generated documents, and projects belong to that
account; an id from another account returns 404. See
[ACCOUNTS_AND_ISOLATION.md](ACCOUNTS_AND_ISOLATION.md).


Upload a document to a project (any type the Documents page accepts; a PDF's
text layer is also kept per page for generation). Existing documents are linked
rather than uploaded again; see
[PROJECT_SECTIONS.md](PROJECT_SECTIONS.md#project-documents):

```http
POST /api/projects/{project_id}/source-documents
Content-Type: multipart/form-data

file=<file>
```

List project sources:

```http
GET /api/projects/{project_id}/source-documents
```

## Language, evidence and Bangla

- **One language per document.** `language` is `English` (default) or `Bangla`.
  With English, Bangla evidence is translated and a person's, company's or
  place's name is followed by its Bangla form in brackets; with Bangla, the
  whole narrative is Bangla while codes, amounts and dates stay as written.
  Section headings come from the template and stay in English.
- **Fuller evidence.** Each retrieved page is quoted up to 4,000 characters
  (`BUILDMARSHAL_DOCGEN_PAGE_CHARS`, total `BUILDMARSHAL_DOCGEN_EVIDENCE_CHARS`
  = 24,000). A longer page -- a programme sheet -- is quoted by the lines that
  match the section, plus its opening lines, in page order, instead of its
  first few hundred characters.
- **Bangla text extraction.** PDF text is read with PyMuPDF, which keeps Bangla
  in reading order; pypdf returned vowel signs displaced (`িববরণী` for
  `বিবরণী`).
- **Bangla rendering.** Words containing Bangla are set in a Bangla font
  (Nirmala UI on Windows; Noto Sans Bengali or Lohit Bengali on Linux -- the
  Kaggle cell installs `fonts-noto-core`; `BUILDMARSHAL_BENGALI_FONT` overrides)
  and shaped with HarfBuzz (`uharfbuzz`), so conjuncts and vowel signs join.
  Before this, every Bangla word -- the project name in the title included --
  printed as blank space. The PDF's copy/search text layer for shaped Bangla is
  not reliable (a ReportLab limitation); what is printed is.
- Section sources list document and page. The retrieval score is kept in the
  record but not printed: scores are normalised within a section, so the
  weakest candidate always read 0.000 however relevant it was.

Generate a document:

```http
POST /api/projects/{project_id}/documents
Content-Type: application/json

{
  "doc_kind": "tender_summary",
  "language": "English",
  "title": null,
  "instructions": "Focus on revised deadlines and allowances",
  "top_k_per_section": 6
}
```

The response contains a stable generated-document ID and `download_url`:

```http
GET /api/generated-documents/{generated_id}/download
```

## Kaggle notebook integration

`backend/Dual_t4_Working_with_Document_Generation.ipynb` contains an integration cell immediately before the server-launch cell. It installs `reportlab` and `pypdf`, downloads the module from the `docgen-pipeline` branch, and calls:

```python
from document_generation import register_kaggle_routes
DOCUMENT_GENERATION_SERVICE = register_kaggle_routes(globals())
```

Run the notebook with the Kaggle `GPU T4 x2` accelerator and Internet enabled. The notebook keeps `vidore/colpali-v1.2` in FP16 on `cuda:0` and Qwen2.5-VL-7B-Instruct in 4-bit on `cuda:1`. The original `document_pages` ChromaDB collection is reused when Kaggle file persistence restores it.

## Evidence rules

- Retrieval is limited to the documents linked to the project (a document can be linked to several).
- Every generated section records its source document and page.
- A Qwen citation can reference only source numbers supplied in that section prompt.
- Later dated addenda are instructed to supersede conflicting original tender information.
- Missing evidence is reported explicitly instead of being invented.

## Tests

The local integration test copies two real PDFs from `D:\Capstone Project\Sample project pdfs`, extracts their page text, generates a cited PDF, verifies the registry, and reads the generated PDF back with `pypdf`.

```powershell
python -m pytest backend\tests\test_document_generation.py -q
```

The Kaggle integration run uses the preliminary schedule and Tender Addendum 02 as the initial two-document source set.
