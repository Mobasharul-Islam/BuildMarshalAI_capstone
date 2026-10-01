"""Projects end to end: the manager and members are users, the People tab shows
everyone on the project, Project Documents uploads and links, a document can
belong to several projects or none, and a chat question naming a project is
answered from that project's documents only.

The project, document-list and chat routes live in the notebook, so they are
lifted out of the exported server with ``ast`` -- the code under test is the
code that ships -- and run against a real account workspace and registry.
"""

from __future__ import annotations

import ast
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.testclient import TestClient

from backend import chat_scope, document_links, entity_schema, project_people
from backend import tasks as task_module
from backend import chat_records
from backend.chat_scope import mentioned_projects, resolve_chat_scope
from backend.document_generation import register_kaggle_routes
from backend.document_links import (
    ORIGIN_LABELS, document_listing, document_project_ids, link_document, project_documents,
    set_document_projects, unlink_document,
)
from backend.hybrid_retrieval import HybridColPaliRetriever
from backend.ingestion_formats import file_digest, find_duplicate, split_pages
from backend.project_management import register_project_management_routes
from backend.project_people import project_people as people_of
from backend.tasks import register_task_routes

# The notebook imports these by their bare names.
for _name, _module in (("document_links", document_links), ("project_people", project_people),
                       ("entity_schema", entity_schema), ("chat_scope", chat_scope),
                       ("tasks", task_module), ("chat_records", chat_records)):
    sys.modules.setdefault(_name, _module)

SERVER = Path(__file__).resolve().parents[1] / "run_backend.py"
PASSWORD = "Passw0rd!123"


def lift(names: set[str], namespace: dict) -> dict:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    wanted = [node for node in tree.body
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in wanted} == names
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace


def make_pdf(path: Path, lines: list[str]) -> Path:
    import fitz

    document = fitz.open()
    for line in lines:
        document.new_page().insert_text((72, 72), line, fontsize=14)
    document.save(path)
    document.close()
    return path


# -- the app -----------------------------------------------------------------------

@pytest.fixture
def world(make_account, registry, tmp_path):
    """The project, task, people, document and chat routes over one real account."""
    context = make_account("owner@example.com", name="Olivia Owner")
    people = {
        "sam": registry.create_user(account_id=context.account_id, name="Sam Field",
                                    email="sam@example.com", password=PASSWORD, role=""),
        "priya": registry.create_user(account_id=context.account_id, name="Priya Das",
                                      email="priya@example.com", password=PASSWORD, role=""),
        "gone": registry.create_user(account_id=context.account_id, name="Gone Person",
                                     email="gone@example.com", password=PASSWORD, role="",
                                     status="Inactive"),
    }
    people["owner"] = context.user
    app = FastAPI()
    retrieved: list[dict] = []
    generated: list[dict] = []

    async def require_account():
        return context

    def retrieve_context(query, top_k=5, project_id=None, workspace=None):
        retrieved.append({"query": query, "project_id": project_id})
        return HYBRID.retrieve(query, top_k=top_k, project_id=project_id, workspace=workspace)

    async def generate_response(query, pages, history, model=None, records="", documents=""):
        generated.append({"query": query, "docs": sorted({p["doc_id"] for p in pages}), "records": records,
                          "documents": documents})
        return {"response": "answer", "sources": [{"doc_id": p["doc_id"]} for p in pages],
                "model_used": "fake"}

    def ingest_document(file_path, doc_id, workspace, display_name=None, project_id=None, origin=None):
        """The real ingestion's bookkeeping, without rendering or embedding."""
        meta = workspace.load_metadata()
        digest = file_digest(file_path)
        duplicate = find_duplicate(meta.get("documents", {}), digest, doc_id, project_id)
        if duplicate:
            Path(file_path).unlink(missing_ok=True)
            stored = meta["documents"][duplicate["id"]]
            linked = link_document(stored, project_id) if project_id else False
            if linked:
                workspace.save_metadata(meta)
            return {**stored, "id": duplicate["id"], "status": "duplicate", "linked": linked}
        pages, _ = split_pages(Path(file_path), doc_id, workspace.pages_dir,
                               display_name=display_name)
        record = {"id": doc_id, "name": display_name or Path(file_path).name,
                  "type": Path(file_path).suffix, "digest": digest, "pages": pages,
                  "page_count": len(pages), "status": "indexed",
                  "created_at": datetime.now().isoformat()}
        if origin in ORIGIN_LABELS:
            record["origin"] = origin
        set_document_projects(record, [project_id] if project_id else [])
        meta.setdefault("documents", {})[doc_id] = record
        workspace.save_metadata(meta)
        return record

    namespace = {
        "app": app, "Depends": Depends, "Request": Request, "HTTPException": HTTPException,
        "UploadFile": UploadFile, "File": File, "Form": Form,
        "require_account": require_account, "ACCOUNT_REGISTRY": registry,
        "uuid": uuid, "datetime": datetime, "timezone": timezone, "asyncio": asyncio,
        "logger": SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
        "document_listing": document_listing, "ORIGIN_LABELS": ORIGIN_LABELS, "retrieve_context": retrieve_context,
        "generate_response": generate_response, "ingest_document": ingest_document,
        "embed_query": lambda q: None, "vl_generate": lambda *a, **k: "",
        "MAX_UPLOAD_BYTES": 10 * 1024 * 1024,
    }
    lift({"_make_project", "_check_project_currency", "_project_or_404", "_account_users",
          "_bind_manager", "_initial_members", "_present", "list_projects", "get_project",
          "create_project", "update_project", "delete_project", "list_documents",
          "scope_documents", "chat"}, namespace)
    register_task_routes(namespace)
    register_project_management_routes(namespace)
    register_kaggle_routes(namespace)

    retriever = object.__new__(HybridColPaliRetriever)
    retriever._query_multivector = lambda query: None      # lexical ranking only: no GPU
    global HYBRID
    HYBRID = retriever
    return SimpleNamespace(context=context, people=people, client=TestClient(app), retriever_namespace=namespace,
                           workspace=context.workspace, retrieved=retrieved,
                           generated=generated, tmp=tmp_path, registry=registry)


