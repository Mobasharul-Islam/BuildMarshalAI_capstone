"""Which projects a document belongs to.

One indexed document can serve several projects -- a shared specification, a
company standard, a supplier's catalogue -- so a document record holds a list,
``project_ids``, rather than a single project. Linking a document to another
project adds an id to that list; it never copies the file or indexes it again.
A document with an empty list is unassigned (an orphan): it is still searchable
account-wide, it just belongs to no project.

``project_id`` is kept beside the list as the first linked project, for readers
that only ever needed one. :func:`set_document_projects` is the one place both
are written, so they cannot disagree.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping

from fastapi import Depends, HTTPException, Request

#: Where a document entered the account, for the "link an existing document"
#: picker. ``origin`` is recorded at upload; older documents are classified by
#: what else their record says.
ORIGIN_LABELS = {
    "documents": "Documents",
    "chat": "Chat upload",
    "project": "Project upload",
    "onboarding": "Onboarding",
    "google": "Google Workspace",
    "microsoft": "Microsoft 365",
}


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def document_project_ids(document: Mapping[str, Any]) -> list[str]:
    """The projects a document is linked to, oldest link first, no repeats."""
    raw = document.get("project_ids")
    if isinstance(raw, (list, tuple)):
        ids = [_text(value) for value in raw]
    else:
        ids = [_text(document.get("project_id"))]
    return list(dict.fromkeys(value for value in ids if value))


def set_document_projects(document: MutableMapping[str, Any], project_ids: Iterable[str]) -> None:
    ids = list(dict.fromkeys(_text(value) for value in project_ids if _text(value)))
    document["project_ids"] = ids
    document["project_id"] = ids[0] if ids else None


def link_document(document: MutableMapping[str, Any], project_id: str) -> bool:
    """Add one project to a document; True if it was not already linked."""
    ids = document_project_ids(document)
    if project_id in ids:
        set_document_projects(document, ids)      # normalise a legacy record
        return False
    set_document_projects(document, [*ids, project_id])
    return True


def unlink_document(document: MutableMapping[str, Any], project_id: str) -> bool:
    """Remove one project from a document; True if it was linked."""
    ids = document_project_ids(document)
    if project_id not in ids:
        return False
    set_document_projects(document, [value for value in ids if value != project_id])
    return True


def is_linked(document: Mapping[str, Any], project_id: str) -> bool:
    return project_id in document_project_ids(document)


def project_documents(documents: Mapping[str, Mapping[str, Any]],
                      project_ids: Iterable[str]) -> dict[str, Mapping[str, Any]]:
    """The documents linked to any of ``project_ids``, keyed by document id."""
    wanted = set(project_ids)
    return {doc_id: doc for doc_id, doc in documents.items()
            if wanted.intersection(document_project_ids(doc))}


def document_origin(document: Mapping[str, Any]) -> str:
    """Where the document came from: one of :data:`ORIGIN_LABELS`' keys."""
    origin = _text(document.get("origin"))
    if origin in ORIGIN_LABELS:
        return origin
    provider = _text(document.get("provider")).casefold()
    if provider in ("google", "microsoft"):
        return provider
    # Only the project upload route classifies a source; the others never did.
    if document.get("source_type"):
        return "project"
    return "documents"


