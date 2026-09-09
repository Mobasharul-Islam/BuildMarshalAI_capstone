"""
═══════════════════════════════════════════════════════════════════════
BuildMarshalAI — Kaggle Backend Server
═══════════════════════════════════════════════════════════════════════

Copy each section (marked with "# ═══ CELL N") into separate Kaggle
notebook cells and run them in order.

Architecture:
  1. Install deps
  2. Configure secrets & storage
  3. Initialize ColPali (Byaldi) model for visual document retrieval
  4. Document ingestion pipeline (PDF, Excel, Images, Word)
  5. Query pipeline (retrieve + Gemini multimodal generation)
  6. FastAPI application with all endpoints
  7. Launch ngrok tunnel + uvicorn server

Designed for Kaggle's free GPU tier (P100 16GB).
Uses colpali-v1.2 (lighter model to fit in memory).
"""


# ═══════════════════════════════════════════════════════════════════════
# CELL 1 — Install Dependencies
# ═══════════════════════════════════════════════════════════════════════
# Run this cell first. It may take 2-3 minutes.

# !pip install -q fastapi uvicorn[standard] pyngrok nest-asyncio \
#     byaldi google-genai python-multipart Pillow openpyxl pandas \
#     pdf2image python-docx torch

# !apt-get install -y poppler-utils  # Required by pdf2image


# ═══════════════════════════════════════════════════════════════════════
# CELL 2 — Configuration & Imports
# ═══════════════════════════════════════════════════════════════════════

import os
import json
import uuid
import time
import shutil
import base64
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from io import BytesIO
from datetime import datetime

import nest_asyncio
nest_asyncio.apply()

import torch
import pandas as pd
from PIL import Image
from pdf2image import convert_from_path
from openpyxl import load_workbook

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

from pyngrok import ngrok

# ── Logging ──
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger("BuildMarshalAI")

# ── Paths ──
BASE_DIR = Path("/kaggle/working/buildmarshal")
DOCS_DIR = BASE_DIR / "documents"
PAGES_DIR = BASE_DIR / "pages"       # Rendered page images
INDEX_DIR = BASE_DIR / "index"
META_FILE = BASE_DIR / "metadata.json"

