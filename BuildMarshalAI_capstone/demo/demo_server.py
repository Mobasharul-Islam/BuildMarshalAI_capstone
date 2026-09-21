"""A local demonstration backend for BuildMarshalAI.

The real backend loads ColPali and a vision model, which needs a GPU and several
minutes. That is the wrong shape for walking someone through the product, so this
serves the same API without the models.

**Everything interesting is the real code.** Tasks, costs, procurement, company
settings, roles and permissions, onboarding, analytics, reports and storage are
registered from `backend/*.py` exactly as the notebook registers them, against a
real `AccountWorkspace` with real authentication. Only the routes that live in
the notebook itself -- project CRUD, document upload, retrieval and chat -- are
reimplemented here, and the retrieval ones answer from a fixed script rather
than from a model.

So a figure on screen during a demo was computed by the code that will compute
it in production. Run it, then open http://127.0.0.1:8000.

    python demo/demo_server.py [--reset]

Not a deployment target: it holds one seeded account with a known password and
never loads the retrieval stack.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import make_demo_pack as pack  # noqa: E402
import providers  # noqa: E402
from backend import (accounts, chat_entities, company_settings,  # noqa: E402
                     document_storage, evidence_viewer, project_analytics,
                     project_management, project_onboarding, project_report,
                     tasks as task_routes, todo_lists, user_roles)

RUNTIME = HERE / ".demo-runtime"
FRONTEND = REPO / "frontend"
PACK = HERE / "project-pack"

DEMO_EMAIL = "rafiqul.islam@purbachalcon.example"
DEMO_PASSWORD = "PadmaView2026!"
ACCOUNT_NAME = "Purbachal Construction Ltd"


# ── The namespace the route modules expect ───────────────────────────────

app = FastAPI(title="BuildMarshalAI demonstration backend")


class StubCollection:
    """Stands in for the Chroma collection. Nothing here is indexed."""

    def __init__(self, name: str) -> None:
        self.name = name

    def count(self) -> int:
        return 0

    def add(self, **_: object) -> None:
        return None

    def query(self, **_: object) -> dict:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def delete(self, **_: object) -> None:
        return None


def build_account_collection(account_id: str):
    return StubCollection(f"demo-{account_id}")


NAMESPACE: dict = {
    "app": app,
    "BASE_DIR": str(RUNTIME),
    "build_account_collection": build_account_collection,
}

RUNTIME.mkdir(parents=True, exist_ok=True)
NAMESPACE.update(accounts.register_account_routes(NAMESPACE))
REGISTRY = NAMESPACE["ACCOUNT_REGISTRY"]
require_account = NAMESPACE["require_account"]


def ingest_document(*_args, **_kwargs):
    raise HTTPException(503, "Document indexing is not available in the demonstration backend")


async def vl_generate(*_args, **_kwargs) -> str:
    """The onboarding assistant's model call.

    Returning nothing usable is honest: this backend has no model. The
    onboarding code already treats an unusable reply as 'ask the admin',
    which is the behaviour worth demonstrating anyway.
    """
    return ""


def _make_project(data: dict) -> dict:
    """Mirrors the notebook's project factory."""
    text = lambda key, fallback="": str(data.get(key, fallback) or "").strip()  # noqa: E731
    return {
        "id": str(uuid.uuid4()),
        "name": text("name"), "project_code": text("project_code"),
        "manager": text("manager"), "type": text("type"),
        "status": text("status", "Active") or "Active",
        "start_date": str(data.get("start_date", "") or ""),
        "end_date": str(data.get("end_date", "") or ""),
        "description": text("description"),
        "address_line1": text("address_line1"), "address_line2": text("address_line2"),
        "city": text("city"), "state": text("state"),
        "postal_code": text("postal_code"), "country": text("country"),
        "archived": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


NAMESPACE.update({"ingest_document": ingest_document, "vl_generate": vl_generate,
                  "_make_project": _make_project})

for register in (task_routes.register_task_routes,
                 project_management.register_project_management_routes,
                 company_settings.register_company_settings_routes,
                 user_roles.register_user_role_routes,
                 todo_lists.register_todo_list_routes,
                 evidence_viewer.register_evidence_viewer_routes,
                 project_onboarding.register_project_onboarding_routes,
                 chat_entities.register_chat_entity_routes,
                 project_analytics.register_project_analytics_routes,
                 project_report.register_project_report_routes,
                 document_storage.register_document_storage_routes):
    register(NAMESPACE)


# ── The notebook-only routes, reimplemented ──────────────────────────────

def project_or_404(workspace, project_id: str) -> dict:
    project = workspace.load_projects().get(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@app.get("/api/health")
async def health() -> dict:
    # The frontend reads "healthy" literally; anything else shows Disconnected.
    return {"status": "healthy", "gpu": "demonstration backend — no GPU in use",
            "model": "not loaded", "documents": len(DEMO_DOCUMENTS)}


@app.get("/api/status")
async def status(context=Depends(require_account)) -> dict:
    meta = context.workspace.load_metadata()
    documents = meta.get("documents", {})
    return {"documents": len(documents), "indexed": len(documents),
            "pages": sum(int(d.get("page_count", 0)) for d in documents.values()),
            "model": "ColPali v1.2 (not loaded in the demonstration backend)"}


@app.get("/api/chroma/stats")
async def chroma_stats(context=Depends(require_account)) -> dict:
    return {"collection": f"account-{context.account_id}", "vectors": 0,
            "note": "The demonstration backend does not index."}


@app.get("/api/cliproxy/status")
async def cliproxy_status() -> dict:
    return {"available": False, "base_url": "not configured",
            "detail": "The demonstration backend answers from a script, not a model."}


@app.get("/api/projects")
async def list_projects(name: str = "", manager: str = "", type: str = "",
                        status: str = "", show_archived: bool = False,
                        page: int = 1, per_page: int = 10,
                        context=Depends(require_account)) -> dict:
    items = list(context.workspace.load_projects().values())
    if not show_archived:
        items = [p for p in items if not p.get("archived")]
    if name and len(name) >= 2:
        items = [p for p in items if name.lower() in p.get("name", "").lower()]
    if manager and len(manager) >= 2:
        items = [p for p in items if manager.lower() in p.get("manager", "").lower()]
    for field, raw in (("type", type), ("status", status)):
        wanted = [value.strip() for value in raw.split(",") if value.strip()]
        if wanted:
            items = [p for p in items if p.get(field) in wanted]
    items.sort(key=lambda p: str(p.get("created_at", "")), reverse=True)
    per_page = max(1, min(per_page, 100))
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    return {"projects": items[start:start + per_page], "total": total,
            "page": page, "per_page": per_page, "pages": pages}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str, context=Depends(require_account)) -> dict:
    return project_or_404(context.workspace, project_id)


@app.post("/api/projects")
async def create_project(request: Request, context=Depends(require_account)) -> dict:
    context.require("project.create", "creating projects")
    data = await request.json()
    if not str(data.get("name", "")).strip():
        raise HTTPException(422, "Name is required")
    if not str(data.get("project_code", "")).strip():
        raise HTTPException(422, "Project code is required")
    workspace = context.workspace
    projects = workspace.load_projects()
    code = str(data["project_code"]).strip().upper()
    if any(str(p.get("project_code", "")).upper() == code for p in projects.values()):
        raise HTTPException(409, "Project code already in use")
    project = _make_project(data)
    projects[project["id"]] = project
    workspace.save_projects(projects)
    return project


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, request: Request,
                         context=Depends(require_account)) -> dict:
    context.require("project.update", "editing projects")
    workspace = context.workspace
    projects = workspace.load_projects()
    project = projects.get(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    data = await request.json()
    editable = ("name", "project_code", "manager", "type", "status", "start_date",
                "end_date", "description", "address_line1", "address_line2",
                "city", "state", "postal_code", "country", "archived")
    project.update({key: data[key] for key in editable if key in data})
    projects[project_id] = project
    workspace.save_projects(projects)
    return project


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, context=Depends(require_account)) -> dict:
    # The real route has no permission check here, and takes the project's tasks
    # and procurement with it rather than orphaning rows nothing can reach.
    workspace = context.workspace
    projects = workspace.load_projects()
    if project_id not in projects:
        raise HTTPException(404, "Project not found")
    projects.pop(project_id)
    workspace.save_projects(projects)
    tasks = workspace.load_tasks()
    if tasks.pop(project_id, None) is not None:
        workspace.save_tasks(tasks)
    procurement = workspace.load_procurement()
    if procurement.pop(project_id, None) is not None:
        workspace.save_procurement(procurement)
    return {"status": "deleted"}


