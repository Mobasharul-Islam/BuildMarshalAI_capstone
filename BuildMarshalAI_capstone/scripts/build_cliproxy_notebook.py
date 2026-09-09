"""Build the CLIProxyAPI notebook variant from the preserved Qwen notebook."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend" / "Dual_t4_Working_with_Document_Generation.ipynb"
BACKUP = ROOT / "backend" / "backup" / "Dual_t4_Working_with_Document_Generation_pre_CLIPROXYAPI.ipynb"
OUTPUT = ROOT / "backend" / "Local_Working_with_Document_Generation_CLIProxyAPI.ipynb"
CLIENT_MODULE = ROOT / "backend" / "cliproxy_client.py"
HYBRID_MODULE = ROOT / "backend" / "hybrid_retrieval.py"
EVIDENCE_MODULE = ROOT / "backend" / "evidence_viewer.py"


CELL_0 = r'''# STEP 0 - Runtime and Hugging Face configuration
import os, re, subprocess, sys
from pathlib import Path

# Configure UTF-8 streams on Windows to prevent UnicodeEncodeError with emoji outputs
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

if os.name != "nt":
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "120"
os.environ["HF_HUB_ETAG_TIMEOUT"] = "60"

# Prevent torchao / torch.int1 mismatch on PyTorch < 2.6
sys.modules.setdefault("torchao", None)

IS_KAGGLE = Path("/kaggle/working").exists()
_cwd = Path.cwd()
if (_cwd / "BuildMarshalAI_capstone").exists():
    _local_repo_root = _cwd / "BuildMarshalAI_capstone"
elif _cwd.name == "backend" and (_cwd.parent / "frontend").exists():
    _local_repo_root = _cwd.parent
else:
    _local_repo_root = _cwd
RUNTIME_ROOT = Path("/kaggle/working") if IS_KAGGLE else _local_repo_root / ".buildmarshal_runtime"
RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(RUNTIME_ROOT / "hf_cache"))
os.environ.setdefault("PIP_CACHE_DIR", str(RUNTIME_ROOT / "pip_cache"))
# Kaggle can discard large weights after loading to conserve session disk.
# A local backend keeps the verified files so later starts do not redownload them.
os.environ.setdefault("BUILDMARSHAL_KEEP_MODEL_FILES", "0" if IS_KAGGLE else "1")

# Load secrets without printing their values. Local Windows runs use environment variables.
if IS_KAGGLE:
    try:
        from kaggle_secrets import UserSecretsClient
        _secrets = UserSecretsClient()
        for _name in ("HF_TOKEN", "NGROK_AUTH_TOKEN", "CLIPROXY_BASE_URL", "CLIPROXY_API_KEY", "CLIPROXY_MODEL"):
            try:
                _value = _secrets.get_secret(_name)
                if _value:
                    os.environ[_name] = _value
            except Exception:
                pass
        print("Secrets loaded from Kaggle Secrets where available")
    except Exception as _secret_error:
        print(f"Kaggle Secrets unavailable: {_secret_error}")
else:
    # Reuse the API key already configured for the local CLIProxyAPI service.
    # The value is loaded into memory only and is never printed or copied into
    # this notebook, so a fresh VS Code kernel does not need manual env setup.
    _proxy_config = Path.home() / ".cli-proxy-api" / "config.yaml"
    if not os.environ.get("CLIPROXY_API_KEY") and _proxy_config.exists():
        _config_text = _proxy_config.read_text(encoding="utf-8")
        _key_match = re.search(r"(?m)^api-keys:\s*\r?\n\s*-\s*[\"']?([^\"'\r\n#]+)", _config_text)
        if _key_match:
            os.environ["CLIPROXY_API_KEY"] = _key_match.group(1).strip()
    os.environ.setdefault("CLIPROXY_BASE_URL", "http://127.0.0.1:8317/v1")
    os.environ.setdefault("CLIPROXY_MODEL", "gemini-3.7-flash-high")

# Keep Kaggle's CUDA wheel repair, but never replace the user's local Windows torch install.
if IS_KAGGLE:
    subprocess.run([
        sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", "--upgrade",
        "torch", "torchvision", "torchaudio", "--index-url",
        "https://download.pytorch.org/whl/cu121",
    ], check=True)

import torch
print("PyTorch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise RuntimeError("A CUDA GPU is required for the ColPali retriever.")
for i in range(torch.cuda.device_count()):
    props = torch.cuda.get_device_properties(i)
    print(f"  [cuda:{i}] {props.name} - {props.total_memory/1e9:.1f} GB")
'''


CELL_1 = '''import subprocess, sys

def pip_install(*packages: str, label: str = ""):
    """Install dependencies and stop immediately if pip fails."""
    cmd = [sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", *packages]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        raise RuntimeError(f"pip install failed{f' ({label})' if label else ''}")
    print(f"Installed: {label or ', '.join(packages)}")

pip_install(
    "fastapi==0.115.6", "uvicorn[standard]==0.34.0",
    "python-multipart==0.0.20", "pyngrok==7.2.2", "nest-asyncio==1.6.0",
    "Pillow==11.1.0", "PyMuPDF>=1.24.0", "openpyxl==3.1.5",
    "pandas==2.2.3", "python-docx==1.1.2", "matplotlib", "fpdf2==2.8.1",
    "requests>=2.32.0", label="core packages",
)
pip_install("chromadb>=0.5.0", label="chromadb")
print("All dependencies installed")
'''


CELL_2 = '''# ColPali dependencies. Qwen, bitsandbytes, and qwen-vl-utils are intentionally absent.
pip_install(
    "transformers>=4.46.0,<5.0.0",
    "peft>=0.11.0",
    "accelerate>=0.27.0",
    label="ColPali dependencies",
)
pip_install("colpali-engine==0.3.1", "--no-deps", label="colpali-engine")
'''


CELL_3 = '''import os, json, uuid, time, shutil, base64, asyncio, logging, sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from io import BytesIO
from datetime import datetime

try:
    import asyncio
    asyncio.get_running_loop()
    import nest_asyncio
    nest_asyncio.apply()
except (RuntimeError, NameError):
    pass

import torch
import pandas as pd
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn
from pyngrok import ngrok

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("BuildMarshalAI")

BASE_DIR = Path(os.environ.get("BUILDMARSHAL_DATA_DIR", str(RUNTIME_ROOT / "buildmarshal")))
DOCS_DIR = BASE_DIR / "documents"
PAGES_DIR = BASE_DIR / "pages"
INDEX_DIR = BASE_DIR / "index"
CHROMA_DIR = BASE_DIR / "chroma_db"
META_FILE = BASE_DIR / "metadata.json"
for directory in (BASE_DIR, DOCS_DIR, PAGES_DIR, INDEX_DIR, CHROMA_DIR):
    directory.mkdir(parents=True, exist_ok=True)

NGROK_AUTH_TOKEN = os.environ.get("NGROK_AUTH_TOKEN", "").strip()

def load_metadata() -> Dict:
    if META_FILE.exists():
        return json.loads(META_FILE.read_text(encoding="utf-8"))
    return {"documents": {}}

def save_metadata(meta: Dict):
    META_FILE.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

NUM_GPUS = torch.cuda.device_count()
COLPALI_DEVICE_IDX = 0
COLPALI_DEVICE = "cuda:0"
print(f"Config ready | GPUs detected: {NUM_GPUS}")
print(f"ColPali retrieval -> {COLPALI_DEVICE}; generation -> CLIProxyAPI at "
      f"{os.environ.get('CLIPROXY_BASE_URL', 'http://127.0.0.1:8317/v1')}")
'''


GENERATION_SUFFIX = r'''

CLIPROXY_CLIENT = CLIProxyClient()
CLIPROXY_LABEL = f"cliproxyapi:{CLIPROXY_CLIENT.preferred_model}"
_LAST_GENERATION_MODEL = None

def vl_generate(messages: list, max_new_tokens: int = 4096, model: str | None = None) -> str:
    """Compatibility entry point used by chat, document, Gmail, and Calendar flows."""
    global _LAST_GENERATION_MODEL, CLIPROXY_LABEL
    response, selected_model = CLIPROXY_CLIENT.chat(
        messages, max_tokens=max_new_tokens, model=model
    )
    _LAST_GENERATION_MODEL = selected_model
    CLIPROXY_LABEL = f"cliproxyapi:{selected_model}"
    return response

def image_to_base64(image_path: str) -> Optional[str]:
    try:
        with open(image_path, "rb") as handle:
            data = base64.b64encode(handle.read()).decode("utf-8")
        return f"data:image/png;base64,{data}"
    except Exception:
        return None

async def generate_response(
    query: str,
    context_pages: List[Dict],
    history: List[Dict],
    model: str | None = None,
) -> Dict:
    system_prompt = (
        "You are BuildMarshalAI, an intelligent construction document assistant.\n"
        "Answer only from the supplied project-document evidence. If the evidence does not "
        "contain the answer, say so. Cite document names and page numbers. Use clear markdown "
        "and describe relevant drawings or diagrams. Cite factual claims using the supplied "
        "numeric source labels, for example [1] or [2]. Never invent a citation number."
    )
    messages = [{"role": "system", "content": system_prompt}]
    for message in history[-6:]:
        messages.append({
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
        })

    user_content = []
    images_added = 0
    for page in context_pages:
        image_path = page.get("image_path")
        if images_added >= 4:
            break
        if image_path and os.path.exists(image_path):
            user_content.append({"type": "image", "image": image_path})
            images_added += 1

    context_text = "Relevant document pages:\n"
    for index, page in enumerate(context_pages):
        context_text += (
            f"\n[Source {index + 1}: {page['doc_name']}, Page {page['page']}"
            f" | similarity={page.get('score', 0):.3f}]"
        )
        if page.get("text_content"):
            context_text += f"\n{page['text_content'][:800]}"
    user_content.append({"type": "text", "text": f"{context_text}\n\nUser question: {query}"})
    messages.append({"role": "user", "content": user_content})

    try:
        response = await asyncio.get_running_loop().run_in_executor(
            None, lambda: vl_generate(messages, max_new_tokens=4096, model=model)
        )
    except CLIProxyError as exc:
        logger.error("CLIProxyAPI inference error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Generation failed")
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}") from exc

    sources = []
    for rank, page in enumerate(context_pages, 1):
        source = {
            "doc_name": page["doc_name"], "doc_id": page["doc_id"],
            "page": page["page"], "score": page.get("score", 0.0), "image_url": None,
            "rank": rank,
            "query": query,
            "retrieval_method": page.get("retrieval_method", "hybrid retrieval"),
            "score_breakdown": page.get("score_breakdown", {}),
            "matched_terms": page.get("matched_terms", []),
            "source_type": page.get("source_type", "project_document"),
            "evidence_text": page.get("text_content", "")[:1600],
        }
        if page.get("image_path"):
            source["image_url"] = image_to_base64(page["image_path"])
        sources.append(source)
    return {"response": response, "sources": sources, "model_used": _LAST_GENERATION_MODEL}

print("Query pipeline ready - ColPali retrieval + CLIProxyAPI Antigravity generation")
'''


CELL_12 = '''# CELL 11b - Document generation + Google Workspace integration
import importlib.util, os, subprocess, sys, urllib.request
from pathlib import Path

_integration_modules = ("reportlab", "pypdf", "googleapiclient", "google.auth", "cryptography")
if any(importlib.util.find_spec(name) is None for name in _integration_modules):
    subprocess.run([
        sys.executable, "-m", "pip", "install", "-q",
        "reportlab==4.4.3", "pypdf==5.7.0",
        "google-api-python-client==2.176.0", "google-auth==2.40.3",
        "cryptography==45.0.5",
    ], check=True)
else:
    print("Document-generation and Google integration packages already installed")

if IS_KAGGLE:
    try:
        from kaggle_secrets import UserSecretsClient
        _secrets = UserSecretsClient()
        for _name in (
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
            "GOOGLE_TOKEN_ENCRYPTION_KEY", "GOOGLE_ALLOWED_ORIGINS",
        ):
            try:
                _value = _secrets.get_secret(_name)
                if _value:
                    os.environ[_name] = _value
            except Exception:
                pass
    except Exception as exc:
        print(f"Kaggle Secrets unavailable: {exc}")

if IS_KAGGLE:
    integration_dir = RUNTIME_ROOT / "integration"
    integration_dir.mkdir(parents=True, exist_ok=True)
    (integration_dir / "hybrid_retrieval.py").write_text(
        __EMBEDDED_HYBRID_RETRIEVAL__, encoding="utf-8"
    )
    (integration_dir / "evidence_viewer.py").write_text(
        __EMBEDDED_EVIDENCE_VIEWER__, encoding="utf-8"
    )
    repository = "https://raw.githubusercontent.com/shafitanvir32/BuildMarshalAI_capstone/docgen-pipeline/backend"
    for filename in ("document_generation.py", "google_workspace.py"):
        urllib.request.urlretrieve(f"{repository}/{filename}", integration_dir / filename)
else:
    candidates = [
        Path.cwd() / "backend",
        Path.cwd(),
        Path.cwd() / "BuildMarshalAI_capstone" / "backend",
        Path.cwd() / "BuildMarshalAI_capstone",
    ]
    integration_dir = next(
        (candidate for candidate in candidates
         if (candidate / "document_generation.py").exists()
         and (candidate / "google_workspace.py").exists()
         and (candidate / "hybrid_retrieval.py").exists()
         and (candidate / "evidence_viewer.py").exists()),
        None,
    )
    if integration_dir is None:
        raise RuntimeError(
            "Run this notebook from the BuildMarshalAI repository root or backend directory."
        )

sys.path.insert(0, str(integration_dir))
from hybrid_retrieval import install_hybrid_retrieval
from evidence_viewer import register_evidence_viewer_routes
from document_generation import register_kaggle_routes
from google_workspace import register_google_workspace_routes

HYBRID_RETRIEVER = install_hybrid_retrieval(globals())
EVIDENCE_VIEWER_SERVICE = register_evidence_viewer_routes(globals())
DOCUMENT_GENERATION_SERVICE = register_kaggle_routes(globals())
GOOGLE_WORKSPACE_SERVICE = register_google_workspace_routes(globals())
print("Hybrid text + ColPali MaxSim retrieval registered")
print("Exact-page evidence viewer routes registered")
print("Project document-generation routes registered")
print("Google Workspace routes registered", "(configured)" if GOOGLE_WORKSPACE_SERVICE["configured"] else "(configure OAuth variables to enable)")
'''


def set_source(cell: dict, source: str) -> None:
    cell["source"] = source


def get_source(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else str(source)


def main() -> None:
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, BACKUP)

    notebook = json.loads(SOURCE.read_text(encoding="utf-8"))
    notebook.setdefault("metadata", {})["kernelspec"] = {
        "display_name": "BuildMarshalAI GPU (Python 3.13)",
        "language": "python",
        "name": "buildmarshal-gpu",
    }
    notebook["metadata"].setdefault("language_info", {})["version"] = "3.13"
    for cell in notebook["cells"]:
        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []

    set_source(notebook["cells"][0], CELL_0)
    set_source(notebook["cells"][1], CELL_1)
    set_source(notebook["cells"][2], CELL_2)
    set_source(notebook["cells"][3], CELL_3)

    colpali_source = get_source(notebook["cells"][4])
    colpali_source = colpali_source.replace(
        'MODEL_ROOT = Path("/kaggle/working/hf_models")',
        'MODEL_ROOT = BASE_DIR / "hf_models"',
    )
    # The notebook rewrites adapter_config.json so PEFT resolves the pinned base
    # model from the local cache. On the next launch that intentional rewrite
    # changes the file size (750 -> ~860 bytes); accept it as a valid cached
    # adapter config instead of deleting and downloading it again.
    colpali_source = colpali_source.replace(
        '    if destination.exists() and destination.stat().st_size == expected_size:\n',
        '    locally_rewritten_adapter = (\n'
        '        filename == "adapter_config.json"\n'
        '        and destination.exists()\n'
        '        and os.path.normcase(os.path.abspath(\n'
        '            json.loads(destination.read_text(encoding="utf-8")).get("base_model_name_or_path", "")\n'
        '        )) == os.path.normcase(os.path.abspath(str(BASE_MODEL_DIR)))\n'
        '    )\n'
        '    if locally_rewritten_adapter or (destination.exists() and destination.stat().st_size == expected_size):\n',
    )
    # Keep the explicit device_map from the source notebook. Transformers then
    # streams each safetensors shard directly to CUDA instead of first staging
    # the 5.8 GB model in Windows CPU/pagefile memory (which can raise OS 1455).
    colpali_source = colpali_source.replace(
        "from transformers import PaliGemmaForConditionalGeneration",
        "import sys\nsys.modules.setdefault('torchao', None)\nfrom transformers import PaliGemmaForConditionalGeneration",
    )
    set_source(notebook["cells"][4], colpali_source)

    ingestion_source = get_source(notebook["cells"][5])
    pdf_start = ingestion_source.index("def process_pdf(")
    pdf_end = ingestion_source.index("\n\ndef _df_to_image", pdf_start)
    pymupdf_pdf = '''def process_pdf(file_path: Path, doc_id: str) -> List[Dict]:
    """Render PDF pages with PyMuPDF (no external Poppler installation)."""
    import fitz

    logger.info(f"Processing PDF: {file_path.name}")
    page_infos = []
    with fitz.open(file_path) as document:
        scale = 150 / 72
        matrix = fitz.Matrix(scale, scale)
        for index, pdf_page in enumerate(document):
            pixmap = pdf_page.get_pixmap(matrix=matrix, alpha=False)
            page_img = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            page_img.thumbnail((1024, 1024))
            page_path = PAGES_DIR / f"{doc_id}_page_{index + 1}.png"
            page_img.save(page_path, "PNG")
            page_infos.append({
                "page_num": index + 1,
                "image_path": str(page_path),
                "width": page_img.width,
                "height": page_img.height,
                "text_content": pdf_page.get_text("text")[:12000],
            })
    logger.info(f"PDF: {len(page_infos)} pages extracted")
    return page_infos
'''
    ingestion_source = ingestion_source[:pdf_start] + pymupdf_pdf + ingestion_source[pdf_end:]
    set_source(notebook["cells"][5], ingestion_source)

    embedded_client = CLIENT_MODULE.read_text(encoding="utf-8")
    set_source(notebook["cells"][6], embedded_client + GENERATION_SUFFIX)

    api_source = get_source(notebook["cells"][7])
    api_source = api_source.replace(
        'description="ColPali (ChromaDB vector store) + Qwen2.5-VL document chatbot",',
        'description="ColPali (ChromaDB vector store) + CLIProxyAPI Antigravity generation",',
    ).replace(
        '            if i == VL_DEVICE_IDX:\n                hosts.append("qwen2.5-vl")\n',
        '',
    ).replace(
        '        "generator":       f"{VL_QUANT_LABEL} ({VL_DEVICE})",',
        '        "generator":       CLIPROXY_LABEL,\n        "cliproxy_base_url": CLIPROXY_CLIENT.base_url,',
    ).replace(
        '    model   = body.get("model", "qwen2.5-vl")',
        '    model   = body.get("model")',
    ).replace(
        '# Step 2: Generate answer with Qwen2.5-VL using retrieved pages',
        '# Step 2: Generate through CLIProxyAPI using text plus retrieved page images',
    )
    api_source = api_source.replace(
        '    top_k   = min(body.get("top_k", 5), 20)\n',
        '    top_k   = min(body.get("top_k", 5), 20)\n'
        '    project_id = body.get("project_id")\n',
        1,
    ).replace(
        '    context_pages = retrieve_context(query, top_k=top_k)\n',
        '    context_pages = retrieve_context(query, top_k=top_k, project_id=project_id)\n',
        1,
    )
    health_marker = '        "documents_count": len(load_metadata().get("documents", {})),\n'
    api_source = api_source.replace(
        health_marker,
        health_marker + '        "generator": CLIPROXY_LABEL,\n        "cliproxy_base_url": CLIPROXY_CLIENT.base_url,\n',
        1,
    )
    route_marker = '\n\n@app.get("/api/status")\n'
    proxy_route = '''\n\n@app.get("/api/cliproxy/status")
async def cliproxy_status():
    return await asyncio.get_running_loop().run_in_executor(None, CLIPROXY_CLIENT.status)
'''
    api_source = api_source.replace(route_marker, proxy_route + route_marker, 1)
    set_source(notebook["cells"][7], api_source)

    integration_source = CELL_12.replace(
        "__EMBEDDED_HYBRID_RETRIEVAL__",
        repr(HYBRID_MODULE.read_text(encoding="utf-8")),
    ).replace(
        "__EMBEDDED_EVIDENCE_VIEWER__",
        repr(EVIDENCE_MODULE.read_text(encoding="utf-8")),
    )
    set_source(notebook["cells"][12], integration_source)

    server_source = '''import uvicorn
from pyngrok import ngrok

def start_server():
    port = int(os.environ.get("BUILDMARSHAL_PORT", "8000"))
    public_url = None
    if NGROK_AUTH_TOKEN:
        try:
            ngrok.set_auth_token(NGROK_AUTH_TOKEN)
            for tunnel in ngrok.get_tunnels():
                ngrok.disconnect(tunnel.public_url)
            ngrok.kill()
            public_url = ngrok.connect(port).public_url
        except Exception as exc:
            print(f"ngrok could not start; continuing locally: {exc}")

    local_url = f"http://127.0.0.1:{port}"
    shown_url = public_url or local_url
    print("\\n" + "=" * 60)
    print("BuildMarshalAI CLIProxyAPI Backend is LIVE")
    print("=" * 60)
    print(f"Backend URL : {shown_url}")
    print(f"API Docs    : {shown_url}/docs")
    print(f"Health      : {shown_url}/api/health")
    print(f"Proxy check : {shown_url}/api/cliproxy/status")
    print(f"Retrieval   : ColPali on {COLPALI_DEVICE}")
    print(f"Generation  : {CLIPROXY_CLIENT.base_url}")
    print("=" * 60 + "\\n")
    uvicorn.run(app, host="0.0.0.0", port=port)

start_server()
'''
    set_source(notebook["cells"][13], server_source)

    OUTPUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Backup: {BACKUP}")
    print(f"Created: {OUTPUT}")


if __name__ == "__main__":
    main()
