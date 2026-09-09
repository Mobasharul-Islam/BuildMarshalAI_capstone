"""
Comprehensive End-to-End Test Suite for BuildMarshalAI
Tests all 9 Core Modules and 25+ REST Endpoints.
"""

import sys, os, time, json, urllib.request, urllib.error
from pathlib import Path

# Force UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8000"
passed = 0
failed = 0
results = []

# Every account-scoped endpoint needs a bearer token.  SESSION_TOKEN holds the
# primary account's session; pass token=... to act as a different account, or
# token="" to call an endpoint with no credentials at all.
SESSION_TOKEN = ""
_UNSET = object()

def req(path, method="GET", data=None, headers=None, expect_status=200, token=_UNSET, timeout=45):
    url = f"{BASE_URL}{path}"
    headers = dict(headers or {})
    bearer = SESSION_TOKEN if token is _UNSET else token
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if data is not None and isinstance(data, (dict, list)):
        data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            raw = response.read()
            if "application/json" in content_type:
                body = json.loads(raw.decode("utf-8"))
            elif "application/pdf" in content_type or "image/" in content_type:
                body = raw
            else:
                body = raw.decode("utf-8", errors="ignore")
            return status, body
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw.decode("utf-8"))
        except:
            body = raw.decode("utf-8", errors="ignore")
        return e.code, body
    except Exception as e:
        return 0, str(e)

def test_feature(module, name, fn):
    global passed, failed
    print(f"Testing [{module}] {name}...", end=" ", flush=True)
    t0 = time.time()
    try:
        res = fn()
        dt = round((time.time() - t0) * 1000, 1)
        passed += 1
        print(f"PASSED ({dt}ms)")
        results.append({"module": module, "name": name, "status": "PASSED", "duration_ms": dt, "details": res})
    except AssertionError as ae:
        dt = round((time.time() - t0) * 1000, 1)
        failed += 1
        print(f"FAILED ({dt}ms): {ae}")
        results.append({"module": module, "name": name, "status": "FAILED", "duration_ms": dt, "error": str(ae)})
    except Exception as e:
        dt = round((time.time() - t0) * 1000, 1)
        failed += 1
        print(f"ERROR ({dt}ms): {e}")
        results.append({"module": module, "name": name, "status": "ERROR", "duration_ms": dt, "error": str(e)})

print("=" * 70)
print("BUILDMARSHAL AI - GROUND-UP AUTOMATED TEST SUITE")
print("=" * 70)

# ── Module 0: Session bootstrap ──
# Everything below runs inside one account.  Prefer the administrator that ships
# with the handover data; fall back to a fresh account on an empty runtime.
primary_account_name = ""

def t_bootstrap_session():
    global SESSION_TOKEN, primary_account_name
    st, data = req("/api/auth/login", method="POST", token="", data={
        "email": "admin@buildmarshal.com", "password": "admin123",
    })
    if st != 200:
        st, data = req("/api/auth/register", method="POST", token="", data={
            "name": "Suite Runner",
            "email": f"suite_{int(time.time())}@buildmarshal.com",
            "password": "SuiteRunner!2026",
            "account_name": "Suite Workspace",
        })
        assert st == 200, f"Could not establish a session: {st} {data}"
    SESSION_TOKEN = data["token"]
    primary_account_name = data["account"]["name"]
    assert SESSION_TOKEN, "No session token returned"
    return f"Account: {primary_account_name} | User: {data['user']['name']}"

def t_reject_anonymous_access():
    for path in ("/api/documents", "/api/projects", "/api/users", "/api/status", "/api/conversations"):
        st, _ = req(path, token="")
        assert st == 401, f"{path} answered {st} without credentials; expected 401"
    return "5 account-scoped endpoints refuse anonymous callers"

test_feature("0. Session", "Authenticate Primary Account", t_bootstrap_session)
test_feature("0. Session", "Anonymous Requests Rejected", t_reject_anonymous_access)

# ── Module 1: System & Engine Health ──
def t_health():
    st, data = req("/api/health")
    assert st == 200, f"Expected 200, got {st}"
    assert data.get("status") == "healthy", f"Expected status healthy, got {data}"
    assert data.get("gpu_available") == True, "Expected GPU to be available"
    return f"GPU: {data['gpus'][0]['name']}, Chroma Pages: {data['chroma_pages']}"

def t_proxy_status():
    st, data = req("/api/cliproxy/status")
    assert st == 200, f"Expected 200, got {st}"
    assert data.get("ok") == True or "gemini" in str(data).lower(), f"Unexpected proxy status: {data}"
    return f"Proxy OK: {data.get('ok')}, Model: {data.get('model')}"

def t_chroma_stats():
    st, data = req("/api/chroma/stats")
    assert st == 200, f"Expected 200, got {st}"
    assert data.get("total_pages", 0) >= 0, "Expected non-negative total_pages"
    return f"Total Indexed Pages: {data['total_pages']}"

test_feature("1. System Health", "Backend & GPU Health Check", t_health)
test_feature("1. System Health", "CLIProxyAPI Gemini Connectivity", t_proxy_status)
test_feature("1. System Health", "ChromaDB Vector Store Inspection", t_chroma_stats)