@app.get("/api/projects/{project_id}/timeline")
async def timeline(project_id: str, context=Depends(require_account)) -> dict:
    workspace = context.workspace
    project = project_or_404(workspace, project_id)
    items = workspace.load_tasks().get(project_id, [])
    bars = [{"id": task.get("id"), "name": task.get("name"),
             "start": task.get("start_time") or task.get("due_date") or "",
             "end": task.get("end_time") or task.get("due_date") or "",
             "status": task.get("status"), "parent_id": task.get("parent_id") or "",
             "trade": task.get("trade", ""), "assignee": task.get("assignee", "")}
            for task in items]
    return {"project": {"id": project_id, "name": project.get("name"),
                        "start_date": project.get("start_date"),
                        "end_date": project.get("end_date")},
            "tasks": [bar for bar in bars if bar["start"] and bar["end"]]}


# -- the catalogues the notebook owns ------------------------------------

def mgmt_list(context, key: str) -> list:
    return context.workspace.load_mgmt().get(key, [])


def mgmt_save(context, key: str, rows: list) -> None:
    data = context.workspace.load_mgmt()
    data[key] = rows
    context.workspace.save_mgmt(data)


def catalogue(path: str, key: str) -> None:
    """Register the list-shaped catalogues the notebook keeps.

    No permission check, because the notebook's own trade, vendor and
    team-member routes have none: a stub that is stricter than the thing it
    stands in for teaches the wrong lesson during a demonstration.
    """

    @app.get(path, name=f"list_{key}")
    async def _list(context=Depends(require_account)) -> dict:
        return {key: mgmt_list(context, key)}

    @app.post(path, name=f"create_{key}")
    async def _create(request: Request, context=Depends(require_account)) -> dict:
        body = await request.json()
        rows = mgmt_list(context, key)
        row = {"id": uuid.uuid4().hex[:12], "status": "Active",
               **{k: v for k, v in body.items() if k != "id"}}
        rows.append(row)
        mgmt_save(context, key, rows)
        return row

    @app.put(path + "/{row_id}", name=f"update_{key}")
    async def _update(row_id: str, request: Request,
                      context=Depends(require_account)) -> dict:
        body = await request.json()
        rows = mgmt_list(context, key)
        for row in rows:
            if row.get("id") == row_id:
                row.update({k: v for k, v in body.items() if k != "id"})
                mgmt_save(context, key, rows)
                return row
        raise HTTPException(404, "Not found")

    @app.delete(path + "/{row_id}", name=f"delete_{key}")
    async def _delete(row_id: str, context=Depends(require_account)) -> dict:
        rows = [row for row in mgmt_list(context, key) if row.get("id") != row_id]
        mgmt_save(context, key, rows)
        return {"status": "deleted"}


