"""User Roles: the permission sets a Super Admin defines for their workspace.

Only two roles exist without being created -- Super Admin and System Admin --
and neither can be edited or removed here. Every other role in an account is a
name plus the permissions ticked for it.

Creating, editing, and deleting roles is Super Admin work and is not itself a
permission. An authority that could be ticked on a custom role would be an
authority a Super Admin could give away by accident, so it is not offered.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from fastapi import Depends, HTTPException, Request

try:  # the notebook puts this directory on sys.path
    from permissions import (
        BUILTIN_ROLES, PERMISSION_KEYS, SUPER_ADMIN_ROLE, SYSTEM_ADMIN_ROLE,
        clean_permissions, permission_catalogue,
    )
except ModuleNotFoundError:  # imported as backend.user_roles
    from backend.permissions import (
        BUILTIN_ROLES, PERMISSION_KEYS, SUPER_ADMIN_ROLE, SYSTEM_ADMIN_ROLE,
        clean_permissions, permission_catalogue,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def make_role(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": f"role-{uuid.uuid4().hex[:8]}",
        "name": _text(data.get("name")),
        "description": _text(data.get("description")),
        "permissions": clean_permissions(data.get("permissions") or ()),
        "created_at": _now(),
        "updated_at": _now(),
    }


def validate_role_name(name: str, roles: Sequence[Mapping[str, Any]],
                       ignore_id: str | None = None) -> str:
    if not name:
        raise HTTPException(422, "Role name is required")
    lowered = name.casefold()
    if lowered in {builtin.casefold() for builtin in BUILTIN_ROLES}:
        raise HTTPException(409, f"\"{name}\" is a built-in role and cannot be redefined")
    for role in roles:
        if role.get("id") == ignore_id:
            continue
        if _text(role.get("name")).casefold() == lowered:
            raise HTTPException(409, f"A role named \"{name}\" already exists")
    return name


def count_role_holders(users: Sequence[Mapping[str, Any]], name: str) -> int:
    lowered = name.casefold()
    return sum(1 for user in users if _text(user.get("role")).casefold() == lowered)


def builtin_role_rows() -> list[dict[str, Any]]:
    """The two built-ins, shaped like custom roles so one table renders both."""
    return [
        {
            "id": f"builtin-{name.replace(' ', '-').lower()}",
            "name": name,
            "description": (
                "Full access to everything, and the only role that can manage roles "
                "and permissions."
                if name == SUPER_ADMIN_ROLE else
                "Account administration: users, company settings, and workspace catalogues."
            ),
            "permissions": sorted(PERMISSION_KEYS),
            "builtin": True,
            "editable": False,
        }
        for name in BUILTIN_ROLES
    ]


def register_user_role_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    required = ("app", "require_account")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"User roles integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]
    registry = namespace.get("ACCOUNT_REGISTRY")

    def account_users(context: Any) -> list[dict[str, Any]]:
        if registry is None:
            return []
        return list(registry.users_for_account(context.account_id))

    @app.get("/api/permissions")
    async def list_permissions(context=Depends(require_account)) -> dict[str, Any]:
        """The catalogue the role form renders. Readable by any member."""
        return {"groups": permission_catalogue(), "total": len(PERMISSION_KEYS)}

    @app.get("/api/user-roles")
    async def list_roles(context=Depends(require_account)) -> dict[str, Any]:
        """Every role in this account. Any member may look; only a Super Admin may change."""
        custom = [
            {**role, "builtin": False, "editable": True,
             "users": count_role_holders(account_users(context), role.get("name", ""))}
            for role in context.workspace.load_roles()
        ]
        builtins = [
            {**row, "users": count_role_holders(account_users(context), row["name"])}
            for row in builtin_role_rows()
        ]
        return {
            "roles": builtins + custom,
            "total": len(builtins) + len(custom),
            # The client hides its buttons with this; the server enforces the
            # same rule on every write regardless of what it renders.
            "can_manage": context.is_super_admin,
            "my_permissions": sorted(context.permissions),
        }

    @app.post("/api/user-roles")
    async def create_role(request: Request, context=Depends(require_account)) -> dict[str, Any]:
        context.require_super_admin()
        data = await request.json()
        roles = context.workspace.load_roles()
        name = validate_role_name(_text(data.get("name")), roles)
        role = make_role({**data, "name": name})
        roles.append(role)
        context.workspace.save_roles(roles)
        return {**role, "builtin": False, "editable": True, "users": 0}

    @app.put("/api/user-roles/{role_id}")
    async def update_role(role_id: str, request: Request,
                          context=Depends(require_account)) -> dict[str, Any]:
        context.require_super_admin()
        data = await request.json()
        roles = context.workspace.load_roles()
        role = next((item for item in roles if item.get("id") == role_id), None)
        if not role:
            raise HTTPException(404, "Role not found")

        previous = role["name"]
        if "name" in data:
            role["name"] = validate_role_name(_text(data["name"]), roles, ignore_id=role_id)
        if "description" in data:
            role["description"] = _text(data["description"])
        if "permissions" in data:
            role["permissions"] = clean_permissions(data["permissions"] or ())
        role["updated_at"] = _now()
        context.workspace.save_roles(roles)

        # A rename has to follow the people holding it, or they would be left
        # pointing at a role that no longer exists and lose every permission.
        renamed = 0
        if registry is not None and role["name"] != previous:
            for user in account_users(context):
                if _text(user.get("role")).casefold() == previous.casefold():
                    registry.update_user(user["id"], {"role": role["name"]})
                    renamed += 1
        return {**role, "builtin": False, "editable": True,
                "users": count_role_holders(account_users(context), role["name"]),
                "renamed_users": renamed}

    @app.delete("/api/user-roles/{role_id}")
    async def delete_role(role_id: str, context=Depends(require_account)) -> dict[str, Any]:
        context.require_super_admin()
        roles = context.workspace.load_roles()
        role = next((item for item in roles if item.get("id") == role_id), None)
        if not role:
            raise HTTPException(404, "Role not found")

        holders = count_role_holders(account_users(context), role["name"])
        if holders:
            raise HTTPException(
                409,
                f"\"{role['name']}\" is assigned to {holders} "
                f"user{'' if holders == 1 else 's'}. Move them to another role first.",
            )
        context.workspace.save_roles([item for item in roles if item.get("id") != role_id])
        return {"message": "Role deleted", "id": role_id}

    return {"builtin_roles": list(BUILTIN_ROLES), "permissions": len(PERMISSION_KEYS)}


__all__ = [
    "builtin_role_rows", "count_role_holders", "make_role",
    "register_user_role_routes", "validate_role_name",
]