# ── Module 2: Multi-Format Document Ingestion ──
test_doc_id = f"test_doc_{int(time.time())}"
def t_doc_upload():
    global test_doc_id
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(200, 10, text="BuildMarshal AI Test Document - Foundation Inspection Spec")
    pdf.ln(10)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 10, text="Section 1.0: Foundation concrete strength must achieve 4000 PSI at 28 days.\nSection 2.0: Rebar placement inspection required prior to pour.")
    pdf_bytes = bytes(pdf.output())
    
    boundary = "----WebKitFormBoundaryTest12345"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="doc_id"\r\n\r\n{test_doc_id}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="Test_Foundation_Spec.pdf"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + pdf_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    
    st, data = req("/api/upload", method="POST", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("status") == "indexed", f"Expected status indexed, got {data}"
    assert data.get("pages") >= 1, f"Expected at least 1 page, got {data}"
    return f"Indexed Doc ID: {data['id']}, Pages: {data['pages']}"

def t_list_docs():
    st, data = req("/api/documents")
    assert st == 200, f"Expected 200, got {st}"
    assert "documents" in data, "Missing documents list"
    uploaded = next((d for d in data["documents"] if d["id"] == test_doc_id), None)
    assert uploaded is not None, f"Uploaded doc {test_doc_id} not found in doc list"
    # The list and the citations in chat answers must show the name the user
    # uploaded, not the generated id the file is stored under.
    assert uploaded["name"] == "Test_Foundation_Spec.pdf", (
        f"Original filename was not preserved: {uploaded['name']!r}"
    )
    return f"Document Count: {len(data['documents'])}, Name Preserved: {uploaded['name']}"

test_feature("2. Ingestion", "Upload & Index PDF with ColPali", t_doc_upload)
test_feature("2. Ingestion", "List Indexed Documents", t_list_docs)

# ── Module 3: Multimodal RAG Chatbot ──
def t_rag_chat():
    payload = {
        "query": "What are the foundation concrete requirements in the specs?",
        "history": [],
        "model": "gemini-3.7-flash-high",
        "top_k": 3
    }
    st, data = req("/api/chat", method="POST", data=payload)
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert "response" in data and len(data["response"]) > 0, "Empty response from chat"
    assert "sources" in data, "Missing sources in chat response"
    return f"Response Length: {len(data['response'])} chars, Sources: {len(data.get('sources', []))}"

def t_chat_export_pdf():
    payload = {
        "title": "Site Inspection Chat Session",
        "messages": [
            {"role": "user", "content": "What are the foundation concrete requirements?", "timestamp": "10:00 AM"},
            {"role": "bot", "content": "The foundation concrete strength must achieve 4000 PSI at 28 days.", "timestamp": "10:01 AM"}
        ]
    }
    st, data = req("/api/chat/export-pdf", method="POST", data=payload)
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert isinstance(data, (bytes, bytearray)) and len(data) > 500, "Expected valid PDF binary"
    return f"Generated Chat PDF Size: {len(data)} bytes"

test_feature("3. RAG Chatbot", "ColPali Multi-Vector Retrieval & Gemini Generation", t_rag_chat)
test_feature("3. RAG Chatbot", "Export Chat Transcript to PDF", t_chat_export_pdf)

# ── Module 4: Evidence Viewer & Active Learning Feedback ──
def t_evidence_viewer():
    st, data = req(f"/api/evidence/{test_doc_id}/1")
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("doc_id") == test_doc_id, f"Expected doc_id {test_doc_id}"
    assert "image_endpoint" in data or "evidence_text" in data, "Missing evidence data in payload"
    return f"Evidence Doc: {data.get('doc_name')}, Endpoint: {data.get('image_endpoint')}"

def t_evidence_feedback():
    payload = {
        "doc_id": test_doc_id,
        "page": 1,
        "query": "foundation concrete requirements",
        "rating": "relevant"
    }
    st, data = req("/api/evidence/feedback", method="POST", data=payload)
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("status") == "saved", f"Unexpected response: {data}"
    return f"Feedback Saved ID: {data.get('feedback_id')}"

def t_feedback_stats():
    st, data = req("/api/evidence-feedback/stats")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Feedback Metrics: {data}"

test_feature("4. Evidence & Feedback", "Fetch High-Res Page Evidence & Metadata", t_evidence_viewer)
test_feature("4. Evidence & Feedback", "Submit Active Learning Retrieval Feedback", t_evidence_feedback)
test_feature("4. Evidence & Feedback", "Inspect Feedback Analytics & Accuracy Stats", t_feedback_stats)

# ── Module 5: Projects & Tasks Management ──
created_project_id = None
created_task_id = None

def t_create_project():
    global created_project_id
    payload = {
        "name": "Skyline Commercial Center",
        "project_code": f"PRJ-{int(time.time())}",
        "manager": "Alex Smith",
        "type": "Commercial",
        "status": "Active",
        "description": "High-rise construction project with reinforced concrete structure.",
        "address_line1": "742 Evergreen Terrace",
        "city": "Springfield",
        "state": "IL",
        "postal_code": "62704",
        "country": "USA"
    }
    st, data = req("/api/projects", method="POST", data=payload)
    assert st == 200, f"Expected 200, got {st}: {data}"
    created_project_id = data.get("id") or data.get("project", {}).get("id")
    assert created_project_id is not None, f"Failed to get project ID: {data}"
    return f"Created Project ID: {created_project_id}"

def t_get_project():
    st, data = req(f"/api/projects/{created_project_id}")
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("name") == "Skyline Commercial Center", f"Unexpected project: {data}"
    return f"Project Name: {data.get('name')}, Manager: {data.get('manager')}"

def t_create_task():
    global created_task_id
    payload = {
        "name": "Pour Level 1 Foundation Slab",
        "assignee": "Concrete Subcontractor",
        "due_date": "2026-09-15",
        "status": "In Progress"
    }
    st, data = req(f"/api/projects/{created_project_id}/tasks", method="POST", data=payload)
    assert st == 200, f"Expected 200, got {st}: {data}"
    created_task_id = data.get("id") or data.get("task", {}).get("id")
    assert created_task_id is not None, f"Failed to get task ID: {data}"
    return f"Created Task ID: {created_task_id}"

def t_list_tasks():
    st, data = req(f"/api/projects/{created_project_id}/tasks")
    assert st == 200, f"Expected 200, got {st}: {data}"
    tasks = data.get("tasks", []) if isinstance(data, dict) else data
    assert any(t.get("id") == created_task_id for t in tasks), f"Task {created_task_id} not found in task list"
    return f"Task Count for Project: {len(tasks)}"

def t_update_task():
    payload = {
        "status": "Completed"
    }
    st, data = req(f"/api/projects/{created_project_id}/tasks/{created_task_id}", method="PUT", data=payload)
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Task Status updated to: {data.get('status', 'Completed')}"

test_feature("5. Projects & Tasks", "Create New Project", t_create_project)
test_feature("5. Projects & Tasks", "Read Project Details", t_get_project)
test_feature("5. Projects & Tasks", "Create Project Task", t_create_task)
test_feature("5. Projects & Tasks", "List Project Tasks", t_list_tasks)
subtask_id = None

def t_task_full_record():
    """Every field the Task Manager edits must round-trip."""
    payload = {
        "name": "Hardwood install downstairs garageroom",
        "task_type": "Inspection", "trade": "Carpentry", "assignee": "Site Lead",
        "field_worker": "Crew A", "start_time": "2027-03-26T02:00",
        "end_time": "2027-04-14T11:00", "priority": "High", "status": "Open",
        "delegation": "Framing crew", "description": "Install hardwood throughout.",
    }
    st, data = req(f"/api/projects/{created_project_id}/tasks", method="POST", data=payload)
    assert st == 200, f"Expected 200, got {st}: {data}"
    for key, value in payload.items():
        assert data.get(key) == value, f"{key} did not round-trip: {data.get(key)!r}"
    assert data["archived"] is False and data["parent_id"] is None
    return f"Task stored with {len(payload)} fields"

def t_task_subtasks():
    global subtask_id
    st, child = req(f"/api/projects/{created_project_id}/tasks", method="POST", data={
        "name": "Move garageroom furniture", "parent_id": created_task_id})
    assert st == 200, f"Expected 200, got {st}: {child}"
    subtask_id = child["id"]
    assert child["parent_id"] == created_task_id, f"Parent not set: {child}"

    st, detail = req(f"/api/projects/{created_project_id}/tasks/{created_task_id}")
    assert st == 200, f"Expected 200, got {st}: {detail}"
    assert any(s["id"] == subtask_id for s in detail.get("subtasks", [])), f"Subtask missing: {detail}"

    st, roots = req(f"/api/projects/{created_project_id}/tasks?parent_id=root")
    assert all(t.get("parent_id") is None for t in roots["tasks"]), "Root filter returned a child"
    return f"Subtask linked; {len(roots['tasks'])} root task(s)"

def t_task_filters_and_archive():
    st, named = req(f"/api/projects/{created_project_id}/tasks?name=furniture")
    assert st == 200 and named["total"] >= 1, f"Name filter failed: {named}"

    st, _ = req(f"/api/projects/{created_project_id}/tasks/{subtask_id}",
                method="PUT", data={"archived": True})
    st, visible = req(f"/api/projects/{created_project_id}/tasks")
    assert not any(t["id"] == subtask_id for t in visible["tasks"]), "Archived task still listed"
    st, all_tasks = req(f"/api/projects/{created_project_id}/tasks?show_archived=true")
    assert any(t["id"] == subtask_id for t in all_tasks["tasks"]), "Archived task not retrievable"
    req(f"/api/projects/{created_project_id}/tasks/{subtask_id}", method="PUT", data={"archived": False})
    return "Name filter and archive round-trip work"

def t_task_validation():
    """Bad values must be refused rather than stored."""
    st, _ = req(f"/api/projects/{created_project_id}/tasks", method="POST", data={"name": "  "})
    assert st == 422, f"Blank name accepted (status {st})"
    st, _ = req(f"/api/projects/{created_project_id}/tasks/{created_task_id}",
                method="PUT", data={"status": "Nonsense"})
    assert st == 422, f"Invalid status accepted (status {st})"
    st, _ = req(f"/api/projects/{created_project_id}/tasks/{created_task_id}",
                method="PUT", data={"parent_id": created_task_id})
    assert st == 422, f"Self-parent accepted (status {st})"
    st, _ = req(f"/api/projects/{created_project_id}/tasks/{created_task_id}", method="PUT",
                data={"start_time": "2027-04-01T10:00", "end_time": "2027-03-01T10:00"})
    assert st == 422, f"End before start accepted (status {st})"
    return "Blank name, bad status, self-parent, and reversed times all rejected"

def t_task_types_directory():
    st, data = req("/api/task-types")
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert len(data.get("task_types", [])) >= 1, f"No task types seeded: {data}"
    return f"Task types: {[t['name'] for t in data['task_types']][:3]}"

test_feature("5. Projects & Tasks", "Update Task Status", t_update_task)
test_feature("5. Projects & Tasks", "Task Record Keeps Every Field", t_task_full_record)
test_feature("5. Projects & Tasks", "Subtasks & Task Detail View", t_task_subtasks)
test_feature("5. Projects & Tasks", "Task Filters & Archive", t_task_filters_and_archive)
test_feature("5. Projects & Tasks", "Task Validation Rejects Bad Input", t_task_validation)
def t_project_sections():
    """People, cost, timeline, and procurement for a project."""
    st, members = req(f"/api/projects/{created_project_id}/members")
    assert st == 200 and "available" in members, f"Members unavailable: {members}"
    me = req("/api/auth/me")[1]["user"]["id"]
    st, added = req(f"/api/projects/{created_project_id}/members", method="POST",
                    data={"user_ids": [me], "project_role": "Suite runner"})
    assert st == 200 and added["added"] == 1, f"Could not add a member: {added}"
    st, _ = req(f"/api/projects/{created_project_id}/members/{me}", method="DELETE")
    assert st == 200, "Could not remove the member"

    req(f"/api/projects/{created_project_id}/costs/baseline", method="PUT", data={"amount": 1000})
    st, cost = req(f"/api/projects/{created_project_id}/costs", method="POST",
                   data={"name": "Suite cost", "details": "temp", "amount": 250})
    assert st == 200, f"Could not add a cost: {cost}"
    st, breakdown = req(f"/api/projects/{created_project_id}/costs")
    expected = breakdown["baseline_cost"] + breakdown["additional_total"] + breakdown["tasks_total"]
    assert abs(breakdown["total"] - expected) < 0.01, f"Total does not add up: {breakdown}"
    req(f"/api/projects/{created_project_id}/costs/{cost['cost']['id']}", method="DELETE")

    st, timeline = req(f"/api/projects/{created_project_id}/timeline")
    assert st == 200 and "window" in timeline and "tasks" in timeline, f"Bad timeline: {timeline}"

    st, item = req(f"/api/projects/{created_project_id}/procurement", method="POST",
                   data={"name": "Suite material", "quantity": 3, "unit_cost": 10, "status": "Ordered"})
    assert st == 200, f"Could not add procurement: {item}"
    st, listed = req(f"/api/projects/{created_project_id}/procurement")
    assert listed["total"] == 30, f"Committed spend wrong: {listed}"
    return f"People, cost (total {breakdown['total']}), timeline, and procurement all work"

def t_project_delete_clears_its_data():
    """Deleting a project must not leave tasks or procurement behind."""
    st, project = req("/api/projects", method="POST", data={
        "name": f"Teardown check {int(time.time())}", "project_code": f"TD{int(time.time())%10000}"})
    assert st == 200, f"Could not create the project: {project}"
    pid = project["id"]
    req(f"/api/projects/{pid}/tasks", method="POST", data={"name": "Temp task"})
    req(f"/api/projects/{pid}/procurement", method="POST", data={"name": "Temp item", "unit_cost": 5})
    assert req(f"/api/projects/{pid}/procurement")[1]["count"] == 1

    assert req(f"/api/projects/{pid}", method="DELETE")[0] == 200
    # The project is gone, so its sections must be gone with it.
    for path in (f"/api/projects/{pid}/tasks", f"/api/projects/{pid}/procurement"):
        assert req(path)[0] == 404, f"{path} survived the project delete"

    # Re-creating an id-less project must not inherit the old rows.
    st, again = req("/api/projects", method="POST", data={
        "name": f"Teardown check 2 {int(time.time())}", "project_code": f"TE{int(time.time())%10000}"})
    assert req(f"/api/projects/{again['id']}/procurement")[1]["count"] == 0, "Stale procurement leaked"
    req(f"/api/projects/{again['id']}", method="DELETE")
    return "Deleting a project clears its tasks and procurement"

test_feature("5. Projects & Tasks", "Task Types Directory", t_task_types_directory)
test_feature("5. Projects & Tasks", "Project People, Cost, Timeline & Procurement", t_project_sections)
test_feature("5. Projects & Tasks", "Project Delete Clears Its Data", t_project_delete_clears_its_data)

# ── Module 6: AI Construction Document Generation ──
generated_doc_id = None
project_source_id = f"src_{int(time.time())}"


def build_source_pdf() -> bytes:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(200, 10, text="Skyline Commercial Center - Tender Addendum 01")
    pdf.ln(10)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 8, text=(
        "1.0 Scope: Structural steel erection for levels 1 through 8.\n"
        "2.0 Schedule: Substantial completion is required by 2027-04-30.\n"
        "3.0 Mandatory requirement: all bidders must submit a WCB clearance letter.\n"
        "4.0 Exclusions: site dewatering and hazardous material abatement are excluded."
    ))
    return bytes(pdf.output())


def multipart(fields: dict, filename: str, payload: bytes) -> tuple[str, bytes]:
    boundary = "----WebKitFormBoundaryBuildMarshal"
    body = b""
    for name, value in fields.items():
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
        ).encode("utf-8")
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return f"multipart/form-data; boundary={boundary}", body