catalogue("/api/trades", "trades")
catalogue("/api/vendors", "vendors")
catalogue("/api/team-members", "team_members")


# -- documents, retrieval and chat ---------------------------------------

DEMO_DOCUMENTS = [
    ("06_Dorpotro-Bibaroni_Tender-Specification.pdf", 3, "project_document"),
    ("01_Prokolpo-Bibaroni_Project-Brief.pdf", 2, "project_document"),
    ("07_Nokshaa-Talika_Drawing-Register.pdf", 1, "project_document"),
    ("08_Sthapatya-Noksha_Ground-Floor-Plan.pdf", 1, "project_document"),
    ("02_Kajer-Somoysuchi_Works-Programme.xlsx", 2, "project_document"),
    ("04_Kroy-Talika_Procurement-Schedule.xlsx", 1, "project_document"),
    ("05_Byay-Porikolpona_Cost-Plan.csv", 1, "project_document"),
    ("09_Site-Instruction_SI-014.docx", 1, "project_document"),
]


@app.get("/api/documents")
async def list_documents(context=Depends(require_account)) -> dict:
    meta = context.workspace.load_metadata()
    return {"documents": [
        {"id": doc_id, "name": document["name"],
         "type": document.get("type", Path(document["name"]).suffix.lstrip(".")),
         "size": document.get("size", 0),
         "pages": document.get("page_count", 0),
         "status": document.get("status", "indexed"),
         "project_id": document.get("project_id"),
         "created_at": document.get("uploaded_at")}
        for doc_id, document in meta.get("documents", {}).items()]}


@app.get("/api/documents/{doc_id}/status")
async def document_status(doc_id: str, context=Depends(require_account)) -> dict:
    document = context.workspace.load_metadata().get("documents", {}).get(doc_id)
    if not document:
        raise HTTPException(404, "Document not found")
    return {"id": doc_id, "status": document.get("status", "indexed"),
            "pages": document.get("page_count", 0)}


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, context=Depends(require_account)) -> dict:
    workspace = context.workspace
    meta = workspace.load_metadata()
    if doc_id not in meta.get("documents", {}):
        raise HTTPException(404, "Document not found")
    meta["documents"].pop(doc_id)
    workspace.save_metadata(meta)
    return {"status": "deleted"}