for d in [BASE_DIR, DOCS_DIR, PAGES_DIR, INDEX_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Secrets ──
# Option A: Kaggle Secrets (recommended)
try:
    from kaggle_secrets import UserSecretsClient
    secrets = UserSecretsClient()
    GEMINI_API_KEY = secrets.get_secret("GEMINI_API_KEY")
    NGROK_AUTH_TOKEN = secrets.get_secret("NGROK_AUTH_TOKEN")
    logger.info("Loaded secrets from Kaggle Secrets")
except Exception:
    # Option B: Hardcode (NOT recommended for shared notebooks)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
    NGROK_AUTH_TOKEN = os.environ.get("NGROK_AUTH_TOKEN", "YOUR_NGROK_AUTH_TOKEN_HERE")
    logger.warning("Using environment variables or hardcoded keys. Consider using Kaggle Secrets.")

# ── Metadata Store ──
def load_metadata() -> Dict:
    if META_FILE.exists():
        return json.loads(META_FILE.read_text())
    return {"documents": {}}

def save_metadata(meta: Dict):
    META_FILE.write_text(json.dumps(meta, indent=2, default=str))


# ═══════════════════════════════════════════════════════════════════════
# CELL 3 — Initialize ColPali Model (Byaldi)
# ═══════════════════════════════════════════════════════════════════════

from byaldi import RAGMultiModalModel

logger.info("Loading ColPali model (colpali-v1.2) via Byaldi...")
logger.info(f"GPU Available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    logger.info(f"GPU: {torch.cuda.get_device_name(0)}")
    logger.info(f"GPU Memory: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB")

# Load the lighter model
RAG_MODEL = None
INDEX_LOADED = False

def init_rag_model():
    """Initialize or load the RAG model. Creates a new index if none exists."""
    global RAG_MODEL, INDEX_LOADED

    index_path = INDEX_DIR / ".byaldi"

    if index_path.exists():
        logger.info("Loading existing Byaldi index...")
        try:
            RAG_MODEL = RAGMultiModalModel.from_index(
                str(INDEX_DIR),
                verbose=1
            )
            INDEX_LOADED = True
            logger.info("Existing index loaded successfully!")
            return
        except Exception as e:
            logger.warning(f"Could not load existing index: {e}. Will create new one.")

    logger.info("Initializing fresh ColPali model...")
    RAG_MODEL = RAGMultiModalModel.from_pretrained(
        "vidore/colpali-v1.2",
        verbose=1
    )
    INDEX_LOADED = False
    logger.info("ColPali model loaded!")

init_rag_model()


# ═══════════════════════════════════════════════════════════════════════
# CELL 4 — Document Ingestion Pipeline
# ═══════════════════════════════════════════════════════════════════════

def process_pdf(file_path: Path, doc_id: str) -> List[Dict]:
    """Convert PDF pages to images and return page info."""
    logger.info(f"Processing PDF: {file_path.name}")
    pages = convert_from_path(str(file_path), dpi=200, fmt='png')
    page_infos = []

    for i, page_img in enumerate(pages):
        page_path = PAGES_DIR / f"{doc_id}_page_{i+1}.png"
        page_img.save(str(page_path), "PNG")
        page_infos.append({
            "page_num": i + 1,
            "image_path": str(page_path),
            "width": page_img.width,
            "height": page_img.height
        })

    logger.info(f"PDF processed: {len(pages)} pages extracted")
    return page_infos


def process_excel(file_path: Path, doc_id: str) -> List[Dict]:
    """
    Convert Excel sheets to images (render as table screenshots).
    Falls back to text extraction for Gemini context.
    """
    logger.info(f"Processing Excel: {file_path.name}")
    page_infos = []
    ext = file_path.suffix.lower()

    try:
        if ext == '.csv':
            dfs = {'Sheet1': pd.read_csv(str(file_path))}
        else:
            dfs = pd.read_excel(str(file_path), sheet_name=None)

        for sheet_name, df in dfs.items():
            # Create a visual representation of the spreadsheet
            # Render as an image using matplotlib
            try:
                import matplotlib
                matplotlib.use('Agg')
                import matplotlib.pyplot as plt

                fig_height = max(2, min(20, len(df) * 0.4 + 1))
                fig_width = max(4, min(20, len(df.columns) * 1.5 + 1))
                fig, ax = plt.subplots(figsize=(fig_width, fig_height))
                ax.axis('off')

                # Render table
                table_data = df.head(50).fillna('').astype(str)
                table = ax.table(
                    cellText=table_data.values,
                    colLabels=table_data.columns,
                    cellLoc='left',
                    loc='center'
                )
                table.auto_set_font_size(False)
                table.set_fontsize(8)
                table.scale(1, 1.3)

                # Style header
                for (row, col), cell in table.get_celld().items():
                    if row == 0:
                        cell.set_facecolor('#4472C4')
                        cell.set_text_props(color='white', fontweight='bold')
                    else:
                        cell.set_facecolor('#f0f0f0' if row % 2 == 0 else 'white')

                plt.title(f"{file_path.stem} — {sheet_name}", fontsize=10, fontweight='bold')
                plt.tight_layout()

                page_path = PAGES_DIR / f"{doc_id}_sheet_{sheet_name}.png"
                plt.savefig(str(page_path), dpi=150, bbox_inches='tight',
                           facecolor='white', edgecolor='none')
                plt.close(fig)

                page_infos.append({
                    "page_num": len(page_infos) + 1,
                    "image_path": str(page_path),
                    "sheet_name": sheet_name,
                    "text_content": df.head(100).to_string()
                })
            except Exception as e:
                logger.warning(f"Could not render sheet {sheet_name} as image: {e}")
                # Fallback: save text content only
                page_infos.append({
                    "page_num": len(page_infos) + 1,
                    "image_path": None,
                    "sheet_name": sheet_name,
                    "text_content": df.head(100).to_string()
                })

    except Exception as e:
        logger.error(f"Excel processing error: {e}")

    logger.info(f"Excel processed: {len(page_infos)} sheets extracted")
    return page_infos


def process_image(file_path: Path, doc_id: str) -> List[Dict]:
    """Store image directly as a page."""
    logger.info(f"Processing image: {file_path.name}")
    img = Image.open(str(file_path))

    # Convert to RGB if needed
    if img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGB')

    page_path = PAGES_DIR / f"{doc_id}_img.png"
    img.save(str(page_path), "PNG")

    return [{
        "page_num": 1,
        "image_path": str(page_path),
        "width": img.width,
        "height": img.height
    }]


def process_docx(file_path: Path, doc_id: str) -> List[Dict]:
    """Extract text from Word documents and render as image."""
    logger.info(f"Processing DOCX: {file_path.name}")
    from docx import Document as DocxDocument

    doc = DocxDocument(str(file_path))
    full_text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

    # Render text as image
    page_infos = []
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        # Split into pages of ~2000 chars
        chunk_size = 2000
        chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]

        for idx, chunk in enumerate(chunks):
            fig, ax = plt.subplots(figsize=(10, 14))
            ax.axis('off')
            ax.text(0.05, 0.95, chunk, transform=ax.transAxes,
                   fontsize=9, verticalalignment='top', fontfamily='monospace',
                   wrap=True)
            plt.title(f"{file_path.stem} — Page {idx+1}", fontsize=10, fontweight='bold')

            page_path = PAGES_DIR / f"{doc_id}_page_{idx+1}.png"
            plt.savefig(str(page_path), dpi=150, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            plt.close(fig)

            page_infos.append({
                "page_num": idx + 1,
                "image_path": str(page_path),
                "text_content": chunk
            })
    except Exception as e:
        logger.warning(f"Could not render DOCX as image: {e}")
        page_infos.append({
            "page_num": 1,
            "image_path": None,
            "text_content": full_text[:5000]
        })

    logger.info(f"DOCX processed: {len(page_infos)} pages")
    return page_infos


def ingest_document(file_path: Path, doc_id: str) -> Dict:
    """
    Main ingestion function. Processes document and adds to ColPali index.
    Returns document metadata.
    """
    ext = file_path.suffix.lower()
    meta = load_metadata()

    # Process based on file type
    if ext == '.pdf':
        pages = process_pdf(file_path, doc_id)
    elif ext in ('.xlsx', '.xls', '.csv'):
        pages = process_excel(file_path, doc_id)
    elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff'):
        pages = process_image(file_path, doc_id)
    elif ext in ('.doc', '.docx'):
        pages = process_docx(file_path, doc_id)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # Index pages with ColPali (only pages that have images)
    image_paths = [p["image_path"] for p in pages if p.get("image_path")]

    global INDEX_LOADED
    if image_paths:
        try:
            if not INDEX_LOADED:
                # First document — create index
                logger.info(f"Creating new index with {len(image_paths)} pages...")
                RAG_MODEL.index(
                    input_path=image_paths[0] if len(image_paths) == 1 else str(PAGES_DIR),
                    index_name="buildmarshal_index",
                    store_collection_with_index=False,
                    overwrite=True
                )
                INDEX_LOADED = True
            else:
                # Add to existing index
                logger.info(f"Adding {len(image_paths)} pages to existing index...")
                for img_path in image_paths:
                    try:
                        RAG_MODEL.add_to_index(
                            input_item=img_path,
                            store_collection_with_index=False
                        )
                    except Exception as e:
                        logger.warning(f"Could not add page to index: {e}")
        except Exception as e:
            logger.error(f"Indexing error: {e}")
            # Continue without index — Gemini can still use raw images

    # Save metadata
    doc_meta = {
        "id": doc_id,
        "name": file_path.name,
        "type": ext,
        "size": file_path.stat().st_size,
        "pages": pages,
        "page_count": len(pages),
        "status": "indexed",
        "created_at": datetime.now().isoformat()
    }
    meta["documents"][doc_id] = doc_meta
    save_metadata(meta)

    logger.info(f"Document ingested: {file_path.name} ({len(pages)} pages)")
    return doc_meta


# ═══════════════════════════════════════════════════════════════════════
# CELL 5 — Query Pipeline (Retrieve + Gemini)
# ═══════════════════════════════════════════════════════════════════════

from google import genai

# Initialize Gemini client
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

def retrieve_context(query: str, top_k: int = 5) -> List[Dict]:
    """
    Use ColPali (Byaldi) to find the most relevant document pages.
    Returns page info with image paths and scores.
    """
    if not INDEX_LOADED or RAG_MODEL is None:
        logger.warning("No index loaded — skipping retrieval")
        return []

    try:
        results = RAG_MODEL.search(query, k=top_k)
        meta = load_metadata()

        context_pages = []
        for result in results:
            # Find which document this page belongs to
            result_path = str(result.get("doc_id", result.get("page_id", "")))

            # Search metadata for matching page
            for doc_id, doc in meta["documents"].items():
                for page in doc["pages"]:
                    page_img = page.get("image_path", "")
                    if page_img and (result_path in page_img or str(result.doc_id) in page_img):
                        context_pages.append({
                            "doc_name": doc["name"],
                            "doc_id": doc_id,
                            "page": page["page_num"],
                            "image_path": page_img,
                            "text_content": page.get("text_content", ""),
                            "score": float(result.score) if hasattr(result, 'score') else 0.0
                        })
                        break

        # Deduplicate
        seen = set()
        unique_pages = []
        for p in context_pages:
            key = f"{p['doc_id']}_{p['page']}"
            if key not in seen:
                seen.add(key)
                unique_pages.append(p)

        return unique_pages[:top_k]

    except Exception as e:
        logger.error(f"Retrieval error: {e}")
        # Fallback: return all pages (up to top_k)
        return get_all_pages(top_k)


def get_all_pages(limit: int = 5) -> List[Dict]:
    """Fallback: return pages from metadata when retrieval fails."""
    meta = load_metadata()
    pages = []
    for doc_id, doc in meta["documents"].items():
        for page in doc["pages"]:
            pages.append({
                "doc_name": doc["name"],
                "doc_id": doc_id,
                "page": page["page_num"],
                "image_path": page.get("image_path", ""),
                "text_content": page.get("text_content", ""),
                "score": 0.0
            })
            if len(pages) >= limit:
                return pages
    return pages


def image_to_base64(image_path: str) -> Optional[str]:
    """Convert image file to base64 data URL."""
    try:
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/png;base64,{data}"
    except Exception:
        return None


async def generate_response(
    query: str,
    context_pages: List[Dict],
    history: List[Dict],
    model: str = "gemini-2.5-flash"
) -> Dict:
    """
    Generate a response using Gemini with multimodal context.
    Sends retrieved page images alongside the query.
    """
    # Build the content parts for Gemini
    contents = []

    # System instruction
    system_instruction = """You are BuildMarshalAI, an intelligent construction document assistant.
You help users understand and analyze their uploaded project documents including PDFs, spreadsheets, images, and drawings.

Guidelines:
- Answer based ONLY on the provided document context (images and text below).
- If the answer is not in the documents, say so clearly.
- Cite which document and page your answer comes from.
- Format your response with clear headers, bullet points, and tables when appropriate.
- Be precise and professional.
- If you see tables or spreadsheet data, format relevant data as markdown tables.
- If you see drawings or diagrams, describe what you observe in detail."""

    # Add conversation history
    history_text = ""
    if history:
        history_text = "\n\nPrevious conversation:\n"
        for msg in history[-6:]:  # Last 6 messages
            role = "User" if msg.get("role") == "user" else "Assistant"
            history_text += f"{role}: {msg.get('content', '')}\n"

    # Build content with images
    context_text = "\n\nRelevant document pages:"
    image_parts = []

    for i, page in enumerate(context_pages):
        context_text += f"\n[Source {i+1}: {page['doc_name']}, Page {page['page']}]"
        if page.get("text_content"):
            context_text += f"\nText content: {page['text_content'][:1000]}"

        # Load image for multimodal Gemini
        if page.get("image_path") and os.path.exists(page["image_path"]):
            try:
                img = Image.open(page["image_path"])
                image_parts.append(img)
            except Exception as e:
                logger.warning(f"Could not load image {page['image_path']}: {e}")

    # Compose the prompt
    full_prompt = f"{system_instruction}{history_text}{context_text}\n\nUser question: {query}"

    # Build contents list: images first, then text prompt
    contents = []
    for img in image_parts:
        contents.append(img)
    contents.append(full_prompt)

    try:
        response = gemini_client.models.generate_content(
            model=model,
            contents=contents
        )

        # Prepare sources for frontend
        sources = []
        for page in context_pages:
            source = {
                "doc_name": page["doc_name"],
                "page": page["page"],
                "score": page.get("score", 0.0),
                "image_url": None
            }
            # Convert image to base64 URL for frontend display
            if page.get("image_path"):
                source["image_url"] = image_to_base64(page["image_path"])
            sources.append(source)

        return {
            "response": response.text,
            "sources": sources
        }

    except Exception as e:
        logger.error(f"Gemini generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════
# CELL 6 — FastAPI Application
# ═══════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="BuildMarshalAI Backend",
    description="Context-aware document chatbot powered by ColPali + Gemini",
    version="1.0.0"
)

# CORS — allow all origins (frontend can be anywhere)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health Check ──
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "gpu_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "index_loaded": INDEX_LOADED,
        "documents_count": len(load_metadata().get("documents", {}))
    }


# ── Status ──
@app.get("/api/status")
async def get_status():
    meta = load_metadata()
    docs = meta.get("documents", {})
    total_pages = sum(d.get("page_count", 0) for d in docs.values())
    return {
        "documents_count": len(docs),
        "total_pages": total_pages,
        "index_loaded": INDEX_LOADED,
        "model": "colpali-v1.2"
    }


# ── Upload Document ──
@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    doc_id: str = Form(None)
):
    if not doc_id:
        doc_id = str(uuid.uuid4())[:12]

    # Validate file type
    ext = Path(file.filename).suffix.lower()
    allowed = {'.pdf', '.xlsx', '.xls', '.csv', '.png', '.jpg', '.jpeg',
               '.gif', '.webp', '.bmp', '.tiff', '.doc', '.docx'}
    if ext not in allowed:
        raise HTTPException(400, detail=f"Unsupported file type: {ext}")

    # Save file
    save_path = DOCS_DIR / f"{doc_id}{ext}"
    try:
        content = await file.read()
        save_path.write_bytes(content)
    except Exception as e:
        raise HTTPException(500, detail=f"Could not save file: {e}")

    # Start ingestion (runs synchronously for now; could be async with background tasks)
    try:
        doc_meta = ingest_document(save_path, doc_id)
        return {
            "id": doc_id,
            "name": file.filename,
            "pages": doc_meta["page_count"],
            "status": "indexed",
            "message": f"Document indexed with {doc_meta['page_count']} pages"
        }
    except Exception as e:
        logger.error(f"Ingestion error: {e}")
        return {
            "id": doc_id,
            "name": file.filename,
            "pages": 0,
            "status": "error",
            "message": str(e)
        }


