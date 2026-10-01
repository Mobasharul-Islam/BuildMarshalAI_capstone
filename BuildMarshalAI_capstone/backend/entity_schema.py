"""What every project entity is, in one place, derived from the code that owns it.

Onboarding, the draft editor, and the assistant that fills a draft in
conversation all need the same three answers about an entity: which fields it
has, which of them it cannot be created without, and what it must hang off.
Answering those separately is how a chatbot ends up inventing a requirement the
application does not have, or missing one it does.

So nothing here is a second opinion:

* **Fields** come from the tuples the owning modules already export --
  ``tasks.TASK_FIELDS``, ``project_management.PROCUREMENT_FIELDS`` -- and, at
  startup, :func:`reconcile` runs each record constructor and refuses to boot if
  this file claims a field the constructor does not accept.  Drift is a crash,
  not a silent divergence.
* **Choices** come from the same constants the routes validate against:
  ``TASK_STATUSES``, ``TASK_PRIORITIES``, ``PROCUREMENT_STATUSES``, the
  permission catalogue.  Choices that name other records -- a task's project, a
  cost's task -- are resolved against live data at request time.
* **Validation** calls the application's own validators.  :func:`validate_entity`
  is a dispatcher onto ``validate_task``, ``validate_role_name``, ``money``,
  ``validate_email`` and friends; it implements no rule of its own.

What this file does declare is which fields are *mandatory*, because the
application states that inside its route handlers (``if not name: raise``) where
nothing can read it.  The test suite closes that gap: every entry in
:data:`REQUIRED` is asserted against the validator or constructor that actually
enforces it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Iterable, Mapping, Sequence

from fastapi import HTTPException

try:  # the notebook puts this directory on sys.path
    from tasks import TASK_FIELDS, TASK_PRIORITIES, TASK_STATUSES, validate_task
    from project_management import (
        PROCUREMENT_FIELDS, PROCUREMENT_STATUSES, as_date, make_procurement_item, money,
    )
    from permissions import PERMISSIONS, PERMISSION_KEYS, clean_permissions, role_names
    from user_roles import validate_role_name
    from company_settings import assert_unique
    from accounts import validate_email
except ModuleNotFoundError:  # imported as backend.entity_schema
    from backend.tasks import TASK_FIELDS, TASK_PRIORITIES, TASK_STATUSES, validate_task
    from backend.project_management import (
        PROCUREMENT_FIELDS, PROCUREMENT_STATUSES, as_date, make_procurement_item, money,
    )
    from backend.permissions import PERMISSIONS, PERMISSION_KEYS, clean_permissions, role_names
    from backend.user_roles import validate_role_name
    from backend.company_settings import assert_unique
    from backend.accounts import validate_email


# ──────────────────────────────────────────────────────────────────────────
# Specs
# ──────────────────────────────────────────────────────────────────────────

#: Field kinds the editor and the assistant both understand.
FIELD_TYPES = (
    "text", "textarea", "number", "money", "date", "datetime",
    "select", "reference", "permissions",
)


@dataclass(frozen=True)
class FieldSpec:
    """One field of one entity."""

    name: str
    label: str
    required: bool = False
    type: str = "text"
    #: A fixed set of values, for ``select``.
    options: tuple[str, ...] = ()
    #: The entity kind this field names, for ``reference``.  Its choices are the
    #: records that actually exist, resolved per request.
    reference: str = ""
    help: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "label": self.label, "required": self.required,
            "type": self.type, "options": list(self.options),
            "reference": self.reference, "help": self.help,
        }


@dataclass(frozen=True)
class EntitySpec:
    """One entity kind: its fields, and what it has to hang off."""

    kind: str
    label: str
    plural: str
    fields: tuple[FieldSpec, ...]
    #: The kind this entity cannot exist without.  A task needs a project; a
    #: task cost needs a task.  Empty for entities that stand alone.
    parent: str = ""
    parent_label: str = ""
    #: An optional same-kind parent, which is how subtasks work.
    self_parent: bool = False
    #: Where a committed record lands, for the confirmation summary.
    stored_in: str = ""
    #: The permission a caller needs to create one.  Administrators hold every
    #: permission, so this only bites if onboarding is opened up later.
    permission: str = ""
    #: Fields applied outside the record constructor, so :func:`reconcile`
    #: knows not to expect them from it.
    applied_after_build: tuple[str, ...] = ()

    @property
    def field_map(self) -> dict[str, FieldSpec]:
        return {spec.name: spec for spec in self.fields}

    @property
    def required_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(spec for spec in self.fields if spec.required)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "label": self.label, "plural": self.plural,
            "parent": self.parent, "parent_label": self.parent_label,
            "self_parent": self.self_parent, "stored_in": self.stored_in,
            "permission": self.permission,
            "fields": [spec.as_dict() for spec in self.fields],
            "required": [spec.name for spec in self.required_fields],
        }


def _labelled(name: str) -> str:
    return name.replace("_", " ").replace("id", "ID").capitalize()


# ──────────────────────────────────────────────────────────────────────────
# The entities
#
# Field order is form order.  ``required`` mirrors what the application refuses
# to create without; the tests prove each one against the real validator.
# ──────────────────────────────────────────────────────────────────────────

#: Project record fields.  ``_make_project`` lives in the notebook and cannot be
#: imported here, so :func:`reconcile` checks this list against it at startup.
PROJECT_STATUSES: tuple[str, ...] = (
    "Active", "Planning", "On Hold", "Completed", "Cancelled",
)

#: The currencies a project may be priced in. The frontend formats each of these,
#: and the lakh/crore ones (BDT, INR, PKR, LKR, NPR) the South Asian way.
PROJECT_CURRENCIES: tuple[str, ...] = (
    "USD", "GBP", "EUR", "JPY", "INR", "ZAR", "BDT", "PKR", "LKR", "NPR",
    "CAD", "AUD", "NZD", "AED", "SAR", "SGD",
)

_PROJECT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("name", "Project name", required=True),
    FieldSpec("project_code", "Project code", required=True,
              help="Unique within this workspace."),
    FieldSpec("type", "Project type", type="reference", reference="project_type"),
    FieldSpec("manager", "Manager"),
    FieldSpec("status", "Status", type="select", options=PROJECT_STATUSES),
    FieldSpec("currency", "Currency", type="select", options=PROJECT_CURRENCIES,
              help="What the project's costs are counted in."),
    FieldSpec("start_date", "Start date", type="date"),
    FieldSpec("end_date", "End date", type="date"),
    FieldSpec("baseline_cost", "Baseline cost", type="money",
              help="The figure the project total is built on."),
    FieldSpec("description", "Description", type="textarea"),
    FieldSpec("address_line1", "Address"),
    FieldSpec("address_line2", "Address line 2"),
    FieldSpec("city", "City"),
    FieldSpec("state", "State"),
    FieldSpec("postal_code", "Postal code"),
    FieldSpec("country", "Country"),
)

#: Task fields, in ``TASK_FIELDS`` order minus the two the draft models as links
#: (``parent_id``) or as a child entity (``cost``).
_TASK_FIELD_SPECS: dict[str, FieldSpec] = {
    "name": FieldSpec("name", "Task name", required=True),
    "task_type": FieldSpec("task_type", "Task type", type="reference", reference="task_type"),
    "trade": FieldSpec("trade", "Trade", type="reference", reference="trade"),
    "assignee": FieldSpec("assignee", "Assignee", type="reference", reference="user"),
    "field_worker": FieldSpec("field_worker", "On-site worker", type="reference", reference="user"),
    "start_time": FieldSpec("start_time", "Start", type="datetime"),
    "end_time": FieldSpec("end_time", "End", type="datetime"),
    "due_date": FieldSpec("due_date", "Due date", type="date"),
    "priority": FieldSpec("priority", "Priority", type="select", options=TASK_PRIORITIES),
    "status": FieldSpec("status", "Status", type="select", options=TASK_STATUSES),
    "delegation": FieldSpec("delegation", "Delegation"),
    "description": FieldSpec("description", "Description", type="textarea"),
    "archived": FieldSpec("archived", "Archived", type="select", options=("No", "Yes")),
}

# Built from TASK_FIELDS so a field added there shows up here automatically.
_TASK_FIELDS: tuple[FieldSpec, ...] = tuple(
    _TASK_FIELD_SPECS.get(name, FieldSpec(name, _labelled(name)))
    for name in TASK_FIELDS
    if name not in ("parent_id", "cost")
)

_PROCUREMENT_FIELD_SPECS: dict[str, FieldSpec] = {
    "name": FieldSpec("name", "Item", required=True),
    "supplier": FieldSpec("supplier", "Supplier", type="reference", reference="vendor"),
    "trade": FieldSpec("trade", "Trade", type="reference", reference="trade"),
    "quantity": FieldSpec("quantity", "Quantity", type="number"),
    "unit_cost": FieldSpec("unit_cost", "Unit cost", type="money"),
    "status": FieldSpec("status", "Status", type="select", options=PROCUREMENT_STATUSES),
    "needed_by": FieldSpec("needed_by", "Needed by", type="date"),
    "ordered_on": FieldSpec("ordered_on", "Ordered on", type="date"),
    "description": FieldSpec("description", "Description", type="textarea"),
    "notes": FieldSpec("notes", "Notes", type="textarea"),
}

_PROCUREMENT_FIELDS: tuple[FieldSpec, ...] = tuple(
    _PROCUREMENT_FIELD_SPECS.get(name, FieldSpec(name, _labelled(name)))
    for name in PROCUREMENT_FIELDS
)

_ACTIVE_INACTIVE = ("Active", "Inactive")

ENTITIES: dict[str, EntitySpec] = {
    "project_type": EntitySpec(
        kind="project_type", label="Project type", plural="Project types",
        stored_in="Company Settings → Project Types", permission="project_type.manage",
        fields=(
            FieldSpec("name", "Project type", required=True, help="Unique in this workspace."),
            FieldSpec("description", "Description"),
            FieldSpec("status", "Status", type="select", options=_ACTIVE_INACTIVE),
        ),
    ),
    "task_type": EntitySpec(
        kind="task_type", label="Task type", plural="Task types",
        stored_in="Company Settings → Task Types", permission="task_type.manage",
        fields=(
            FieldSpec("name", "Task type", required=True, help="Unique in this workspace."),
            FieldSpec("description", "Description"),
            FieldSpec("status", "Status", type="select", options=_ACTIVE_INACTIVE),
        ),
    ),
    "trade": EntitySpec(
        kind="trade", label="Trade", plural="Trades",
        stored_in="Company Settings → Trades", permission="trade.manage",
        fields=(
            FieldSpec("name", "Trade", required=True),
            FieldSpec("description", "Description"),
            FieldSpec("status", "Status", type="select", options=_ACTIVE_INACTIVE),
        ),
    ),
    "vendor": EntitySpec(
        kind="vendor", label="External company", plural="External companies",
        stored_in="Company Settings → External Companies", permission="vendor.manage",
        fields=(
            FieldSpec("name", "Company name", required=True),
            FieldSpec("vendorType", "Type", type="select",
                      options=("Material Supplier", "Subcontractor", "Consultant", "Equipment")),
            FieldSpec("trade", "Trade", type="reference", reference="trade"),
            FieldSpec("status", "Status", type="select", options=_ACTIVE_INACTIVE),
        ),
    ),
    "role_type": EntitySpec(
        kind="role_type", label="Role", plural="Roles",
        stored_in="Company Settings → User Roles",
        fields=(
            FieldSpec("name", "Role name", required=True,
                      help="Cannot be one of the built-in roles."),
            FieldSpec("description", "Description"),
            FieldSpec("permissions", "Permissions", type="permissions",
                      help="What this role is allowed to do."),
        ),
    ),
    "project": EntitySpec(
        kind="project", label="Project", plural="Projects",
        stored_in="Projects", permission="project.create",
        fields=_PROJECT_FIELDS,
        applied_after_build=("baseline_cost",),
    ),
    "user": EntitySpec(
        kind="user", label="User", plural="People",
        stored_in="Company Settings → Users",
        fields=(
            FieldSpec("name", "Full name", required=True),
            FieldSpec("email", "Email", required=True,
                      help="Used to sign in. A first-login password is generated at onboarding."),
            FieldSpec("role", "Role", type="reference", reference="role_type"),
            FieldSpec("project_role", "Role on the project"),
            FieldSpec("department", "Department"),
            FieldSpec("designation", "Designation"),
            FieldSpec("company", "Company"),
            FieldSpec("phone", "Phone"),
            FieldSpec("address", "Address"),
            FieldSpec("time_zone", "Time zone"),
            FieldSpec("status", "Status", type="select", options=_ACTIVE_INACTIVE),
        ),
    ),
    "task": EntitySpec(
        kind="task", label="Task", plural="Tasks",
        parent="project", parent_label="Project", self_parent=True,
        stored_in="the project's Tasks", permission="task.create",
        fields=_TASK_FIELDS,
    ),
    "project_cost": EntitySpec(
        kind="project_cost", label="Project cost", plural="Project costs",
        parent="project", parent_label="Project",
        stored_in="the project's Cost tab", permission="project.cost.additional",
        fields=(
            FieldSpec("name", "Cost name", required=True),
            FieldSpec("amount", "Amount", required=True, type="money"),
            FieldSpec("details", "Details", type="textarea"),
        ),
    ),
    "task_cost": EntitySpec(
        kind="task_cost", label="Task cost", plural="Task costs",
        parent="task", parent_label="Task",
        stored_in="the task's cost, which rolls up into the project total",
        permission="project.cost.task",
        fields=(
            FieldSpec("amount", "Amount", required=True, type="money"),
            FieldSpec("name", "Note", help="Kept on the draft for the audit trail."),
        ),
    ),
    "procurement": EntitySpec(
        kind="procurement", label="Procurement item", plural="Procurement",
        parent="project", parent_label="Project",
        stored_in="the project's Procurement tab", permission="procurement.manage",
        fields=_PROCUREMENT_FIELDS,
    ),
}

#: Creation order: a kind never precedes something it depends on.
ENTITY_ORDER: tuple[str, ...] = (
    "project_type", "task_type", "trade", "vendor", "role_type",
    "project", "user", "task", "project_cost", "task_cost", "procurement",
)

assert set(ENTITY_ORDER) == set(ENTITIES), "ENTITY_ORDER must cover every entity"


def entity(kind: str) -> EntitySpec:
    spec = ENTITIES.get(kind)
    if spec is None:
        raise HTTPException(422, detail=f"\"{kind}\" is not something this workspace holds")
    return spec


def field_names(kind: str) -> tuple[str, ...]:
    return tuple(spec.name for spec in entity(kind).fields)


def catalog() -> list[dict[str, Any]]:
    """Every entity, in creation order, as the client and the assistant read it."""
    return [ENTITIES[kind].as_dict() for kind in ENTITY_ORDER]


# ──────────────────────────────────────────────────────────────────────────
# Completeness and validation
# ──────────────────────────────────────────────────────────────────────────

def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def read_date(value: Any) -> str:
    """A date, however a construction document happened to write it.

    The application's ``as_date`` decides what a stored date *is*; it only
    accepts ISO. Reading "14/03/2027" off a schedule is a parsing job that has
    to happen before the value is offered to it, so the lenient attempt runs
    first and its result is then put through ``as_date`` like any other.
    """
    text = _text(value)
    if not text:
        return ""
    settled = as_date(text)
    if settled:
        return settled
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
    else:
        # Day-first, which is what the documents in use are written in.
        match = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text)
        if not match:
            return ""
        day, month, year = (int(part) for part in match.groups())
    try:
        return as_date(date(year, month, day).isoformat())
    except ValueError:
        return ""


def _is_blank(spec: FieldSpec, value: Any) -> bool:
    """Whether a value counts as "not supplied" for this field.

    A money field is a special case: nothing and zero are different answers, so
    only nothing is missing.
    """
    if value is None:
        return True
    if spec.type in ("money", "number"):
        return _text(value) == ""
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    return _text(value) == ""


def missing_required(kind: str, fields: Mapping[str, Any], *,
                     has_parent: bool = True) -> list[dict[str, str]]:
    """Which mandatory fields this record still needs, with their labels.

    The parent counts as a mandatory field: a task without a project is as
    incomplete as a task without a name, and the assistant has to ask for it
    the same way.
    """
    spec = entity(kind)
    missing = [
        {"name": item.name, "label": item.label, "type": item.type,
         "reference": item.reference}
        for item in spec.required_fields
        if _is_blank(item, fields.get(item.name))
    ]
    if spec.parent and not has_parent:
        missing.insert(0, {
            "name": spec.parent, "label": spec.parent_label or spec.parent,
            "type": "reference", "reference": spec.parent,
        })
    return missing


def is_complete(kind: str, fields: Mapping[str, Any], *, has_parent: bool = True) -> bool:
    return not missing_required(kind, fields, has_parent=has_parent)


def coerce(kind: str, name: str, value: Any) -> Any:
    """Put one supplied value into the shape the record stores.

    Uses the application's own converters, so a date written any of the ways a
    construction document writes it lands the same way it would through the UI.
    """
    spec = entity(kind).field_map.get(name)
    if spec is None:
        return _text(value)
    if spec.type == "money":
        return money(value, spec.label) if _text(value) != "" else ""
    if spec.type == "number":
        if _text(value) == "":
            return ""
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            raise HTTPException(422, detail=f"{spec.label} must be a number") from None
    if spec.type == "date":
        return read_date(value)
    if spec.type == "permissions":
        return clean_permissions(value or ())
    if spec.type == "select" and spec.options:
        wanted = _text(value).casefold()
        if not wanted:
            return ""
        for option in spec.options:
            if option.casefold() == wanted:
                return option
        # An unrecognised choice is refused rather than quietly stored: the
        # assistant must ask again rather than settle for something close.
        raise HTTPException(
            422,
            detail=f"{spec.label} must be one of: {', '.join(spec.options)}",
        )
    return _text(value)


def coerce_fields(kind: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce every recognised field in ``data``; ignore anything else."""
    known = entity(kind).field_map
    return {name: coerce(kind, name, value) for name, value in data.items() if name in known}