@app.post("/api/upload")
async def upload() -> JSONResponse:
    return JSONResponse(status_code=503, content={
        "detail": "Uploading indexes the document, which the demonstration "
                  "backend cannot do. The pack is already loaded."})


@app.get("/api/pages/{doc_id}/{page_num}")
async def page_image(doc_id: str, page_num: int,
                     context=Depends(require_account)) -> FileResponse:
    path = HERE / "page-images" / f"{doc_id}_{page_num}.png"
    if not path.exists():
        raise HTTPException(404, "Page image not available in the demonstration backend")
    return FileResponse(path, media_type="image/png")


#: What Marshal answers, keyed by the words a question contains. Every answer
#: cites the page that actually states it, so a demonstration can be checked
#: against the specification in `demo/project-pack`.
SCRIPTED_ANSWERS: tuple[tuple[tuple[str, ...], str, tuple[tuple[str, int], ...]], ...] = (
    (("rfi", "response", "reply", "respond", "information"),
     "The consultant team must respond to an RFI within **7 working days** of receipt.\n\n"
     "An RFI that affects the critical path is marked **Urgent** and must be answered "
     "within **3 working days**. There is a limit on entitlement: an RFI raised later "
     "than 15 working days before the information is needed carries no extension of time.",
     (("06_Tender-Specification.pdf", 2),)),
    (("concrete", "grade", "slab", "psi", "casting", "cement"),
     "Concrete grades are specified by location:\n\n"
     "* Piles and pile caps \u2014 **4000 psi (C30/37)**, 75 mm cover\n"
     "* Grade beams \u2014 4000 psi, 50 mm cover\n"
     "* Slabs and beams, Levels 1\u20135 \u2014 **3500 psi (C25/30)**, 25 mm cover\n"
     "* Columns \u2014 4000 psi, 40 mm cover\n\n"
     "All concrete must come from a BSTI-accredited ready-mix plant, with one set of "
     "cylinder tests per 50 cubic metres or per pour, whichever is more frequent.",
     (("06_Tender-Specification.pdf", 2),)),
    (("glazing", "sample", "lead time", "aluminium", "panel"),
     "The glazing lead time is **12 weeks from written approval of the sample panel** "
     "\u2014 and the panel has not been approved. The task *Glazing sample panel "
     "approval* is currently **Blocked**.\n\n"
     "The system must be thermally broken aluminium with 6 mm + 12 mm air gap + 6 mm "
     "double glazed units, tested for air permeability. Manufacture cannot be released "
     "until the Architect approves the full-size sample panel in writing.",
     (("06_Tender-Specification.pdf", 3),
      ("04_Procurement-Schedule.xlsx", 1))),
    (("damages", "liquidated", "penalty", "late", "delay"),
     "Liquidated damages are **0.05% per day, capped at 10% of the contract sum** "
     "\u2014 a maximum of \u09f3 6,00,00,000.\n\n"
     "The date for completion is **30 June 2027**. Retention is 10 per cent: 5% released "
     "at completion and 5% at the end of the 12-month defects liability period.",
     (("06_Tender-Specification.pdf", 1),)),
    (("working hours", "noise", "friday", "holiday", "hours"),
     "Working hours are **08:00 to 18:00, Saturday to Thursday**. **Friday is the weekly "
     "holiday** and no work is permitted on Friday or public holidays.\n\n"
     "Noisy operations \u2014 anything above **75 dB(A)** at the site boundary \u2014 "
     "are further restricted to **09:00 to 17:00**, because the adjoining outpatient "
     "department stays in clinical use throughout the works.",
     (("06_Tender-Specification.pdf", 1),)),
    (("operation theatre", "theatre", "iso", "class 7", "hepa", "air change"),
     "The two modular operation theatres must achieve **ISO 14644-1 Class 7**, with a "
     "minimum of **20 air changes per hour** and **+15 Pa positive pressure** relative "
     "to adjacent areas.\n\n"
     "HEPA filters are verified by an independent agency after installation and before "
     "handover.",
     (("06_Tender-Specification.pdf", 3),)),
    (("drawing", "revision", "superseded", "a-201", "sheet"),
     "Sheet **A-201 (Ground floor plan)** was reissued at **Revision D** on 2 September "
     "2026, relocating the emergency department entrance from grid C to grid D.\n\n"
     "**Revision C is superseded** and must be withdrawn from site. Two sheets are still "
     "marked 'For approval' and must not be built from: **A-420** and **E-500**.",
     (("07_Drawing-Register.pdf", 1),)),
    (("lift", "elevator", "import", "letter of credit", "lc"),
     "There are four lifts, two of them stretcher lifts, and they are imported with a "
     "**16-week lead time**.\n\n"
     "The need-by date is 21 March 2027, which means the date for opening the letter of "
     "credit has already passed \u2014 the line is still marked *Requested* on the "
     "procurement schedule.",
     (("04_Procurement-Schedule.xlsx", 1),
      ("01_Project-Brief.pdf", 1))),
    (("monsoon", "rain", "weather", "season"),
     "From June to September the Contractor must maintain adequate covering, pumping and "
     "temporary drainage for open slabs and castings.\n\n"
     "Claims for weather delay are admissible **only with Bangladesh Meteorological "
     "Department records** for the days claimed.",
     (("06_Tender-Specification.pdf", 1),)),
    (("handover", "occupancy", "rajuk", "completion", "commissioning"),
     "Practical completion is due **30 June 2027**, and cannot be certified until all "
     "commissioning is complete and the handover documentation has been accepted.\n\n"
     "* Witnessed commissioning \u2014 **4 weeks** before completion\n"
     "* Draft O&M manuals \u2014 **8 weeks** before completion\n"
     "* RAJUK occupancy certificate and Fire Service clearance \u2014 at completion\n"
     "* Building user training \u2014 4 sessions, 2 weeks before completion",
     (("06_Tender-Specification.pdf", 3),)),
)