# ── List Documents ──
@app.get("/api/documents")
async def list_documents():
    meta = load_metadata()
    docs = []
    for doc_id, doc in meta.get("documents", {}).items():
        docs.append({
            "id": doc_id,
            "name": doc["name"],
            "type": doc["type"],
            "size": doc.get("size", 0),
            "pages": doc.get("page_count", 0),
            "status": doc.get("status", "indexed"),
            "created_at": doc.get("created_at")
        })
    return {"documents": docs}


# ── Document Status ──
@app.get("/api/documents/{doc_id}/status")
async def document_status(doc_id: str):
    meta = load_metadata()
    doc = meta.get("documents", {}).get(doc_id)
    if not doc:
        raise HTTPException(404, detail="Document not found")
    return {
        "id": doc_id,
        "status": doc.get("status", "unknown"),
        "pages": doc.get("page_count", 0)
    }


# ── Delete Document ──
@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    meta = load_metadata()
    doc = meta.get("documents", {}).get(doc_id)
    if not doc:
        raise HTTPException(404, detail="Document not found")

    # Remove page images
    for page in doc.get("pages", []):
        img_path = page.get("image_path")
        if img_path and os.path.exists(img_path):
            os.remove(img_path)

    # Remove source file
    for f in DOCS_DIR.glob(f"{doc_id}*"):
        f.unlink()

    # Remove from metadata
    del meta["documents"][doc_id]
    save_metadata(meta)

    # Note: We can't easily remove from Byaldi index, so we rebuild on next restart
    return {"message": "Document deleted", "id": doc_id}


