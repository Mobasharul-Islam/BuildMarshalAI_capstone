"""Onboarding a project: from its documents, or from a conversation, into a draft.

An administrator either uploads whatever the project already has -- a schedule
spreadsheet, a tender PDF, a contact list -- or simply says what they want
("create a project called Website Redesign"). Either way the result is an
*editable draft*, and nothing reaches the live stores until a confirmed commit.

Two rules hold the feature together.

**The application's schema is the source of truth.** This module owns no opinion
about what a project is, which of a task's fields are mandatory, or what a valid
cost looks like. All of that comes from :mod:`entity_schema`, which in turn
derives from the modules that own each record and is reconciled against their
constructors at startup. Adding a field to a task shows up here without a line
being written.

**The assistant asks rather than guesses.** A creation request that is missing a
mandatory field becomes an *incomplete* draft item, and the conversation
continues until the schema says it is complete. The follow-up questions, and the
choices offered for a field that names another record, are generated from the
schema and the workspace's real data -- not by the model -- so there is nothing
for it to invent.

The flow, end to end::

    documents or prompt
        -> analyse / create      (draft items, possibly incomplete)
        -> ask for what is missing
        -> admin reviews and edits
        -> select, with dependencies enforced
        -> confirm
        -> commit                (transactional, rolls back on failure)
"""

from __future__ import annotations

import copy
import json
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from fastapi import Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

try:  # the notebook puts this directory on sys.path
    from entity_schema import (
        ENTITIES, ENTITY_ORDER, catalog, coerce_fields, missing_required, permission_catalogue_rows, reconcile, reference_choices,
        validate_entity,
    )
    from permissions import canonical_role, role_names
    from project_people import member_id, resolve_user
    from document_links import link_document
except ModuleNotFoundError:  # imported as backend.project_onboarding
    from backend.entity_schema import (
        ENTITIES, ENTITY_ORDER, catalog, coerce_fields, missing_required, permission_catalogue_rows, reconcile, reference_choices,
        validate_entity,
    )
    from backend.permissions import canonical_role, role_names
    from backend.project_people import member_id, resolve_user
    from backend.document_links import link_document


#: The kinds a draft can hold, in the order they must be created.
ITEM_KINDS: tuple[str, ...] = ENTITY_ORDER

#: Characters of entropy behind a generated first-login password.
TEMP_PASSWORD_BYTES = 12

MAX_DOCUMENT_CHARS = 24000
MAX_ANALYSIS_TOKENS = 4096
MAX_COMMAND_TOKENS = 2048

#: How many existing records to show the assistant per reference field. Enough
#: to choose from; not so many that the prompt is mostly inventory.
MAX_CHOICES_IN_PROMPT = 40


# ──────────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def _fold(value: Any) -> str:
    """A name reduced to what duplicate matching should consider equal."""
    return re.sub(r"\s+", " ", _text(value)).casefold()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def temporary_password() -> str:
    """A first-login password for a user the draft creates.

    Generated per user at commit time and returned to the administrator exactly
    once, in the commit result, so it can be handed over and changed. It is
    never stored on the draft.
    """
    return secrets.token_urlsafe(TEMP_PASSWORD_BYTES)


def kind_label(kind: str, plural: bool = False) -> str:
    spec = ENTITIES.get(kind)
    if spec is None:
        return kind
    return spec.plural if plural else spec.label


# ──────────────────────────────────────────────────────────────────────────
# Draft and item records
# ──────────────────────────────────────────────────────────────────────────

def new_draft(name: str = "", user: Mapping[str, Any] | None = None) -> dict[str, Any]:
    user = user or {}
    return {
        "id": new_id("onb"),
        "name": _text(name) or "Project onboarding",
        "status": "draft",
        "documents": [],
        "items": {},
        "selection": [],
        "analysis": {},
        # The creation the assistant is still collecting fields for.
        "pending": None,
        "commit": None,
        "created_at": _now(),
        "updated_at": _now(),
        "created_by": _text(user.get("id")),
        "created_by_name": _text(user.get("name")) or _text(user.get("email")),
    }


