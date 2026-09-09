# 🏗️ BuildMarshalAI

**An intelligent, context-aware construction document assistant** powered by ColPali visual document retrieval and Google Gemini AI.

Upload your project documents — PDFs, spreadsheets, images, drawings — and ask questions in natural language. Get accurate, cited answers backed by visual document understanding.

---

---
Frontend deployed on
https://build-marshal-ai-capstone.vercel.app/
---
## Architecture

```
┌──────────────┐    ┌─────────────────────────────────────────────────┐
│   Frontend   │    │         Backend (Kaggle Notebook)               │
│  (Browser)   │◄──►│                                                 │
│              │    │  ┌─────────┐  ┌─────────┐  ┌──────────────┐   │
│  • Chat UI   │    │  │ FastAPI │  │ ColPali  │  │   Gemini AI  │   │
│  • Doc Upload│    │  │ Server  │──│ (Byaldi) │──│ (Multimodal) │   │
│  • Citations │    │  └────┬────┘  └─────────┘  └──────────────┘   │
│              │    │       │                                         │
└──────────────┘    │  ┌────▼────┐                                   │
       ▲            │  │  Ngrok  │                                   │
       │            │  │ Tunnel  │                                   │
       └────────────│──┘         │                                   │
                    └─────────────────────────────────────────────────┘
```

## Features

- 🤖 **AI Chat** — Natural language Q&A over your documents
- 📄 **Multi-format Upload** — PDF, Excel, CSV, Images, Word (.docx)
- 🔍 **Visual Retrieval** — ColPali-based retrieval that understands document layout, tables, and images
- 📎 **Source Citations** — Every answer shows which document page it came from
- 🖼️ **Page Preview** — Click citations to see the actual document page
- 💬 **Chat History** — Persistent conversation threads, stored per account
- 📊 **Project People, Cost, Timeline & Procurement** — Member assignment, a full cost breakdown, a Gantt timeline, and procurement tracking (see [docs/PROJECT_SECTIONS.md](docs/PROJECT_SECTIONS.md))
- 🗓️ **Global Calendar** — Project, task, Google, and Outlook events in one month view, and a **New event** button that creates one on either connected calendar with a Google Meet or Teams link
- ✅ **Task Management** — Per-project tasks with subtasks, filters, a detail view, and full editing (see [docs/TASK_MANAGEMENT.md](docs/TASK_MANAGEMENT.md))
- 📅 **Schedule meetings from chat** — Marshal asks for anything missing, confirms, then books a Google Meet or a Teams meeting and returns the join link. It can also reschedule or rename an existing event on either calendar
- 🔗 **Google + Microsoft** — Link Google Workspace and Microsoft 365 accounts side by side: Drive/OneDrive import, Gmail/Outlook read & send, Google/Outlook Calendar (see [docs/MICROSOFT_365_INTEGRATION.md](docs/MICROSOFT_365_INTEGRATION.md))
- 🏢 **Company Settings** — Company profile plus the task-type and project-type catalogs; everyone can read them, only administrators can change them, enforced on the server (see [docs/COMPANY_SETTINGS.md](docs/COMPANY_SETTINGS.md))
- 🛡️ **User Roles & Permissions** — Super Admin defines roles from 24 granular permissions (per task field, per cost type); every role is created per account, nothing is hardcoded, and each permission is enforced on the API as well as the UI (see [docs/ROLES_AND_COSTS.md](docs/ROLES_AND_COSTS.md))
- 🔐 **Accounts & Isolation** — Sign-in required; every account has its own files, vector index, projects, settings, conversations, and Google integrations, with no cross-account access (see [docs/ACCOUNTS_AND_ISOLATION.md](docs/ACCOUNTS_AND_ISOLATION.md))
- 🌙 **Premium Dark UI** — Glassmorphism design with smooth animations
- 📱 **Responsive** — Works on desktop, tablet, and mobile
- 🆓 **Free GPU** — Runs on Kaggle's free GPU tier
- 🧾 **Project Document Generation** — Creates cited tender, project, schedule, and addendum PDFs from project-linked source documents

---

## Quick Start

### 1. Backend Setup (Kaggle)