# ── Chat ──
@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    query = body.get("query", "").strip()
    history = body.get("history", [])
    model = body.get("model", "gemini-2.5-flash")
    top_k = min(body.get("top_k", 5), 20)

    if not query:
        raise HTTPException(400, detail="Query cannot be empty")

    # Step 1: Retrieve relevant document pages
    logger.info(f"Query: {query[:100]}...")
    context_pages = retrieve_context(query, top_k=top_k)
    logger.info(f"Retrieved {len(context_pages)} context pages")

    # Step 2: Generate response with Gemini
    result = await generate_response(query, context_pages, history, model=model)

    return result


# ── Serve page image ──
@app.get("/api/pages/{doc_id}/{page_num}")
async def get_page_image(doc_id: str, page_num: int):
    """Serve a document page image."""
    meta = load_metadata()
    doc = meta.get("documents", {}).get(doc_id)
    if not doc:
        raise HTTPException(404, detail="Document not found")

    for page in doc.get("pages", []):
        if page.get("page_num") == page_num:
            img_path = page.get("image_path")
            if img_path and os.path.exists(img_path):
                with open(img_path, "rb") as f:
                    img_data = f.read()
                return StreamingResponse(
                    BytesIO(img_data),
                    media_type="image/png"
                )

    raise HTTPException(404, detail="Page not found")