def new_project(world, name="Padma View", code="PV", **extra):
    body = {"name": name, "project_code": code, "manager_id": world.people["owner"]["id"], **extra}
    response = world.client.post("/api/projects", json=body)
    assert response.status_code == 200, response.json()
    return response.json()


# -- 2. the manager is chosen from the users -------------------------------------------

def test_a_project_needs_a_manager_chosen_from_the_users(world):
    base = {"name": "Tower", "project_code": "TWR"}
    missing = world.client.post("/api/projects", json=base)
    assert missing.status_code == 422 and "project manager" in missing.json()["detail"]
    typed = world.client.post("/api/projects", json={**base, "manager": "Somebody Typed"})
    assert typed.status_code == 422 and "not one of this account's users" in typed.json()["detail"]
    unknown = world.client.post("/api/projects", json={**base, "manager_id": "no-such-user"})
    assert unknown.status_code == 422
    inactive = world.client.post("/api/projects", json={**base, "manager_id": world.people["gone"]["id"]})
    assert inactive.status_code == 422 and "not an active user" in inactive.json()["detail"]

    created = world.client.post("/api/projects", json={**base, "manager_id": world.people["sam"]["id"]})
    assert created.status_code == 200
    project = created.json()
    assert project["manager_id"] == world.people["sam"]["id"] and project["manager"] == "Sam Field"
    stored = world.workspace.load_projects()[project["id"]]
    assert stored["manager_id"] == world.people["sam"]["id"]


def test_the_managers_name_follows_their_user_record(world):
    project = new_project(world, manager_id=world.people["sam"]["id"])
    world.registry.update_user(world.people["sam"]["id"], {"name": "Samuel Field"})
    shown = world.client.get(f"/api/projects/{project['id']}").json()
    assert shown["manager"] == "Samuel Field"
    listed = world.client.get("/api/projects").json()["projects"]
    assert [p["manager"] for p in listed if p["id"] == project["id"]] == ["Samuel Field"]


def test_the_manager_can_be_changed_but_only_to_a_user(world):
    project = new_project(world)
    moved = world.client.put(f"/api/projects/{project['id']}",
                             json={"manager_id": world.people["priya"]["id"]})
    assert moved.status_code == 200 and moved.json()["manager"] == "Priya Das"
    assert world.client.put(f"/api/projects/{project['id']}",
                            json={"manager": "Made Up"}).status_code == 422
    assert world.client.put(f"/api/projects/{project['id']}",
                            json={"manager_id": ""}).status_code == 422
    # An edit that does not touch the manager leaves it alone.
    renamed = world.client.put(f"/api/projects/{project['id']}", json={"name": "Padma View II"})
    assert renamed.status_code == 200 and renamed.json()["manager_id"] == world.people["priya"]["id"]


def test_a_chat_seeded_manager_name_resolves_to_its_user(world):
    """The chat hands the form a name; the server stores the user it names."""
    created = world.client.post("/api/projects", json={"name": "Annex", "project_code": "ANX",
                                                       "manager": "priya das"})
    assert created.status_code == 200 and created.json()["manager_id"] == world.people["priya"]["id"]


# -- 3. members and the People tab ----------------------------------------------------

def test_members_are_chosen_at_creation_and_must_be_active_users(world):
    bad = world.client.post("/api/projects", json={
        "name": "X", "project_code": "X1", "manager_id": world.people["owner"]["id"],
        "member_ids": ["nobody"]})
    assert bad.status_code == 422
    inactive = world.client.post("/api/projects", json={
        "name": "X", "project_code": "X2", "manager_id": world.people["owner"]["id"],
        "member_ids": [world.people["gone"]["id"]]})
    assert inactive.status_code == 422
    project = new_project(world, member_ids=[world.people["sam"]["id"], world.people["sam"]["id"]])
    assert [m["user_id"] for m in project["members"]] == [world.people["sam"]["id"]]