def normalise_fields(kind: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Put supplied values into the shape the live record stores them in.

    Thin on purpose: every conversion is the application's own, reached through
    :func:`entity_schema.coerce_fields`.
    """
    return coerce_fields(kind, data)


def make_item(kind: str, data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a draft item. ``kind`` is validated by the caller."""
    data = data or {}
    source = data.get("source") if isinstance(data.get("source"), Mapping) else {}
    return {
        "id": new_id("it"),
        "kind": kind,
        "fields": normalise_fields(kind, data.get("fields") or data),
        # The item this one cannot exist without: a task's project, a task
        # cost's task. Empty for entities that stand alone.
        "parent_ref": _text(data.get("parent_ref")) or None,
        # A same-kind parent, which is how subtasks nest.
        "parent_id": _text(data.get("parent_id")) or None,
        # Projects a person should join once those projects exist.
        "project_refs": [
            _text(ref) for ref in (data.get("project_refs") or []) if _text(ref)
        ],
        "source": {
            "doc_id": _text(source.get("doc_id")),
            "doc_name": _text(source.get("doc_name")),
            "page": int(source.get("page") or 0) or None,
        },
        "confidence": round(min(max(float(data.get("confidence") or 0.0), 0.0), 1.0), 2),
        "origin": _text(data.get("origin"), "extracted") or "extracted",
        "created_at": _now(),
        "updated_at": _now(),
    }


def apply_item_updates(item: dict[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the client-settable parts of ``data`` onto ``item`` in place.

    Only the fields actually sent are touched. A patch that sets a due date must
    not also write the defaults of every field it never mentioned.
    """
    if "fields" in data and isinstance(data["fields"], Mapping):
        item["fields"].update(normalise_fields(item["kind"], data["fields"]))
    for link in ("parent_ref", "parent_id"):
        if link in data:
            item[link] = _text(data[link]) or None
    if "project_refs" in data:
        item["project_refs"] = [_text(ref) for ref in (data["project_refs"] or []) if _text(ref)]
    item["updated_at"] = _now()
    return item


# ──────────────────────────────────────────────────────────────────────────
# Hierarchy
# ──────────────────────────────────────────────────────────────────────────

def dependencies_of(item: Mapping[str, Any]) -> list[str]:
    """The draft items that must exist before ``item`` can.

    The single definition of the hierarchy. Selection closure, cascade,
    deletion, and commit ordering all read it, so they cannot drift apart.
    Which links exist for a kind comes from the schema, not from a list here.
    """
    spec = ENTITIES.get(item.get("kind") or "")
    if spec is None:
        return []
    refs: list[str] = []
    if spec.parent and item.get("parent_ref"):
        refs.append(item["parent_ref"])
    if spec.self_parent and item.get("parent_id"):
        refs.append(item["parent_id"])
    return refs


def ancestors_of(items: Mapping[str, Mapping[str, Any]], item_id: str) -> list[str]:
    """Every dependency of ``item_id``, transitively, nearest first."""
    found: list[str] = []
    seen = {item_id}
    queue = list(dependencies_of(items.get(item_id) or {}))
    while queue:
        current = queue.pop(0)
        if current in seen or current not in items:
            continue
        seen.add(current)
        found.append(current)
        queue.extend(dependencies_of(items[current]))
    return found


def descendants_of(items: Mapping[str, Mapping[str, Any]], item_id: str) -> list[str]:
    """Every item that depends on ``item_id``, transitively."""
    found: list[str] = []
    frontier = {item_id}
    while frontier:
        children = {
            other_id for other_id, other in items.items()
            if other_id not in found and other_id != item_id
            and frontier.intersection(dependencies_of(other))
        }
        if not children:
            break
        found.extend(sorted(children))
        frontier = children
    return found


def parent_of(draft: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any] | None:
    return (draft.get("items") or {}).get(item.get("parent_ref") or "")


def item_missing(draft: Mapping[str, Any], item: Mapping[str, Any]) -> list[dict[str, str]]:
    """Mandatory fields this item still needs, the parent among them."""
    spec = ENTITIES.get(item.get("kind") or "")
    if spec is None:
        return []
    has_parent = not spec.parent or bool(parent_of(draft, item))
    return missing_required(item["kind"], item.get("fields") or {}, has_parent=has_parent)


def item_issues(draft: Mapping[str, Any], item: Mapping[str, Any],
                *, roles: Sequence[Mapping[str, Any]] = ()) -> list[str]:
    """Anything the application's own validators object to, in plain words.

    Kept separate from the missing-field list: a field can be present and still
    wrong, and the administrator needs to be told which it is.
    """
    if item_missing(draft, item):
        # Complaining that a value is invalid before it has been supplied is
        # noise; the missing-field list already says what to do.
        return []
    siblings = [
        other["fields"] | {"id": other["id"]}
        for other in (draft.get("items") or {}).values()
        if other.get("kind") == item.get("kind") and other["id"] != item["id"]
    ]
    parent = (draft.get("items") or {}).get(item.get("parent_ref") or "") or {}
    project = parent.get("fields") if item.get("kind") == "task" and parent.get("kind") == "project" else None
    try:
        validate_entity(item["kind"], item.get("fields") or {},
                        siblings=siblings, roles=roles, ignore_id=item["id"],
                        project=({**project, "name": project.get("name")} if project else None))
    except HTTPException as error:
        return [str(error.detail)]
    return []


def item_status(draft: Mapping[str, Any], item: Mapping[str, Any],
                *, roles: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    missing = item_missing(draft, item)
    issues = item_issues(draft, item, roles=roles)
    return {
        "missing": missing,
        "issues": issues,
        "complete": not missing and not issues,
    }


def validate_item(item: Mapping[str, Any], draft: Mapping[str, Any]) -> None:
    """Refuse a draft item the UI must not be able to store.

    Structural rules only -- a link has to point at the right kind of thing, and
    a task still cannot be its own ancestor. Missing mandatory fields are *not*
    refused here: an incomplete item is a legitimate state that the draft shows
    and the conversation fills in. The commit is where completeness is enforced.
    """
    kind = item.get("kind")
    spec = ENTITIES.get(kind or "")
    if spec is None:
        raise HTTPException(422, detail=f"\"{kind}\" is not something this workspace holds")
    items = draft.get("items") or {}

    parent_ref = item.get("parent_ref")
    if parent_ref:
        if not spec.parent:
            raise HTTPException(422, detail=f"A {spec.label.lower()} does not belong to anything")
        parent = items.get(parent_ref)
        if not parent or parent.get("kind") != spec.parent:
            raise HTTPException(
                422,
                detail=f"That {spec.label.lower()}'s {spec.parent_label.lower()} is not in this draft",
            )

    if not spec.self_parent or not item.get("parent_id"):
        return

    parent_id = item["parent_id"]
    parent = items.get(parent_id)
    if not parent or parent.get("kind") != kind:
        raise HTTPException(422, detail=f"That parent {spec.label.lower()} is not in this draft")
    if parent.get("parent_ref") != item.get("parent_ref"):
        raise HTTPException(
            422,
            detail=f"A sub{spec.label.lower()} must sit under one in the same {spec.parent_label.lower()}",
        )
    if parent_id == item.get("id"):
        raise HTTPException(422, detail=f"A {spec.label.lower()} cannot be its own parent")

    # Walk up from the proposed parent; reaching this item means a loop.
    seen: set[str] = set()
    cursor: str | None = parent_id
    while cursor:
        if cursor == item.get("id"):
            raise HTTPException(422, detail="That parent would create a loop of subtasks")
        if cursor in seen:
            break
        seen.add(cursor)
        cursor = (items.get(cursor) or {}).get("parent_id")


def resolve_selection(draft: Mapping[str, Any], wanted: Iterable[str]) -> dict[str, Any]:
    """Turn a requested set of ids into a valid one.

    Selecting a task pulls in its project and its whole parent chain; selecting
    a cost pulls in what it is a cost of. Anything naming an item that is not in
    the draft is reported rather than silently dropped.
    """
    items = draft.get("items") or {}
    requested = [ref for ref in dict.fromkeys(_text(ref) for ref in wanted) if ref]
    unknown = [ref for ref in requested if ref not in items]
    selected = {ref for ref in requested if ref in items}

    added: list[str] = []
    for item_id in list(selected):
        for parent in ancestors_of(items, item_id):
            if parent not in selected:
                selected.add(parent)
                added.append(parent)

    return {
        "selection": [item_id for item_id in items if item_id in selected],
        "added_parents": added,
        "unknown": unknown,
    }


def cascade_deselect(draft: Mapping[str, Any], removed: Iterable[str]) -> list[str]:
    """Ids that must also come off when ``removed`` is deselected."""
    items = draft.get("items") or {}
    dropped: set[str] = set()
    for item_id in removed:
        dropped.update(descendants_of(items, item_id))
    return sorted(dropped)


def set_selection(draft: dict[str, Any], wanted: Iterable[str]) -> dict[str, Any]:
    resolved = resolve_selection(draft, wanted)
    draft["selection"] = resolved["selection"]
    draft["updated_at"] = _now()
    return resolved


def delete_item(draft: dict[str, Any], item_id: str) -> list[str]:
    """Remove an item and everything that depended on it.

    Leaving the children behind would produce tasks pointing at a project that
    is no longer in the draft, which the confirmation step could not describe.
    """
    items = draft.get("items") or {}
    if item_id not in items:
        raise HTTPException(404, detail="That item is not in this draft")
    removed = [item_id, *descendants_of(items, item_id)]
    for gone in removed:
        items.pop(gone, None)
    # A person's project memberships can point at a project that has just gone.
    for item in items.values():
        if item.get("project_refs"):
            item["project_refs"] = [ref for ref in item["project_refs"] if ref not in removed]
    draft["selection"] = [ref for ref in draft.get("selection", []) if ref not in removed]
    if (draft.get("pending") or {}).get("item_id") in removed:
        draft["pending"] = None
    draft["updated_at"] = _now()
    return removed


def add_item(draft: dict[str, Any], kind: str, data: Mapping[str, Any],
             *, select: bool = True) -> dict[str, Any]:
    if kind not in ENTITIES:
        raise HTTPException(422, detail=f"\"{kind}\" is not something this workspace holds")
    item = make_item(kind, {**data, "origin": data.get("origin", "manual")})
    draft.setdefault("items", {})[item["id"]] = item
    validate_item(item, draft)
    if select:
        set_selection(draft, [*draft.get("selection", []), item["id"]])
    draft["updated_at"] = _now()
    return item


def update_item(draft: dict[str, Any], item_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
    item = (draft.get("items") or {}).get(item_id)
    if not item:
        raise HTTPException(404, detail="That item is not in this draft")
    before = json.dumps(item, sort_keys=True)
    apply_item_updates(item, data)
    try:
        validate_item(item, draft)
    except HTTPException:
        # Put the item back rather than leaving a half-applied edit behind.
        draft["items"][item_id] = json.loads(before)
        raise
    # A move can orphan a selected descendant's parent chain; re-close it.
    if draft.get("selection"):
        set_selection(draft, draft["selection"])
    draft["updated_at"] = _now()
    return item


# ──────────────────────────────────────────────────────────────────────────
# Presenting a draft
# ──────────────────────────────────────────────────────────────────────────

def draft_summary(draft: Mapping[str, Any], *,
                  roles: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Counts per kind, plus how much of the draft is ready to be created."""
    items = (draft.get("items") or {}).values()
    selection = set(draft.get("selection") or ())
    counts = {kind: 0 for kind in ITEM_KINDS}
    selected = {kind: 0 for kind in ITEM_KINDS}
    incomplete = 0
    incomplete_selected = 0
    for item in items:
        kind = item.get("kind")
        if kind not in counts:
            continue
        counts[kind] += 1
        ready = item_status(draft, item, roles=roles)["complete"]
        if not ready:
            incomplete += 1
        if item.get("id") in selection:
            selected[kind] += 1
            if not ready:
                incomplete_selected += 1
    return {
        "counts": counts, "selected": selected,
        "total": sum(counts.values()), "total_selected": sum(selected.values()),
        "incomplete": incomplete, "incomplete_selected": incomplete_selected,
        # The Onboard button is only live when every selected item is ready.
        "ready_to_onboard": bool(selection) and incomplete_selected == 0,
    }


def draft_view(draft: Mapping[str, Any], *,
               roles: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The whole draft as the page renders it.

    Items come back as a list in creation order with their dependencies and
    their missing mandatory fields spelled out, so the client can grey out a
    checkbox and explain an incomplete record without re-deriving the rules.
    """
    items = draft.get("items") or {}
    selection = set(draft.get("selection") or ())
    rows = []
    for item_id, item in items.items():
        deps = dependencies_of(item)
        rows.append({
            **item,
            **item_status(draft, item, roles=roles),
            "depends_on": deps,
            "blocked_by": [ref for ref in deps if ref not in selection],
            "dependents": descendants_of(items, item_id),
            "selected": item_id in selection,
            "label": kind_label(item.get("kind") or ""),
        })
    return {
        **{key: value for key, value in draft.items() if key != "items"},
        "items": rows,
        "summary": draft_summary(draft, roles=roles),
        "kinds": list(ITEM_KINDS),
        "entities": catalog(),
    }


# ──────────────────────────────────────────────────────────────────────────
# Describing the schema to the model
#
# Both prompts are generated from the entity catalogue, so an entity or a field
# added to the application is offered to the assistant without an edit here.
# ──────────────────────────────────────────────────────────────────────────

def response_key(kind: str) -> str:
    """The JSON key the extraction prompt uses for a kind."""
    return "procurement" if kind == "procurement" else f"{kind}s"


#: Response key -> draft kind.
RESPONSE_KINDS: dict[str, str] = {response_key(kind): kind for kind in ITEM_KINDS}


def describe_entities_for_model(include_optional: bool = True) -> str:
    """Every entity, its fields, and which of them are mandatory."""
    lines: list[str] = []
    for kind in ITEM_KINDS:
        spec = ENTITIES[kind]
        parts = []
        for item in spec.fields:
            if not include_optional and not item.required:
                continue
            mark = "*" if item.required else ""
            detail = ""
            if item.type == "select" and item.options:
                detail = f" (one of: {', '.join(item.options)})"
            elif item.type == "reference":
                detail = f" (an existing {kind_label(item.reference).lower()})"
            elif item.type in ("money", "number"):
                detail = " (a number)"
            elif item.type == "date":
                detail = " (YYYY-MM-DD)"
            parts.append(f"{item.name}{mark}{detail}")
        parent = ""
        if spec.parent:
            parent = f"  [belongs to a {spec.parent_label.lower()}: give \"parent\"]"
        if spec.self_parent:
            parent += "  [may nest: give \"parent_task\"]"
        lines.append(f"- {response_key(kind)}: {', '.join(parts)}{parent}")
    return "\n".join(lines)


def describe_choices_for_model(choices: Mapping[str, Sequence[Mapping[str, str]]]) -> str:
    """The records that already exist, which is what the model must choose from."""
    lines: list[str] = []
    for kind, rows in choices.items():
        if not rows:
            continue
        shown = [row["label"] for row in rows[:MAX_CHOICES_IN_PROMPT] if row.get("label")]
        if not shown:
            continue
        more = "" if len(rows) <= MAX_CHOICES_IN_PROMPT else f", … ({len(rows)} in total)"
        lines.append(f"- {kind_label(kind, plural=True)}: {', '.join(shown)}{more}")
    return "\n".join(lines) or "(this workspace has no records yet)"


_EXTRACTION_RULES = """Rules:
- Fields marked * are mandatory. Supply one only if the document states it.
- Leave a field out rather than guessing. An incomplete record is fine; an
  invented one is not.
- "parent" names the record this one belongs to, by name.
- "parent_task" nests a task under another task in the same project.
- Preserve the work-breakdown hierarchy the document shows.
- Do not invent projects, people, tasks, or amounts the documents do not mention.
- Return JSON only, with no commentary and no code fence."""


class ExtractionPass(BaseModel):
    """One analysis pass over a document.

    A pass is a focus plus the entity keys it may fill. Adding a document family
    later means appending a pass, not editing the analyser.
    """

    key: str
    label: str
    focus: str
    kinds: list[str] = Field(default_factory=lambda: list(ITEM_KINDS))


#: The passes run for every document. One by default, because the models in use
#: read a whole document far better in a single look than in several narrow
#: ones; the structure exists so that can be split per document family without
#: touching the caller.
EXTRACTION_PASSES: tuple[ExtractionPass, ...] = (
    ExtractionPass(
        key="full",
        label="Projects, tasks, people, costs and catalogues",
        focus=(
            "Read this construction project document and extract every record it "
            "describes: projects, tasks and subtasks with their hierarchy, people, "
            "costs, procurement, and the task types, project types, trades and roles "
            "they imply."
        ),
    ),
)


def build_extraction_prompt(pass_spec: ExtractionPass, document: Mapping[str, Any],
                            instructions: str = "",
                            choices: Mapping[str, Sequence[Mapping[str, str]]] | None = None) -> str:
    """The prompt for one document.

    Page text is sent with its page number so extracted records can cite where
    they came from, which is what makes an AI-written draft reviewable.
    """
    body: list[str] = []
    budget = MAX_DOCUMENT_CHARS
    for page in document.get("pages", []):
        text = re.sub(r"[ \t]+", " ", _text(page.get("text_content")))
        if not text:
            continue
        chunk = f"[page {int(page.get('page_num') or 1)}]\n{text}"
        if budget - len(chunk) <= 0:
            body.append(chunk[:budget])
            break
        body.append(chunk)
        budget -= len(chunk)

    extra = f"\n\nAdministrator's instructions: {_text(instructions)}" if _text(instructions) else ""
    permissions = "\n".join(f"- {row['key']}: {row['name']}" for row in permission_catalogue_rows())
    existing = f"\n\nRecords this workspace already has:\n{describe_choices_for_model(choices or {})}"
    return (
        f"{pass_spec.focus}\n\n"
        f"Document: {_text(document.get('name'), 'Untitled')}{extra}\n\n"
        "Return ONE JSON object. Every key is optional and holds an array:\n"
        f"{describe_entities_for_model()}\n\n"
        f"{_EXTRACTION_RULES}\n\n"
        f"Permission keys available for a role's \"permissions\":\n{permissions}"
        f"{existing}\n\n"
        "--- DOCUMENT CONTENT ---\n" + "\n\n".join(body) + "\n--- END ---"
    )


def _json_object(text: str) -> dict[str, Any] | None:
    """Recover the JSON object from a model reply, fence or no fence."""
    text = _text(text)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(candidate[start:end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def parse_extraction(raw: str) -> dict[str, list[dict[str, Any]]]:
    """Turn one model reply into per-kind lists of plain field dicts.

    A reply that is not JSON at all yields nothing rather than an exception: one
    unreadable document must not lose the extraction from the others. A value
    the schema refuses -- a status that is not a status -- drops that one field
    rather than the whole record.
    """
    parsed = _json_object(raw) or {}
    result: dict[str, list[dict[str, Any]]] = {kind: [] for kind in ITEM_KINDS}
    for key, kind in RESPONSE_KINDS.items():
        entries = parsed.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            fields: dict[str, Any] = {}
            for name, value in entry.items():
                try:
                    fields.update(normalise_fields(kind, {name: value}))
                except HTTPException:
                    continue  # a value the schema refuses is dropped, not stored
            record: dict[str, Any] = {"fields": fields}
            for link in ("parent", "parent_task"):
                if _text(entry.get(link)):
                    record[link] = _text(entry[link])
            if kind == "task_cost":
                # A cost with no amount is not a cost.
                if _text(fields.get("amount")) == "":
                    continue
            elif not _text(fields.get("name")):
                continue
            result[kind].append(record)
    return result


def merge_extraction(draft: dict[str, Any], extracted: Mapping[str, list[dict[str, Any]]],
                     source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Fold one document's extraction into the draft.

    Two documents describing the same project must not produce two draft
    projects, so an entity whose name already appears is filled in rather than
    repeated -- a later document can supply a field an earlier one left blank,
    but never overwrite one it already found.
    """
    source = source or {}
    items = draft.setdefault("items", {})
    added: dict[str, int] = {kind: 0 for kind in ITEM_KINDS}
    enriched = 0

    def existing(kind: str, name: str, parent_ref: str | None = None) -> dict[str, Any] | None:
        for item in items.values():
            if item.get("kind") != kind or _fold(item["fields"].get("name")) != _fold(name):
                continue
            if parent_ref and item.get("parent_ref") != parent_ref:
                continue
            return item
        return None

    def fill(item: dict[str, Any], fields: Mapping[str, Any]) -> None:
        nonlocal enriched
        changed = False
        for key, value in fields.items():
            if value in ("", None, []) or item["fields"].get(key) not in ("", None, []):
                continue
            item["fields"][key] = value
            changed = True
        if changed:
            item["updated_at"] = _now()
            enriched += 1

    def place(kind: str, record: Mapping[str, Any], **links: Any) -> dict[str, Any]:
        fields = record["fields"]
        found = None
        if _text(fields.get("name")):
            found = existing(kind, fields["name"], links.get("parent_ref"))
        if found:
            fill(found, fields)
            return found
        item = make_item(kind, {**record, **links, "source": source, "origin": "extracted"})
        items[item["id"]] = item
        added[kind] += 1
        return item

    # An index of everything in the draft that a child could name as its parent.
    def index_of(kind: str) -> dict[str, str]:
        return {
            _fold(item["fields"].get("name")): item["id"]
            for item in items.values() if item.get("kind") == kind
        }

    # Standalone kinds first; the rest reference them by name.
    for kind in ("project_type", "task_type", "trade", "vendor", "role_type", "project", "user"):
        for record in extracted.get(kind, []):
            item = place(kind, record)
            if kind == "user":
                project_id = _resolve_parent(record, index_of("project"))
                if project_id and project_id not in item["project_refs"]:
                    item["project_refs"].append(project_id)

    projects = index_of("project")

    # Tasks in two passes: create them all, then wire the parents up, so a
    # subtask listed before its parent still lands in the right place.
    pending_parents: list[tuple[str, str]] = []
    for record in extracted.get("task", []):
        parent_ref = _resolve_parent(record, projects)
        if not parent_ref:
            continue  # a task with no project cannot be onboarded
        item = place("task", record, parent_ref=parent_ref)
        if _text(record.get("parent_task")):
            pending_parents.append((item["id"], _text(record["parent_task"])))

    tasks_by_project: dict[tuple[str, str], str] = {
        (item.get("parent_ref") or "", _fold(item["fields"].get("name"))): item["id"]
        for item in items.values() if item.get("kind") == "task"
    }
    for task_id, parent_name in pending_parents:
        task = items.get(task_id)
        if not task or task.get("parent_id"):
            continue
        parent_id = tasks_by_project.get((task.get("parent_ref") or "", _fold(parent_name)))
        if not parent_id or parent_id == task_id:
            continue
        task["parent_id"] = parent_id
        try:
            validate_item(task, draft)
        except HTTPException:
            # A hierarchy the document implies but the app cannot hold (a loop,
            # a cross-project parent) leaves the task at the project root.
            task["parent_id"] = None

    tasks = index_of("task")
    for kind, parents in (("project_cost", projects), ("procurement", projects),
                          ("task_cost", tasks)):
        for record in extracted.get(kind, []):
            parent_ref = _resolve_parent(record, parents)
            if not parent_ref:
                continue  # a cost with nothing to cost cannot be onboarded
            place(kind, record, parent_ref=parent_ref)

    return {"added": added, "enriched": enriched, "total_added": sum(added.values())}


def _resolve_parent(record: Mapping[str, Any], index: Mapping[str, str]) -> str | None:
    """The draft id of the parent a record names, or the only candidate.

    A document about one project need not repeat its name on every row, so a
    single candidate is taken as the answer. Several candidates and no name is
    ambiguous, and the record is left for the administrator rather than guessed.
    """
    named = _fold(record.get("parent"))
    if named and named in index:
        return index[named]
    if named:
        return None
    return next(iter(index.values())) if len(index) == 1 else None


# ──────────────────────────────────────────────────────────────────────────
# Editing and creating in conversation
# ──────────────────────────────────────────────────────────────────────────

_COMMAND_RULES = """Return ONE JSON object: {"operations": [...], "reply": "..."}

Operations:
  {"op":"create","kind":"<kind>","fields":{...},"parent":"<name>","parent_task":"<name>"}
  {"op":"update","target":"<name or id>","kind":"<kind>","fields":{...}}
  {"op":"delete","target":"<name or id>","kind":"<kind>"}
  {"op":"move","target":"<name or id>","parent":"<name>","parent_task":"<name or ''>"}
  {"op":"select","target":"<name or id>","kind":"<kind>"}
  {"op":"deselect","target":"<name or id>","kind":"<kind>"}

Rules that matter more than being helpful:
- NEVER invent a value for a field. Put in "fields" only what the administrator
  actually said. Leaving a mandatory field out is correct; the system asks for
  it and tells them what the choices are.
- A field that names another record must use one of the existing names listed
  below, exactly. If several could match, or none do, leave it out.
- Do not assume an id, a date, an amount, an assignee, or a relationship.
- "reply" is one short sentence in plain language. Do not list missing fields in
  it; that is added for you.
Return JSON only, with no commentary and no code fence."""


def describe_draft_for_model(draft: Mapping[str, Any], limit: int = 120) -> str:
    """A compact inventory the command interpreter resolves names against."""
    items = draft.get("items") or {}
    lines: list[str] = []
    for kind in ITEM_KINDS:
        rows = [item for item in items.values() if item.get("kind") == kind]
        if not rows:
            continue
        lines.append(f"{kind_label(kind, plural=True)}:")
        for item in rows[:limit]:
            name = _text(item["fields"].get("name")) or _text(item["fields"].get("amount")) or "(unnamed)"
            detail = []
            parent = items.get(item.get("parent_ref") or "")
            if parent:
                detail.append(f"{ENTITIES[kind].parent_label.lower()}: "
                              f"{_text(parent['fields'].get('name'))}")
            nested = items.get(item.get("parent_id") or "")
            if nested:
                detail.append(f"under: {_text(nested['fields'].get('name'))}")
            if kind == "user" and _text(item["fields"].get("email")):
                detail.append(_text(item["fields"]["email"]))
            missing = item_missing(draft, item)
            if missing:
                detail.append("still needs " + ", ".join(row["label"] for row in missing))
            suffix = f" [{'; '.join(detail)}]" if detail else ""
            lines.append(f"  - {name}{suffix} (id: {item['id']})")
    return "\n".join(lines) or "(the draft is empty)"


def build_command_prompt(draft: Mapping[str, Any], text: str,
                         choices: Mapping[str, Sequence[Mapping[str, str]]] | None = None) -> str:
    pending = draft.get("pending") or {}
    pending_line = ""
    if pending.get("item_id"):
        item = (draft.get("items") or {}).get(pending["item_id"])
        if item:
            wanted = ", ".join(row["label"] for row in item_missing(draft, item))
            pending_line = (
                f"\nYou last asked the administrator for: {wanted or 'nothing'} "
                f"(for {kind_label(item['kind']).lower()} id {item['id']}). Their message is "
                f"most likely answering that, so prefer an \"update\" on that id.\n"
            )
    return (
        "You maintain a draft of records that are about to be created in a "
        "construction project workspace. Turn the administrator's message into "
        "operations on that draft. Nothing you return is applied to live data.\n\n"
        f"{_COMMAND_RULES}\n\n"
        f"Record types and their fields (* = mandatory):\n{describe_entities_for_model()}\n\n"
        f"Records that already exist in the workspace:\n{describe_choices_for_model(choices or {})}\n\n"
        f"--- CURRENT DRAFT ---\n{describe_draft_for_model(draft)}\n--- END ---\n"
        f"{pending_line}\n"
        f"Administrator: {_text(text)}"
    )


def parse_command_response(raw: str) -> dict[str, Any]:
    parsed = _json_object(raw) or {}
    operations = parsed.get("operations")
    return {
        "operations": [op for op in operations if isinstance(op, Mapping)] if isinstance(operations, list) else [],
        "reply": _text(parsed.get("reply")),
    }


def find_item(draft: Mapping[str, Any], target: str, kind: str = "") -> dict[str, Any] | None:
    """Resolve a command's target by id first, then by name."""
    items = draft.get("items") or {}
    target = _text(target)
    if not target:
        return None
    if target in items and (not kind or items[target].get("kind") == kind):
        return items[target]
    matches = [
        item for item in items.values()
        if _fold(item["fields"].get("name")) == _fold(target)
        and (not kind or item.get("kind") == kind)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        # An email identifies a person more reliably than a name does.
        by_email = [
            item for item in items.values()
            if item.get("kind") == "user" and _fold(item["fields"].get("email")) == _fold(target)
        ]
        return by_email[0] if len(by_email) == 1 else None
    return None


def _resolve_link(draft: Mapping[str, Any], operation: Mapping[str, Any],
                  kind: str) -> tuple[str | None, str]:
    """Find the parent an operation names, or say why it could not be found.

    A single candidate of the right kind is taken; several are ambiguous and are
    sent back as a question rather than resolved by picking one.
    """
    spec = ENTITIES[kind]
    if not spec.parent:
        return None, ""
    named = _text(operation.get("parent"))
    if named:
        found = find_item(draft, named, spec.parent)
        if found:
            return found["id"], ""
        return None, f"\"{named}\" is not a {spec.parent_label.lower()} in the draft"
    candidates = [item for item in (draft.get("items") or {}).values()
                  if item.get("kind") == spec.parent]
    if len(candidates) == 1:
        return candidates[0]["id"], ""
    if not candidates:
        return None, f"add a {spec.parent_label.lower()} to the draft first"
    return None, f"say which {spec.parent_label.lower()} it belongs to"


def apply_operations(draft: dict[str, Any], operations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Apply interpreted operations to the draft.

    Every operation is applied or reported; one that names something absent is
    skipped with a reason rather than failing the batch, because a four-part
    instruction should not lose its three good parts to one bad one.

    A ``create`` lands an item even when mandatory fields are still missing.
    That is the point: the draft shows it as incomplete, and the conversation
    carries on filling it in.
    """
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    touched: list[str] = []

    def refuse(operation: Mapping[str, Any], reason: str) -> None:
        skipped.append({"op": _text(operation.get("op")), "target": _text(operation.get("target")),
                        "reason": reason})

    def record(op: str, item: Mapping[str, Any], **extra: Any) -> None:
        applied.append({
            "op": op, "kind": item["kind"], "id": item["id"],
            "name": _text(item["fields"].get("name")) or _text(item["fields"].get("amount")),
            "label": kind_label(item["kind"]), **extra,
        })
        touched.append(item["id"])

    for operation in operations:
        op = _fold(operation.get("op"))
        kind = _fold(operation.get("kind")).replace(" ", "_")
        if kind and kind not in ENTITIES:
            refuse(operation, f"\"{operation.get('kind')}\" is not something this workspace holds")
            continue
        try:
            if op in ("add", "create"):
                if not kind:
                    refuse(operation, "no record type was given")
                    continue
                links: dict[str, Any] = {}
                parent_ref, problem = _resolve_link(draft, operation, kind)
                if problem and ENTITIES[kind].parent:
                    # Not a refusal: the item is created without the link and
                    # the administrator is asked for it, which is the whole point.
                    parent_ref = None
                links["parent_ref"] = parent_ref
                if ENTITIES[kind].self_parent and _text(operation.get("parent_task")):
                    nested = find_item(draft, operation["parent_task"], kind)
                    if nested and nested.get("parent_ref") == parent_ref:
                        links["parent_id"] = nested["id"]
                item = add_item(draft, kind, {"fields": operation.get("fields") or {}, **links})
                record("create", item)

            elif op in ("update", "delete", "select", "deselect", "move"):
                item = find_item(draft, operation.get("target", ""), kind)
                if not item:
                    refuse(operation, f"\"{_text(operation.get('target'))}\" is not in the draft")
                    continue
                if op == "update":
                    update_item(draft, item["id"], {"fields": operation.get("fields") or {}})
                    record("update", item)
                elif op == "delete":
                    removed = delete_item(draft, item["id"])
                    applied.append({"op": "delete", "kind": item["kind"], "id": item["id"],
                                    "name": _text(item["fields"].get("name")),
                                    "label": kind_label(item["kind"]), "removed": len(removed)})
                elif op == "move":
                    changes: dict[str, Any] = {}
                    if "parent" in operation:
                        parent_ref, problem = _resolve_link(draft, operation, item["kind"])
                        if problem:
                            refuse(operation, problem)
                            continue
                        changes["parent_ref"] = parent_ref
                        changes["parent_id"] = ""
                    if "parent_task" in operation:
                        name = _text(operation.get("parent_task"))
                        if name:
                            nested = find_item(draft, name, item["kind"])
                            if not nested:
                                refuse(operation, f"\"{name}\" is not in the draft")
                                continue
                            changes["parent_id"] = nested["id"]
                        else:
                            changes["parent_id"] = ""
                    update_item(draft, item["id"], changes)
                    record("move", item)
                elif op == "select":
                    set_selection(draft, [*draft.get("selection", []), item["id"]])
                    record("select", item)
                else:
                    dropped = {item["id"], *cascade_deselect(draft, [item["id"]])}
                    set_selection(draft, [ref for ref in draft.get("selection", []) if ref not in dropped])
                    record("deselect", item)
            else:
                refuse(operation, f"\"{operation.get('op')}\" is not an operation")
        except HTTPException as error:
            refuse(operation, str(error.detail))

    _update_pending(draft, touched)
    return {"applied": applied, "skipped": skipped}


def _update_pending(draft: dict[str, Any], touched: Sequence[str]) -> None:
    """Point the conversation at whatever still needs answering.

    The most recently touched incomplete item wins; if everything the assistant
    touched is now complete, the previous pending item keeps the floor, and if
    that is complete too the conversation is finished.
    """
    items = draft.get("items") or {}
    for item_id in reversed(list(touched)):
        item = items.get(item_id)
        if item and item_missing(draft, item):
            draft["pending"] = {"item_id": item_id, "kind": item["kind"], "asked_at": _now()}
            return
    current = (draft.get("pending") or {}).get("item_id")
    if current and current in items and item_missing(draft, items[current]):
        return
    draft["pending"] = None


def pending_question(draft: Mapping[str, Any],
                     choices: Mapping[str, Sequence[Mapping[str, str]]] | None = None) -> str:
    """The question to put to the administrator, built from the schema.

    Deliberately not left to the model: what is missing, and what the valid
    answers are, are facts the application knows exactly.
    """
    pending = draft.get("pending") or {}
    item = (draft.get("items") or {}).get(pending.get("item_id") or "")
    if not item:
        return ""
    missing = item_missing(draft, item)
    if not missing:
        return ""
    name = _text(item["fields"].get("name")) or kind_label(item["kind"]).lower()
    lines = [f"**{kind_label(item['kind'])}: {name}** still needs "
             f"{', '.join(row['label'] for row in missing)}."]
    for row in missing:
        if not row.get("reference"):
            continue
        options = list((choices or {}).get(row["reference"]) or [])
        draft_options = [
            _text(other["fields"].get("name"))
            for other in (draft.get("items") or {}).values()
            if other.get("kind") == row["reference"] and _text(other["fields"].get("name"))
        ]
        labels = [entry["label"] for entry in options if entry.get("label")] + draft_options
        labels = list(dict.fromkeys(labels))[:12]
        if labels:
            lines.append(f"- **{row['label']}** — choose one of: {', '.join(labels)}")
        else:
            lines.append(f"- **{row['label']}** — nothing to choose from yet; add one first")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# Matching against what already exists
# ──────────────────────────────────────────────────────────────────────────

#: Where a catalogue kind lives inside the management store.
MGMT_KEYS: dict[str, str] = {
    "task_type": "task_types", "project_type": "project_types",
    "trade": "trades", "vendor": "vendors",
}


def match_existing(kind: str, fields: Mapping[str, Any], *, projects: Mapping[str, Any] | None = None,
                   tasks: Sequence[Mapping[str, Any]] = (), users: Sequence[Mapping[str, Any]] = (),
                   catalog_entries: Sequence[Mapping[str, Any]] = (), roles: Sequence[str] = (),
                   costs: Sequence[Mapping[str, Any]] = (), procurement: Sequence[Mapping[str, Any]] = (),
                   parent_real_id: str | None = None,
                   parent_record: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """The live record this draft item should reuse, if there is one.

    Onboarding the same documents twice, or onboarding a project that was partly
    entered by hand, must not double everything up.
    """
    projects = projects or {}
    name = _fold(fields.get("name"))
    if kind == "project":
        code = _fold(fields.get("project_code"))
        for project in projects.values():
            if code and _fold(project.get("project_code")) == code:
                return {"id": project["id"], "label": _text(project.get("name")), "on": "project code"}
        for project in projects.values():
            if name and _fold(project.get("name")) == name:
                return {"id": project["id"], "label": _text(project.get("name")), "on": "name"}
        return None
    if kind == "task":
        for task in tasks:
            if _fold(task.get("name")) == name and (task.get("parent_id") or None) == (parent_real_id or None):
                return {"id": task["id"], "label": _text(task.get("name")), "on": "name and parent"}
        return None
    if kind == "user":
        email = _fold(fields.get("email"))
        for user in users:
            if email and _fold(user.get("email")) == email:
                return {"id": user["id"], "label": _text(user.get("email")), "on": "email"}
        return None
    if kind in MGMT_KEYS:
        for entry in catalog_entries:
            if _fold(entry.get("name")) == name:
                return {"id": _text(entry.get("id")), "label": _text(entry.get("name")), "on": "name"}
        return None
    if kind == "role_type":
        # A document may still use a built-in's former name ("Super Admin").
        wanted = _fold(canonical_role(fields.get("name")))
        for role in roles:
            if _fold(role) in (name, wanted):
                return {"id": _text(role), "label": _text(role), "on": "name"}
        return None
    if kind == "project_cost":
        for entry in costs:
            if _fold(entry.get("name")) == name:
                return {"id": _text(entry.get("id")), "label": _text(entry.get("name")), "on": "name"}
        return None
    if kind == "task_cost":
        # A cost is a figure on the task, not a record of its own: it is already
        # there when the task carries that exact amount.
        if parent_record is not None:
            try:
                current = float(parent_record.get("cost") or 0)
                wanted = float(fields.get("amount") or 0)
            except (TypeError, ValueError):
                return None
            if current and abs(current - wanted) < 0.005:
                return {"id": _text(parent_record.get("id")),
                        "label": f"{current:g}", "on": "the task's existing cost"}
        return None
    if kind == "procurement":
        for entry in procurement:
            if _fold(entry.get("name")) == name:
                return {"id": _text(entry.get("id")), "label": _text(entry.get("name")), "on": "name"}
    return None


def _commit_order(draft: Mapping[str, Any], selection: Iterable[str]) -> list[str]:
    """Selected ids in an order where every dependency precedes its dependant."""
    items = draft.get("items") or {}
    selected = [ref for ref in selection if ref in items]
    ordered: list[str] = []
    for kind in ITEM_KINDS:
        rows = [ref for ref in selected if items[ref].get("kind") == kind]
        if not ENTITIES[kind].self_parent:
            ordered.extend(rows)
            continue
        # Parents before children, however deep the tree goes.
        remaining, placed = list(rows), set()
        while remaining:
            ready = [ref for ref in remaining
                     if not items[ref].get("parent_id") or items[ref]["parent_id"] in placed
                     or items[ref]["parent_id"] not in rows]
            if not ready:  # a cycle validation should have prevented
                ready = remaining
            ordered.extend(ready)
            placed.update(ready)
            remaining = [ref for ref in remaining if ref not in placed]
    return ordered


def build_plan(draft: Mapping[str, Any], *, projects: Mapping[str, Any],
               tasks: Mapping[str, Sequence[Mapping[str, Any]]],
               users: Sequence[Mapping[str, Any]], mgmt: Mapping[str, Any],
               roles: Sequence[Mapping[str, Any]],
               procurement: Mapping[str, Sequence[Mapping[str, Any]]] | None = None) -> dict[str, Any]:
    """What committing this draft would do, without doing any of it.

    Every selected item resolves to "create" or "reuse an existing record", and
    anything that cannot be created is listed with the reason, so the
    confirmation step is the truth rather than an optimistic summary.
    """
    items = draft.get("items") or {}
    procurement = procurement or {}
    selection = [ref for ref in draft.get("selection") or () if ref in items]
    ordered = _commit_order(draft, selection)
    role_catalogue = role_names(roles)

    rows: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    # Draft id -> the live record it will land in, so a child can be matched
    # against the right parent's existing children.
    target: dict[str, str | None] = {}
    live_task: dict[str, Mapping[str, Any] | None] = {}

    for item_id in ordered:
        item = items[item_id]
        kind, fields = item["kind"], item["fields"]
        spec = ENTITIES[kind]
        name = _text(fields.get("name")) or _text(fields.get("amount"))

        missing = [ref for ref in dependencies_of(item) if ref not in selection]
        if missing:
            blocked.append({"id": item_id, "kind": kind, "name": name,
                            "label": spec.label,
                            "reason": f"its {spec.parent_label.lower() or 'parent'} is not selected",
                            "missing": []})
            continue

        status = item_status(draft, item, roles=roles)
        if not status["complete"]:
            blocked.append({
                "id": item_id, "kind": kind, "name": name, "label": spec.label,
                "reason": "; ".join(status["issues"]) or "required fields are missing",
                "missing": status["missing"],
            })
            continue

        parent_draft_id = item.get("parent_ref") or ""
        parent_live = target.get(parent_draft_id)
        existing = match_existing(
            kind, fields,
            projects=projects,
            tasks=tasks.get(parent_live or "", []) if kind == "task" else (),
            users=users,
            catalog_entries=mgmt.get(MGMT_KEYS.get(kind, ""), []) or [],
            roles=role_catalogue,
            costs=(projects.get(parent_live or "", {}) or {}).get("additional_costs", []) or [],
            procurement=procurement.get(parent_live or "", []) if kind == "procurement" else (),
            parent_real_id=target.get(item.get("parent_id") or ""),
            parent_record=live_task.get(parent_draft_id),
        )
        target[item_id] = existing["id"] if existing else None
        if kind == "task":
            live_task[item_id] = next(
                (task for task in tasks.get(parent_live or "", [])
                 if existing and task["id"] == existing["id"]), None)

        row = {
            "id": item_id, "kind": kind, "label": spec.label, "name": name,
            "action": "reuse" if existing else "create",
            "match": existing,
            "stored_in": spec.stored_in,
            "parent": _text((items.get(item.get("parent_ref") or "") or {}).get("fields", {}).get("name")),
            "nested_under": _text((items.get(item.get("parent_id") or "") or {}).get("fields", {}).get("name")),
        }
        rows.append(row)

    creating = {kind: sum(1 for row in rows if row["kind"] == kind and row["action"] == "create")
                for kind in ITEM_KINDS}
    reusing = {kind: sum(1 for row in rows if row["kind"] == kind and row["action"] == "reuse")
               for kind in ITEM_KINDS}
    return {
        "rows": rows, "blocked": blocked,
        "creating": creating, "reusing": reusing,
        "total_creating": sum(creating.values()), "total_reusing": sum(reusing.values()),
        "memberships": sum(
            1 for item_id in selection
            if items[item_id]["kind"] == "user"
            for ref in items[item_id].get("project_refs", []) if ref in selection
        ),
        # Nothing is created while anything selected is incomplete.
        "can_commit": bool(rows) and not blocked,
    }


# ──────────────────────────────────────────────────────────────────────────
# Committing
# ──────────────────────────────────────────────────────────────────────────

class _Transaction:
    """Everything the commit touches, so a failure leaves nothing behind.

    The unit of work: read every store once, mutate the copies, write them all
    at the end. :func:`commit_draft` runs it inside one database transaction
    (``workspace.atomic()``), so a failure rolls back every store and every user
    created on the way. The snapshot restore below is the same guarantee for a
    workspace without transactions.
    """

    def __init__(self, workspace: Any, registry: Any) -> None:
        self.workspace = workspace
        self.registry = registry
        self.projects = workspace.load_projects()
        self.tasks = workspace.load_tasks()
        self.mgmt = workspace.load_mgmt()
        self.roles = workspace.load_roles()
        self.procurement = workspace.load_procurement()
        self.created_user_ids: list[str] = []
        self._before = {
            "projects": copy.deepcopy(self.projects),
            "tasks": copy.deepcopy(self.tasks),
            "mgmt": copy.deepcopy(self.mgmt),
            "roles": copy.deepcopy(self.roles),
            "procurement": copy.deepcopy(self.procurement),
        }

    def commit(self) -> None:
        self.workspace.save_mgmt(self.mgmt)
        self.workspace.save_roles(self.roles)
        self.workspace.save_projects(self.projects)
        self.workspace.save_tasks(self.tasks)
        self.workspace.save_procurement(self.procurement)

    def rollback(self) -> None:
        # Inside the commit's transaction this is undone with everything else;
        # it matters only for a workspace without transactions, where nothing
        # was written unless commit() ran -- restoring always keeps the
        # guarantee unconditional.
        self.workspace.save_projects(self._before["projects"])
        self.workspace.save_tasks(self._before["tasks"])
        self.workspace.save_mgmt(self._before["mgmt"])
        self.workspace.save_roles(self._before["roles"])
        self.workspace.save_procurement(self._before["procurement"])
        for user_id in self.created_user_ids:
            try:
                self.registry.delete_user(user_id)
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def commit_draft(draft: dict[str, Any], *, workspace: Any, **kwargs: Any) -> dict[str, Any]:
    """Create the selected draft items for real, in one transaction.

    See :func:`_commit_draft`. With a database-backed workspace the whole commit
    is one transaction: an exception anywhere rolls back every record and every
    user it created.
    """
    atomic = getattr(workspace, "atomic", None)
    if atomic is None:
        return _commit_draft(draft, workspace=workspace, **kwargs)
    with atomic():
        return _commit_draft(draft, workspace=workspace, **kwargs)


def _bind_people(work: Any, real_id: Mapping[str, str], items: Mapping[str, Any],
                 ordered: Sequence[str], users: Sequence[Mapping[str, Any]]) -> list[str]:
    """Turn the manager and assignee names of new records into user ids.

    A name that matches no user, or several, is cleared rather than stored as
    text that looks like a person; the returned notes say which, so the
    manager can be chosen on the project and the task reassigned.
    """
    notes: list[str] = []
    created = {real_id[ref] for ref in ordered if ref in real_id}
    for project_id, project in list(work.projects.items()):
        if project_id not in created or project.get("manager_id"):
            continue
        named = _text(project.get("manager"))
        if not named:
            continue
        user = resolve_user(users, name=named)
        if user:
            project["manager_id"], project["manager"] = user["id"], user.get("name") or user.get("email")
        else:
            project["manager"] = ""
            notes.append(f"{project.get('name')}: the manager {named!r} is not a user in this "
                         "account, so no manager was set. Choose one on the project.")
        work.projects[project_id] = project
    for project_id, tasks in work.tasks.items():
        project = work.projects.get(project_id)
        if project is None:
            continue
        members = list(project.get("members", []) or [])
        present = {member_id(entry) for entry in members} | {_text(project.get("manager_id"))}
        for task in tasks:
            if task.get("id") not in created or task.get("assignee_id") or not _text(task.get("assignee")):
                continue
            named = _text(task.get("assignee"))
            user = resolve_user(users, name=named)
            if user is None:
                task["assignee"] = ""
                notes.append(f"{task.get('name')}: the assignee {named!r} is not a user in this "
                             "account, so the task was left unassigned.")
                continue
            task["assignee_id"], task["assignee"] = user["id"], user.get("name") or user.get("email")
            if user["id"] not in present:
                members.append({"user_id": user["id"], "project_role": "", "added_at": _now()})
                present.add(user["id"])
        project["members"] = members
        work.projects[project_id] = project
    return notes


def _link_draft_documents(workspace: Any, draft: Mapping[str, Any], items: Mapping[str, Any],
                          real_id: Mapping[str, str]) -> int:
    """Link each document the draft was built from to the project it describes.

    A document belongs to every project that one of its items belongs to: a
    project it named, or the project above a task, cost or procurement line it
    produced, or a project a person it listed is on. When the draft holds one
    project, every attached document is that project's. Only documents attached
    to this draft are ever linked. Returns the number of new links.
    """
    projects = [ref for ref, item in items.items() if item.get("kind") == "project" and ref in real_id]
    if not projects:
        return 0
    attached = {_text(d.get("doc_id")) for d in draft.get("documents", []) or [] if d.get("doc_id")}

    def owning_projects(item: Mapping[str, Any]) -> set[str]:
        if item.get("kind") == "project":
            return {item["id"]}
        if item.get("kind") == "user":
            return {ref for ref in item.get("project_refs", []) or [] if ref in projects}
        seen: set[str] = set()
        cursor = item
        while cursor and cursor.get("parent_ref") and cursor["parent_ref"] not in seen:
            seen.add(cursor["parent_ref"])
            cursor = items.get(cursor["parent_ref"])
            if cursor and cursor.get("kind") == "project":
                return {cursor["id"]}
        return set()

    wanted: dict[str, set[str]] = {ref: set() for ref in projects}
    for item in items.values():
        doc_id = _text((item.get("source") or {}).get("doc_id"))
        if doc_id in attached:
            for ref in owning_projects(item):
                wanted.setdefault(ref, set()).add(doc_id)
    if len(projects) == 1:
        wanted[projects[0]] |= attached

    metadata = workspace.load_metadata()
    documents = metadata.get("documents", {})
    linked = 0
    for ref, doc_ids in wanted.items():
        for doc_id in doc_ids:
            if doc_id in documents and link_document(documents[doc_id], real_id[ref]):
                linked += 1
    if linked:
        workspace.save_metadata(metadata)
    return linked


def _commit_draft(draft: dict[str, Any], *, workspace: Any, registry: Any,
                 account_id: str, make_project: Callable[[Mapping[str, Any]], dict[str, Any]],
                 make_task: Callable[[Mapping[str, Any], str], dict[str, Any]],
                 catalog_entry: Callable[[Mapping[str, Any], str], dict[str, Any]],
                 make_role: Callable[[Mapping[str, Any]], dict[str, Any]],
                 make_procurement: Callable[[Mapping[str, Any], str], dict[str, Any]],
                 allow_roles: bool = True) -> dict[str, Any]:
    """Create the selected draft items for real.

    The record builders are passed in rather than imported so this runs through
    exactly the same constructors the ordinary create routes use. An onboarded
    project is therefore indistinguishable from one typed in by hand.

    Order follows :data:`ITEM_KINDS`: catalogues, then projects and people, then
    tasks parent-first, then the costs and procurement that hang off them. The
    whole thing is one unit of work -- any exception restores every store and
    removes any user that had already been created.
    """
    items = draft.get("items") or {}
    selection = [ref for ref in draft.get("selection") or () if ref in items]
    blocked = {row["id"] for row in draft.get("_plan_blocked", ())}
    ordered = [ref for ref in _commit_order(draft, selection) if ref not in blocked]

    work = _Transaction(workspace, registry)
    account_users = list(registry.users_for_account(account_id)) if registry else []

    real_id: dict[str, str] = {}
    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    credentials: list[dict[str, str]] = []
    project_members: dict[str, list[str]] = {}
    member_roles: dict[str, str] = {}

    def note(bucket: list[dict[str, Any]], item: Mapping[str, Any], target: str, extra: str = "") -> None:
        bucket.append({
            "id": item["id"], "kind": item["kind"], "label": kind_label(item["kind"]),
            "name": _text(item["fields"].get("name")) or _text(item["fields"].get("amount")),
            "target_id": target, "detail": extra,
        })

    def live_parent(item: Mapping[str, Any]) -> str | None:
        return real_id.get(item.get("parent_ref") or "")

    try:
        for item_id in ordered:
            item = items[item_id]
            kind, fields = item["kind"], item["fields"]
            spec = ENTITIES[kind]
            name = _text(fields.get("name"))

            unmet = [ref for ref in dependencies_of(item) if ref in items and ref not in real_id]
            if unmet:
                skipped.append({"id": item_id, "kind": kind, "name": name,
                                "reason": f"its {spec.parent_label.lower() or 'parent'} was not created"})
                continue

            if kind in MGMT_KEYS:
                key = MGMT_KEYS[kind]
                entries = list(work.mgmt.get(key, []) or [])
                match = match_existing(kind, fields, catalog_entries=entries)
                if match:
                    real_id[item_id] = match["id"]
                    note(reused, item, match["id"])
                    continue
                if kind in ("task_type", "project_type"):
                    entry = catalog_entry(fields, "ta" if kind == "task_type" else "pr")
                else:
                    # Mirrors the shape /api/trades and /api/vendors build.
                    entry = {"id": f"{'tr' if kind == 'trade' else 'v'}-{uuid.uuid4().hex[:8]}",
                             "name": name,
                             "description": _text(fields.get("description")) or "-",
                             "status": _text(fields.get("status")) or "Active"}
                    if kind == "vendor":
                        entry.update({
                            "vendorType": _text(fields.get("vendorType")) or "Material Supplier",
                            "trade": _text(fields.get("trade")),
                            "activeProjects": 0,
                        })
                        entry.pop("description", None)
                entries.append(entry)
                work.mgmt[key] = entries
                real_id[item_id] = entry["id"]
                note(created, item, entry["id"])

            elif kind == "role_type":
                if not allow_roles:
                    skipped.append({"id": item_id, "kind": kind, "name": name,
                                    "reason": "only a Head (Super Admin) can create roles"})
                    continue
                match = match_existing(kind, fields, roles=role_names(work.roles))
                if match:
                    real_id[item_id] = match["id"]
                    note(reused, item, match["id"])
                    continue
                role = make_role(fields)
                work.roles.append(role)
                real_id[item_id] = role["id"]
                note(created, item, role["id"],
                     f"{len(role.get('permissions') or ())} permission(s) proposed")

            elif kind == "project":
                match = match_existing(kind, fields, projects=work.projects)
                if match:
                    real_id[item_id] = match["id"]
                    note(reused, item, match["id"], f"matched on {match['on']}")
                    continue
                project = make_project(fields)
                if _text(fields.get("baseline_cost")):
                    # Not part of the constructor; the Cost tab sets it after.
                    project["baseline_cost"] = fields["baseline_cost"]
                work.projects[project["id"]] = project
                work.tasks.setdefault(project["id"], [])
                real_id[item_id] = project["id"]
                note(created, item, project["id"])

            elif kind == "task":
                project_id = live_parent(item)
                if not project_id:
                    skipped.append({"id": item_id, "kind": kind, "name": name,
                                    "reason": "its project was not created"})
                    continue
                project_tasks = work.tasks.setdefault(project_id, [])
                parent_real = real_id.get(item.get("parent_id") or "") or None
                match = match_existing(kind, fields, tasks=project_tasks, parent_real_id=parent_real)
                if match:
                    real_id[item_id] = match["id"]
                    note(reused, item, match["id"])
                    continue
                task = make_task({**fields, "parent_id": parent_real or ""}, project_id)
                project_tasks.append(task)
                real_id[item_id] = task["id"]
                note(created, item, task["id"])

            elif kind == "project_cost":
                project_id = live_parent(item)
                project = work.projects.get(project_id or "")
                if not project:
                    skipped.append({"id": item_id, "kind": kind, "name": name,
                                    "reason": "its project was not created"})
                    continue
                costs = list(project.get("additional_costs", []) or [])
                match = match_existing(kind, fields, costs=costs)
                if match:
                    real_id[item_id] = match["id"]
                    note(reused, item, match["id"])
                    continue
                # The shape /api/projects/{id}/costs builds.
                entry = {
                    "id": uuid.uuid4().hex[:12],
                    "name": name,
                    "details": _text(fields.get("details")),
                    "amount": fields.get("amount"),
                    "created_at": _now(), "updated_at": _now(),
                }
                costs.append(entry)
                project["additional_costs"] = costs
                work.projects[project_id] = project
                real_id[item_id] = entry["id"]
                note(created, item, entry["id"])

            elif kind == "task_cost":
                task_draft_id = item.get("parent_ref") or ""
                task_id = real_id.get(task_draft_id)
                owning_project = real_id.get((items.get(task_draft_id) or {}).get("parent_ref") or "")
                task = next((row for row in work.tasks.get(owning_project or "", [])
                             if row["id"] == task_id), None)
                if task is None:
                    skipped.append({"id": item_id, "kind": kind, "name": name,
                                    "reason": "its task was not created"})
                    continue
                amount = fields.get("amount")
                if match_existing(kind, fields, parent_record=task):
                    real_id[item_id] = task["id"]
                    note(reused, item, task["id"], "the task already carries this figure")
                    continue
                task["cost"] = amount
                task["updated_at"] = _now()
                real_id[item_id] = task["id"]
                note(created, item, task["id"], f"cost set on {_text(task.get('name'))}")

            elif kind == "procurement":
                project_id = live_parent(item)
                if not project_id:
                    skipped.append({"id": item_id, "kind": kind, "name": name,
                                    "reason": "its project was not created"})
                    continue
                lines = work.procurement.setdefault(project_id, [])
                match = match_existing(kind, fields, procurement=lines)
                if match:
                    real_id[item_id] = match["id"]
                    note(reused, item, match["id"])
                    continue
                entry = make_procurement(fields, project_id)
                lines.append(entry)
                real_id[item_id] = entry["id"]
                note(created, item, entry["id"])

            elif kind == "user":
                email = _text(fields.get("email"))
                match = match_existing(kind, fields, users=account_users)
                if match:
                    real_id[item_id] = match["id"]
                    note(reused, item, match["id"], "matched on email")
                else:
                    # A role the documents named but this account does not have
                    # would resolve to no permissions at all, so it is dropped
                    # and reported rather than stored as a dangling label.
                    known = {_fold(role): role for role in role_names(work.roles)}
                    role = known.get(_fold(fields.get("role")), "")
                    password = temporary_password()
                    user = registry.create_user(
                        account_id=account_id, name=name, email=email,
                        password=password, role=role,
                        phone=fields.get("phone", ""), address=fields.get("address", ""),
                        department=fields.get("department", ""),
                        designation=fields.get("designation", ""),
                        company=fields.get("company", ""),
                        time_zone=fields.get("time_zone", "") or "UTC",
                        status=fields.get("status", "") or "Active",
                    )
                    work.created_user_ids.append(user["id"])
                    account_users.append(user)
                    real_id[item_id] = user["id"]
                    credentials.append({"name": name, "email": email, "password": password})
                    note(created, item, user["id"],
                         f"role: {role}" if role else "no role yet — assign one on the Users page")

                member_roles[real_id[item_id]] = _text(fields.get("project_role"))
                for ref in item.get("project_refs", []):
                    project_id = real_id.get(ref)
                    if project_id:
                        project_members.setdefault(project_id, []).append(real_id[item_id])

        # Memberships last: both sides of every pair now exist.
        memberships = 0
        for project_id, user_ids in project_members.items():
            project = work.projects.get(project_id)
            if not project:
                continue
            members = list(project.get("members", []) or [])
            present = {entry.get("user_id") if isinstance(entry, dict) else entry for entry in members}
            for user_id in user_ids:
                if user_id in present:
                    continue
                members.append({
                    "user_id": user_id,
                    # What the documents called them on this project, if anything.
                    "project_role": _text(member_roles.get(user_id)),
                    "added_at": _now(),
                })
                present.add(user_id)
                memberships += 1
            project["members"] = members
            work.projects[project_id] = project

        # People last of all. A manager and an assignee are users, so the names
        # the documents gave are matched to the account's users -- including the
        # ones just created -- and anyone given a task joins its project.
        people_notes = _bind_people(work, real_id, items, ordered, account_users)

        work.commit()
        # The documents the project was onboarded from are its documents: link
        # them, so its Project Documents list and project-scoped chat have them.
        documents_linked = _link_draft_documents(workspace, draft, items, real_id)
    except Exception:
        work.rollback()
        raise

    result = {
        "created": created, "reused": reused, "skipped": skipped,
        "memberships": memberships, "people_notes": people_notes,
        "documents_linked": documents_linked,
        "counts": {kind: sum(1 for row in created if row["kind"] == kind) for kind in ITEM_KINDS},
        "total_created": len(created), "total_reused": len(reused),
        "project_ids": [real_id[ref] for ref in ordered
                        if items[ref]["kind"] == "project" and ref in real_id],
        "committed_at": _now(),
    }
    draft["status"] = "committed"
    draft["commit"] = dict(result)
    draft["pending"] = None
    draft["updated_at"] = _now()
    # Credentials are handed back once and never stored on the draft.
    return {**result, "credentials": credentials}


# ──────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────

class DraftRequest(BaseModel):
    name: str = ""


class AnalyzeRequest(BaseModel):
    instructions: str = ""
    doc_ids: list[str] = Field(default_factory=list)


class ItemRequest(BaseModel):
    kind: str
    fields: dict[str, Any] = Field(default_factory=dict)
    parent_ref: str | None = None
    parent_id: str | None = None
    project_refs: list[str] = Field(default_factory=list)


class ItemPatch(BaseModel):
    fields: dict[str, Any] | None = None
    parent_ref: str | None = None
    parent_id: str | None = None
    project_refs: list[str] | None = None


class SelectionRequest(BaseModel):
    selection: list[str] = Field(default_factory=list)


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class CommitRequest(BaseModel):
    confirm: bool = False


def register_project_onboarding_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register the Onboarding routes on the notebook app.

    Everything here is administrator work, and everything before ``/commit`` is
    read-only with respect to the live stores: drafts are the account's own
    records (the ``onboarding_drafts`` table).
    """
    required = ("app", "require_account", "ingest_document", "vl_generate", "_make_project")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Project onboarding integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]
    ingest_document = namespace["ingest_document"]
    vl_generate = namespace["vl_generate"]
    registry = namespace.get("ACCOUNT_REGISTRY")
    make_project = namespace["_make_project"]

    try:  # the notebook puts this directory on sys.path
        from tasks import make_task as _make_task
        from company_settings import catalog_entry as _catalog_entry
        from user_roles import make_role as _make_role
        from project_management import make_procurement_item as _make_procurement
    except ModuleNotFoundError:  # imported as backend.project_onboarding
        from backend.tasks import make_task as _make_task
        from backend.company_settings import catalog_entry as _catalog_entry
        from backend.user_roles import make_role as _make_role
        from backend.project_management import make_procurement_item as _make_procurement

    # Prefer the notebook's own objects where it has them, so onboarding can
    # never drift from the constructors the ordinary create routes use.
    def _resolve(name: str, fallback: Callable[..., Any]) -> Callable[..., Any]:
        candidate = namespace.get(name)
        return candidate if callable(candidate) else fallback

    make_task = _resolve("make_task", _make_task)
    catalog_entry = _resolve("catalog_entry", _catalog_entry)
    make_role = _resolve("make_role", _make_role)
    make_procurement = _resolve("make_procurement_item", _make_procurement)

    # The schema is checked against those constructors now rather than the first
    # time somebody tries to onboard something.
    schema_notes = reconcile(
        {
            "project": lambda: make_project({}),
            "task": lambda: make_task({}, "reconcile"),
            "task_type": lambda: catalog_entry({}, "ta"),
            "project_type": lambda: catalog_entry({}, "pr"),
            "role_type": lambda: make_role({}),
            "procurement": lambda: make_procurement({}, "reconcile"),
        },
        server_owned={
            # currency is not here: it is a field the person chooses, and the
            # project constructor stores it like any other.
            "project": ("id", "archived", "created_at", "updated_at", "members",
                        "additional_costs"),
            "task": ("id", "project_id", "created_at", "updated_at", "parent_id", "cost"),
            "task_type": ("id", "created_at"), "project_type": ("id", "created_at"),
            "role_type": ("id", "created_at", "updated_at", "upgrades"),
            "procurement": ("id", "project_id", "created_at", "updated_at"),
        },
    )

    async def compose(prompt: str, max_tokens: int = MAX_ANALYSIS_TOKENS) -> str:
        import asyncio

        messages = [
            {"role": "system", "content": (
                "You are BuildMarshalAI's project onboarding analyst. You read "
                "construction project documents and administrator instructions and "
                "return strict JSON. You never invent a value the source did not give "
                "you; leaving a field out is always better than guessing it."
            )},
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: vl_generate(messages, max_new_tokens=max_tokens)
        )

    # -- storage ---------------------------------------------------------

    def load_drafts(workspace: Any) -> dict[str, Any]:
        data = workspace.load_onboarding()
        return data if isinstance(data, dict) else {}

    def draft_or_404(workspace: Any, draft_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        drafts = load_drafts(workspace)
        draft = drafts.get(draft_id)
        if not draft:
            raise HTTPException(404, detail="Onboarding draft not found")
        return drafts, draft

    def roles_of(context: Any) -> list[dict[str, Any]]:
        return context.workspace.load_roles()

    def store(context: Any, drafts: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
        drafts[draft["id"]] = draft
        context.workspace.save_onboarding(drafts)
        return draft_view(draft, roles=roles_of(context))

    def admin_only(context: Any) -> None:
        if not context.is_admin:
            raise HTTPException(403, detail="Onboarding a project is an administrator action")

    def live_choices(context: Any) -> dict[str, list[dict[str, str]]]:
        """Every record a reference field could point at, for prompts and forms."""
        wanted = {spec.reference for entity_spec in ENTITIES.values()
                  for spec in entity_spec.fields if spec.reference}
        wanted.update(entity_spec.parent for entity_spec in ENTITIES.values() if entity_spec.parent)
        return {
            kind: reference_choices(kind, workspace=context.workspace, registry=registry,
                                    account_id=context.account_id)
            for kind in sorted(wanted)
        }

    # -- schema ----------------------------------------------------------

    @app.get("/api/onboarding/schema")
    async def read_schema(context=Depends(require_account)) -> dict[str, Any]:
        """The entity definitions the draft editor renders its forms from.

        Served rather than duplicated in the client, so the mandatory fields the
        UI enforces are the ones the server enforces.
        """
        admin_only(context)
        return {
            "entities": catalog(),
            "choices": live_choices(context),
            "permissions": permission_catalogue_rows(),
            "notes": schema_notes,
        }

    # -- drafts ----------------------------------------------------------

    @app.get("/api/onboarding/drafts")
    async def list_drafts(context=Depends(require_account)) -> dict[str, Any]:
        admin_only(context)
        drafts = load_drafts(context.workspace)
        roles = roles_of(context)
        rows = sorted(drafts.values(), key=lambda d: str(d.get("created_at", "")), reverse=True)
        return {
            "drafts": [
                {
                    **{key: value for key, value in draft.items() if key != "items"},
                    "summary": draft_summary(draft, roles=roles),
                    "document_count": len(draft.get("documents", [])),
                }
                for draft in rows
            ],
            "total": len(rows),
        }

    @app.post("/api/onboarding/drafts", status_code=201)
    async def create_draft(body: DraftRequest, context=Depends(require_account)) -> dict[str, Any]:
        admin_only(context)
        drafts = load_drafts(context.workspace)
        return store(context, drafts, new_draft(body.name, context.user))

    @app.get("/api/onboarding/drafts/{draft_id}")
    async def read_draft(draft_id: str, context=Depends(require_account)) -> dict[str, Any]:
        admin_only(context)
        _, draft = draft_or_404(context.workspace, draft_id)
        return draft_view(draft, roles=roles_of(context))

    @app.delete("/api/onboarding/drafts/{draft_id}")
    async def remove_draft(draft_id: str, context=Depends(require_account)) -> dict[str, Any]:
        admin_only(context)
        drafts, _ = draft_or_404(context.workspace, draft_id)
        drafts.pop(draft_id, None)
        context.workspace.save_onboarding(drafts)
        return {"message": "Draft deleted", "id": draft_id}

    # -- documents -------------------------------------------------------

    @app.post("/api/onboarding/drafts/{draft_id}/documents")
    async def upload_draft_document(
        draft_id: str, file: UploadFile = File(...), doc_id: str = Form(None),
        context=Depends(require_account),
    ) -> dict[str, Any]:
        """Index a document into the account, and attach it to this draft.

        Uses the ordinary ingestion pipeline, so every format the rest of the
        app accepts is accepted here too and the pages stay searchable in chat.
        """
        admin_only(context)
        workspace = context.workspace
        drafts, draft = draft_or_404(workspace, draft_id)
        safe_name = Path(file.filename or "document").name
        extension = Path(safe_name).suffix.lower()
        if not extension:
            raise HTTPException(400, detail="That file has no extension, so it cannot be indexed")
        clean_id = re.sub(r"[^A-Za-z0-9._-]+", "", _text(doc_id))[:64].strip("._-") or uuid.uuid4().hex[:12]
        save_path = Path(workspace.docs_dir) / f"{clean_id}{extension}"
        limit = int(namespace.get("MAX_UPLOAD_BYTES") or 100 * 1024 * 1024)
        written = 0
        try:
            with save_path.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    written += len(chunk)
                    if written > limit:
                        destination.close()
                        save_path.unlink(missing_ok=True)
                        raise HTTPException(
                            413, detail=f"File exceeds the {limit // (1024 * 1024)} MB upload limit")
                    destination.write(chunk)
        except HTTPException:
            raise
        except Exception as error:
            save_path.unlink(missing_ok=True)
            raise HTTPException(500, detail=f"Could not save file: {error}") from None

        meta = ingest_document(save_path, clean_id, workspace, display_name=safe_name,
                               origin="onboarding")
        # Bytes already indexed come back as the existing document.
        clean_id = str(meta.get("id") or clean_id)
        record = {
            "doc_id": clean_id, "name": safe_name,
            "pages": int(meta.get("page_count") or 0),
            "analyzed": False, "added_at": _now(),
        }
        draft["documents"] = [d for d in draft.get("documents", []) if d.get("doc_id") != clean_id]
        draft["documents"].append(record)
        draft["updated_at"] = _now()
        store(context, drafts, draft)
        return record

    @app.delete("/api/onboarding/drafts/{draft_id}/documents/{doc_id}")
    async def detach_draft_document(draft_id: str, doc_id: str,
                                    context=Depends(require_account)) -> dict[str, Any]:
        admin_only(context)
        drafts, draft = draft_or_404(context.workspace, draft_id)
        remaining = [d for d in draft.get("documents", []) if d.get("doc_id") != doc_id]
        if len(remaining) == len(draft.get("documents", [])):
            raise HTTPException(404, detail="That document is not attached to this draft")
        draft["documents"] = remaining
        draft["updated_at"] = _now()
        return store(context, drafts, draft)

    # -- analysis --------------------------------------------------------

    @app.post("/api/onboarding/drafts/{draft_id}/analyze")
    async def analyze_draft(draft_id: str, body: AnalyzeRequest,
                            context=Depends(require_account)) -> dict[str, Any]:
        """Read the attached documents into draft items.

        Writes only to the draft. Re-running is safe: an entity already in the
        draft is filled in rather than duplicated.
        """
        admin_only(context)
        workspace = context.workspace
        drafts, draft = draft_or_404(workspace, draft_id)
        attached = draft.get("documents", [])
        wanted = set(body.doc_ids) or {d["doc_id"] for d in attached}
        targets = [d for d in attached if d["doc_id"] in wanted]
        if not targets:
            raise HTTPException(422, detail="Upload at least one document before analyzing")

        stored_docs = workspace.load_metadata().get("documents", {})
        choices = live_choices(context)
        warnings: list[str] = []
        added_total = 0
        for record in targets:
            document = stored_docs.get(record["doc_id"])
            if not document:
                warnings.append(f"{record['name']}: the indexed copy is missing")
                continue
            for pass_spec in EXTRACTION_PASSES:
                prompt = build_extraction_prompt(pass_spec, document, body.instructions, choices)
                try:
                    raw = await compose(prompt)
                except Exception as error:  # pragma: no cover - model transport
                    warnings.append(f"{record['name']}: {str(error)[:200]}")
                    continue
                extracted = parse_extraction(raw)
                if not any(extracted.values()):
                    warnings.append(f"{record['name']}: nothing could be extracted from this document")
                    continue
                added_total += merge_extraction(draft, extracted, {
                    "doc_id": record["doc_id"], "doc_name": record["name"], "page": 1,
                })["total_added"]
            record["analyzed"] = True
            record["analyzed_at"] = _now()

        # Everything extracted starts selected; the administrator prunes.
        set_selection(draft, list(draft.get("items", {})))
        draft["analysis"] = {
            "ran_at": _now(), "documents": len(targets), "added": added_total,
            "warnings": warnings, "instructions": _text(body.instructions),
        }
        draft["updated_at"] = _now()
        return store(context, drafts, draft)

    # -- editing ---------------------------------------------------------

    @app.post("/api/onboarding/drafts/{draft_id}/items", status_code=201)
    async def create_draft_item(draft_id: str, body: ItemRequest,
                                context=Depends(require_account)) -> dict[str, Any]:
        admin_only(context)
        drafts, draft = draft_or_404(context.workspace, draft_id)
        item = add_item(draft, body.kind, body.model_dump())
        return {**store(context, drafts, draft), "item_id": item["id"]}

    @app.patch("/api/onboarding/drafts/{draft_id}/items/{item_id}")
    async def patch_draft_item(draft_id: str, item_id: str, body: ItemPatch,
                               context=Depends(require_account)) -> dict[str, Any]:
        admin_only(context)
        drafts, draft = draft_or_404(context.workspace, draft_id)
        update_item(draft, item_id, body.model_dump(exclude_none=True))
        _update_pending(draft, [item_id])
        return store(context, drafts, draft)

    @app.delete("/api/onboarding/drafts/{draft_id}/items/{item_id}")
    async def remove_draft_item(draft_id: str, item_id: str,
                                context=Depends(require_account)) -> dict[str, Any]:
        admin_only(context)
        drafts, draft = draft_or_404(context.workspace, draft_id)
        removed = delete_item(draft, item_id)
        return {**store(context, drafts, draft), "removed": removed}

    @app.put("/api/onboarding/drafts/{draft_id}/selection")
    async def put_selection(draft_id: str, body: SelectionRequest,
                            context=Depends(require_account)) -> dict[str, Any]:
        """Replace the selection, closed over the hierarchy.

        Selecting a subtask pulls in its parent chain and its project, and a
        cost pulls in what it is a cost of; the response says what was added so
        the page can explain itself.
        """
        admin_only(context)
        drafts, draft = draft_or_404(context.workspace, draft_id)
        resolved = set_selection(draft, body.selection)
        return {**store(context, drafts, draft),
                "added_parents": resolved["added_parents"], "unknown": resolved["unknown"]}

    @app.post("/api/onboarding/drafts/{draft_id}/command")
    async def run_command(draft_id: str, body: CommandRequest,
                          context=Depends(require_account)) -> dict[str, Any]:
        """Create or edit draft records from a sentence, typed or dictated.

        The model decides what the administrator meant; the schema decides what
        is still missing and what the valid answers are, and that part of the
        reply is composed here rather than by the model.
        """
        admin_only(context)
        drafts, draft = draft_or_404(context.workspace, draft_id)
        choices = live_choices(context)
        try:
            raw = await compose(build_command_prompt(draft, body.text, choices), MAX_COMMAND_TOKENS)
        except Exception as error:  # pragma: no cover - model transport
            raise HTTPException(503, detail=f"Marshal could not be reached: {str(error)[:200]}") from None
        interpreted = parse_command_response(raw)
        outcome = apply_operations(draft, interpreted["operations"])

        question = pending_question(draft, choices)
        if outcome["applied"]:
            headline = interpreted["reply"] or _describe_applied(outcome["applied"])
        elif outcome["skipped"]:
            headline = interpreted["reply"] or "I could not do that: " + \
                "; ".join(row["reason"] for row in outcome["skipped"][:3])
        else:
            headline = interpreted["reply"] or (
                "I could not tell what to change. Try naming the record and what to set."
            )
        reply = f"{headline}\n\n{question}" if question else headline
        return {**store(context, drafts, draft), **outcome,
                "reply": reply, "question": question}

    # -- confirm and commit ----------------------------------------------

    def plan_for(context: Any, draft: Mapping[str, Any]) -> dict[str, Any]:
        workspace = context.workspace
        return build_plan(
            draft,
            projects=workspace.load_projects(),
            tasks=workspace.load_tasks(),
            users=list(registry.users_for_account(context.account_id)) if registry else [],
            mgmt=workspace.load_mgmt(),
            roles=workspace.load_roles(),
            procurement=workspace.load_procurement(),
        )

    @app.get("/api/onboarding/drafts/{draft_id}/plan")
    async def read_plan(draft_id: str, context=Depends(require_account)) -> dict[str, Any]:
        """The confirmation summary: exactly what committing would create."""
        admin_only(context)
        _, draft = draft_or_404(context.workspace, draft_id)
        return {**plan_for(context, draft), "can_create_roles": context.is_super_admin}

    @app.post("/api/onboarding/drafts/{draft_id}/commit")
    async def commit(draft_id: str, body: CommitRequest,
                     context=Depends(require_account)) -> dict[str, Any]:
        """Create the selected items for real. Needs an explicit confirmation."""
        admin_only(context)
        drafts, draft = draft_or_404(context.workspace, draft_id)
        if draft.get("status") == "committed":
            raise HTTPException(409, detail="This draft has already been onboarded")
        if not draft.get("selection"):
            raise HTTPException(422, detail="Select at least one item to onboard")

        # Re-validated on the server, against live data, at the moment of the
        # commit -- not against whatever the client last saw.
        plan = plan_for(context, draft)
        if not body.confirm:
            return {"confirmation_required": True, **plan,
                    "can_create_roles": context.is_super_admin}
        if plan["blocked"]:
            names = ", ".join(f"{row['label']} \"{row['name']}\"" for row in plan["blocked"][:5])
            raise HTTPException(
                422,
                detail=(f"{len(plan['blocked'])} selected item(s) are not ready to onboard: {names}. "
                        "Complete or deselect them first."),
            )

        draft["_plan_blocked"] = plan["blocked"]
        result = commit_draft(
            draft, workspace=context.workspace, registry=registry,
            account_id=context.account_id, make_project=make_project,
            make_task=make_task, catalog_entry=catalog_entry, make_role=make_role,
            make_procurement=make_procurement, allow_roles=context.is_super_admin,
        )
        draft.pop("_plan_blocked", None)
        view = store(context, drafts, draft)
        return {"confirmation_required": False, **result, "draft": view}

    return {"kinds": list(ITEM_KINDS), "passes": [item.key for item in EXTRACTION_PASSES],
            "schema_notes": schema_notes}


def _describe_applied(applied: Sequence[Mapping[str, Any]]) -> str:
    verbs = {"create": "Added", "update": "Updated", "delete": "Removed",
             "move": "Moved", "select": "Selected", "deselect": "Deselected"}
    parts = [f"{verbs.get(row['op'], row['op'])} {row.get('label', '').lower()} "
             f"{row.get('name') or ''}".strip() for row in applied[:4]]
    return "; ".join(parts) + ("." if parts else "")


__all__ = [
    "EXTRACTION_PASSES", "ITEM_KINDS", "MGMT_KEYS", "RESPONSE_KINDS",
    "ExtractionPass", "add_item", "ancestors_of", "apply_item_updates",
    "apply_operations", "build_command_prompt", "build_extraction_prompt",
    "build_plan", "cascade_deselect", "commit_draft", "delete_item",
    "dependencies_of", "descendants_of", "describe_draft_for_model",
    "describe_entities_for_model", "draft_summary", "draft_view", "find_item",
    "item_missing", "item_status", "kind_label",
    "make_item", "match_existing", "merge_extraction", "new_draft",
    "normalise_fields", "parse_command_response", "parse_extraction",
    "pending_question", "register_project_onboarding_routes", "resolve_selection",
    "response_key", "set_selection", "temporary_password", "update_item",
    "validate_item",
]