# ═══════════════════════════════════════════════════════════════════════
# CELL 6b — Management APIs (Trades, Vendors, Team Members)
# ═══════════════════════════════════════════════════════════════════════

MGMT_FILE = BASE_DIR / "management.json"

def load_mgmt() -> Dict:
    if MGMT_FILE.exists():
        return json.loads(MGMT_FILE.read_text())
    return {
        "trades": [
            {"id":"tr-1","name":"Carpentry","description":"-","status":"Active"},
            {"id":"tr-2","name":"Concrete","description":"-","status":"Active"},
            {"id":"tr-3","name":"Drywall","description":"-","status":"Active"},
            {"id":"tr-4","name":"Electrical","description":"-","status":"Active"},
            {"id":"tr-5","name":"Exterior Works","description":"-","status":"Active"},
            {"id":"tr-6","name":"Flooring / Finishing","description":"-","status":"Active"},
            {"id":"tr-7","name":"HVAC","description":"-","status":"Active"},
            {"id":"tr-8","name":"Insulation","description":"-","status":"Active"},
            {"id":"tr-9","name":"Landscaping","description":"-","status":"Active"},
            {"id":"tr-10","name":"Masonry","description":"-","status":"Active"},
            {"id":"tr-11","name":"Painting","description":"-","status":"Active"},
            {"id":"tr-12","name":"Plumbing","description":"-","status":"Active"},
            {"id":"tr-13","name":"Roofing","description":"-","status":"Active"},
        ],
        "vendors": [
            {"id":"v-1","name":"Clover Paints","vendorType":"Material Supplier","trade":"Painting","activeProjects":0,"status":"Active"},
            {"id":"v-2","name":"Jim's electrical Company","vendorType":"Material Supplier","trade":"Electrical","activeProjects":1,"status":"Active"},
        ],
        "team_members": [
            {"id":"tm-1","name":"admin","email":"admin@bm.ai","department":"—","category":"internal"},
            {"id":"tm-2","name":"Jim Co","email":"jim@buildmarshal.ai","department":"Finance & Accounts","category":"internal"},
        ]
    }