1. Go to [Kaggle](https://www.kaggle.com/) and create a new notebook
2. Enable **GPU** (Settings → Accelerator → GPU P100)
3. Enable **Internet** (Settings → Internet → On)
4. Add your secrets (Add-ons → Secrets):
   - `GEMINI_API_KEY` — Get from [Google AI Studio](https://aistudio.google.com/)
   - `NGROK_AUTH_TOKEN` — Get from [ngrok.com](https://ngrok.com/)
> [!WARNING]
> `backend/kaggle_server.py` is a **legacy single-tenant backend**. It predates
> CLIProxyAPI generation, document generation, the Google Workspace integration,
> and the account system, and it exposes every endpoint without authentication.
> Do not deploy it on a reachable host. The maintained backend is
> `backend/Local_Working_with_Document_Generation_CLIProxyAPI.ipynb`
> (exported to `backend/run_backend.py` by `scripts/export_run_backend.py`).

5. Copy the contents of `backend/kaggle_server.py` into notebook cells:
   - **Cell 1**: Install dependencies (the `!pip install` and `!apt-get` lines)
   - **Cell 2**: Configuration & Imports
   - **Cell 3**: Initialize ColPali Model
   - **Cell 4**: Document Ingestion Pipeline
   - **Cell 5**: Query Pipeline
   - **Cell 6**: FastAPI Application
   - **Cell 7**: Launch Server (`start_server()`)
6. Run all cells. The last cell will print your **public ngrok URL**.

### 2. Frontend Setup

#### Option A: GitHub Pages (Recommended)

1. Create a GitHub repository
2. Push the `frontend/` folder to the repo
3. Go to Settings → Pages → Source: Deploy from branch → `main` → `/frontend`
4. Your frontend will be live at `https://yourusername.github.io/repo-name/`

#### Option B: Local

```bash
cd frontend
python3 -m http.server 3000
# Open http://localhost:3000
```

### 3. Connect

1. Open the frontend in your browser
2. Click **⚙ Settings** in the sidebar
3. Paste your **ngrok URL** from the Kaggle notebook
4. Click **Save** — the status indicator should turn green ✅
5. Upload documents via the **📄 Documents** panel
6. Start chatting!

---

## Project Structure

```
BuildMarshalAI/
├── frontend/
│   ├── index.html      # Main chatbot page
│   ├── styles.css       # Premium dark theme + glassmorphism
│   ├── config.js        # Configuration (backend URL, settings)
│   └── app.js           # Chat logic, uploads, streaming, citations
│
├── backend/
│   ├── kaggle_server.py # Legacy single-tenant Kaggle backend (no auth; superseded)
│   └── requirements.txt # Python dependencies
│
├── docs/                # Place your documents here for reference
│
└── README.md            # This file
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check + GPU status |
| `GET` | `/api/status` | Index statistics |
| `POST` | `/api/upload` | Upload a document (multipart form) |
| `GET` | `/api/documents` | List all indexed documents |
| `GET` | `/api/documents/{id}/status` | Check indexing status |
| `DELETE` | `/api/documents/{id}` | Remove a document |
| `POST` | `/api/chat` | Send query, get AI response with sources |
| `GET` | `/api/pages/{doc_id}/{page_num}` | Serve a page image |
| `GET` | `/api/document-templates` | List supported generated-document templates |
| `POST` | `/api/projects/{id}/source-documents` | Upload and index a PDF as a project source |
| `GET` | `/api/projects/{id}/source-documents` | List source PDFs linked to a project |
| `POST` | `/api/projects/{id}/documents` | Generate a cited project PDF |
| `GET` | `/api/generated-documents/{id}/download` | Download a generated project PDF |

See [`docs/DOCUMENT_GENERATION_PIPELINE.md`](docs/DOCUMENT_GENERATION_PIPELINE.md) for the evidence rules, Kaggle integration cell, request payloads, and tests.

---

## Supported File Types

| Type | Extensions | Processing |
|------|-----------|------------|
| PDF | `.pdf` | Rendered to page images → ColPali indexed |
| Excel | `.xlsx`, `.xls`, `.csv` | Sheets rendered as table images + text extracted |
| Images | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.tiff` | Directly indexed |
| Word | `.doc`, `.docx` | Text extracted → rendered as images |

---

## Kaggle Limitations

- ⏱️ **Max 12 hours** per session
- 💤 **60-min idle timeout** (keep interacting or use "Save & Run All")
- 🔄 **Ngrok URL changes** each session — update frontend Settings
- 🎮 **30 hours/week** GPU quota
- 💾 Data in `/kaggle/working/` is lost after session (save important indices as datasets)

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Backend | Python, FastAPI, Uvicorn |
| Document Retrieval | ColPali v1.2 via Byaldi |
| AI Generation | Google Gemini (2.5 Flash / Pro) |
| Tunnel | ngrok (pyngrok) |
| GPU | Kaggle P100 (free tier) |

---

## License

MIT License — Built with ❤️ by Ahtashamul Haque 
BuildMarshalAI