FALLBACK_ANSWER = (
    "I can only answer from the documents indexed for this account, and I could not find "
    "a passage that settles that.\n\n"
    "This workspace holds the tender specification, the drawing register, the ground "
    "floor plan, the works programme, the cost plan, the procurement schedule and a site "
    "instruction \u2014 try asking about the RFI response period, concrete grades, the "
    "glazing lead time, liquidated damages, working hours, the operation theatre "
    "standard, the lift import, monsoon provisions, or handover.")


@app.post("/api/chat")
async def chat(request: Request, context=Depends(require_account)) -> dict:
    body = await request.json()
    question = str(body.get("message", body.get("query", ""))).lower()
    answer, cites = FALLBACK_ANSWER, ()
    best = 0
    for keywords, text, sources in SCRIPTED_ANSWERS:
        score = sum(1 for word in keywords if word in question)
        if score > best:
            answer, cites, best = text, sources, score

    documents = context.workspace.load_metadata().get("documents", {})
    by_name = {doc.get("name"): doc_id for doc_id, doc in documents.items()}
    sources = [{"doc_id": by_name.get(name, name), "doc_name": name, "page": page,
                "score": round(0.94 - index * 0.07, 2)}
               for index, (name, page) in enumerate(cites)]
    return {"response": answer, "answer": answer, "sources": sources,
            "message_id": uuid.uuid4().hex,
            "model": "demonstration backend — scripted, not generated"}


@app.post("/api/chat/export-pdf")
async def export_chat() -> JSONResponse:
    return JSONResponse(status_code=503,
                        content={"detail": "Chat export needs the document renderer."})


@app.get("/api/document-templates")
async def document_templates() -> dict:
    return {"templates": [
        {"id": "tender_summary", "name": "Tender Summary",
         "description": "Scope, particulars and key requirements, cited to the tender pack."},
        {"id": "project_overview", "name": "Project Overview",
         "description": "A briefing document assembled from the project's own sources."},
        {"id": "schedule_narrative", "name": "Schedule Narrative",
         "description": "The programme explained in prose, with the dates cited."},
        {"id": "addendum", "name": "Addendum",
         "description": "Changes since the last issue, with the clause each one touches."}]}


@app.get("/api/projects/{project_id}/source-documents")
async def source_documents(project_id: str, context=Depends(require_account)) -> dict:
    documents = context.workspace.load_metadata().get("documents", {})
    return {"documents": [doc for doc in documents.values()
                          if doc.get("project_id") == project_id]}


# -- Google Workspace and Microsoft 365, simulated -----------------------
# Nothing here reaches a provider. Every account, file, message and meeting
# link is invented, and every response says so with "simulated": true, so the
# Drive indexing, mail and calendar features can be walked through without
# anybody signing in to anything.

