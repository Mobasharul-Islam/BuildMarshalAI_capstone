"""Ingestion of files pulled in from a linked external account.

Google Drive/Gmail and OneDrive/Outlook all end up doing the same thing: drop a
downloaded file into the caller's workspace, run the normal ColPali ingestion
over it, then enrich the resulting metadata and vector records with the display
name, the project link, and a pointer back to the external item.

Keeping that in one place matters because the Chroma enrichment is subtle: the
collection uses a no-op embedding function (ColPali produced the vectors), so
records must be updated with their existing embeddings or Chroma tries to embed
the documents itself and fails.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Mapping

from fastapi import HTTPException

try:  # the notebook puts this directory on sys.path
    from document_links import link_document
except ModuleNotFoundError:  # imported as backend.external_imports
    from backend.document_links import link_document


class ExternalImporter:
    """Ingest downloaded external files into one account's workspace."""

    def __init__(self, ingest_document: Any, provider: str):
        self.ingest_document = ingest_document
        # Provider key under which the external reference is recorded, and the
        # prefix used for the matching Chroma metadata fields.
        self.provider = provider

    def enrich_index(
        self,
        workspace: Any,
        doc_id: str,
        display_name: str,
        project_id: str | None,
        source_type: str,
        external: Mapping[str, Any],
    ) -> dict[str, Any]:
        collection = workspace.collection
        metadata = workspace.load_metadata()
        stored = (metadata.get("documents") or {}).get(doc_id)
        if not stored:
            raise RuntimeError("Ingested document metadata was not created")
        stored.update({
            "name": display_name,
            "source_type": source_type,
            "provider": self.provider,
            "origin": self.provider,
            self.provider: dict(external),
        })
        if project_id:
            link_document(stored, project_id)
        ids: list[str] = []
        metadatas: list[dict[str, Any]] = []
        documents: list[str] = []
        for index, page in enumerate(stored.get("pages") or []):
            number = int(page.get("page_num", index + 1))
            text = str(page.get("text_content", ""))
            ids.append(f"{doc_id}_p{number}")
            item = {
                "doc_id": doc_id, "doc_name": display_name, "page_num": number,
                "image_path": str(page.get("image_path") or ""),
                "text_content": text[:1000], "source_type": source_type,
                "provider": self.provider,
                f"{self.provider}_account_id": str(external.get("account_id", "")),
                f"{self.provider}_item_id": str(external.get("item_id", "")),
            }
            metadatas.append(item)
            documents.append(text[:8000])
        workspace.save_metadata(metadata)
        if ids:
            # Preserve the ColPali vectors written during ingestion; updating
            # without them would make Chroma call the no-op embedding function.
            existing = collection.get(ids=ids, include=["embeddings"])
            vectors = {
                item_id: value.tolist() if hasattr(value, "tolist") else value
                for item_id, value in zip(existing.get("ids", []), existing.get("embeddings", []))
            }
            indexes = [i for i, item_id in enumerate(ids) if item_id in vectors]
            if indexes:
                collection.update(
                    ids=[ids[i] for i in indexes],
                    embeddings=[vectors[ids[i]] for i in indexes],
                    metadatas=[metadatas[i] for i in indexes],
                    documents=[documents[i] for i in indexes],
                )
        return stored

    def ingest_path(
        self,
        workspace: Any,
        path: Path,
        display_name: str,
        project_id: str | None,
        source_type: str,
        external: Mapping[str, Any],
    ) -> dict[str, Any]:
        if project_id and project_id not in workspace.load_projects():
            raise HTTPException(404, "Project not found")
        doc_id = uuid.uuid4().hex[:12]
        destination = Path(workspace.docs_dir) / f"{doc_id}{path.suffix.lower()}"
        if path != destination:
            destination.write_bytes(path.read_bytes())
        result = self.ingest_document(destination, doc_id, workspace,
                                      display_name=display_name, project_id=project_id,
                                      origin=self.provider)
        if result.get("status") == "duplicate":
            # Already in the account; ingestion removed the new copy and linked
            # the existing one to the project, if one was given.
            return {
                "id": result["id"], "name": result.get("name", display_name),
                "project_id": project_id, "pages": result.get("page_count", 0),
                "status": "duplicate", "source_type": result.get("source_type", source_type),
                "provider": self.provider,
            }
        # Generic PDF ingestion renders page images but leaves text_content
        # empty.  Preserve selectable PDF text so imported files also work well
        # for Q&A and long-form document generation.
        if destination.suffix.lower() == ".pdf":
            try:
                # PyMuPDF keeps Bangla in reading order; pypdf scrambles its vowel signs.
                import fitz

                with fitz.open(str(destination)) as document:
                    texts = [(page.get_text() or "").strip() for page in document]
                metadata = workspace.load_metadata()
                stored = metadata["documents"][doc_id]
                for index, page in enumerate(stored.get("pages") or []):
                    page["text_content"] = texts[index] if index < len(texts) else ""
                workspace.save_metadata(metadata)
            except Exception:
                pass
        stored = self.enrich_index(workspace, doc_id, display_name, project_id, source_type, external)
        return {
            "id": doc_id, "name": display_name, "project_id": project_id,
            "pages": result.get("page_count", stored.get("page_count", 0)),
            "status": "indexed", "source_type": source_type,
            "provider": self.provider,
        }


__all__ = ["ExternalImporter"]