def validate_entity(kind: str, fields: Mapping[str, Any], *,
                    siblings: Sequence[Mapping[str, Any]] = (),
                    roles: Sequence[Mapping[str, Any]] = (),
                    ignore_id: str | None = None,
                    project: Mapping[str, Any] | None = None) -> None:
    """Run the application's own rules over a candidate record.

    Every branch calls the function the live route calls.  Nothing is decided
    here that is not already decided there.
    """
    spec = entity(kind)
    for item in spec.required_fields:
        if _is_blank(item, fields.get(item.name)):
            raise HTTPException(422, detail=f"{item.label} is required")

    if kind == "task":
        # The real task validator: statuses, priorities, end-before-start, and
        # the project's dates when the task's project is known.
        validate_task({**fields, "parent_id": ""}, list(siblings), project=project)
    elif kind == "user":
        validate_email(fields.get("email", ""))
    elif kind == "role_type":
        validate_role_name(_text(fields.get("name")), list(roles), ignore_id=ignore_id)
        unknown = set(fields.get("permissions") or ()) - set(PERMISSION_KEYS)
        if unknown:
            raise HTTPException(422, detail="That role includes permissions this build does not define")
    elif kind in ("task_type", "project_type", "trade", "vendor"):
        assert_unique(siblings, _text(fields.get("name")), spec.label, ignore_id=ignore_id)
    elif kind == "project":
        code = _text(fields.get("project_code"))
        for other in siblings:
            if other.get("id") == ignore_id:
                continue
            if _text(other.get("project_code")).upper() == code.upper():
                raise HTTPException(409, detail="Project code already in use")
        if _text(fields.get("baseline_cost")):
            money(fields["baseline_cost"], "Baseline cost")
    elif kind in ("project_cost", "task_cost"):
        money(fields.get("amount"), entity(kind).field_map["amount"].label)
    elif kind == "procurement":
        # Builds a throwaway record purely to run the real field validators.
        make_procurement_item(fields, "validation")


