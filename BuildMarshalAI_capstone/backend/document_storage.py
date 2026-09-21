"""Keeping the document store from growing without bound.

Indexing one PDF page costs far more than the page.  It leaves an original in
``documents/``, a rendered image in ``pages/``, a ColPali multi-vector in
``colpali_v1_2_multivectors/`` (a thousand-odd patch vectors, comfortably the
largest of them), a pooled vector in Chroma, and often a downscaled tile in the
vision cache.  A few hundred pages is gigabytes, and none of it announces
itself.

This module makes that visible and reclaimable, on three principles:

**Originals are never touched.**  They are the only thing that cannot be
rebuilt.  Everything else here is derived and can be regenerated from them, so
everything else is fair game.

**Reclaim the free wins first.**  Files nobody owns any more, then bytes that
are simply duplicated, then caches that can be rebuilt on demand.  Only after
those does anything lossy get suggested, and never without being asked.

**Nothing is deleted without being described first.**  :func:`plan_sweep` is
read-only and returns exactly what :func:`run_sweep` would remove, so the
confirmation is the truth rather than a summary of it.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Area:
    """One directory of the workspace, and what losing it would cost."""

    key: str
    label: str
    #: ``source`` cannot be rebuilt; ``derived`` can; ``index`` is rebuilt by
    #: re-indexing; ``output`` is something the user asked us to make.
    nature: str
    detail: str

    @property
    def reclaimable(self) -> bool:
        return self.nature == "derived"


#: Every directory an account's documents occupy.  Attribute names on
#: ``AccountWorkspace``, so a workspace that gains a directory is picked up by
#: adding one row here.
AREAS: tuple[Area, ...] = (
    Area("docs_dir", "Original uploads", "source",
         "The files people uploaded. The only thing here that cannot be rebuilt."),
    Area("pages_dir", "Page images", "derived",
         "One rendered image per page. Rebuilt by re-indexing the original; also "
         "what the page preview and ColPali read."),
    Area("multivector_dir", "ColPali page vectors", "derived",
         "The late-interaction vectors behind reranking. Usually the largest area, "
         "and recomputed from the page image on the next search that needs it."),
    Area("vision_cache_dir", "Vision tiles", "derived",
         "Small JPEGs the document composer sends to the model. Remade on demand."),
    Area("chroma_dir", "Vector index", "index",
         "The searchable index. Rebuilt only by re-indexing every document."),
    Area("generated_dir", "Generated documents", "output",
         "Reports and documents this workspace produced."),
    Area("imports_dir", "Imported files", "source",
         "Files pulled in from a connected Drive or OneDrive."),
)

#: Suffixes the page renderer produces, cheapest-to-largest.
PAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

#: What a sweep may do, in the order it should be considered.
SWEEP_ACTIONS: tuple[tuple[str, str], ...] = (
    ("orphans", "Remove derived files whose document is gone"),
    ("duplicates", "Collapse documents that are byte-for-byte identical"),
    ("compact", "Recompress page images that are larger than they need to be"),
    ("evict", "Drop rebuildable caches for the least recently used documents"),
)

DEFAULT_POLICY: dict[str, Any] = {
    # Nothing is reclaimed below this; a small workspace is not worth managing.
    "budget_mb": 2048,
    # Page images are rendered at up to 1024px; 1400 leaves headroom for a
    # workspace that raises it later.
    "page_max_edge": 1400,
    "page_quality": 82,
    # Refuse a duplicate at upload rather than indexing the same bytes twice.
    "deduplicate": True,
    # Documents used within this window are never evicted from cache.
    "keep_warm_days": 30,
}

POLICY_KEY = "storage_policy"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def human_bytes(size: float) -> str:
    """A size a person can read at a glance."""
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ──────────────────────────────────────────────────────────────────────────
# Measuring
# ──────────────────────────────────────────────────────────────────────────

def directory_size(path: Path) -> tuple[int, int]:
    """Total bytes and file count under ``path``, ignoring what cannot be read."""
    total = count = 0
    if not path or not Path(path).exists():
        return 0, 0
    for item in Path(path).rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
                count += 1
        except OSError:  # a file that vanished mid-walk is simply not counted
            continue
    return total, count


def policy_of(workspace: Any) -> dict[str, Any]:
    """This account's storage policy, defaults filled in."""
    stored = (workspace.load_mgmt() or {}).get(POLICY_KEY)
    policy = dict(DEFAULT_POLICY)
    if isinstance(stored, Mapping):
        for key, value in stored.items():
            if key in DEFAULT_POLICY:
                policy[key] = value
    return policy