def save_mgmt(data: Dict):
    MGMT_FILE.write_text(json.dumps(data, indent=2, default=str))


# ── Trades CRUD ──
@app.get("/api/trades")
async def list_trades():
    return {"trades": load_mgmt().get("trades", [])}

@app.post("/api/trades")
async def create_trade(request: Request):
    body = await request.json()
    mgmt = load_mgmt()
    trade = {
        "id": f"tr-{uuid.uuid4().hex[:8]}",
        "name": body.get("name", "").strip(),
        "description": body.get("description", "-"),
        "status": body.get("status", "Active")
    }
    if not trade["name"]:
        raise HTTPException(400, detail="Name is required")
    mgmt["trades"].append(trade)
    save_mgmt(mgmt)
    return trade

@app.put("/api/trades/{trade_id}")
async def update_trade(trade_id: str, request: Request):
    body = await request.json()
    mgmt = load_mgmt()
    for t in mgmt["trades"]:
        if t["id"] == trade_id:
            t["name"] = body.get("name", t["name"])
            t["description"] = body.get("description", t["description"])
            t["status"] = body.get("status", t["status"])
            save_mgmt(mgmt)
            return t
    raise HTTPException(404, detail="Trade not found")

@app.delete("/api/trades/{trade_id}")
async def delete_trade(trade_id: str):
    mgmt = load_mgmt()
    mgmt["trades"] = [t for t in mgmt["trades"] if t["id"] != trade_id]
    save_mgmt(mgmt)
    return {"message": "Trade deleted", "id": trade_id}