# ──────────────────────────────────────────────────────────────────────────
# Choices that name other records
# ──────────────────────────────────────────────────────────────────────────

def reference_choices(kind: str, *, workspace: Any = None, registry: Any = None,
                      account_id: str = "") -> list[dict[str, str]]:
    """The records that actually exist for a ``reference`` field.

    The assistant is shown these and told to pick from them, which is what stops
    it inventing a project or a person that nobody has.
    """
    if workspace is None:
        return []
    if kind == "project":
        return [{"id": row["id"], "label": _text(row.get("name")),
                 "detail": _text(row.get("project_code"))}
                for row in workspace.load_projects().values()]
    if kind == "task":
        return [{"id": task["id"], "label": _text(task.get("name")), "detail": project_id}
                for project_id, tasks in workspace.load_tasks().items() for task in tasks]
    if kind == "user":
        people = registry.users_for_account(account_id) if registry else []
        return [{"id": row["id"], "label": _text(row.get("name")),
                 "detail": _text(row.get("email"))} for row in people]
    if kind == "role_type":
        return [{"id": name, "label": name, "detail": ""}
                for name in role_names(workspace.load_roles())]
    mgmt_key = {"task_type": "task_types", "project_type": "project_types",
                "trade": "trades", "vendor": "vendors"}.get(kind)
    if mgmt_key:
        return [{"id": _text(row.get("id")), "label": _text(row.get("name")), "detail": ""}
                for row in workspace.load_mgmt().get(mgmt_key, []) or []]
    return []