def save_policy(workspace: Any, changes: Mapping[str, Any]) -> dict[str, Any]:
    policy = policy_of(workspace)
    for key, value in changes.items():
        if key not in DEFAULT_POLICY:
            continue
        if key in ("budget_mb", "page_max_edge", "page_quality", "keep_warm_days"):
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise HTTPException(422, detail=f"{key} must be a whole number") from None
            if number < 0:
                raise HTTPException(422, detail=f"{key} cannot be negative")
            if key == "page_quality" and not 30 <= number <= 100:
                raise HTTPException(422, detail="page_quality must be between 30 and 100")
            if key == "page_max_edge" and not 256 <= number <= 4096:
                raise HTTPException(422, detail="page_max_edge must be between 256 and 4096")
            policy[key] = number
        else:
            policy[key] = bool(value)
    mgmt = workspace.load_mgmt()
    mgmt[POLICY_KEY] = policy
    workspace.save_mgmt(mgmt)
    return policy


def area_usage(workspace: Any) -> list[dict[str, Any]]:
    """Bytes per area, largest first, with what each one is."""
    rows = []
    for area in AREAS:
        path = getattr(workspace, area.key, None)
        size, count = directory_size(Path(path)) if path else (0, 0)
        rows.append({
            "key": area.key, "label": area.label, "nature": area.nature,
            "detail": area.detail, "bytes": size, "human": human_bytes(size),
            "files": count, "reclaimable": area.reclaimable,
        })
    rows.sort(key=lambda row: -row["bytes"])
    return rows


# ──────────────────────────────────────────────────────────────────────────
# Mapping documents to the files they own
# ──────────────────────────────────────────────────────────────────────────

def _cache_stem(image_path: str | Path) -> str:
    """The multi-vector cache name for a page image.

    Mirrors ``HybridColPaliRetriever._cache_path`` exactly; if that changes,
    :func:`find_orphans` would start reporting live caches as orphans, which the
    tests check for.
    """
    return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(image_path).stem)


def document_files(workspace: Any, doc_id: str, document: Mapping[str, Any]) -> dict[str, list[Path]]:
    """Every file on disk that belongs to one document."""
    pages: list[Path] = []
    vectors: list[Path] = []
    tiles: list[Path] = []
    for page in document.get("pages", []) or []:
        resolved = workspace.resolve_page_path(page.get("image_path"))
        if resolved:
            pages.append(Path(resolved))
        stem = _cache_stem(page.get("image_path") or "")
        if stem:
            vector = Path(workspace.multivector_dir) / f"{stem}.npy"
            if vector.exists():
                vectors.append(vector)
            tile = Path(workspace.vision_cache_dir) / f"{stem}_512.jpg"
            if tile.exists():
                tiles.append(tile)
    originals = [
        item for item in Path(workspace.docs_dir).iterdir()
        if item.is_file() and item.stem == doc_id
    ] if Path(workspace.docs_dir).exists() else []
    return {"originals": originals, "pages": pages, "vectors": vectors, "tiles": tiles}