def test_people_are_the_manager_the_members_and_the_assignees(world):
    project = new_project(world, member_ids=[world.people["sam"]["id"]])
    pid = project["id"]
    # An older task assigned by name to someone who was never added.
    tasks = world.workspace.load_tasks()
    tasks[pid] = [{"id": "legacy", "project_id": pid, "name": "Survey", "assignee": "Priya Das"}]
    world.workspace.save_tasks(tasks)

    people = world.client.get(f"/api/projects/{pid}/members").json()
    rows = {row["name"]: row for row in people["members"]}
    assert rows["Olivia Owner"]["sources"] == ["Manager"]
    assert rows["Sam Field"]["sources"] == ["Member"]
    assert rows["Priya Das"]["sources"] == ["Task assignee"] and rows["Priya Das"]["task_count"] == 1
    assert [row["removable"] for row in people["members"]] == [False, True, False]
    assert people["available"] == []            # the only other user is inactive
    assert people["total"] == 3


def test_adding_and_removing_members(world):
    project = new_project(world)
    pid = project["id"]
    added = world.client.post(f"/api/projects/{pid}/members",
                              json={"user_ids": [world.people["sam"]["id"], world.people["priya"]["id"]]})
    assert added.status_code == 200 and added.json()["added"] == 2
    assert world.client.post(f"/api/projects/{pid}/members",
                             json={"user_ids": [world.people["gone"]["id"]]}).status_code == 422
    assert world.client.post(f"/api/projects/{pid}/members",
                             json={"user_ids": ["stranger"]}).status_code == 404

    removed = world.client.delete(f"/api/projects/{pid}/members/{world.people['priya']['id']}")
    assert removed.status_code == 200
    names = [row["name"] for row in removed.json()["members"]]
    assert "Priya Das" not in names and "Sam Field" in names
    # The manager is not a membership to take away.
    manager = world.client.delete(f"/api/projects/{pid}/members/{world.people['owner']['id']}")
    assert manager.status_code == 409 and "project manager" in manager.json()["detail"]


def test_someone_with_open_tasks_cannot_be_removed(world):
    project = new_project(world, member_ids=[world.people["sam"]["id"]])
    pid = project["id"]
    task = world.client.post(f"/api/projects/{pid}/tasks",
                             json={"name": "Pour", "assignee_id": world.people["sam"]["id"]}).json()
    blocked = world.client.delete(f"/api/projects/{pid}/members/{world.people['sam']['id']}")
    assert blocked.status_code == 409 and "Reassign" in blocked.json()["detail"]
    world.client.put(f"/api/projects/{pid}/tasks/{task['id']}", json={"assignee_id": "", "assignee": ""})
    assert world.client.delete(f"/api/projects/{pid}/members/{world.people['sam']['id']}").status_code == 200


def test_tasks_go_only_to_the_projects_people(world):
    project = new_project(world, member_ids=[world.people["sam"]["id"]])
    pid = project["id"]
    offered = world.client.get(f"/api/projects/{pid}/assignees").json()["assignees"]
    assert {row["name"] for row in offered} == {"Olivia Owner", "Sam Field"}
    outsider = world.client.post(f"/api/projects/{pid}/tasks",
                                 json={"name": "X", "assignee_id": world.people["priya"]["id"]})
    assert outsider.status_code == 422 and "not on Padma View" in outsider.json()["detail"]
    ok = world.client.post(f"/api/projects/{pid}/tasks",
                           json={"name": "Y", "assignee_id": world.people["sam"]["id"]})
    assert ok.status_code == 200
    # Once Priya is added, she can be given work.
    world.client.post(f"/api/projects/{pid}/members", json={"user_ids": [world.people["priya"]["id"]]})
    assert world.client.post(f"/api/projects/{pid}/tasks",
                             json={"name": "Z", "assignee_id": world.people["priya"]["id"]}).status_code == 200


# -- 5 and 6. Project Documents, shared documents and orphans ----------------------------

def upload(world, pid, path, name=None):
    with open(path, "rb") as handle:
        return world.client.post(f"/api/projects/{pid}/source-documents",
                                 files={"file": (name or path.name, handle, "application/octet-stream")})


def test_any_supported_file_can_be_uploaded_into_a_project(world):
    pid = new_project(world)["id"]
    notes = world.tmp / "site-notes.txt"
    notes.write_text("Crane lift on Monday at 7am.", encoding="utf-8")
    uploaded = upload(world, pid, notes)
    assert uploaded.status_code == 200 and uploaded.json()["status"] == "indexed"
    pdf = upload(world, pid, make_pdf(world.tmp / "spec.pdf", ["RFI period ten working days"]))
    assert pdf.status_code == 200
    bad = world.tmp / "virus.exe"
    bad.write_bytes(b"MZ")
    assert upload(world, pid, bad).status_code == 400
    listed = world.client.get(f"/api/projects/{pid}/source-documents").json()
    assert {d["name"] for d in listed["documents"]} == {"site-notes.txt", "spec.pdf"}
    assert all(d["origin"] == "project" for d in listed["documents"])


