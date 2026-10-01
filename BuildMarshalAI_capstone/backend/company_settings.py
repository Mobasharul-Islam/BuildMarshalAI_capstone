"""Company profile, task types, and project types.

The Company Settings section of the product. All three are per account and
readable by any member; only account administrators -- the owner, or a user
whose role is Head (Super Admin) or Head (System Admin) -- may change them. The
permission check lives here on the server, so a client that hides its buttons is
a convenience, not the control.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from fastapi import Depends, HTTPException, Request


# Fields the company profile stores. Anything else sent is ignored.
COMPANY_FIELDS = (
    "name", "legal_name", "registration_number", "tax_id", "industry",
    "founded", "website", "email", "phone", "address_line1", "address_line2",
    "city", "state", "postal_code", "country", "contact_name", "contact_role",
    "contact_email", "contact_phone", "about",
)

CATALOGS = {
    # url segment -> (management-store key, human label)
    "task-types": ("task_types", "Task type"),
    "project-types": ("project_types", "Project type"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def empty_company() -> dict[str, Any]:
    return {field: "" for field in COMPANY_FIELDS}


def company_profile(stored: Mapping[str, Any] | None, settings: Mapping[str, Any] | None = None,
                    account: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The company record, seeded from what the account already knows.

    A workspace that has never opened Company Info still shows its account name
    and the contact details captured at sign-up, rather than an empty form.
    """
    profile = empty_company()
    settings = settings or {}
    account = account or {}
    profile["name"] = _text(settings.get("company_name")) or _text(account.get("name"))
    profile["email"] = _text(settings.get("company_email"))
    profile["phone"] = _text(settings.get("company_phone"))
    profile["address_line1"] = _text(settings.get("company_address"))
    if isinstance(stored, Mapping):
        for field in COMPANY_FIELDS:
            if stored.get(field) not in (None, ""):
                profile[field] = _text(stored.get(field))
    profile["updated_at"] = (stored or {}).get("updated_at")
    profile["updated_by"] = (stored or {}).get("updated_by")
    return profile


def apply_company_updates(profile: dict[str, Any], data: Mapping[str, Any], user: Mapping[str, Any]) -> dict[str, Any]:
    for field in COMPANY_FIELDS:
        if field in data:
            profile[field] = _text(data[field])
    profile["updated_at"] = _now()
    profile["updated_by"] = _text(user.get("name")) or _text(user.get("email"))
    return profile


def validate_company(data: Mapping[str, Any]) -> None:
    if "name" in data and not _text(data["name"]):
        raise HTTPException(422, detail="Company name cannot be empty")
    email = _text(data.get("email"))
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        raise HTTPException(422, detail="Company email is not a valid address")
    contact_email = _text(data.get("contact_email"))
    if contact_email and ("@" not in contact_email or "." not in contact_email.split("@")[-1]):
        raise HTTPException(422, detail="Contact email is not a valid address")
    website = _text(data.get("website"))
    if website and not website.startswith(("http://", "https://")):
        raise HTTPException(422, detail="Website must start with http:// or https://")


