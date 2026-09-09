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


Upload a PDF source to a project:

```http
POST /api/projects/{project_id}/source-documents
Content-Type: multipart/form-data

file=<pdf>
```

List project sources:

```http
GET /api/projects/{project_id}/source-documents
```

Generate a document:

```http
POST /api/projects/{project_id}/documents
Content-Type: application/json

{
  "doc_kind": "tender_summary",
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

- Retrieval is filtered by `project_id`.
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