def test_existing_documents_are_linked_not_copied(world):
    a = new_project(world, "Padma View", "PV")["id"]
    b = new_project(world, "River Tower", "RT")["id"]
    spec = make_pdf(world.tmp / "spec.pdf", ["Shared standard"])
    first = upload(world, a, spec).json()
    docs_dir = Path(world.workspace.docs_dir)
    files_before = sorted(p.name for p in docs_dir.iterdir())

    linkable = world.client.get(f"/api/projects/{b}/linkable-documents").json()["documents"]
    assert [d["id"] for d in linkable] == [first["id"]]
    assert linkable[0]["projects"] == [{"id": a, "name": "Padma View", "project_code": "PV"}]
    linked = world.client.post(f"/api/projects/{b}/source-documents/link", json={"doc_ids": [first["id"]]})
    assert linked.status_code == 200 and linked.json()["linked"] == [first["id"]]
    assert sorted(p.name for p in docs_dir.iterdir()) == files_before          # no copy made
    assert world.client.get(f"/api/projects/{b}/linkable-documents").json()["documents"] == []

    again = world.client.post(f"/api/projects/{b}/source-documents/link", json={"doc_ids": [first["id"]]})
    assert again.json()["already_linked"] == [first["id"]]
    assert world.client.post(f"/api/projects/{b}/source-documents/link",
                             json={"doc_ids": ["nope"]}).status_code == 404
    stored = world.workspace.load_metadata()["documents"][first["id"]]
    assert stored["project_ids"] == [a, b]


def test_uploading_bytes_the_account_already_has_links_them(world):
    a = new_project(world, "Padma View", "PV")["id"]
    b = new_project(world, "River Tower", "RT")["id"]
    spec = make_pdf(world.tmp / "spec.pdf", ["Shared standard"])
    first = upload(world, a, spec).json()
    second = upload(world, b, spec, name="spec (copy).pdf").json()
    assert second["status"] == "duplicate" and second["linked"] is True and second["id"] == first["id"]
    assert "linked it to this project" in second["message"]
    assert len(world.workspace.load_metadata()["documents"]) == 1


def test_documents_from_chat_and_the_documents_page_can_be_linked(world):
    pid = new_project(world)["id"]
    meta = world.workspace.load_metadata()
    meta.setdefault("documents", {}).update({
        "chat1": {"name": "photo.png", "type": ".png", "origin": "chat", "project_ids": []},
        "gen1": {"name": "brief.pdf", "type": ".pdf", "project_ids": []},
    })
    world.workspace.save_metadata(meta)
    linkable = {d["id"]: d for d in world.client.get(f"/api/projects/{pid}/linkable-documents").json()["documents"]}
    assert linkable["chat1"]["origin_label"] == "Chat upload"
    assert linkable["gen1"]["origin_label"] == "Documents"
    world.client.post(f"/api/projects/{pid}/source-documents/link", json={"doc_ids": ["chat1", "gen1"]})
    assert {d["id"] for d in world.client.get(f"/api/projects/{pid}/source-documents").json()["documents"]} \
        == {"chat1", "gen1"}


def test_the_documents_list_shows_projects_and_orphans(world):
    a = new_project(world, "Padma View", "PV")["id"]
    b = new_project(world, "River Tower", "RT")["id"]
    meta = world.workspace.load_metadata()
    meta.setdefault("documents", {}).update({
        "shared": {"name": "std.pdf", "type": ".pdf", "project_ids": [a, b]},
        "only_a": {"name": "a.pdf", "type": ".pdf", "project_ids": [a]},
        "orphan": {"name": "loose.pdf", "type": ".pdf", "project_ids": []},
        "legacy": {"name": "old.pdf", "type": ".pdf", "project_id": b},
        "stale": {"name": "stale.pdf", "type": ".pdf", "project_ids": ["deleted-project"]},
    })
    world.workspace.save_metadata(meta)
    listed = {d["id"]: d for d in world.client.get("/api/documents").json()["documents"]}
    assert [p["name"] for p in listed["shared"]["projects"]] == ["Padma View", "River Tower"]
    assert listed["legacy"]["project_ids"] == [b]
    assert listed["orphan"]["unassigned"] is True and listed["shared"]["unassigned"] is False
    assert listed["stale"]["unassigned"] is True          # a link to a deleted project is no link
    orphans = world.client.get("/api/documents?scope=unassigned").json()
    assert {d["id"] for d in orphans["documents"]} == {"orphan", "stale"}
    of_b = world.client.get(f"/api/documents?project_id={b}").json()
    assert {d["id"] for d in of_b["documents"]} == {"shared", "legacy"}


def test_unlinking_keeps_the_document_and_deleting_a_project_keeps_shared_ones(world):
    a = new_project(world, "Padma View", "PV")["id"]
    b = new_project(world, "River Tower", "RT")["id"]
    meta = world.workspace.load_metadata()
    meta.setdefault("documents", {}).update({
        "shared": {"name": "std.pdf", "type": ".pdf", "project_ids": [a, b]},
        "only_a": {"name": "a.pdf", "type": ".pdf", "project_ids": [a]},
    })
    world.workspace.save_metadata(meta)
    off = world.client.delete(f"/api/projects/{b}/source-documents/shared")
    assert off.status_code == 200 and off.json()["project_ids"] == [a]
    assert world.client.delete(f"/api/projects/{b}/source-documents/shared").status_code == 404
    assert "shared" in world.workspace.load_metadata()["documents"]

    world.client.post(f"/api/projects/{b}/source-documents/link", json={"doc_ids": ["shared"]})
    assert world.client.delete(f"/api/projects/{a}").status_code == 200
    documents = world.workspace.load_metadata()["documents"]
    assert documents["shared"]["project_ids"] == [b]         # still on the other project
    assert documents["only_a"]["project_ids"] == []          # now an orphan, not deleted