def catalog_entry(data: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    return {
        "id": f"{prefix}-{uuid.uuid4().hex[:8]}",
        "name": _text(data.get("name")),
        "description": _text(data.get("description")) or "-",
        "status": _text(data.get("status"), "Active") or "Active",
        "created_at": _now(),
    }


def assert_unique(entries: Iterable[Mapping[str, Any]], name: str, label: str,
                  ignore_id: str | None = None) -> None:
    lowered = name.casefold()
    for entry in entries:
        if entry.get("id") == ignore_id:
            continue
        if _text(entry.get("name")).casefold() == lowered:
            raise HTTPException(409, detail=f"{label} \"{name}\" already exists")


def count_task_type_usage(all_tasks: Mapping[str, Sequence[Mapping[str, Any]]], name: str) -> int:
    return sum(
        1
        for tasks in all_tasks.values()
        for task in tasks
        if _text(task.get("task_type")).casefold() == name.casefold()
    )


def count_project_type_usage(projects: Mapping[str, Mapping[str, Any]], name: str) -> int:
    return sum(
        1 for project in projects.values()
        if _text(project.get("type")).casefold() == name.casefold()
    )


def register_company_settings_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register the company profile and the task/project type catalogs."""
    required = ("app", "require_account")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Company settings integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]

    # ── Company profile ───────────────────────────────────────────────────

    @app.get("/api/company")
    async def get_company(context=Depends(require_account)) -> dict[str, Any]:
        """Readable by every member of the account."""
        profile = company_profile(
            context.workspace.load_company(),
            context.workspace.load_settings(),
            context.account,
        )
        # The client uses this to decide whether to offer the edit controls;
        # the server enforces the same rule on write regardless.
        return {"company": profile, "can_edit": context.is_admin}

    @app.put("/api/company")
    async def update_company(request: Request, context=Depends(require_account)) -> dict[str, Any]:
        context.require_admin()
        data = await request.json()
        validate_company(data)
        stored = context.workspace.load_company() or {}
        profile = company_profile(stored, context.workspace.load_settings(), context.account)
        apply_company_updates(profile, data, context.user)
        context.workspace.save_company(profile)

        # Keep the account settings copy in step so the rest of the app keeps
        # showing the same company details it always did.
        if "name" in data or "email" in data or "phone" in data or "address_line1" in data:
            settings = context.workspace.load_settings()
            settings.update({
                "company_name": profile["name"], "company_email": profile["email"],
                "company_phone": profile["phone"], "company_address": profile["address_line1"],
            })
            context.workspace.save_settings(settings)
        return {"company": profile, "can_edit": True}

    # ── Task types and project types ──────────────────────────────────────

    def read_catalog(workspace: Any, key: str) -> list[dict[str, Any]]:
        return list(workspace.load_mgmt().get(key, []) or [])

    def register_catalog(segment: str) -> None:
        key, label = CATALOGS[segment]
        plural = key
        # Managing a catalogue is a permission a custom role can be given, so
        # an administrator is no longer the only one who may curate them.
        permission = "task_type.manage" if key == "task_types" else "project_type.manage"

        def may_manage(context: Any) -> bool:
            return context.is_admin or context.can(permission)

        def require_manage(context: Any) -> None:
            if not may_manage(context):
                raise HTTPException(403, f"Your role does not allow managing {label.lower()}s")

        @app.get(f"/api/{segment}", name=f"list_{key}")
        async def list_entries(context=Depends(require_account)) -> dict[str, Any]:
            entries = read_catalog(context.workspace, key)
            return {plural: entries, "total": len(entries), "can_edit": may_manage(context)}

        @app.post(f"/api/{segment}", name=f"create_{key}")
        async def create_entry(request: Request, context=Depends(require_account)) -> dict[str, Any]:
            require_manage(context)
            data = await request.json()
            name = _text(data.get("name"))
            if not name:
                raise HTTPException(422, detail=f"{label} name is required")
            mgmt = context.workspace.load_mgmt()
            entries = list(mgmt.get(key, []) or [])
            assert_unique(entries, name, label)
            entry = catalog_entry({**data, "name": name}, segment[:2])
            entries.append(entry)
            mgmt[key] = entries
            context.workspace.save_mgmt(mgmt)
            return entry

        @app.put(f"/api/{segment}/{{entry_id}}", name=f"update_{key}")
        async def update_entry(entry_id: str, request: Request,
                               context=Depends(require_account)) -> dict[str, Any]:
            require_manage(context)
            data = await request.json()
            mgmt = context.workspace.load_mgmt()
            entries = list(mgmt.get(key, []) or [])
            entry = next((item for item in entries if item.get("id") == entry_id), None)
            if not entry:
                raise HTTPException(404, detail=f"{label} not found")
            if "name" in data:
                name = _text(data["name"])
                if not name:
                    raise HTTPException(422, detail=f"{label} name cannot be empty")
                assert_unique(entries, name, label, ignore_id=entry_id)
                entry["name"] = name
            if "description" in data:
                entry["description"] = _text(data["description"]) or "-"
            if "status" in data:
                entry["status"] = _text(data["status"], "Active") or "Active"
            mgmt[key] = entries
            context.workspace.save_mgmt(mgmt)
            return entry

        @app.delete(f"/api/{segment}/{{entry_id}}", name=f"delete_{key}")
        async def delete_entry(entry_id: str, context=Depends(require_account)) -> dict[str, Any]:
            require_manage(context)
            mgmt = context.workspace.load_mgmt()
            entries = list(mgmt.get(key, []) or [])
            entry = next((item for item in entries if item.get("id") == entry_id), None)
            if not entry:
                raise HTTPException(404, detail=f"{label} not found")

            # Removing a type that records still reference would leave them
            # pointing at something that no longer exists, so say so instead.
            if key == "task_types":
                used = count_task_type_usage(context.workspace.load_tasks(), entry["name"])
                noun = "task"
            else:
                used = count_project_type_usage(context.workspace.load_projects(), entry["name"])
                noun = "project"
            if used:
                raise HTTPException(
                    409,
                    detail=(f"\"{entry['name']}\" is used by {used} {noun}"
                            f"{'' if used == 1 else 's'}. Change those first, then delete it."),
                )

            mgmt[key] = [item for item in entries if item.get("id") != entry_id]
            context.workspace.save_mgmt(mgmt)
            return {"message": f"{label} deleted", "id": entry_id}

    for segment in CATALOGS:
        register_catalog(segment)

    return {"catalogs": list(CATALOGS)}


__all__ = [
    "CATALOGS", "COMPANY_FIELDS", "apply_company_updates", "assert_unique",
    "catalog_entry", "company_profile", "count_project_type_usage",
    "count_task_type_usage", "empty_company", "register_company_settings_routes",
    "validate_company",
]