providers.register_simulated_providers(NAMESPACE)


# ── Seeding ──────────────────────────────────────────────────────────────

def iso(value: str) -> str:
    return value


def seed() -> str:
    """Create the account and load the demonstration project into it."""
    account = REGISTRY.create_account(ACCOUNT_NAME)
    owner = REGISTRY.create_user(
        account_id=account["id"], name="Md. Rafiqul Islam", email=DEMO_EMAIL,
        password=DEMO_PASSWORD, role="Super Admin", is_owner=True,
        department="Management", designation="Project Director",
        company=ACCOUNT_NAME, phone="01711-902345", time_zone="Asia/Dhaka")
    REGISTRY.update_account(account["id"], {"owner_user_id": owner["id"]})
    workspace = REGISTRY.workspace(account["id"])

    # -- company and catalogues ------------------------------------------
    workspace.save_company({
        "name": ACCOUNT_NAME,
        "registration": "RJSC C-118472/2009",
        "email": "info@purbachalcon.example", "phone": "+880 2 5566 1180",
        "address": "House 27, Road 5, Dhanmondi, Dhaka 1209, Bangladesh",
        "website": "https://purbachalcon.example", "founded": "2009",
        "description": "Principal contractor for healthcare, education and commercial "
                       "buildings across Dhaka and Chattogram."})

    mgmt = workspace.load_mgmt()
    mgmt["trades"] = [
        {"id": uuid.uuid4().hex[:12], "name": name, "description": detail, "status": "Active"}
        for name, detail in (
            ("General", "Preliminaries, management and works not otherwise classified"),
            ("Earthworks", "Excavation, filling, drainage and external works"),
            ("Piling", "Bored and driven piling"),
            ("Concrete", "Ready-mix and site concrete"),
            ("Rebar", "Reinforcement cutting, bending and fixing"),
            ("Masonry", "Brickwork and plaster"),
            ("Glazing", "Aluminium glazing, windows and external doors"),
            ("Electrical", "Power, lighting, generator and substation"),
            ("Plumbing", "Water supply, sanitary and drainage"),
            ("HVAC", "Chillers, ducting and air handling"),
            ("Tiling", "Floor and wall tiling"),
            ("Painting", "Internal and external painting"),
            ("Lifts", "Lift supply and installation"),
            ("Fire Safety", "Hydrants, sprinklers and detection"))]

    mgmt["vendors"] = [
        {"id": uuid.uuid4().hex[:12], "name": supplier, "status": "Active",
         "trade": trade, "vendorType": "Supplier",
         "contact": "orders@" + supplier.split()[0].lower() + ".example",
         "description": "-"}
        for supplier, trade in sorted({(row[1], row[2]) for row in pack.PROCUREMENT})]

    mgmt["project_types"] = [
        {"id": "pt-health", "name": "Healthcare", "status": "Active",
         "description": "Hospitals, clinics and diagnostic centres"},
        {"id": "pt-edu", "name": "Education", "status": "Active",
         "description": "Schools, colleges and university buildings"},
        {"id": "pt-com", "name": "Commercial", "status": "Active",
         "description": "Offices and retail"},
        {"id": "pt-res", "name": "Residential", "status": "Active",
         "description": "Apartments and housing projects"}]

    mgmt["task_types"] = [
        {"id": "tt-con", "name": "Construction", "status": "Active",
         "description": "Physical work on site"},
        {"id": "tt-des", "name": "Design", "status": "Active",
         "description": "Design, approvals and sample panels"},
        {"id": "tt-sur", "name": "Survey", "status": "Active",
         "description": "Soil testing and topographic survey"},
        {"id": "tt-pha", "name": "Phase", "status": "Active",
         "description": "A programme phase containing other tasks"},
        {"id": "tt-com", "name": "Commissioning", "status": "Active",
         "description": "Testing, balancing and witnessed commissioning"},
        {"id": "tt-han", "name": "Handover", "status": "Active",
         "description": "Documentation, training and completion"}]
    workspace.save_mgmt(mgmt)

    # -- roles -------------------------------------------------------------
    from backend.permissions import PERMISSIONS

    keys = [entry["key"] for entry in PERMISSIONS]
    grants = {
        "Project Manager": [k for k in keys if not k.startswith("settings.")],
        "Site Supervisor": [k for k in keys
                            if k.startswith("task.") and "cost" not in k] + ["project.view"],
        "Cost Manager": [k for k in keys if k.startswith("cost.") or k == "project.view"
                         or k.startswith("procurement.")],
        "Viewer": [k for k in keys if k.endswith(".view")],
    }
    descriptions = (
        "Full project and task control, may approve costs",
        "Task status and progress updates, no cost visibility",
        "Costs and procurement, read-only on tasks",
        "Read-only access to the project, no editing")
    workspace.save_roles([
        {"id": uuid.uuid4().hex[:12], "name": name, "permissions": sorted(set(granted)),
         "description": detail, "created_at": datetime.now(timezone.utc).isoformat()}
        for (name, granted), detail in zip(grants.items(), descriptions)])

    # -- the people --------------------------------------------------------
    for name, bengali, email, title, role, department, phone in pack.TEAM:
        if email == DEMO_EMAIL:
            continue
        REGISTRY.create_user(account_id=account["id"], name=name, email=email,
                             password=DEMO_PASSWORD, role=role, phone=phone,
                             department=department, designation=title,
                             company=ACCOUNT_NAME, time_zone="Asia/Dhaka")

    # -- the project -------------------------------------------------------
    project = _make_project({
        "name": pack.PROJECT_EN, "project_code": pack.CODE,
        "manager": "Md. Rafiqul Islam",
        "type": "Healthcare", "status": "Active",
        "start_date": pack.START.isoformat(), "end_date": pack.FINISH.isoformat(),
        "description": f"Six-storey specialised hospital extension of {pack.GIA_M2:,} m2 "
                       f"for {pack.CLIENT_EN}, with two modular operation theatres, an "
                       f"18-bed ICU and a 12-bed emergency unit on 320 bored piles.",
        "address_line1": "Road 4, Sector 11", "address_line2": "Uttara",
        "city": "Dhaka", "state": "Dhaka Division",
        "postal_code": "1230", "country": "Bangladesh"})
    project["currency"] = "BDT"
    project["baseline_cost"] = pack.PRELIMINARIES
    project["additional_costs"] = [
        {"id": uuid.uuid4().hex[:12], "name": row[1], "amount": row[3],
         "cost_type": row[4], "description": row[2]}
        for row in pack.COSTS if row[4] not in ("Construction", "Preliminaries")]
    project["members"] = [
        {"user_id": user["id"], "name": user["name"], "role": user.get("role", ""),
         "added_at": datetime.now(timezone.utc).isoformat()}
        for user in REGISTRY._users().values()  # noqa: SLF001
        if user.get("account_id") == account["id"]]

    # -- the programme -----------------------------------------------------
    by_name: dict[str, str] = {}
    rows: list[dict] = []
    for name, parent, trade, who, begins, ends, cost, priority, state, kind in pack.TASKS:
        task_id = uuid.uuid4().hex[:12]
        by_name[name] = task_id
        rows.append({
            "id": task_id, "name": name, "task_type": kind, "trade": trade,
            "assignee": who, "field_worker": "", "start_time": begins, "end_time": ends,
            "due_date": ends, "priority": priority, "status": state,
            "delegation": "", "description": "", "cost": cost, "archived": False,
            "parent_id": "", "_parent_name": parent,
            "created_at": datetime.now(timezone.utc).isoformat()})
    for row in rows:
        row["parent_id"] = by_name.get(row.pop("_parent_name", ""), "")

    # -- procurement -------------------------------------------------------
    procurement_rows = [
        {"id": uuid.uuid4().hex[:12], "name": name, "description": "", "supplier": supplier,
         "trade": trade, "quantity": quantity, "unit": unit, "unit_cost": unit_cost,
         "status": state, "needed_by": needed, "ordered_on": ordered, "notes": notes,
         "created_at": datetime.now(timezone.utc).isoformat()}
        for name, supplier, trade, quantity, unit, unit_cost, state, needed, ordered, notes
        in pack.PROCUREMENT]

    # -- two more projects, so the register shows more than one phase ------
    extra_projects: dict[str, dict] = {}
    extra_tasks: dict[str, list] = {}
    today = date.today()

    def simple(name: str, code: str, kind: str, manager: str, status: str,
               begins: date, ends: date, city: str,
               rows_in: list[tuple[str, int, str, str]]) -> None:
        item = _make_project({
            "name": name, "project_code": code, "manager": manager, "type": kind,
            "status": status, "start_date": begins.isoformat(),
            "end_date": ends.isoformat(), "city": city,
            "country": "\u09ac\u09be\u0982\u09b2\u09be\u09a6\u09c7\u09b6 (Bangladesh)"})
        item["currency"] = "BDT"
        item["baseline_cost"] = 0
        item["additional_costs"] = []
        item["members"] = project["members"][:4]
        extra_projects[item["id"]] = item
        span = max(4, (ends - begins).days // max(1, len(rows_in)))
        extra_tasks[item["id"]] = [
            {"id": uuid.uuid4().hex[:12], "name": title, "task_type": "Construction",
             "trade": trade, "assignee": manager, "field_worker": "",
             "start_time": (begins + timedelta(days=span * index)).isoformat(),
             "end_time": (begins + timedelta(days=span * (index + 1) - 1)).isoformat(),
             "due_date": (begins + timedelta(days=span * (index + 1) - 1)).isoformat(),
             "priority": "Normal", "status": state, "delegation": "",
             "description": "", "cost": cost, "archived": False, "parent_id": "",
             "created_at": datetime.now(timezone.utc).isoformat()}
            for index, (title, cost, trade, state) in enumerate(rows_in)]

    simple("Banasree School Building", "BSB-2027", "Education",
           "Nusrat Jahan", "Active", today + timedelta(days=61),
           today + timedelta(days=440), "Dhaka", [
               ("Site preparation", 3_800_000, "General", "Open"),
               ("Piling and foundation", 18_500_000, "Piling", "Open"),
               ("Superstructure", 42_000_000, "Concrete", "Open"),
               ("Envelope", 16_200_000, "Glazing", "Open"),
               ("MEP and finishing", 27_400_000, "Electrical", "Open"),
               ("Handover", 4_600_000, "General", "Open")])

    simple("Agrabad Office Refurbishment", "AOR-2025", "Commercial",
           "Sabrina Chowdhury", "Completed", today - timedelta(days=455),
           today - timedelta(days=58), "Chattogram", [
               ("Strip out", 4_200_000, "Earthworks", "Completed"),
               ("Structural alteration", 11_800_000, "Concrete", "Completed"),
               ("Window replacement", 15_400_000, "Glazing", "Completed"),
               ("MEP installation", 19_600_000, "Electrical", "Completed"),
               ("Partitions and finishes", 13_900_000, "Tiling", "Completed"),
               ("Commissioning and handover", 3_100_000, "General", "Completed")])

    workspace.save_projects({project["id"]: project, **extra_projects})
    workspace.save_tasks({project["id"]: rows, **extra_tasks})
    workspace.save_procurement({project["id"]: procurement_rows})

    # -- the indexed documents --------------------------------------------
    meta = workspace.load_metadata()
    meta.setdefault("documents", {})
    for index, (name, pages, kind) in enumerate(DEMO_DOCUMENTS):
        doc_id = uuid.uuid4().hex[:12]
        source = PACK / name
        meta["documents"][doc_id] = {
            "id": doc_id, "name": name, "project_id": project["id"],
            "source_type": kind, "status": "indexed", "page_count": pages,
            "size": source.stat().st_size if source.exists() else 0,
            "digest": uuid.uuid4().hex,
            "uploaded_at": (today - timedelta(days=30 - index * 3)).isoformat(),
            "accessed_at": (today - timedelta(days=index)).isoformat(),
            "pages": [{"page_num": page, "image_path": f"{name}_{page}.png",
                       "text_content": ""} for page in range(1, pages + 1)]}
    workspace.save_metadata(meta)

    return account["id"]


# ── Static frontend, mounted last so /api wins ───────────────────────────

app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true",
                        help="discard the seeded workspace and build it again")
    parser.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()

    if options.reset and RUNTIME.exists():
        shutil.rmtree(RUNTIME)
        RUNTIME.mkdir(parents=True)

    marker = RUNTIME / "seeded.json"
    if not marker.exists():
        account_id = seed()
        marker.write_text(json.dumps({"account_id": account_id,
                                      "seeded_at": datetime.now(timezone.utc).isoformat()}),
                          encoding="utf-8")
        print(f"seeded account {account_id}")

    print("=" * 66)
    print("  BuildMarshalAI — demonstration backend")
    print("=" * 66)
    print(f"  Open      http://127.0.0.1:{options.port}")
    print(f"  Sign in   {DEMO_EMAIL}")
    print(f"  Password  {DEMO_PASSWORD}")
    print("  Retrieval answers from a script; nothing is indexed.")
    print("=" * 66)
    uvicorn.run(app, host="127.0.0.1", port=options.port, log_level="warning")


if __name__ == "__main__":
    main()