# -- 7. project-aware chat --------------------------------------------------------------

def test_a_project_is_recognised_by_name_or_code_as_whole_words():
    projects = [{"id": "1", "name": "Padma View", "project_code": "PV-01"},
                {"id": "2", "name": "Tower", "project_code": "TWR"},
                {"id": "3", "name": "Tower B", "project_code": "TWB"},
                {"id": "4", "name": "AB", "project_code": "A"}]
    assert [p["id"] for p in mentioned_projects("RFI period on padma view?", projects)] == ["1"]
    assert [p["id"] for p in mentioned_projects("what about PV-01", projects)] == ["1"]
    assert [p["id"] for p in mentioned_projects("steel for Tower B", projects)] == ["3"]
    # Both named: the longer, more specific one first; the "Tower" inside "Tower B" is not a mention.
    assert [p["id"] for p in mentioned_projects("Tower and Tower B", projects)] == ["3", "2"]
    assert mentioned_projects("the towering crane", projects) == []
    # A long name is usually said shorter: its first two or more words count.
    long_name = [{"id": "p", "name": "Padma View Specialised Hospital Extension", "project_code": "PVH-2026"},
                 {"id": "q", "name": "Padma River Bridge", "project_code": "PRB"}]
    assert [p["id"] for p in mentioned_projects("RFI period on Padma View?", long_name)] == ["p"]
    assert [p["id"] for p in mentioned_projects("padma view specialised hospital cost", long_name)] == ["p"]
    assert mentioned_projects("anything about padma?", long_name) == []      # one word is not enough
    assert [p["id"] for p in mentioned_projects("pvh-2026 schedule", long_name)] == ["p"]
    assert mentioned_projects("a b c", projects) == []          # too short to be a name


def test_the_scope_prefers_a_named_project_over_the_page(world):
    projects = {"a": {"id": "a", "name": "Padma View"}, "b": {"id": "b", "name": "River Tower"}}
    assert resolve_chat_scope("fire rating on River Tower", projects, "a")["project_ids"] == ["b"]
    assert resolve_chat_scope("fire rating?", projects, "a")["project_ids"] == ["a"]
    assert resolve_chat_scope("fire rating?", projects, None)["project_ids"] == []


def seed_two_projects(world):
    a = new_project(world, "Padma View", "PV")["id"]
    b = new_project(world, "River Tower", "RT")["id"]
    meta = world.workspace.load_metadata()
    page = lambda text: [{"page_num": 1, "text_content": text, "image_path": None}]  # noqa: E731
    meta.setdefault("documents", {}).update({
        "pv_spec": {"name": "pv-spec.pdf", "project_ids": [a],
                    "pages": page("RFI response period is ten working days.")},
        "rt_spec": {"name": "rt-spec.pdf", "project_ids": [b],
                    "pages": page("RFI response period is five working days.")},
        "shared": {"name": "company-standard.pdf", "project_ids": [a, b],
                   "pages": page("RFI forms use the company template.")},
        "orphan": {"name": "loose.pdf", "project_ids": [],
                   "pages": page("RFI response period is thirty days.")},
    })
    world.workspace.save_metadata(meta)
    return a, b


def test_naming_a_project_searches_only_its_documents(world):
    a, b = seed_two_projects(world)
    reply = world.client.post("/api/chat", json={"query": "What is the RFI response period on River Tower?"})
    assert reply.status_code == 200
    assert reply.json()["scope"]["project_ids"] == [b]
    assert world.retrieved[-1]["project_id"] == [b]
    assert set(world.generated[-1]["docs"]) <= {"rt_spec", "shared"}
    assert "rt_spec" in world.generated[-1]["docs"]
    assert {s["doc_id"] for s in reply.json()["sources"]}.isdisjoint({"pv_spec", "orphan"})


def test_without_a_named_project_the_whole_account_is_searched(world):
    seed_two_projects(world)
    reply = world.client.post("/api/chat", json={"query": "What is the RFI response period?"})
    assert reply.json()["scope"]["project_ids"] == []
    assert world.retrieved[-1]["project_id"] is None
    assert {"pv_spec", "rt_spec", "orphan"} & set(world.generated[-1]["docs"])


def test_a_named_project_with_no_documents_is_answered_from_its_records_only(world):
    seed_two_projects(world)
    new_project(world, "Empty Yard", "EY", start_date="2027-01-01", end_date="2027-12-31")
    world.retrieved.clear()
    reply = world.client.post("/api/chat", json={"query": "Who manages Empty Yard and when does it end?"})
    body = reply.json()
    sent = world.generated[-1]
    assert sent["docs"] == [] and world.retrieved == []         # no retrieval pass at all
    assert "PROJECT: Empty Yard" in sent["records"] and "End date: 2027-12-31" in sent["records"]
    assert "Manager: Olivia Owner" in sent["records"]
    assert "Padma View" not in sent["records"] and "River Tower" not in sent["records"]
    assert body["scope"]["records"]["project_ids"] == [body["scope"]["project_ids"][0]]