def _bytes_of(paths: Iterable[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def last_used(document: Mapping[str, Any]) -> str:
    """When this document was last read, falling back to when it arrived."""
    return _text(document.get("accessed_at")) or _text(document.get("created_at"))


def document_rows(workspace: Any) -> list[dict[str, Any]]:
    """Per-document storage, so it is obvious what is expensive."""
    metadata = workspace.load_metadata().get("documents", {})
    rows = []
    for doc_id, document in metadata.items():
        files = document_files(workspace, doc_id, document)
        sizes = {name: _bytes_of(paths) for name, paths in files.items()}
        total = sum(sizes.values())
        rows.append({
            "id": doc_id,
            "name": _text(document.get("name")) or doc_id,
            "project_id": document.get("project_id"),
            "pages": int(document.get("page_count") or len(document.get("pages", []) or [])),
            "bytes": total, "human": human_bytes(total),
            "breakdown": {name: {"bytes": size, "human": human_bytes(size),
                                 "files": len(files[name])}
                          for name, size in sizes.items()},
            # Only the rebuildable part is worth quoting as reclaimable.
            "reclaimable": sizes["vectors"] + sizes["tiles"],
            "last_used": last_used(document),
            "digest": _text(document.get("digest")),
        })
    rows.sort(key=lambda row: -row["bytes"])
    return rows


def note_access(workspace: Any, doc_ids: Sequence[str]) -> None:
    """Record that these documents were read just now.

    Cheap, and the only thing that separates a document somebody uses weekly
    from one indexed a year ago and never opened. Without it an eviction can
    only go on age, which throws away the wrong things.
    """
    wanted = [doc_id for doc_id in doc_ids if doc_id]
    if not wanted:
        return
    metadata = workspace.load_metadata()
    documents = metadata.get("documents", {})
    stamp = _now()
    touched = False
    for doc_id in wanted:
        if doc_id in documents:
            documents[doc_id]["accessed_at"] = stamp
            touched = True
    if touched:
        workspace.save_metadata(metadata)


# ──────────────────────────────────────────────────────────────────────────
# Reclaimable: orphans, duplicates, cold caches
# ──────────────────────────────────────────────────────────────────────────

def find_orphans(workspace: Any) -> dict[str, Any]:
    """Derived files no live document owns.

    Deleting a document removes its page images, its original and its vectors
    from the index, but the ColPali cache and the vision tiles are keyed by page
    *filename* and outlive it. Over a workspace's life that is the single
    largest avoidable cost, and none of it is reachable.
    """
    metadata = workspace.load_metadata().get("documents", {})
    live_stems: set[str] = set()
    live_pages: set[str] = set()
    for document in metadata.values():
        for page in document.get("pages", []) or []:
            stored = page.get("image_path") or ""
            if not stored:
                continue
            live_stems.add(_cache_stem(stored))
            live_pages.add(Path(stored).name)

    orphans: list[dict[str, Any]] = []

    def collect(directory: Path, label: str, belongs: Callable[[Path], bool]) -> None:
        if not directory.exists():
            return
        for item in sorted(directory.iterdir()):
            if not item.is_file() or belongs(item):
                continue
            try:
                size = item.stat().st_size
            except OSError:
                continue
            orphans.append({"path": str(item), "name": item.name, "area": label,
                            "bytes": size, "human": human_bytes(size)})

    collect(Path(workspace.multivector_dir), "ColPali page vectors",
            lambda item: item.suffix != ".npy" or item.stem in live_stems)
    collect(Path(workspace.vision_cache_dir), "Vision tiles",
            lambda item: not item.name.endswith("_512.jpg")
            or item.name[: -len("_512.jpg")] in live_stems)
    # A page image whose document is gone is equally unreachable.
    collect(Path(workspace.pages_dir), "Page images",
            lambda item: item.name in live_pages)

    total = sum(row["bytes"] for row in orphans)
    return {"files": orphans, "count": len(orphans), "bytes": total,
            "human": human_bytes(total)}


def digest_of(path: str | Path, chunk: int = 1024 * 1024) -> str:
    """A content hash, read in chunks so a large upload never lands in memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def find_by_digest(workspace: Any, digest: str, exclude: str = "") -> dict[str, Any] | None:
    """An already-indexed document with exactly these bytes."""
    if not digest:
        return None
    for doc_id, document in workspace.load_metadata().get("documents", {}).items():
        if doc_id != exclude and _text(document.get("digest")) == digest:
            return {**document, "id": doc_id}
    return None


def duplicate_groups(workspace: Any) -> dict[str, Any]:
    """Documents that are byte-for-byte the same file indexed more than once.

    Only the copies are counted as reclaimable; the first one stays.
    """
    by_digest: dict[str, list[dict[str, Any]]] = {}
    rows = {row["id"]: row for row in document_rows(workspace)}
    for doc_id, document in workspace.load_metadata().get("documents", {}).items():
        digest = _text(document.get("digest"))
        if not digest:
            continue
        by_digest.setdefault(digest, []).append({
            "id": doc_id, "name": _text(document.get("name")) or doc_id,
            "project_id": document.get("project_id"),
            "bytes": rows.get(doc_id, {}).get("bytes", 0),
            "created_at": _text(document.get("created_at")),
        })

    groups = []
    reclaimable = 0
    for digest, members in by_digest.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda row: row["created_at"])
        copies = members[1:]
        saving = sum(row["bytes"] for row in copies)
        reclaimable += saving
        groups.append({"digest": digest, "keep": members[0], "copies": copies,
                       "bytes": saving, "human": human_bytes(saving)})
    groups.sort(key=lambda row: -row["bytes"])
    return {"groups": groups, "count": len(groups), "bytes": reclaimable,
            "human": human_bytes(reclaimable)}


def cold_documents(workspace: Any, *, keep_warm_days: int, now: datetime | None = None,
                   rows: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Documents nobody has read lately, coldest first.

    Only their rebuildable caches are ever at stake, so "cold" needs to be a
    useful ordering rather than a precise one.
    """
    now = now or datetime.now(timezone.utc)
    rows = rows if rows is not None else document_rows(workspace)
    cold = []
    for row in rows:
        stamp = row.get("last_used")
        age = None
        if stamp:
            try:
                seen = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
                age = (now - seen).days
            except ValueError:
                age = None
        if age is not None and age < keep_warm_days:
            continue
        if not row.get("reclaimable"):
            continue
        cold.append({**row, "idle_days": age})
    cold.sort(key=lambda row: (-(row["idle_days"] or 10**6), -row["reclaimable"]))
    return cold


def oversized_pages(workspace: Any, *, max_edge: int) -> dict[str, Any]:
    """Page images bigger than the policy wants, and what recompressing saves.

    The saving is an estimate: it is measured exactly at the moment of
    compaction, and the plan says so rather than promising a figure it worked
    out from a formula.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow ships with the app
        return {"files": [], "count": 0, "bytes": 0, "human": human_bytes(0),
                "note": "Pillow is not available, so page images cannot be inspected."}

    candidates = []
    pages_dir = Path(workspace.pages_dir)
    if pages_dir.exists():
        for item in sorted(pages_dir.iterdir()):
            if not item.is_file() or item.suffix.lower() not in PAGE_SUFFIXES:
                continue
            try:
                size = item.stat().st_size
                with Image.open(item) as image:
                    width, height = image.size
            except Exception:
                continue
            if max(width, height) <= max_edge and item.suffix.lower() != ".png":
                continue
            candidates.append({"path": str(item), "name": item.name, "bytes": size,
                               "human": human_bytes(size), "width": width, "height": height})
    total = sum(row["bytes"] for row in candidates)
    # PNG screenshots of documents recompress to WebP at roughly a third; this
    # is the figure shown as an estimate, never as a promise.
    estimate = int(total * 0.65)
    return {"files": candidates, "count": len(candidates), "bytes": estimate,
            "human": human_bytes(estimate), "current_bytes": total,
            "note": "Estimated; the exact saving is measured as each file is rewritten."}


# ──────────────────────────────────────────────────────────────────────────
# Planning and sweeping
# ──────────────────────────────────────────────────────────────────────────

def plan_sweep(workspace: Any, *, actions: Sequence[str] = (),
               policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What a sweep would reclaim, without reclaiming any of it.

    Read-only by construction, and it returns the very lists :func:`run_sweep`
    consumes, so the confirmation an administrator sees is what actually
    happens.
    """
    policy = dict(policy or policy_of(workspace))
    wanted = set(actions) or {key for key, _ in SWEEP_ACTIONS}
    plan: dict[str, Any] = {"policy": policy, "actions": [], "bytes": 0}

    def add(key: str, label: str, detail: dict[str, Any], safe: bool) -> None:
        plan["actions"].append({
            "key": key, "label": label, "bytes": detail["bytes"],
            "human": detail["human"], "count": detail.get("count", 0),
            "safe": safe, "detail": detail,
        })
        plan["bytes"] += detail["bytes"]

    if "orphans" in wanted:
        add("orphans", "Remove files no document owns", find_orphans(workspace), True)
    if "duplicates" in wanted:
        add("duplicates", "Collapse identical documents", duplicate_groups(workspace), False)
    if "compact" in wanted:
        add("compact", "Recompress oversized page images",
            oversized_pages(workspace, max_edge=int(policy["page_max_edge"])), False)
    if "evict" in wanted:
        rows = document_rows(workspace)
        cold = cold_documents(workspace, keep_warm_days=int(policy["keep_warm_days"]), rows=rows)
        used = sum(row["bytes"] for row in rows)
        budget = int(policy["budget_mb"]) * 1024 * 1024
        over = max(0, used - budget) if budget else 0
        # Only evict as much as the budget actually calls for, coldest first.
        chosen, running = [], 0
        for row in cold:
            if budget and running >= over:
                break
            chosen.append(row)
            running += row["reclaimable"]
        add("evict", "Drop rebuildable caches for documents nobody has opened", {
            "bytes": running, "human": human_bytes(running), "count": len(chosen),
            "documents": chosen,
            "over_budget_bytes": over, "used_bytes": used, "budget_bytes": budget,
            "note": ("Within budget, so nothing needs evicting." if not over
                     else f"{human_bytes(over)} over the {policy['budget_mb']} MB budget."),
        }, False)

    plan["human"] = human_bytes(plan["bytes"])
    plan["safe_bytes"] = sum(row["bytes"] for row in plan["actions"] if row["safe"])
    plan["safe_human"] = human_bytes(plan["safe_bytes"])
    return plan


def _unlink(path: str | Path) -> int:
    """Remove a file, returning what it freed."""
    item = Path(path)
    try:
        size = item.stat().st_size
    except OSError:
        return 0
    try:
        item.unlink()
    except OSError:
        return 0
    return size


def compact_page(path: str | Path, *, max_edge: int, quality: int) -> dict[str, Any]:
    """Rewrite one page image smaller, keeping it readable.

    WebP at this quality is visually indistinguishable from the PNG for a
    document page while costing a fraction of it, and the page endpoint already
    serves ``.webp``. ColPali re-encodes from whatever is on disk, so a
    recompressed page keeps working -- the vectors it already produced are
    keyed by the stem, which is preserved.

    A rewrite that would not actually save anything is abandoned, so a page that
    is already small is left exactly as it was.
    """
    from PIL import Image

    source = Path(path)
    before = source.stat().st_size
    target = source.with_suffix(".webp")
    temporary = source.with_name(f"{source.stem}.compacting.webp")
    try:
        with Image.open(source) as image:
            image = image.convert("RGB")
            if max(image.size) > max_edge:
                image.thumbnail((max_edge, max_edge))
            image.save(temporary, "WEBP", quality=quality, method=4)
        after = temporary.stat().st_size
        if after >= before:
            temporary.unlink(missing_ok=True)
            return {"path": str(source), "saved": 0, "skipped": "already compact"}
        temporary.replace(target)
        if target != source:
            source.unlink(missing_ok=True)
        return {"path": str(source), "new_path": str(target),
                "before": before, "after": after, "saved": before - after}
    except Exception as error:
        temporary.unlink(missing_ok=True)
        return {"path": str(source), "saved": 0, "error": str(error)[:160]}


def _repoint_pages(workspace: Any, moves: Mapping[str, str]) -> None:
    """Follow renamed page files in the metadata, so nothing is lost from view."""
    if not moves:
        return
    metadata = workspace.load_metadata()
    changed = False
    for document in metadata.get("documents", {}).values():
        for page in document.get("pages", []) or []:
            stored = page.get("image_path") or ""
            if not stored:
                continue
            moved = moves.get(Path(stored).name)
            if moved:
                page["image_path"] = moved
                changed = True
    if changed:
        workspace.save_metadata(metadata)


def run_sweep(workspace: Any, *, actions: Sequence[str] = (),
              policy: Mapping[str, Any] | None = None,
              delete_document: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Carry out a planned sweep and report exactly what went.

    Ordered cheapest-risk first, and each step re-reads what it is about to
    touch rather than trusting a plan that may be minutes old.
    """
    policy = dict(policy or policy_of(workspace))
    wanted = set(actions) or {"orphans"}
    done: list[dict[str, Any]] = []
    freed = 0

    if "orphans" in wanted:
        orphans = find_orphans(workspace)
        removed = sum(_unlink(row["path"]) for row in orphans["files"])
        freed += removed
        done.append({"key": "orphans", "label": "Files no document owned",
                     "count": orphans["count"], "bytes": removed,
                     "human": human_bytes(removed)})

    if "duplicates" in wanted:
        groups = duplicate_groups(workspace)
        removed_bytes = 0
        removed_docs: list[str] = []
        for group in groups["groups"]:
            for copy in group["copies"]:
                if delete_document is None:
                    break
                before = sum(_bytes_of(paths) for paths in
                             document_files(workspace, copy["id"],
                                            workspace.load_metadata()
                                            .get("documents", {})
                                            .get(copy["id"], {})).values())
                try:
                    delete_document(copy["id"])
                except Exception:  # pragma: no cover - a copy that will not go
                    continue
                removed_bytes += before
                removed_docs.append(copy["id"])
        freed += removed_bytes
        done.append({"key": "duplicates", "label": "Identical documents collapsed",
                     "count": len(removed_docs), "bytes": removed_bytes,
                     "human": human_bytes(removed_bytes), "ids": removed_docs})

    if "compact" in wanted:
        candidates = oversized_pages(workspace, max_edge=int(policy["page_max_edge"]))
        saved = 0
        moves: dict[str, str] = {}
        for row in candidates["files"]:
            outcome = compact_page(row["path"], max_edge=int(policy["page_max_edge"]),
                                   quality=int(policy["page_quality"]))
            saved += outcome.get("saved", 0)
            if outcome.get("new_path") and outcome["new_path"] != outcome["path"]:
                moves[Path(outcome["path"]).name] = outcome["new_path"]
        _repoint_pages(workspace, moves)
        freed += saved
        done.append({"key": "compact", "label": "Page images recompressed",
                     "count": len(candidates["files"]), "bytes": saved,
                     "human": human_bytes(saved)})

    if "evict" in wanted:
        plan = plan_sweep(workspace, actions=["evict"], policy=policy)
        target = next((row for row in plan["actions"] if row["key"] == "evict"), None)
        removed_bytes = 0
        evicted: list[str] = []
        metadata = workspace.load_metadata().get("documents", {})
        for row in (target or {}).get("detail", {}).get("documents", []):
            files = document_files(workspace, row["id"], metadata.get(row["id"], {}))
            for path in files["vectors"] + files["tiles"]:
                removed_bytes += _unlink(path)
            evicted.append(row["id"])
        freed += removed_bytes
        done.append({"key": "evict", "label": "Rebuildable caches dropped",
                     "count": len(evicted), "bytes": removed_bytes,
                     "human": human_bytes(removed_bytes), "ids": evicted,
                     "note": "Rebuilt automatically the next time a search needs them."})

    return {"performed": done, "bytes": freed, "human": human_bytes(freed),
            "swept_at": _now()}


def storage_report(workspace: Any) -> dict[str, Any]:
    """Everything the storage panel shows, in one call."""
    policy = policy_of(workspace)
    areas = area_usage(workspace)
    documents = document_rows(workspace)
    used = sum(row["bytes"] for row in areas)
    budget = int(policy["budget_mb"]) * 1024 * 1024
    plan = plan_sweep(workspace, policy=policy)
    return {
        "total_bytes": used, "total_human": human_bytes(used),
        "budget_bytes": budget, "budget_human": human_bytes(budget),
        "budget_used": round(used / budget, 3) if budget else None,
        "over_budget": bool(budget and used > budget),
        "areas": areas,
        "documents": documents[:50],
        "document_count": len(documents),
        "policy": policy,
        "reclaimable_bytes": plan["bytes"], "reclaimable_human": plan["human"],
        "plan": plan,
        "actions": [{"key": key, "label": label} for key, label in SWEEP_ACTIONS],
    }


# ──────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────

class SweepRequest(BaseModel):
    actions: list[str] = Field(default_factory=list)
    confirm: bool = False


class PolicyRequest(BaseModel):
    budget_mb: int | None = None
    page_max_edge: int | None = None
    page_quality: int | None = None
    deduplicate: bool | None = None
    keep_warm_days: int | None = None


def register_document_storage_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register the storage routes.

    Reading is open to any member -- knowing what the workspace costs is not
    privileged. Changing the policy or running a sweep deletes things, so it is
    administrator work.
    """
    required = ("app", "require_account")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Document storage integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]

    def admin_only(context: Any) -> None:
        if not context.is_admin:
            raise HTTPException(403, detail="Managing document storage is an administrator action")

    def remover(context: Any) -> Callable[[str], None] | None:
        """The application's own document delete, so a swept copy is removed the
        same way a hand-deleted one is -- vectors, files and metadata together."""
        delete = namespace.get("delete_document_files")
        if callable(delete):
            return lambda doc_id: delete(context.workspace, doc_id)
        return None

    @app.get("/api/storage")
    async def read_storage(context=Depends(require_account)) -> dict[str, Any]:
        """Where this workspace's space has gone, and what could be reclaimed."""
        return storage_report(context.workspace)

    @app.get("/api/storage/plan")
    async def read_plan(actions: str = "", context=Depends(require_account)) -> dict[str, Any]:
        """Exactly what a sweep would remove. Reads only."""
        wanted = [item.strip() for item in actions.split(",") if item.strip()]
        unknown = set(wanted) - {key for key, _ in SWEEP_ACTIONS}
        if unknown:
            raise HTTPException(422, detail=f"Unknown sweep action(s): {', '.join(sorted(unknown))}")
        return plan_sweep(context.workspace, actions=wanted)

    @app.post("/api/storage/sweep")
    async def sweep(body: SweepRequest, context=Depends(require_account)) -> dict[str, Any]:
        """Reclaim space. Without ``confirm`` this reports and removes nothing."""
        admin_only(context)
        unknown = set(body.actions) - {key for key, _ in SWEEP_ACTIONS}
        if unknown:
            raise HTTPException(422, detail=f"Unknown sweep action(s): {', '.join(sorted(unknown))}")
        plan = plan_sweep(context.workspace, actions=body.actions)
        if not body.confirm:
            return {"confirmation_required": True, **plan}
        outcome = run_sweep(context.workspace, actions=body.actions,
                            delete_document=remover(context))
        return {"confirmation_required": False, **outcome,
                "storage": storage_report(context.workspace)}

    @app.put("/api/storage/policy")
    async def update_policy(body: PolicyRequest, context=Depends(require_account)) -> dict[str, Any]:
        admin_only(context)
        policy = save_policy(context.workspace, body.model_dump(exclude_none=True))
        return {"policy": policy, "defaults": dict(DEFAULT_POLICY)}

    return {"areas": [area.key for area in AREAS],
            "actions": [key for key, _ in SWEEP_ACTIONS]}


__all__ = [
    "AREAS", "DEFAULT_POLICY", "POLICY_KEY", "SWEEP_ACTIONS", "Area",
    "area_usage", "cold_documents", "compact_page", "digest_of",
    "directory_size", "document_files", "document_rows", "duplicate_groups",
    "find_by_digest", "find_orphans", "human_bytes", "last_used", "note_access",
    "oversized_pages", "plan_sweep", "policy_of",
    "register_document_storage_routes", "run_sweep", "save_policy",
    "storage_report",
]