# ── Vendors CRUD ──
@app.get("/api/vendors")
async def list_vendors():
    return {"vendors": load_mgmt().get("vendors", [])}

@app.post("/api/vendors")
async def create_vendor(request: Request):
    body = await request.json()
    mgmt = load_mgmt()
    vendor = {
        "id": f"v-{uuid.uuid4().hex[:8]}",
        "name": body.get("name", "").strip(),
        "vendorType": body.get("vendorType", "Material Supplier"),
        "trade": body.get("trade", ""),
        "activeProjects": body.get("activeProjects", 0),
        "status": body.get("status", "Active")
    }
    if not vendor["name"]:
        raise HTTPException(400, detail="Name is required")
    mgmt["vendors"].append(vendor)
    save_mgmt(mgmt)
    return vendor

@app.put("/api/vendors/{vendor_id}")
async def update_vendor(vendor_id: str, request: Request):
    body = await request.json()
    mgmt = load_mgmt()
    for v in mgmt["vendors"]:
        if v["id"] == vendor_id:
            v["name"] = body.get("name", v["name"])
            v["vendorType"] = body.get("vendorType", v["vendorType"])
            v["trade"] = body.get("trade", v["trade"])
            v["status"] = body.get("status", v["status"])
            save_mgmt(mgmt)
            return v
    raise HTTPException(404, detail="Vendor not found")

@app.delete("/api/vendors/{vendor_id}")
async def delete_vendor(vendor_id: str):
    mgmt = load_mgmt()
    mgmt["vendors"] = [v for v in mgmt["vendors"] if v["id"] != vendor_id]
    save_mgmt(mgmt)
    return {"message": "Vendor deleted", "id": vendor_id}


# ── Team Members CRUD ──
@app.get("/api/team-members")
async def list_team_members():
    return {"team_members": load_mgmt().get("team_members", [])}

@app.post("/api/team-members")
async def create_team_member(request: Request):
    body = await request.json()
    mgmt = load_mgmt()
    member = {
        "id": f"tm-{uuid.uuid4().hex[:8]}",
        "name": body.get("name", "").strip(),
        "email": body.get("email", ""),
        "department": body.get("department", "—"),
        "category": body.get("category", "internal"),
        "company": body.get("company", ""),
        "contactName": body.get("contactName", ""),
    }
    if not member["name"]:
        raise HTTPException(400, detail="Name is required")
    mgmt["team_members"].append(member)
    save_mgmt(mgmt)
    return member

@app.put("/api/team-members/{member_id}")
async def update_team_member(member_id: str, request: Request):
    body = await request.json()
    mgmt = load_mgmt()
    for m in mgmt["team_members"]:
        if m["id"] == member_id:
            for key in ["name", "email", "department", "category", "company", "contactName"]:
                if key in body:
                    m[key] = body[key]
            save_mgmt(mgmt)
            return m
    raise HTTPException(404, detail="Team member not found")

@app.delete("/api/team-members/{member_id}")
async def delete_team_member(member_id: str):
    mgmt = load_mgmt()
    mgmt["team_members"] = [m for m in mgmt["team_members"] if m["id"] != member_id]
    save_mgmt(mgmt)
    return {"message": "Team member deleted", "id": member_id}


# ═══════════════════════════════════════════════════════════════════════
# CELL 7 — Launch Server with Ngrok Tunnel
# ═══════════════════════════════════════════════════════════════════════

def start_server():
    """Start the FastAPI server with ngrok tunnel."""
    # Configure ngrok
    ngrok.set_auth_token(NGROK_AUTH_TOKEN)

    # Start tunnel
    port = 8000
    public_url = ngrok.connect(port)

    print("\n" + "=" * 60)
    print("🏗️  BuildMarshalAI Backend is LIVE!")
    print("=" * 60)
    print(f"\n🌐 PUBLIC URL: {public_url.public_url}")
    print(f"\n📋 Copy this URL into your frontend Settings panel.")
    print(f"\n🔗 API Docs:   {public_url.public_url}/docs")
    print(f"💚 Health:     {public_url.public_url}/api/health")
    print("\n" + "=" * 60)
    print("⚠️  This URL changes each session. Keep this cell running!")
    print("=" * 60 + "\n")

    # Start uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)

# Uncomment the line below to start the server:
# start_server()