def test_a_named_project_sends_all_its_records_with_the_question(world):
    pid = new_project(world, "Harbour Tower", "HT", start_date="2027-01-01", end_date="2027-12-31",
                      member_ids=[world.people["sam"]["id"]])["id"]
    world.client.put(f"/api/projects/{pid}/costs/baseline", json={"amount": 500000})
    world.client.post(f"/api/projects/{pid}/costs", json={"name": "Crane hire", "amount": 42000})
    parent = world.client.post(f"/api/projects/{pid}/tasks", json={
        "name": "Piling and foundation", "assignee_id": world.people["sam"]["id"], "status": "In Progress",
        "start_time": "2027-02-01T08:00", "end_time": "2027-03-15T17:00", "cost": 180000}).json()
    world.client.post(f"/api/projects/{pid}/tasks", json={"name": "Pile cap pour", "parent_id": parent["id"]})
    world.client.post(f"/api/projects/{pid}/procurement", json={
        "name": "Rebar 16mm", "supplier": "BSRM", "quantity": 20, "unit": "t", "unit_cost": 950, "status": "Ordered"})
    world.client.post("/api/chat", json={"query": "What is the status and total cost of Harbour Tower?"})
    records = world.generated[-1]["records"]
    for fragment in ("PROJECT: Harbour Tower", "Manager: Olivia Owner", "Members: Sam Field",
                     "Start date: 2027-01-01", "Crane hire", "total USD 722,000.00",
                     "Piling and foundation; status In Progress", "assignee Sam Field",
                     "start 2027-02-01T08:00", "Pile cap pour", "subtask of Piling and foundation",
                     "Rebar 16mm: Ordered, supplier BSRM", "Tasks: 2 live"):
        assert fragment in records, fragment


def test_naming_a_task_sends_it_and_its_project(world):
    pid = new_project(world, "Harbour Tower", "HT", start_date="2027-01-01", end_date="2027-12-31")["id"]
    world.client.post(f"/api/projects/{pid}/tasks", json={
        "name": "Curtain wall install", "status": "Blocked", "description": "Waiting for glass delivery"})
    reply = world.client.post("/api/chat", json={"query": "Why is curtain wall install blocked?"})
    records = world.generated[-1]["records"]
    assert records.startswith("TASK: Curtain wall install (project Harbour Tower)")
    assert "status Blocked" in records and "Waiting for glass delivery" in records
    assert "PROJECT: Harbour Tower" in records
    assert reply.json()["scope"]["project_ids"] == [pid]        # its project's documents are searched


def test_a_question_naming_no_project_still_gets_every_project_in_brief(world):
    seed_two_projects(world)
    world.client.post("/api/chat", json={"query": "What is an RFI?"})
    records = world.generated[-1]["records"]
    assert records.startswith("ALL PROJECTS IN THIS WORKSPACE (2):")
    assert "Padma View (code PV" in records and "River Tower (code RT" in records


def test_the_records_go_to_the_model_even_when_retrieval_fails(world, monkeypatch):
    a, _ = seed_two_projects(world)

    def broken(*args, **kwargs):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setitem(world.retriever_namespace, "retrieve_context", broken)
    reply = world.client.post("/api/chat", json={"query": "Who manages Padma View?"})
    assert reply.status_code == 200
    sent = world.generated[-1]
    assert sent["docs"] == [] and "PROJECT: Padma View" in sent["records"]


def test_the_records_go_to_the_model_alongside_retrieved_pages(world):
    a, _ = seed_two_projects(world)
    world.client.post("/api/chat", json={"query": "What is the RFI response period on Padma View?"})
    sent = world.generated[-1]
    assert sent["docs"] and "PROJECT: Padma View" in sent["records"]


def test_a_question_from_the_projects_page_sends_that_projects_records(world):
    a, _ = seed_two_projects(world)
    world.client.post("/api/chat", json={"query": "Who manages this?", "project_id": a})
    assert "PROJECT: Padma View" in world.generated[-1]["records"]


def test_the_hybrid_retriever_scope_includes_shared_documents(world):
    a, b = seed_two_projects(world)
    retriever = object.__new__(HybridColPaliRetriever)
    retriever._query_multivector = lambda query: None
    pages = retriever.retrieve("RFI", top_k=10, project_id=a, workspace=world.workspace)
    assert {p["doc_id"] for p in pages} == {"pv_spec", "shared"}
    both = retriever.retrieve("RFI", top_k=10, project_id=[a, b], workspace=world.workspace)
    assert {p["doc_id"] for p in both} == {"pv_spec", "rt_spec", "shared"}


def test_the_vector_channel_is_filtered_by_document_not_by_a_stale_page_field(world):
    a, _ = seed_two_projects(world)
    seen = {}
    collection = world.workspace.collection
    collection.add(ids=["x"], embeddings=[[0.1]], metadatas=[{"doc_id": "pv_spec"}])

    def query(**kwargs):
        seen.update(kwargs)
        return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

    collection.query = query
    retriever = object.__new__(HybridColPaliRetriever)
    import torch
    retriever._query_multivector = lambda q: torch.ones((2, 4))
    retriever._page_multivector = lambda path, workspace: None
    retriever.retrieve("RFI", top_k=3, project_id=a, workspace=world.workspace)
    assert seen["where"] == {"doc_id": {"$in": ["pv_spec", "shared"]}}