def permission_catalogue_rows() -> list[dict[str, str]]:
    """The permission keys a role may hold, for the role editor and the prompt."""
    return [dict(entry) for entry in PERMISSIONS]


# ──────────────────────────────────────────────────────────────────────────
# Keeping honest
# ──────────────────────────────────────────────────────────────────────────

def reconcile(builders: Mapping[str, Callable[[], Mapping[str, Any]]],
              server_owned: Mapping[str, Iterable[str]] | None = None) -> list[str]:
    """Check this file against the record constructors the application uses.

    Called at startup with the real constructors.  A field declared here that
    the constructor does not produce is a bug in this file and stops the boot; a
    field the constructor produces that this file does not list is reported so it
    can be added, and is otherwise harmless -- it simply is not offered.
    """
    server_owned = server_owned or {}
    notes: list[str] = []
    for kind, build in builders.items():
        spec = ENTITIES.get(kind)
        if spec is None:
            continue
        produced = set(build().keys()) - set(server_owned.get(kind, ()))
        declared = {item.name for item in spec.fields}
        unknown = declared - produced - set(spec.applied_after_build)
        if unknown:
            raise RuntimeError(
                f"entity_schema declares field(s) {sorted(unknown)} for \"{kind}\" that "
                f"{build.__name__} does not accept (it produced {sorted(produced)}). "
                f"Update entity_schema.py."
            )
        undeclared = produced - declared
        if undeclared:
            notes.append(f"{kind}: {', '.join(sorted(undeclared))} not offered by onboarding")
    return notes


__all__ = [
    "ENTITIES", "ENTITY_ORDER", "FIELD_TYPES", "PROJECT_STATUSES", "EntitySpec",
    "FieldSpec", "catalog", "coerce", "coerce_fields", "entity", "field_names",
    "is_complete", "missing_required", "permission_catalogue_rows", "read_date",
    "reconcile",
    "reference_choices", "validate_entity",
]