def document_row(doc_id: str, document: Mapping[str, Any],
                 projects: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """One document as the Documents page and the project pickers show it.

    A link to a project that no longer exists is not a link, so such a
    document reads as unassigned.
    """
    linked = [pid for pid in document_project_ids(document) if pid in projects]
    origin = document_origin(document)
    pages = int(document.get("page_count") or len(document.get("pages", []) or []) or 0)
    return {
        "id": doc_id,
        "name": document.get("name", doc_id),
        "type": document.get("type", ""),
        "size": document.get("size", 0),
        "pages": pages, "page_count": pages,
        "status": document.get("status", "indexed"),
        "source_type": document.get("source_type", ""),
        "created_at": document.get("created_at") or document.get("uploaded_at"),
        "project_ids": linked,
        "project_id": linked[0] if linked else None,
        "projects": [{"id": pid, "name": projects[pid].get("name", ""),
                      "project_code": projects[pid].get("project_code", "")} for pid in linked],
        "unassigned": not linked,
        "origin": origin,
        "origin_label": ORIGIN_LABELS.get(origin, origin),
    }


def document_listing(workspace: Any, *, scope: str = "all", project_id: str = "") -> dict[str, Any]:
    """Every document with its projects; ``scope="unassigned"`` for the orphans only."""
    projects = workspace.load_projects()
    documents = workspace.load_metadata().get("documents", {})
    rows = [document_row(doc_id, doc, projects) for doc_id, doc in documents.items()]
    if scope == "unassigned":
        rows = [row for row in rows if row["unassigned"]]
    if project_id:
        rows = [row for row in rows if project_id in row["project_ids"]]
    return {"documents": rows, "total": len(rows),
            "unassigned_count": sum(1 for row in rows if row["unassigned"])}


def register_project_document_routes(namespace: Mapping[str, Any]) -> None:
    """A project's documents: list them, link existing ones, and unlink.

    Uploading a new one lives with document generation, which also reads PDF
    text; everything here only moves links, never files or vectors.
    """
    app = namespace["app"]
    require_account = namespace["require_account"]

    def project_or_404(workspace: Any, project_id: str) -> dict[str, Any]:
        project = workspace.load_projects().get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @app.get("/api/projects/{project_id}/source-documents")
    async def list_project_sources(project_id: str, context=Depends(require_account)) -> dict[str, Any]:
        workspace = context.workspace
        project_or_404(workspace, project_id)
        listing = document_listing(workspace, project_id=project_id)
        return {"documents": listing["documents"], "total": listing["total"]}

    @app.get("/api/projects/{project_id}/linkable-documents")
    async def list_linkable_documents(project_id: str, context=Depends(require_account)) -> dict[str, Any]:
        """The account's documents not yet linked to this project, newest first."""
        workspace = context.workspace
        project_or_404(workspace, project_id)
        rows = [row for row in document_listing(workspace)["documents"]
                if project_id not in row["project_ids"]]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return {"documents": rows, "total": len(rows)}

    @app.post("/api/projects/{project_id}/source-documents/link")
    async def link_project_sources(project_id: str, request: Request,
                                   context=Depends(require_account)) -> dict[str, Any]:
        """Link documents the account already holds to this project.

        No file is copied and nothing is re-indexed: the document gains one more
        project in its ``project_ids``, and every project it is linked to finds
        the same pages.
        """
        context.require("document.upload", "adding documents to a project")
        workspace = context.workspace
        project_or_404(workspace, project_id)
        body = await request.json()
        raw = body.get("doc_ids") if isinstance(body, dict) else None
        if not isinstance(raw, list) or not raw:
            raise HTTPException(422, detail="Choose at least one document to link")
        metadata = workspace.load_metadata()
        documents = metadata.get("documents", {})
        if any(doc_id not in documents for doc_id in raw):
            raise HTTPException(404, detail="One or more of those documents do not exist in this account")
        wanted = list(dict.fromkeys(raw))
        linked = [doc_id for doc_id in wanted if link_document(documents[doc_id], project_id)]
        if linked:
            workspace.save_metadata(metadata)
        return {"linked": linked, "already_linked": [d for d in wanted if d not in linked],
                "total": len(project_documents(documents, [project_id]))}

    @app.delete("/api/projects/{project_id}/source-documents/{doc_id}")
    async def unlink_project_source(project_id: str, doc_id: str,
                                    context=Depends(require_account)) -> dict[str, Any]:
        """Take a document off this project. The document itself is kept.

        It stays in Documents and on any other project it is linked to; with no
        project left it becomes unassigned.
        """
        context.require("document.upload", "removing documents from a project")
        workspace = context.workspace
        project_or_404(workspace, project_id)
        metadata = workspace.load_metadata()
        document = metadata.get("documents", {}).get(doc_id)
        if not document:
            raise HTTPException(404, detail="Document not found")
        if not unlink_document(document, project_id):
            raise HTTPException(404, detail="That document is not linked to this project")
        workspace.save_metadata(metadata)
        return {"unlinked": doc_id, "project_ids": document_project_ids(document),
                "unassigned": not document_project_ids(document)}


__all__ = [
    "ORIGIN_LABELS", "document_listing", "document_origin", "document_project_ids",
    "document_row", "is_linked", "link_document", "project_documents",
    "register_project_document_routes", "set_document_projects", "unlink_document",
]