# -- helpers ------------------------------------------------------------------------------

def test_link_helpers_keep_project_id_and_project_ids_in_step():
    doc = {"project_id": "a"}
    assert document_project_ids(doc) == ["a"]
    assert link_document(doc, "b") and doc == {"project_id": "a", "project_ids": ["a", "b"]}
    assert not link_document(doc, "b")
    assert unlink_document(doc, "a") and doc["project_id"] == "b"
    assert unlink_document(doc, "b") and doc == {"project_id": None, "project_ids": []}
    assert project_documents({"x": {"project_ids": ["a"]}, "y": {"project_ids": []}}, ["a"]) \
        == {"x": {"project_ids": ["a"]}}


def test_people_rows_are_ordered_manager_first(world):
    project = {"id": "p", "manager_id": world.people["priya"]["id"],
               "members": [{"user_id": world.people["sam"]["id"]}, {"user_id": world.people["priya"]["id"]}]}
    rows = people_of(project, [], world.registry.users_for_account(world.context.account_id))
    assert [r["name"] for r in rows] == ["Priya Das", "Sam Field"]
    assert rows[0]["sources"] == ["Manager", "Member"] and rows[0]["removable"] is True


def test_project_dates_are_checked_on_create_and_edit(world):
    backwards = world.client.post("/api/projects", json={
        "name": "Backwards", "project_code": "BW", "manager_id": world.people["owner"]["id"],
        "start_date": "2027-06-30", "end_date": "2027-03-01"})
    assert backwards.status_code == 422 and "end date cannot be earlier" in backwards.json()["detail"]
    project = new_project(world, start_date="2027-03-01", end_date="2027-06-30")
    pid = project["id"]
    world.client.post(f"/api/projects/{pid}/tasks", json={"name": "Pour", "start_time": "2027-05-01T08:00",
                                                          "end_time": "2027-05-02T08:00"})
    shrink = world.client.put(f"/api/projects/{pid}", json={"end_date": "2027-04-30"})
    assert shrink.status_code == 422 and "Pour" in shrink.json()["detail"]
    assert world.workspace.load_projects()[pid]["end_date"] == "2027-06-30"
    widen = world.client.put(f"/api/projects/{pid}", json={"end_date": "2027-12-31"})
    assert widen.status_code == 200
    # A task outside the new window is still refused through the API.
    assert world.client.post(f"/api/projects/{pid}/tasks", json={
        "name": "Late", "start_time": "2028-01-02T08:00"}).status_code == 422



BENGALI = "পদ্মা ভিউ স্পেশালাইজড হাসপাতাল সম্প্রসারণ"


@pytest.mark.parametrize("question", [
    f"Show me the most costly task from{BENGALI}",      # no space between the scripts
    f"Show me the most costly task from {BENGALI}",
    "পদ্মা ভিউয়ের সবচেয়ে ব্যয়বহুল কাজ কোনটি?",           # a leading run, with a case ending
    f"{BENGALI}-এর খরচ",
])
def test_a_bengali_project_name_is_recognised_however_it_is_written(question):
    projects = [{"id": "bn", "name": BENGALI, "project_code": "PVH-2026"},
                {"id": "en", "name": "Padma View Specialised Hospital Extension", "project_code": "PVX"}]
    assert [p["id"] for p in mentioned_projects(question, projects)] == ["bn"]


def test_latin_names_still_need_whole_words():
    projects = [{"id": "t", "name": "Tower", "project_code": "TWR"}]
    for question in ("the towering crane", "Towers", "TWRX spare"):
        assert mentioned_projects(question, projects) == [], question
    assert [p["id"] for p in mentioned_projects("Tower's budget", projects)] == ["t"]


def test_the_costliest_task_question_sends_every_task_cost(world):
    pid = new_project(world, BENGALI, "PVB", start_date="2027-01-01", end_date="2027-12-31")["id"]
    for name, cost in (("ভিত্তি ও পাইলিং", 1800000), ("ছাদ ঢালাই", 950000), ("রং", 120000)):
        world.client.post(f"/api/projects/{pid}/tasks", json={"name": name, "cost": cost})
    reply = world.client.post("/api/chat", json={"query": f"Show me the most costly task from{BENGALI}"})
    assert reply.json()["scope"]["project_ids"] == [pid]
    records = world.generated[-1]["records"]
    assert f"PROJECT: {BENGALI}" in records
    assert "ভিত্তি ও পাইলিং; status Open" in records and "cost USD 1,800,000.00" in records
    assert "cost USD 950,000.00" in records and "cost USD 120,000.00" in records