def t_upload_project_source():
    content_type, body = multipart(
        {"doc_id": project_source_id}, "Tender_Addendum_01.pdf", build_source_pdf()
    )
    st, data = req(
        f"/api/projects/{created_project_id}/source-documents",
        method="POST", data=body, headers={"Content-Type": content_type},
    )
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("status") == "indexed", f"Expected indexed, got {data}"
    assert data.get("project_id") == created_project_id, f"Source not linked to project: {data}"
    return f"Indexed project source {data['id']} ({data.get('source_type')}, {data.get('pages')} page(s))"


def t_list_project_sources():
    st, data = req(f"/api/projects/{created_project_id}/source-documents")
    assert st == 200, f"Expected 200, got {st}: {data}"
    ids = {d.get("id") for d in data.get("documents", [])}
    assert project_source_id in ids, f"Uploaded source missing from project sources: {ids}"
    return f"Project Sources: {data.get('total')}"


def t_project_overview_pdf():
    st, data = req(f"/api/projects/{created_project_id}/generate-document", method="POST")
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert isinstance(data, (bytes, bytearray)) and len(data) > 500, "Expected valid PDF binary"
    return f"Project Overview PDF Size: {len(data)} bytes"


def t_list_templates():
    st, data = req("/api/document-templates")
    assert st == 200, f"Expected 200, got {st}: {data}"
    templates = data.get("templates", [])
    assert len(templates) >= 1, "Expected at least 1 template"
    return f"Available Templates: {[t['label'] for t in templates]}"

def t_generate_doc():
    global generated_doc_id
    payload = {
        "doc_kind": "tender_summary",
        "title": "Tender Summary - Skyline Commercial Center",
        "instructions": "Focus on mandatory tender requirements, schedule, and scope boundaries."
    }
    st, data = req(f"/api/projects/{created_project_id}/documents", method="POST",
                   data=payload, timeout=600)
    assert st in (200, 201), f"Expected 200/201, got {st}: {data}"
    generated_doc_id = data.get("id") or data.get("generated_id")
    assert generated_doc_id is not None, f"Failed to get generated document ID: {data}"
    assert data.get("source_page_count", 0) >= 1, (
        f"Report cited no source pages; the uploaded project source was not retrieved: {data}"
    )
    return (
        f"Generated Report ID: {generated_doc_id}, Title: {data.get('title')}, "
        f"Cited Pages: {data.get('source_page_count')}"
    )

def t_download_generated_doc():
    st, data = req(f"/api/generated-documents/{generated_doc_id}/download")
    assert st == 200, f"Expected 200, got {st}"
    assert isinstance(data, (bytes, bytearray)) and len(data) > 500, "Expected valid PDF binary"
    return f"Downloaded AI Report Size: {len(data)} bytes"

test_feature("6. AI Doc Generation", "List Construction Templates", t_list_templates)
test_feature("6. AI Doc Generation", "Upload Project Source PDF", t_upload_project_source)
test_feature("6. AI Doc Generation", "List Project Source Documents", t_list_project_sources)
test_feature("6. AI Doc Generation", "Synthesize & Generate AI Construction Report", t_generate_doc)
test_feature("6. AI Doc Generation", "Download Generated PDF Document", t_download_generated_doc)
test_feature("6. AI Doc Generation", "Project Overview PDF Export", t_project_overview_pdf)

# ── Module 7: Trades, Vendors, Team Members & Users ──
created_trade_id = None
created_vendor_id = None

def t_trades():
    global created_trade_id
    st, data = req("/api/trades")
    assert st == 200, f"Expected 200, got {st}: {data}"
    trades = data.get("trades", [])
    assert len(trades) > 0, "Expected trades list"
    
    new_trade = {"name": f"Specialist Glazing Trade", "description": "High-rise facade glazing", "status": "Active"}
    st2, data2 = req("/api/trades", method="POST", data=new_trade)
    assert st2 == 200, f"Failed to add trade: {data2}"
    created_trade_id = data2.get("id")
    return f"Total Trades: {len(trades) + 1}"

def t_vendors():
    global created_vendor_id
    st, data = req("/api/vendors")
    assert st == 200, f"Expected 200, got {st}: {data}"
    
    new_vendor = {
        "name": "Apex Structural Concrete Ltd",
        "contact_person": "Dave Miller",
        "email": "dave@apexconcrete.com",
        "phone": "+1-555-0199",
        "trade": "Concrete",
        "rating": 5
    }
    st2, data2 = req("/api/vendors", method="POST", data=new_vendor)
    assert st2 == 200, f"Failed to add vendor: {data2}"
    created_vendor_id = data2.get("id")
    return "Created vendor Apex Structural Concrete Ltd"

def t_team_members():
    st, data = req("/api/team-members")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Team Members Count: {len(data.get('team_members', []))}"

def t_users():
    st, data = req("/api/users")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Users Count: {len(data.get('users', []))}"

test_feature("7. Company & Trades", "Trades Directory & Custom Trade Registration", t_trades)
test_feature("7. Company & Trades", "External Companies / Vendors Management", t_vendors)
test_feature("7. Company & Trades", "Internal Team Directory", t_team_members)
test_feature("7. Company & Trades", "User Accounts Directory", t_users)

# ── Module 8: Google Workspace Integration ──
google_acc_id = None

def t_google_config():
    st, data = req("/api/google/config")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Google Client ID: {data.get('client_id')}, Scopes: {len(data.get('scopes', []))}"

def t_google_accounts():
    global google_acc_id
    st, data = req("/api/google/accounts")
    assert st == 200, f"Expected 200, got {st}: {data}"
    accounts = data.get("accounts", [])
    if accounts:
        google_acc_id = accounts[0].get("id")
        return f"Connected Account: {accounts[0].get('email')} (ID: {google_acc_id})"
    return "Google accounts store initialized (no accounts connected yet)"

def t_google_drive():
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req(f"/api/google/drive/files?account_id={google_acc_id}")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Drive Files Listed: {len(data.get('files', []))}"

def t_google_calendar():
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req(f"/api/google/calendar/events?account_id={google_acc_id}")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Calendar Events Listed: {len(data.get('events', []))}"

def t_google_gmail_messages():
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req(f"/api/google/gmail/messages?account_id={google_acc_id}&page_size=3")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Gmail Messages Listed: {len(data.get('messages', []))}"