def test_a_reassignment_mid_conversation_reaches_the_next_answer(world):
    """The same question asked again after an edit gets the new records, and the
    earlier answer is marked as possibly out of date."""
    pid = new_project(world, "Harbour Tower", "HT", member_ids=[world.people["sam"]["id"], world.people["priya"]["id"]])["id"]
    made = [world.client.post(f"/api/projects/{pid}/tasks", json={
        "name": f"Task {n}", "assignee_id": world.people["sam"]["id"], "status": "Blocked" if n < 2 else "Open"}).json()
        for n in range(3)]
    question = "Who has the most tasks assigned in Harbour Tower, and how many are blocked?"
    world.client.post("/api/chat", json={"query": question})
    first = world.generated[-1]["records"]
    assert "Workload by assignee (live tasks): Sam Field 3 (2 Blocked, 1 Open)" in first

    for task in made[:2]:
        world.client.put(f"/api/projects/{pid}/tasks/{task['id']}", json={"assignee_id": world.people["priya"]["id"]})
    world.client.post("/api/chat", json={"query": question, "history": [
        {"role": "user", "content": question}, {"role": "assistant", "content": "Sam Field has 3 tasks; 2 are blocked."}]})
    second = world.generated[-1]["records"]
    assert "Priya Das 2 (2 Blocked); Sam Field 1 (1 Open)" in second



def test_every_document_of_the_project_goes_to_the_model_not_just_retrieved_pages(world):
    a, b = seed_two_projects(world)
    world.client.post("/api/chat", json={"query": "Summarise Padma View"})
    sent = world.generated[-1]
    # Both of Padma View's documents in full, including the one shared with River Tower...
    assert "DOCUMENT: pv-spec.pdf" in sent["documents"] and "DOCUMENT: company-standard.pdf" in sent["documents"]
    assert "[pv-spec.pdf p.1] RFI response period is ten working days." in sent["documents"]
    # ...and nothing of another project's, or of an unassigned document.
    assert "rt-spec.pdf" not in sent["documents"] and "loose.pdf" not in sent["documents"]


def test_a_general_question_sends_no_document_dump(world):
    seed_two_projects(world)
    world.client.post("/api/chat", json={"query": "What is an RFI?"})
    assert world.generated[-1]["documents"] == ""


def test_the_document_text_is_capped():
    from backend.chat_records import documents_context
    from types import SimpleNamespace
    big = {"d": {"name": "huge.txt", "project_ids": ["p"],
                 "pages": [{"page_num": n, "text_content": "x" * 1000} for n in range(1, 50)]}}
    ws = SimpleNamespace(load_projects=lambda: {"p": {"name": "P"}}, load_metadata=lambda: {"documents": big})
    out = documents_context(ws, ["p"], max_chars=5000)
    assert out["truncated"] and len(out["text"]) < 5200 and "limit was reached" in out["text"]


def test_a_follow_up_keeps_the_project_and_task_from_earlier(world):
    pid = new_project(world, "Harbour Tower", "HT", member_ids=[world.people["sam"]["id"]])["id"]
    world.client.post(f"/api/projects/{pid}/tasks", json={"name": "Superstructure", "cost": 42000000,
                                                          "assignee_id": world.people["sam"]["id"]})
    first = "What is the costliest task in Harbour Tower?"
    reply = world.client.post("/api/chat", json={"query": "Who is assigned to it, and when does it end?",
                                                 "history": [{"role": "user", "content": first},
                                                             {"role": "assistant", "content": "Superstructure."}]})
    assert reply.json()["scope"]["project_ids"] == [pid]
    assert reply.json()["scope"]["reason"] == "named earlier in the conversation"
    assert "PROJECT: Harbour Tower" in world.generated[-1]["records"]


def test_a_follow_up_naming_another_project_switches_to_it(world):
    a, b = seed_two_projects(world)
    reply = world.client.post("/api/chat", json={"query": "And River Tower?", "history": [
        {"role": "user", "content": "Tell me about Padma View"}, {"role": "assistant", "content": "…"}]})
    assert reply.json()["scope"]["project_ids"] == [b]



def test_parent_tasks_that_repeat_their_subtasks_costs_are_flagged(world):
    pid = new_project(world, "Harbour Tower", "HT")["id"]
    phase = world.client.post(f"/api/projects/{pid}/tasks", json={"name": "Superstructure", "cost": 100}).json()
    for n in (60, 40):
        world.client.post(f"/api/projects/{pid}/tasks", json={"name": f"Slab {n}", "cost": n, "parent_id": phase["id"]})
    world.client.post(f"/api/projects/{pid}/tasks", json={"name": "Survey", "cost": 5})
    world.client.post("/api/chat", json={"query": "What does Harbour Tower cost?"})
    records = world.generated[-1]["records"]
    assert "tasks USD 205.00" in records
    assert "Task costs without the parent tasks: USD 105.00" in records
    assert "Superstructure USD 100.00 (its subtasks USD 100.00)" in records


def test_with_one_project_an_unnamed_question_is_about_it(world):
    pid = new_project(world, "Padma View Specialised Hospital Extension", "PVH")["id"]
    world.client.post(f"/api/projects/{pid}/tasks", json={"name": "সুপারস্ট্রাকচার (Superstructure)", "cost": 142000000})
    reply = world.client.post("/api/chat", json={"query": "পদ্মা ভিউয়ের সুপারস্ট্রাকচারের খরচ কত?"})
    assert reply.json()["scope"]["project_ids"] == [pid]
    assert reply.json()["scope"]["reason"] == "the only project in the workspace"
    records = world.generated[-1]["records"]
    assert records.startswith("TASK: সুপারস্ট্রাকচার (Superstructure)") and "cost USD 142,000,000.00" in records