def t_google_gmail_generate():
    """Compose draft text with the model. Nothing is drafted or sent in Gmail."""
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req("/api/google/gmail/generate", method="POST", data={
        "account_id": google_acc_id,
        "to": "site.super@example.com",
        "subject": "",
        "body": "",
        "instruction": "Ask the site superintendent to confirm the rebar inspection date.",
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("body"), f"Expected generated email body, got {data}"
    return f"Generated Email Subject: {str(data.get('subject'))[:60]}"

def t_google_send_requires_confirmation():
    """An unconfirmed draft/send must be refused before touching Gmail."""
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    for endpoint, action in (("draft", "create_email_draft"), ("send", "send_email")):
        st, data = req(f"/api/google/gmail/{endpoint}", method="POST", data={
            "account_id": google_acc_id, "to": "nobody@example.com",
            "subject": "Test", "body": "Test", "confirm": False,
        })
        assert st == 200, f"Expected 200, got {st}: {data}"
        assert data.get("confirmation_required") is True, f"{endpoint} did not require confirmation: {data}"
        assert data.get("action") == action, f"Unexpected action for {endpoint}: {data}"
    return "Gmail draft and send both refuse to act without explicit confirmation"

def t_google_calendar_requires_confirmation():
    """A task-to-calendar request must return a proposal, not create an event."""
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req(
        f"/api/google/tasks/{created_project_id}/{created_task_id}/calendar",
        method="POST", data={
            "account_id": google_acc_id, "summary": "", "start": "2027-01-04T09:00:00",
            "end": "2027-01-04T10:00:00", "timezone": "UTC", "confirm": False,
        },
    )
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("confirmation_required") is True, f"Calendar event was not gated: {data}"
    assert data.get("event", {}).get("summary"), f"Proposal missing task summary: {data}"
    return f"Calendar proposal returned for review: {data['event']['summary']}"

def t_google_assistant_interpret():
    """The assistant proposes a Calendar event; it never performs the action."""
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req("/api/google/assistant/interpret", method="POST", data={
        "account_id": google_acc_id,
        "query": "Schedule a rebar inspection walkthrough next Tuesday at 9am for one hour",
        "timezone": "UTC",
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert "proposal" in data, f"Expected a proposal, got {data}"
    if data.get("supported"):
        assert data.get("confirmation_required") is True, f"Proposal was not gated: {data}"
    return f"Assistant proposal supported={data.get('supported')}"

test_feature("8. Google Workspace", "Google OAuth Configuration & Scopes", t_google_config)
test_feature("8. Google Workspace", "Connected Google Account Tokens", t_google_accounts)
test_feature("8. Google Workspace", "Google Drive File Indexing & Listing", t_google_drive)
test_feature("8. Google Workspace", "Google Calendar Events & Schedule", t_google_calendar)
test_feature("8. Google Workspace", "Gmail Message Listing", t_google_gmail_messages)
test_feature("8. Google Workspace", "AI Email Composition (no send)", t_google_gmail_generate)
test_feature("8. Google Workspace", "Gmail Draft/Send Require Confirmation", t_google_send_requires_confirmation)
test_feature("8. Google Workspace", "Task-to-Calendar Requires Confirmation", t_google_calendar_requires_confirmation)
def t_google_meet_incomplete_asks_a_question():
    """An incomplete Meet request must come back as a follow-up question."""
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req("/api/google/meet/schedule", method="POST", timeout=180, data={
        "account_id": google_acc_id, "timezone": "UTC",
        "query": "schedule a google meet about the weekly site review",
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("status") == "needs_input", f"Expected a follow-up question: {data}"
    assert data.get("question"), f"No question was returned: {data}"
    assert "start" in data.get("missing", []), f"Expected the time to be missing: {data}"
    return f"Asked: {data['question'][:60]}"

def t_google_meet_proposes_before_creating():
    """A complete request must be proposed, never created without confirmation."""
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req("/api/google/meet/schedule", method="POST", timeout=180, data={
        "account_id": google_acc_id, "timezone": "UTC",
        "known": {"summary": "Suite check", "start": "2027-05-04T09:00:00",
                  "duration_minutes": 30, "attendees": []},
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("status") == "confirm", f"Expected a confirmation step: {data}"
    assert data["proposal"]["end"] == "2027-05-04T09:30:00", f"Bad end time: {data}"
    return "Complete request returned a proposal without creating anything"

def t_google_meet_rejects_invalid_attendees():
    """Invalid attendees stop the booking even when confirm is set."""
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req("/api/google/meet/schedule", method="POST", timeout=180, data={
        "account_id": google_acc_id, "timezone": "UTC", "confirm": True,
        "known": {"summary": "Suite check", "start": "2027-05-04T09:00:00",
                  "attendees": ["definitely-not-an-email"]},
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("status") == "needs_input", f"Invalid attendee was not caught: {data}"
    assert data.get("missing") == ["attendees"], f"Unexpected missing list: {data}"
    return "An invalid attendee blocks the booking and is questioned"

test_feature("8. Google Workspace", "Calendar Assistant Proposal (no write)", t_google_assistant_interpret)
test_feature("8. Google Workspace", "Meet: Incomplete Request Asks A Question", t_google_meet_incomplete_asks_a_question)
test_feature("8. Google Workspace", "Meet: Proposal Before Creation", t_google_meet_proposes_before_creating)
test_feature("8. Google Workspace", "Meet: Invalid Attendees Rejected", t_google_meet_rejects_invalid_attendees)

# ── Module 8b: Microsoft 365 (Graph) ──
# Runs against whatever the backend is configured with. Without Microsoft
# credentials the routes must still answer cleanly rather than erroring, and a
# connected tenant is exercised read-only.
microsoft_acc_id = None
microsoft_configured = False

def t_microsoft_config():
    global microsoft_configured
    st, data = req("/api/microsoft/config")
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert "enabled" in data, f"Missing enabled flag: {data}"
    assert "offline_access" in data.get("scopes", []), "A refresh token scope must be requested"
    microsoft_configured = bool(data["enabled"])
    return f"Configured: {microsoft_configured}, Tenant: {data.get('tenant')}"

def t_microsoft_accounts():
    global microsoft_acc_id
    st, data = req("/api/microsoft/accounts")
    assert st == 200, f"Expected 200, got {st}: {data}"
    accounts = data.get("accounts", [])
    if accounts:
        microsoft_acc_id = accounts[0]["id"]
        assert "refresh_token" not in accounts[0], "Tokens must never be returned"
    return f"Connected Microsoft accounts: {len(accounts)}"

def t_microsoft_oauth_guarded():
    """The OAuth entry points must refuse anonymous and off-origin callers."""
    body = {"redirect_uri": "http://localhost:5500/oauth-callback.html"}
    st, _ = req("/api/microsoft/oauth/start", method="POST", token="", data=body)
    assert st == 401, f"OAuth start accepted an anonymous caller (status {st})"

    st, data = req("/api/microsoft/oauth/start", method="POST",
                   data={"redirect_uri": "http://evil.example/oauth-callback.html"})
    assert st in (403, 503), f"Expected 403/503 for a disallowed redirect, got {st}: {data}"

    st, data = req("/api/microsoft/oauth/code", method="POST", data={
        "code": "fake", "state": "never-issued", "redirect_uri": body["redirect_uri"]})
    assert st in (400, 403, 503), f"Expected rejection of an unknown state, got {st}: {data}"
    return "OAuth start and code exchange require a session, an allowed origin, and a known state"

def t_microsoft_drive():
    if not microsoft_acc_id:
        return "Skipped (no Microsoft account connected)"
    st, data = req(f"/api/microsoft/drive/files?account_id={microsoft_acc_id}&page_size=5")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"OneDrive files listed: {len(data.get('files', []))}"

def t_microsoft_mail():
    if not microsoft_acc_id:
        return "Skipped (no Microsoft account connected)"
    st, data = req(f"/api/microsoft/mail/messages?account_id={microsoft_acc_id}&page_size=5")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Outlook messages listed: {len(data.get('messages', []))}"

def t_microsoft_calendar():
    if not microsoft_acc_id:
        return "Skipped (no Microsoft account connected)"
    st, data = req(f"/api/microsoft/calendar/events?account_id={microsoft_acc_id}&max_results=10")
    assert st == 200, f"Expected 200, got {st}: {data}"
    return f"Outlook calendar events listed: {len(data.get('events', []))}"

def t_microsoft_send_requires_confirmation():
    """Nothing may reach the mailbox or calendar without explicit confirmation."""
    if not microsoft_acc_id:
        return "Skipped (no Microsoft account connected)"
    for endpoint, action in (("draft", "create_email_draft"), ("send", "send_email")):
        st, data = req(f"/api/microsoft/mail/{endpoint}", method="POST", data={
            "account_id": microsoft_acc_id, "to": "nobody@example.com",
            "subject": "Test", "body": "Test", "confirm": False})
        assert st == 200, f"Expected 200, got {st}: {data}"
        assert data.get("confirmation_required") is True, f"{endpoint} was not gated: {data}"
        assert data.get("action") == action, f"Unexpected action for {endpoint}: {data}"
    st, data = req("/api/microsoft/calendar/events", method="POST", data={
        "account_id": microsoft_acc_id, "summary": "Gated", "start": "2027-01-04T09:00:00",
        "end": "2027-01-04T10:00:00", "timezone": "UTC", "confirm": False})
    assert st == 200 and data.get("confirmation_required") is True, f"Calendar not gated: {data}"
    return "Outlook draft, send, and calendar create all require confirmation"

test_feature("8b. Microsoft 365", "Graph OAuth Configuration & Scopes", t_microsoft_config)
test_feature("8b. Microsoft 365", "Connected Microsoft Account Tokens", t_microsoft_accounts)
test_feature("8b. Microsoft 365", "OAuth Entry Points Are Guarded", t_microsoft_oauth_guarded)
test_feature("8b. Microsoft 365", "OneDrive File Listing", t_microsoft_drive)
test_feature("8b. Microsoft 365", "Outlook Mail Listing", t_microsoft_mail)
test_feature("8b. Microsoft 365", "Outlook Calendar Events", t_microsoft_calendar)
test_feature("8b. Microsoft 365", "Outlook Writes Require Confirmation", t_microsoft_send_requires_confirmation)


# ── Module 9: User Authentication & Registration ──
auth_test_email = f"test_engineer_{int(time.time())}@buildmarshal.com"

second_token = ""
second_account_id = ""

def t_auth_session_identity():
    st, data = req("/api/auth/me")
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert "password_hash" not in data.get("user", {}), "Password hash must never be returned"
    assert data.get("account", {}).get("id"), "Session must resolve an account"
    return f"Session belongs to account '{data['account']['name']}'"

def t_auth_register_account():
    global auth_test_email, second_token, second_account_id
    st, data = req("/api/auth/register", method="POST", token="", data={
        "name": "Jane Engineer",
        "email": auth_test_email,
        "password": "strongpassword123",
        "account_name": "Apex Structures",
        "department": "Engineering",
        "company": "Apex Structures"
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("user", {}).get("name") == "Jane Engineer", f"Expected Jane Engineer, got {data}"
    assert data["user"].get("is_owner") is True, "The first user of an account owns it"
    assert "password_hash" not in data.get("user", {}), "Password hash should be excluded from public response"
    second_token = data["token"]
    second_account_id = data["account"]["id"]
    assert second_account_id != req("/api/auth/me")[1]["account"]["id"], "A new account must be distinct"
    return f"Created account '{data['account']['name']}' owned by {data['user']['email']}"

def t_auth_duplicate_rejection():
    st, data = req("/api/auth/register", method="POST", token="", data={
        "name": "Duplicate Jane",
        "email": auth_test_email,
        "password": "strongpassword123"
    })
    assert st == 409, f"Expected 409 Conflict, got {st}: {data}"
    return "Duplicate email rejected with HTTP 409"

def t_auth_weak_password_rejection():
    st, data = req("/api/auth/register", method="POST", token="", data={
        "name": "Weak", "email": f"weak_{int(time.time())}@buildmarshal.com", "password": "short"
    })
    assert st == 422, f"Expected 422, got {st}: {data}"
    return "Passwords under 8 characters rejected with HTTP 422"

def t_auth_invalid_login():
    st, data = req("/api/auth/login", method="POST", token="", data={
        "email": auth_test_email,
        "password": "wrongpassword!"
    })
    assert st == 401, f"Expected 401 Unauthorized, got {st}: {data}"
    return "Invalid password rejected with HTTP 401"

def t_auth_new_user_login():
    st, data = req("/api/auth/login", method="POST", token="", data={
        "email": auth_test_email,
        "password": "strongpassword123"
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("user", {}).get("email") == auth_test_email, f"Expected {auth_test_email}, got {data}"
    return f"New User Logged In: {data['user']['name']} ({data['user']['role']})"

def t_auth_user_id_is_not_a_credential():
    st, data = req("/api/auth/me")
    user_id = data["user"]["id"]
    st, _ = req("/api/auth/me", token=user_id)
    assert st == 401, f"A raw user id was accepted as a token (status {st})"
    st, _ = req("/api/auth/me", token="clearly-not-a-real-token")
    assert st == 401, f"A forged token was accepted (status {st})"
    return "User ids and forged tokens are both rejected with HTTP 401"

def t_auth_logout_revokes_token():
    st, data = req("/api/auth/login", method="POST", token="", data={
        "email": auth_test_email, "password": "strongpassword123"
    })
    throwaway = data["token"]
    assert req("/api/auth/me", token=throwaway)[0] == 200, "Fresh token should work"
    assert req("/api/auth/logout", method="POST", token=throwaway)[0] == 200, "Logout should succeed"
    st, _ = req("/api/auth/me", token=throwaway)
    assert st == 401, f"Token still valid after logout (status {st})"
    return "Logout revokes the session token immediately"

test_feature("9. Authentication", "Signed-In Session Identity", t_auth_session_identity)
test_feature("9. Authentication", "New Account Registration (/api/auth/register)", t_auth_register_account)
test_feature("9. Authentication", "Duplicate Email Conflict Prevention", t_auth_duplicate_rejection)
test_feature("9. Authentication", "Weak Password Rejection", t_auth_weak_password_rejection)
test_feature("9. Authentication", "Invalid Password Authentication Rejection", t_auth_invalid_login)
test_feature("9. Authentication", "Registered User Session Login", t_auth_new_user_login)
def t_auth_profile_update():
    """Run against the disposable second account, never the primary admin."""
    global second_token
    st, data = req("/api/auth/profile", method="PUT", token=second_token, data={
        "name": "Jane Engineer II", "phone": "+1 555-0142", "company": "Apex Structures",
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data["user"]["name"] == "Jane Engineer II", f"Profile not updated: {data}"
    st, me = req("/api/auth/me", token=second_token)
    assert me["user"]["phone"] == "+1 555-0142", f"Profile did not persist: {me}"
    return f"Profile updated for {me['user']['email']}"

def t_auth_password_change():
    """Changing a password must re-issue the caller's session and revoke others."""
    global second_token
    stale, _ = req("/api/auth/login", method="POST", token="", data={
        "email": auth_test_email, "password": "strongpassword123",
    })[1], None
    stale_token = stale["token"]

    st, data = req("/api/auth/password", method="PUT", token=second_token, data={
        "current_password": "strongpassword123", "new_password": "RotatedPassw0rd!",
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("token"), "Password change must return a replacement session token"

    assert req("/api/auth/me", token=stale_token)[0] == 401, "Other sessions were not revoked"
    assert req("/api/auth/me", token=second_token)[0] == 401, "The old session was not revoked"
    second_token = data["token"]
    assert req("/api/auth/me", token=second_token)[0] == 200, "The replacement session does not work"

    st, _ = req("/api/auth/login", method="POST", token="", data={
        "email": auth_test_email, "password": "strongpassword123",
    })
    assert st == 401, "The old password still works"
    st, _ = req("/api/auth/login", method="POST", token="", data={
        "email": auth_test_email, "password": "RotatedPassw0rd!",
    })
    assert st == 200, "The new password does not work"
    return "Password rotated; all prior sessions revoked"

def t_auth_wrong_current_password_rejected():
    st, data = req("/api/auth/password", method="PUT", token=second_token, data={
        "current_password": "not-the-password", "new_password": "AnotherPassw0rd!",
    })
    assert st == 403, f"Expected 403, got {st}: {data}"
    return "A wrong current password is rejected with HTTP 403"

test_feature("9. Authentication", "User Id Is Not A Credential", t_auth_user_id_is_not_a_credential)
test_feature("9. Authentication", "Logout Revokes Session Token", t_auth_logout_revokes_token)
test_feature("9. Authentication", "Self-Service Profile Update", t_auth_profile_update)
test_feature("9. Authentication", "Password Change Revokes Sessions", t_auth_password_change)
test_feature("9. Authentication", "Wrong Current Password Rejected", t_auth_wrong_current_password_rejected)

# ── Module 10: Cross-Account Isolation ──
# The second account registered above starts empty and must stay unable to see
# or touch anything belonging to the primary account.

def t_isolation_new_account_starts_empty():
    st, docs = req("/api/documents", token=second_token)
    assert st == 200, f"Expected 200, got {st}: {docs}"
    assert docs["documents"] == [], f"A new account must start with no documents: {docs}"
    st, projects = req("/api/projects", token=second_token)
    assert projects["total"] == 0, f"A new account must start with no projects: {projects}"
    st, stats = req("/api/chroma/stats", token=second_token)
    assert stats["total_pages"] == 0, f"A new account must start with an empty index: {stats}"
    st, convos = req("/api/conversations", token=second_token)
    assert convos["conversations"] == {}, "A new account must start with no conversations"
    return "New account starts with empty documents, projects, index, and history"

def t_isolation_documents_and_pages():
    st, data = req(f"/api/documents/{test_doc_id}/status", token=second_token)
    assert st == 404, f"Another account's document was visible (status {st}): {data}"
    st, _ = req(f"/api/pages/{test_doc_id}/1", token=second_token)
    assert st == 404, f"Another account's page image was served (status {st})"
    st, data = req(f"/api/evidence/{test_doc_id}/1", token=second_token)
    assert st == 404, f"Another account's evidence was readable (status {st}): {data}"
    st, data = req(f"/api/documents/{test_doc_id}", method="DELETE", token=second_token)
    assert st == 404, f"Another account could delete a document (status {st}): {data}"
    st, _ = req(f"/api/documents/{test_doc_id}/status")
    assert st == 200, "The owning account lost access to its own document"
    return "Documents, page images, and evidence are unreachable across accounts"

def t_isolation_projects_and_tasks():
    st, data = req(f"/api/projects/{created_project_id}", token=second_token)
    assert st == 404, f"Another account's project was visible (status {st}): {data}"
    st, _ = req(f"/api/projects/{created_project_id}/tasks", token=second_token)
    assert st == 404, "Another account could list this project's tasks"
    st, _ = req(f"/api/projects/{created_project_id}", method="DELETE", token=second_token)
    assert st == 404, "Another account could delete this project"
    st, _ = req(f"/api/projects/{created_project_id}")
    assert st == 200, "The owning account lost access to its own project"
    return "Projects and tasks are unreachable across accounts"

def t_isolation_retrieval():
    st, data = req("/api/chat", method="POST", token=second_token, data={
        "query": "What are the foundation concrete requirements in the specs?",
        "history": [], "top_k": 3,
    })
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert not data.get("sources"), f"Retrieval leaked pages from another account: {data.get('sources')}"
    return "Retrieval in an empty account returns no pages from the populated one"

def t_isolation_settings_and_members():
    st, _ = req("/api/account/settings", method="PUT", data={"top_k": 9})
    assert st == 200, "Could not update the primary account's settings"
    st, other = req("/api/account/settings", token=second_token)
    assert other["settings"]["top_k"] == 5, f"Settings leaked across accounts: {other}"
    st, mine = req("/api/account/settings")
    assert mine["settings"]["top_k"] == 9, f"Settings did not persist: {mine}"
    req("/api/account/settings", method="PUT", data={"top_k": 5})

    st, users = req("/api/users", token=second_token)
    emails = {u["email"] for u in users["users"]}
    assert emails == {auth_test_email}, f"Member directory leaked across accounts: {emails}"
    return "Settings and member directories are per-account"

def t_isolation_management_and_generated_docs():
    st, trade = req("/api/trades", method="POST", data={"name": f"Isolation Trade {int(time.time())}"})
    assert st in (200, 201), f"Could not create a trade: {st} {trade}"
    st, mine = req("/api/trades")
    st, theirs = req("/api/trades", token=second_token)
    assert any(t["id"] == trade["id"] for t in mine["trades"]), "Trade missing from its own account"
    assert not any(t["id"] == trade["id"] for t in theirs["trades"]), "Trade leaked to another account"
    req(f"/api/trades/{trade['id']}", method="DELETE")

    if generated_doc_id:
        st, _ = req(f"/api/generated-documents/{generated_doc_id}", token=second_token)
        assert st == 404, "A generated document was readable from another account"
        st, _ = req(f"/api/generated-documents/{generated_doc_id}/download", token=second_token)
        assert st == 404, "A generated document was downloadable from another account"
    return "Company data and generated documents do not cross accounts"

def t_isolation_google_accounts():
    st, theirs = req("/api/google/accounts", token=second_token)
    assert st == 200, f"Expected 200, got {st}: {theirs}"
    assert theirs.get("accounts") == [], f"Connected Google accounts leaked: {theirs}"
    return "Connected Google accounts are scoped to the account that added them"

test_feature("10. Isolation", "New Account Starts Empty", t_isolation_new_account_starts_empty)
test_feature("10. Isolation", "Documents, Pages & Evidence Are Private", t_isolation_documents_and_pages)
def t_isolation_task_detail():
    st, _ = req(f"/api/projects/{created_project_id}/tasks/{created_task_id}", token=second_token)
    assert st == 404, f"Another account read a task detail (status {st})"
    st, _ = req(f"/api/projects/{created_project_id}/tasks/{created_task_id}",
                method="PUT", token=second_token, data={"name": "hijacked"})
    assert st == 404, f"Another account edited a task (status {st})"
    st, _ = req(f"/api/projects/{created_project_id}/tasks/{created_task_id}",
                method="DELETE", token=second_token)
    assert st == 404, f"Another account deleted a task (status {st})"
    st, mine = req(f"/api/projects/{created_project_id}/tasks/{created_task_id}")
    assert st == 200 and mine["name"] != "hijacked", "The owning account lost its task"
    return "Task detail, edit, and delete are all private to the owning account"

test_feature("10. Isolation", "Projects & Tasks Are Private", t_isolation_projects_and_tasks)
test_feature("10. Isolation", "Task Detail & Edit Are Private", t_isolation_task_detail)
test_feature("10. Isolation", "Vector Retrieval Cannot Cross Accounts", t_isolation_retrieval)
test_feature("10. Isolation", "Settings & Member Directory Are Private", t_isolation_settings_and_members)
test_feature("10. Isolation", "Company Data & Generated Documents Are Private", t_isolation_management_and_generated_docs)
def t_isolation_project_sources():
    st, data = req(f"/api/projects/{created_project_id}/source-documents", token=second_token)
    # The project belongs to the other account, so its sources must not appear.
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("documents") == [], f"Project sources leaked across accounts: {data}"
    st, data = req(f"/api/projects/{created_project_id}/documents", method="POST",
                   token=second_token, data={"doc_kind": "tender_summary"})
    assert st == 404, f"Another account could generate against this project (status {st})"
    st, data = req(f"/api/projects/{created_project_id}/generate-document",
                   method="POST", token=second_token)
    assert st == 404, f"Another account could export this project's overview (status {st})"
    return "Project source documents and generation are private to the owning account"

def t_isolation_google_account_id_unusable():
    """A Google account id from one workspace must be unknown in another."""
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    for path in (
        f"/api/google/drive/files?account_id={google_acc_id}",
        f"/api/google/calendar/events?account_id={google_acc_id}",
        f"/api/google/gmail/messages?account_id={google_acc_id}",
    ):
        st, data = req(path, token=second_token)
        assert st == 404, f"{path} answered {st} for another account; expected 404"
    # Import would download the owner's real Drive/Gmail content, so only the
    # refusal path is exercised here.
    for path in ("/api/google/drive/import", "/api/google/gmail/import"):
        st, data = req(path, method="POST", token=second_token, data={
            "account_id": google_acc_id, "item_ids": ["any-id"],
        })
        assert st == 404, f"{path} accepted another account's Google account (status {st})"
    return "Another account's Google account id is rejected for Drive, Calendar, Gmail, and imports"

def t_oauth_code_exchange_is_guarded():
    """The OAuth callback must refuse anonymous and unprotected requests."""
    body = {"code": "fake-authorization-code", "redirect_uri": "http://localhost:5500"}
    st, _ = req("/api/google/oauth/code", method="POST", token="", data=body)
    assert st == 401, f"OAuth exchange accepted an anonymous caller (status {st})"
    # Signed in, but missing the CSRF protection header the client must send.
    st, data = req("/api/google/oauth/code", method="POST", data=body)
    assert st == 400, f"Expected 400 without X-Requested-With, got {st}: {data}"
    st, data = req("/api/google/oauth/code", method="POST", data=body, headers={
        "X-Requested-With": "XmlHttpRequest", "Origin": "http://evil.example",
    })
    assert st == 403, f"Expected 403 for a disallowed origin, got {st}: {data}"
    return "OAuth code exchange requires a session, the CSRF header, and an allowed origin"

test_feature("10. Isolation", "Connected Google Accounts Are Private", t_isolation_google_accounts)
test_feature("10. Isolation", "Project Sources & Generation Are Private", t_isolation_project_sources)
test_feature("10. Isolation", "Google Account Ids Do Not Cross Accounts", t_isolation_google_account_id_unusable)
def t_isolation_microsoft_accounts():
    st, data = req("/api/microsoft/accounts", token=second_token)
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data.get("accounts") == [], f"Connected Microsoft accounts leaked: {data}"
    if microsoft_acc_id:
        for path in (
            f"/api/microsoft/drive/files?account_id={microsoft_acc_id}",
            f"/api/microsoft/mail/messages?account_id={microsoft_acc_id}",
            f"/api/microsoft/calendar/events?account_id={microsoft_acc_id}",
        ):
            st, _ = req(path, token=second_token)
            assert st == 404, f"{path} answered {st} for another account; expected 404"
    return "Microsoft accounts and their ids do not cross BuildMarshal accounts"

test_feature("10. Isolation", "OAuth Code Exchange Is Guarded", t_oauth_code_exchange_is_guarded)
def t_isolation_meet_scheduling():
    """A Google account linked by another workspace cannot be scheduled against."""
    if not google_acc_id:
        return "Skipped (no active Google account connected)"
    st, data = req("/api/google/meet/schedule", method="POST", token=second_token, timeout=120, data={
        "account_id": google_acc_id, "timezone": "UTC",
        "known": {"summary": "Intrusion", "start": "2027-05-04T09:00:00"},
    })
    assert st == 404, f"Another account could schedule a Meet (status {st}): {data}"
    return "Meet scheduling refuses another account's Google connection"

test_feature("10. Isolation", "Microsoft Accounts Are Private", t_isolation_microsoft_accounts)
test_feature("10. Isolation", "Meet Scheduling Respects Account Isolation", t_isolation_meet_scheduling)

# ── Module 12: Company Settings (company info, task types, project types) ──
#
# Read is open to every member of the account; add, edit and delete are for
# administrators only, and the check must hold on the server rather than only
# in the UI.

member_token = ""
member_user_id = ""
created_task_type_id = ""
created_project_type_id = ""

SUITE_MEMBER_EMAIL = "suite.member@buildmarshal.com"
SUITE_MEMBER_PASSWORD = "MemberPass!2026"

def t_company_member_account():
    """An ordinary (non-admin) member to test the permission gate with.

    Deleting a user deactivates rather than removes them, so the suite keeps
    one member and reuses it instead of leaving a new one behind every run.
    """
    global member_token, member_user_id
    st, users = req("/api/users")
    assert st == 200, f"Could not list users: {st} {users}"
    existing = next((u for u in users["users"] if u["email"] == SUITE_MEMBER_EMAIL), None)

    if existing:
        member_user_id = existing["id"]
        # An earlier run left it deactivated; put it back to a plain member.
        st, data = req(f"/api/users/{member_user_id}", method="PUT",
                       data={"status": "Active", "role": "User"})
        assert st == 200, f"Could not reactivate the suite member: {st} {data}"
    else:
        st, data = req("/api/users", method="POST", data={
            "name": "Suite Member", "email": SUITE_MEMBER_EMAIL,
            "password": SUITE_MEMBER_PASSWORD, "role": "User",
        })
        assert st == 200, f"Could not create a member user: {st} {data}"
        member_user_id = data["id"]

    st, login = req("/api/auth/login", method="POST", token="", data={
        "email": SUITE_MEMBER_EMAIL, "password": SUITE_MEMBER_PASSWORD,
    })
    assert st == 200, f"Member could not sign in: {st} {login}"
    member_token = login["token"]
    assert login["user"]["role"] == "User", f"Unexpected role: {login['user']}"
    return "Member signed in to the same account with role User"

def t_company_info_read_and_edit():
    st, data = req("/api/company")
    assert st == 200, f"Expected 200, got {st}: {data}"
    assert data["can_edit"] is True, "The administrator should be allowed to edit"
    assert "name" in data["company"], f"No company profile returned: {data}"

    st, saved = req("/api/company", method="PUT", data={
        "name": "Marshal Build Co", "city": "Sydney", "country": "Australia",
        "website": "https://buildmarshal.ai", "about": "Suite test value.",
    })
    assert st == 200, f"Company save failed: {st} {saved}"
    assert saved["company"]["city"] == "Sydney", f"City not stored: {saved}"

    st, reread = req("/api/company")
    assert reread["company"]["name"] == "Marshal Build Co", f"Not persisted: {reread}"
    assert reread["company"]["updated_by"], "The edit did not record who made it"
    return "Company profile reads back what was saved"

def t_company_info_validation():
    for payload, why in (
        ({"name": "   "}, "a blank name"),
        ({"email": "not-an-address"}, "an invalid email"),
        ({"website": "buildmarshal.ai"}, "a website with no scheme"),
    ):
        st, data = req("/api/company", method="PUT", data=payload)
        assert st == 422, f"Accepted {why}: {st} {data}"
    return "Blank names, bad emails and scheme-less websites are refused"

def t_company_info_member_is_read_only():
    st, data = req("/api/company", token=member_token)
    assert st == 200, f"A member must be able to read: {st} {data}"
    assert data["can_edit"] is False, "A member must not be offered the edit controls"

    st, blocked = req("/api/company", method="PUT", token=member_token,
                      data={"name": "Hijacked"})
    assert st == 403, f"A member changed the company (status {st}): {blocked}"

    st, after = req("/api/company")
    assert after["company"]["name"] == "Marshal Build Co", f"Value changed: {after}"
    return "A member may read the company but the server refuses their writes"

def t_type_catalogs_admin_crud():
    global created_task_type_id, created_project_type_id
    for segment, key, holder in (("task-types", "task_types", "task"),
                                 ("project-types", "project_types", "project")):
        st, listed = req(f"/api/{segment}")
        assert st == 200, f"/api/{segment} answered {st}: {listed}"
        assert listed["can_edit"] is True, f"{segment}: admin should be able to edit"
        assert len(listed[key]) >= 1, f"{segment} shipped no defaults: {listed}"

        name = f"Suite {holder} type {int(time.time())}"
        st, created = req(f"/api/{segment}", method="POST",
                          data={"name": name, "description": "Created by the suite"})
        assert st == 200, f"Could not create in {segment}: {st} {created}"
        if holder == "task":
            created_task_type_id = created["id"]
        else:
            created_project_type_id = created["id"]

        st, updated = req(f"/api/{segment}/{created['id']}", method="PUT",
                          data={"description": "Edited by the suite"})
        assert st == 200 and updated["description"] == "Edited by the suite", \
            f"Update failed in {segment}: {st} {updated}"

        st, again = req(f"/api/{segment}")
        assert any(item["id"] == created["id"] for item in again[key]), \
            f"{segment} did not persist the new entry"
    return "Administrators can list, add and edit both catalogs"

def t_type_catalogs_reject_duplicates():
    for segment in ("task-types", "project-types"):
        st, listed = req(f"/api/{segment}")
        existing = listed[segment.replace("-", "_")][0]["name"]
        st, clash = req(f"/api/{segment}", method="POST", data={"name": existing.upper()})
        assert st == 409, f"{segment} accepted a duplicate name: {st} {clash}"
        st, blank = req(f"/api/{segment}", method="POST", data={"name": "  "})
        assert blank and st == 422, f"{segment} accepted a blank name: {st} {blank}"
    return "Duplicate and blank names are refused in both catalogs"

def t_type_catalogs_member_is_read_only():
    for segment in ("task-types", "project-types"):
        st, listed = req(f"/api/{segment}", token=member_token)
        assert st == 200, f"A member must be able to list {segment}: {st}"
        assert listed["can_edit"] is False, f"{segment}: a member must not be offered edits"
        existing = listed[segment.replace("-", "_")][0]["id"]

        st, _ = req(f"/api/{segment}", method="POST", token=member_token, data={"name": "Sneaky"})
        assert st == 403, f"A member created a {segment} entry (status {st})"
        st, _ = req(f"/api/{segment}/{existing}", method="PUT", token=member_token,
                    data={"name": "Sneaky"})
        assert st == 403, f"A member edited a {segment} entry (status {st})"
        st, _ = req(f"/api/{segment}/{existing}", method="DELETE", token=member_token)
        assert st == 403, f"A member deleted a {segment} entry (status {st})"
    return "Members may list both catalogs but every write is refused"

def t_type_in_use_cannot_be_deleted():
    """Deleting a type that records still reference is refused, not silent."""
    st, project = req("/api/projects", method="POST", data={
        "name": f"Type usage {int(time.time())}", "project_code": f"TU-{int(time.time())}",
        "type": "Commercial", "status": "Active",
    })
    assert st == 200, f"Could not create a project: {st} {project}"
    project_id = project["id"]
    try:
        st, listed = req("/api/project-types")
        commercial = next((t for t in listed["project_types"] if t["name"] == "Commercial"), None)
        assert commercial, f"No Commercial project type to test with: {listed}"
        st, refused = req(f"/api/project-types/{commercial['id']}", method="DELETE")
        assert st == 409, f"Deleted a project type still in use (status {st}): {refused}"
        assert "used by" in str(refused.get("detail", "")), f"Unclear message: {refused}"
    finally:
        req(f"/api/projects/{project_id}", method="DELETE")

    st, gone = req(f"/api/project-types/{created_project_type_id}", method="DELETE")
    assert st == 200, f"An unused project type should delete: {st} {gone}"
    return "A type in use is refused with a reason; an unused one deletes"

def t_calendar_creation_requires_confirmation():
    """Neither provider may write to a real calendar without an explicit confirm."""
    checks = []
    st, google = req("/api/google/calendar/events", method="POST", data={
        "account_id": "unconfirmed", "summary": "Suite proposal",
        "start": "2027-06-01T09:00:00", "end": "2027-06-01T10:00:00", "add_meet": True,
    })
    assert st == 200 and google.get("confirmation_required") is True, \
        f"Google create wrote without confirmation: {st} {google}"
    checks.append("google")

    st, microsoft = req("/api/microsoft/calendar/events", method="POST", data={
        "account_id": "unconfirmed", "summary": "Suite proposal",
        "start": "2027-06-01T09:00:00", "end": "2027-06-01T10:00:00",
        "add_online_meeting": True,
    })
    assert st == 200 and microsoft.get("confirmation_required") is True, \
        f"Microsoft create wrote without confirmation: {st} {microsoft}"
    assert microsoft["event"]["add_online_meeting"] is True, \
        f"The Teams request was dropped from the proposal: {microsoft}"
    checks.append("microsoft")
    return f"Unconfirmed creates on {', '.join(checks)} return a proposal and write nothing"

def t_teams_scheduler_is_account_scoped():
    """The conversational Teams route refuses an account this workspace has not linked."""
    st, data = req("/api/microsoft/meeting/schedule", method="POST", timeout=120, data={
        "account_id": "never-linked", "timezone": "UTC",
        "known": {"summary": "Intrusion", "start": "2027-05-04T09:00:00"},
    })
    if st == 503:
        # Microsoft OAuth is not configured here, so the route stops earlier
        # still. What matters is that it did not schedule anything.
        return "Skipped (Microsoft OAuth is not configured on this backend)"
    assert st == 404, f"Expected 404 for an unlinked account, got {st}: {data}"
    return "Teams scheduling resolves accounts through the caller's workspace only"

def t_company_settings_isolation():
    """Another workspace sees neither the company profile nor the added types."""
    if not second_token:
        return "Skipped (no second account)"
    st, other = req("/api/company", token=second_token)
    assert st == 200, f"Second account could not read its own company: {st} {other}"
    assert other["company"]["city"] != "Sydney", f"Company details leaked: {other}"

    st, types = req("/api/task-types", token=second_token)
    assert not any(t["id"] == created_task_type_id for t in types["task_types"]), \
        "A task type leaked into another account"
    return "Company profile and catalogs stay inside their own account"

test_feature("12. Company Settings", "Member Account For Permission Checks", t_company_member_account)
test_feature("12. Company Settings", "Company Info Read & Edit", t_company_info_read_and_edit)
test_feature("12. Company Settings", "Company Info Validation", t_company_info_validation)
test_feature("12. Company Settings", "Company Info Is Read-Only For Members", t_company_info_member_is_read_only)
test_feature("12. Company Settings", "Task & Project Types CRUD", t_type_catalogs_admin_crud)
test_feature("12. Company Settings", "Type Catalogs Reject Duplicates", t_type_catalogs_reject_duplicates)
test_feature("12. Company Settings", "Type Catalogs Are Read-Only For Members", t_type_catalogs_member_is_read_only)
test_feature("12. Company Settings", "A Type In Use Cannot Be Deleted", t_type_in_use_cannot_be_deleted)
test_feature("12. Company Settings", "Calendar Creation Requires Confirmation", t_calendar_creation_requires_confirmation)
test_feature("12. Company Settings", "Teams Scheduling Respects Isolation", t_teams_scheduler_is_account_scoped)
test_feature("12. Company Settings", "Company Settings Are Account-Isolated", t_company_settings_isolation)

# ── Module 13: Roles & cost permissions ──
#
# Project money belongs to the Project Manager; a task's cost is additionally
# the assignee's. Checked against the running server so a forged request cannot
# get past the rule by skipping the UI.

cost_project_id = ""
my_task_id = ""
other_task_id = ""

def t_role_catalogue_is_account_managed():
    """Only roles this account actually has may be assigned."""
    st, users = req("/api/users")
    target = next(u for u in users["users"] if u["email"] == SUITE_MEMBER_EMAIL)
    original = target["role"]

    st, bad = req(f"/api/users/{target['id']}", method="PUT", data={"role": "Admin"})
    assert st == 422, f"An unknown role was accepted: {st} {bad}"

    st, roles = req("/api/user-roles")
    existing = next(r["name"] for r in roles["roles"] if not r["builtin"])
    st, good = req(f"/api/users/{target['id']}", method="PUT", data={"role": existing})
    assert st == 200 and good["role"] == existing, f"A real role was refused: {st} {good}"

    req(f"/api/users/{target['id']}", method="PUT", data={"role": original})
    return f"Unknown roles refused; \"{existing}\" accepted"

def t_cost_project_setup():
    global cost_project_id, my_task_id, other_task_id
    st, project = req("/api/projects", method="POST", data={
        "name": f"Cost rules {int(time.time())}", "project_code": f"CR-{int(time.time())}",
        "status": "Active",
    })
    assert st == 200, f"Could not create the project: {st} {project}"
    cost_project_id = project["id"]

    st, mine = req(f"/api/projects/{cost_project_id}/tasks", method="POST",
                   data={"name": "Assigned to the member", "assignee": "Suite Member"})
    assert st == 200, f"Could not create a task: {st} {mine}"
    my_task_id = mine["id"]

    st, theirs = req(f"/api/projects/{cost_project_id}/tasks", method="POST",
                     data={"name": "Assigned to someone else", "assignee": "Nobody Else"})
    assert st == 200, f"Could not create a task: {st} {theirs}"
    other_task_id = theirs["id"]
    return "Project with one task per assignee"

def t_owner_may_set_project_costs():
    st, saved = req(f"/api/projects/{cost_project_id}/costs/baseline",
                    method="PUT", data={"amount": 50000})
    assert st == 200 and saved["baseline_cost"] == 50000, f"{st} {saved}"
    assert saved["can_edit_project_cost"] is True, f"Owner should be allowed: {saved}"

    st, added = req(f"/api/projects/{cost_project_id}/costs", method="POST",
                    data={"name": "Site fencing", "amount": 3000})
    assert st == 200, f"Could not add a project cost: {st} {added}"
    return "An account administrator may set the baseline and add costs"

def t_a_member_cannot_touch_project_costs():
    st, blocked = req(f"/api/projects/{cost_project_id}/costs/baseline",
                      method="PUT", token=member_token, data={"amount": 1})
    assert st == 403, f"A member changed the baseline (status {st}): {blocked}"
    assert "does not allow" in str(blocked.get("detail")), f"Unclear reason: {blocked}"

    st, blocked = req(f"/api/projects/{cost_project_id}/costs", method="POST",
                      token=member_token, data={"name": "Sneaky", "amount": 1})
    assert st == 403, f"A member added a project cost (status {st}): {blocked}"

    st, after = req(f"/api/projects/{cost_project_id}/costs")
    assert after["baseline_cost"] == 50000, f"The baseline moved: {after}"
    return "A member is refused on the baseline and on additional costs"

def t_a_member_reads_costs_and_is_told_what_they_may_edit():
    st, view = req(f"/api/projects/{cost_project_id}/costs", token=member_token)
    assert st == 200, f"A member must be able to read costs: {st} {view}"
    assert view["can_edit_project_cost"] is False, f"Wrong flag: {view}"
    editable = view["editable_task_costs"]
    assert my_task_id in editable, "The member's own task should be editable"
    assert other_task_id not in editable, "Another person's task must not be"
    return "The breakdown reports exactly which task costs this user may set"

def t_the_assignee_may_price_their_own_task():
    st, updated = req(f"/api/projects/{cost_project_id}/tasks/{my_task_id}",
                      method="PUT", token=member_token, data={"cost": 1250})
    assert st == 200 and updated["cost"] == 1250, f"{st} {updated}"
    return "The assigned user set the cost of their own task"

def t_a_member_cannot_price_someone_elses_task():
    st, blocked = req(f"/api/projects/{cost_project_id}/tasks/{other_task_id}",
                      method="PUT", token=member_token, data={"cost": 9999})
    assert st == 403, f"A member priced another person's task (status {st}): {blocked}"

    st, task = req(f"/api/projects/{cost_project_id}/tasks/{other_task_id}")
    assert task["cost"] == 0, f"The cost changed anyway: {task}"

    # The rest of the task stays collaborative.
    st, ok = req(f"/api/projects/{cost_project_id}/tasks/{other_task_id}",
                 method="PUT", token=member_token, data={"status": "In Progress"})
    assert st == 200, f"A member should still be able to edit the task itself: {st} {ok}"
    return "Only the cost is restricted; the rest of the task is not"

def t_resending_an_unchanged_cost_is_allowed():
    """The task form saves the whole record, so an unchanged cost must pass."""
    st, ok = req(f"/api/projects/{cost_project_id}/tasks/{other_task_id}",
                 method="PUT", token=member_token,
                 data={"status": "Completed", "cost": 0})
    assert st == 200, f"An unchanged cost was treated as a change: {st} {ok}"
    return "Re-sending the existing cost is not a permission error"

def t_task_costs_roll_into_the_project_total():
    st, view = req(f"/api/projects/{cost_project_id}/costs")
    assert view["tasks_total"] == 1250, f"Task costs did not roll up: {view}"
    assert view["total"] == 50000 + 3000 + 1250, f"Total is wrong: {view}"
    return f"Total {view['total']} = baseline + additional + task costs"

test_feature("13. Roles & Costs", "Roles Come From The Account", t_role_catalogue_is_account_managed)
test_feature("13. Roles & Costs", "Cost Permission Fixture", t_cost_project_setup)
test_feature("13. Roles & Costs", "Administrator May Set Project Costs", t_owner_may_set_project_costs)
test_feature("13. Roles & Costs", "Member Refused On Project Costs", t_a_member_cannot_touch_project_costs)
test_feature("13. Roles & Costs", "Member Told Which Task Costs Are Theirs", t_a_member_reads_costs_and_is_told_what_they_may_edit)
test_feature("13. Roles & Costs", "Assignee May Price Their Own Task", t_the_assignee_may_price_their_own_task)
test_feature("13. Roles & Costs", "Member Refused On Another's Task Cost", t_a_member_cannot_price_someone_elses_task)
test_feature("13. Roles & Costs", "Unchanged Cost Is Not A Change", t_resending_an_unchanged_cost_is_allowed)
test_feature("13. Roles & Costs", "Task Costs Roll Into The Total", t_task_costs_roll_into_the_project_total)

# ── Module 14: User roles & granular permissions ──
#
# Super Admin and System Admin are built in; everything else is created here
# and is exactly the permissions it was given. Managing roles is Super Admin
# work and is deliberately not itself a permission.

created_role_id = ""
scoped_user_id = ""
scoped_token = ""
SCOPED_EMAIL = "scoped.role@buildmarshal.com"
SCOPED_PASSWORD = "ScopedPass!2026"

def t_permission_catalogue_is_served():
    st, body = req("/api/permissions")
    assert st == 200, f"Expected 200, got {st}: {body}"
    keys = {p["key"] for g in body["groups"] for p in g["permissions"]}
    for expected in ("task.create", "project.create", "project.cost.base",
                     "project.cost.additional", "project.cost.task",
                     "project.people.manage", "task_type.manage",
                     "project_type.manage", "task.update.status",
                     "task.update.priority", "task.update.assignee"):
        assert expected in keys, f"{expected} missing from the catalogue"
    # Super Admin authority must not be offered as something to tick.
    assert not any(k.startswith(("role.", "permission.", "company.")) for k in keys), keys
    return f"{body['total']} permissions across {len(body['groups'])} groups"

def t_builtin_roles_are_listed_and_locked():
    st, body = req("/api/user-roles")
    assert st == 200, f"Expected 200, got {st}: {body}"
    builtins = {r["name"]: r for r in body["roles"] if r["builtin"]}
    assert set(builtins) == {"Super Admin", "System Admin"}, list(builtins)
    assert all(r["editable"] is False for r in builtins.values())
    assert body["can_manage"] is True, "The owner is a Super Admin"
    return "Super Admin and System Admin are present and not editable"

def t_super_admin_creates_a_scoped_role():
    global created_role_id
    st, role = req("/api/user-roles", method="POST", data={
        "name": f"Scoped {int(time.time())}",
        "description": "Only the task status field",
        "permissions": ["task.update.status", "not.a.real.permission"],
    })
    assert st == 200, f"Could not create the role: {st} {role}"
    created_role_id = role["id"]
    assert role["permissions"] == ["task.update.status"], \
        f"Unknown keys were stored: {role['permissions']}"
    return f"Created \"{role['name']}\" with 1 permission; the bogus key was dropped"

def t_builtin_names_and_duplicates_are_refused():
    for name in ("Super Admin", "System Admin"):
        st, clash = req("/api/user-roles", method="POST", data={"name": name})
        assert st == 409, f"{name} was allowed as a custom role: {st} {clash}"
    st, roles = req("/api/user-roles")
    existing = next(r["name"] for r in roles["roles"] if not r["builtin"])
    st, dupe = req("/api/user-roles", method="POST", data={"name": existing.upper()})
    assert st == 409, f"A duplicate name was accepted: {st} {dupe}"
    st, blank = req("/api/user-roles", method="POST", data={"name": "   "})
    assert blank is not None and st == 422, f"A blank name was accepted: {st}"
    return "Built-in names, duplicates, and blanks are all refused"

def t_a_user_can_be_created_with_a_custom_role():
    global scoped_user_id, scoped_token
    st, roles = req("/api/user-roles")
    role = next(r for r in roles["roles"] if r["id"] == created_role_id)

    st, users = req("/api/users")
    existing = next((u for u in users["users"] if u["email"] == SCOPED_EMAIL), None)
    if existing:
        scoped_user_id = existing["id"]
        st, _ = req(f"/api/users/{scoped_user_id}", method="PUT",
                    data={"status": "Active", "role": role["name"]})
        assert st == 200
    else:
        st, user = req("/api/users", method="POST", data={
            "name": "Scoped Role User", "email": SCOPED_EMAIL,
            "password": SCOPED_PASSWORD, "role": role["name"]})
        assert st == 200, f"Could not create the user: {st} {user}"
        scoped_user_id = user["id"]

    st, login = req("/api/auth/login", token="", data={
        "email": SCOPED_EMAIL, "password": SCOPED_PASSWORD}, method="POST")
    assert st == 200, f"Scoped user could not sign in: {st} {login}"
    scoped_token = login["token"]
    assert login["user"]["role"] == role["name"]
    return f"Signed in holding \"{role['name']}\""

def t_a_scoped_role_is_enforced_field_by_field():
    st, project = req("/api/projects", method="POST", data={
        "name": f"Perm check {int(time.time())}", "project_code": f"PC-{int(time.time())}",
        "status": "Active"})
    assert st == 200, f"Could not create the project: {st} {project}"
    project_id = project["id"]
    try:
        st, task = req(f"/api/projects/{project_id}/tasks", method="POST",
                       data={"name": "Governed task", "assignee": "Nobody"})
        assert st == 200, f"Could not create the task: {st} {task}"

        allowed = req(f"/api/projects/{project_id}/tasks/{task['id']}", method="PUT",
                      token=scoped_token, data={"status": "In Progress"})
        assert allowed[0] == 200, f"The granted field was refused: {allowed}"

        for label, call in (
            ("priority", req(f"/api/projects/{project_id}/tasks/{task['id']}",
                             method="PUT", token=scoped_token, data={"priority": "High"})),
            ("task creation", req(f"/api/projects/{project_id}/tasks", method="POST",
                                  token=scoped_token, data={"name": "Nope"})),
            ("project creation", req("/api/projects", method="POST", token=scoped_token,
                                     data={"name": "Nope", "project_code": "NOPE-1"})),
            ("baseline cost", req(f"/api/projects/{project_id}/costs/baseline",
                                  method="PUT", token=scoped_token, data={"amount": 1})),
            ("task types", req("/api/task-types", method="POST", token=scoped_token,
                               data={"name": "Nope"})),
        ):
            assert call[0] == 403, f"A permission this role lacks allowed {label}: {call}"
    finally:
        req(f"/api/projects/{project_id}", method="DELETE")
    return "Granted field allowed; every ungranted action refused"

def t_role_management_is_super_admin_only():
    st, listed = req("/api/user-roles", token=scoped_token)
    assert st == 200, f"Everyone may read the role list: {st}"
    assert listed["can_manage"] is False, "A custom role must not report manage rights"

    st, _ = req("/api/user-roles", method="POST", token=scoped_token, data={"name": "Sneaky"})
    assert st == 403, f"A custom role created a role (status {st})"
    st, _ = req(f"/api/user-roles/{created_role_id}", method="PUT",
                token=scoped_token, data={"name": "Hijacked"})
    assert st == 403, f"A custom role edited a role (status {st})"
    st, _ = req(f"/api/user-roles/{created_role_id}", method="DELETE", token=scoped_token)
    assert st == 403, f"A custom role deleted a role (status {st})"
    return "Roles are readable by all and writable only by a Super Admin"

def t_editing_a_role_changes_what_its_holders_may_do():
    """A permission added to a role reaches its holders on the next request."""
    st, updated = req(f"/api/user-roles/{created_role_id}", method="PUT",
                      data={"permissions": ["task.update.status", "task.create"]})
    assert st == 200, f"Could not update the role: {st} {updated}"

    st, project = req("/api/projects", method="POST", data={
        "name": f"Grant check {int(time.time())}", "project_code": f"GC-{int(time.time())}"})
    project_id = project["id"]
    try:
        st, task = req(f"/api/projects/{project_id}/tasks", method="POST",
                       token=scoped_token, data={"name": "Now allowed"})
        assert st == 200, f"The newly granted permission was not applied: {st} {task}"
    finally:
        req(f"/api/projects/{project_id}", method="DELETE")

    req(f"/api/user-roles/{created_role_id}", method="PUT",
        data={"permissions": ["task.update.status"]})
    return "A permission granted on the role took effect immediately"

def t_a_role_in_use_cannot_be_deleted():
    st, blocked = req(f"/api/user-roles/{created_role_id}", method="DELETE")
    assert st == 409, f"A role still assigned was deleted (status {st}): {blocked}"
    assert "assigned to" in str(blocked.get("detail")), f"Unclear reason: {blocked}"
    return "A role someone still holds is refused with a reason"

def t_roles_are_account_isolated():
    if not second_token:
        return "Skipped (no second account)"
    st, roles = req("/api/user-roles", token=second_token)
    assert st == 200, f"Second account could not read its roles: {st}"
    names = [r["name"] for r in roles["roles"]]
    assert not any(r["id"] == created_role_id for r in roles["roles"]), \
        f"A role leaked into another account: {names}"
    return "Roles stay inside the account that created them"

test_feature("14. User Roles", "Permission Catalogue Is Served", t_permission_catalogue_is_served)
test_feature("14. User Roles", "Built-in Roles Listed And Locked", t_builtin_roles_are_listed_and_locked)
test_feature("14. User Roles", "Super Admin Creates A Scoped Role", t_super_admin_creates_a_scoped_role)
test_feature("14. User Roles", "Built-in, Duplicate & Blank Names Refused", t_builtin_names_and_duplicates_are_refused)
test_feature("14. User Roles", "User Created With A Custom Role", t_a_user_can_be_created_with_a_custom_role)
test_feature("14. User Roles", "Scoped Role Enforced Field By Field", t_a_scoped_role_is_enforced_field_by_field)
test_feature("14. User Roles", "Role Management Is Super Admin Only", t_role_management_is_super_admin_only)
test_feature("14. User Roles", "Editing A Role Reaches Its Holders", t_editing_a_role_changes_what_its_holders_may_do)
test_feature("14. User Roles", "A Role In Use Cannot Be Deleted", t_a_role_in_use_cannot_be_deleted)
test_feature("14. User Roles", "Roles Are Account-Isolated", t_roles_are_account_isolated)

# ── Cleanup ──
def t_cleanup():
    req(f"/api/documents/{test_doc_id}", method="DELETE")
    req(f"/api/documents/{project_source_id}", method="DELETE")
    if created_trade_id:
        req(f"/api/trades/{created_trade_id}", method="DELETE")
    if created_vendor_id:
        req(f"/api/vendors/{created_vendor_id}", method="DELETE")
    if created_task_type_id:
        req(f"/api/task-types/{created_task_type_id}", method="DELETE")
    if created_project_type_id:
        req(f"/api/project-types/{created_project_type_id}", method="DELETE")
    if member_user_id:
        req(f"/api/users/{member_user_id}", method="DELETE")
    if cost_project_id:
        req(f"/api/projects/{cost_project_id}", method="DELETE")
    if scoped_user_id:
        req(f"/api/users/{scoped_user_id}", method="DELETE")
        # The role can only go once nobody holds it.
        req(f"/api/users/{scoped_user_id}", method="PUT", data={"role": "System Admin"})
    if created_role_id:
        req(f"/api/user-roles/{created_role_id}", method="DELETE")
    if subtask_id:
        req(f"/api/projects/{created_project_id}/tasks/{subtask_id}", method="DELETE")
    req(f"/api/projects/{created_project_id}/tasks/{created_task_id}", method="DELETE")
    req(f"/api/projects/{created_project_id}", method="DELETE")
    # Remove the whole second workspace, including its files and vector index.
    if second_token:
        req("/api/account", method="DELETE", token=second_token)
    return "Cleaned up temporary test artifacts and the isolation test account"

test_feature("11. Cleanup", "Teardown Test Artifacts", t_cleanup)

print("=" * 70)
print(f"FINAL TEST SUMMARY: {passed} PASSED | {failed} FAILED | TOTAL: {passed + failed}")
print("=" * 70)

# Save JSON results
Path("test_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
if failed > 0:
    sys.exit(1)
