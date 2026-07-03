# =============================================================================
# KAGGLE CELL — User Management  (paste as new cell BEFORE the FastAPI/uvicorn
# launch cell so that APP is already defined when these routes are registered)
#
# Storage: pure in-memory dicts — no external database needed.
# Passwords are stored as SHA-256 hashes (no bcrypt dependency required).
# =============================================================================

import hashlib, uuid
from datetime import datetime

# ── In-memory user store ──────────────────────────────────────────────────────
# Schema per user:
#   id, name, email, password_hash, phone, address,
#   role, department, designation, company, time_zone, status, created_at

def _hash_pw(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()

def _make_user(name, email, password, role="User", phone="", address="",
               department="", designation="", company="", time_zone="UTC",
               status="Active") -> dict:
    return {
        "id":            str(uuid.uuid4()),
        "name":          name,
        "email":         email,
        "password_hash": _hash_pw(password),
        "phone":         phone,
        "address":       address,
        "role":          role,
        "department":    department,
        "designation":   designation,
        "company":       company,
        "time_zone":     time_zone,
        "status":        status,
        "created_at":    datetime.utcnow().isoformat(),
    }

# In-memory store — starts empty; all data lives in Kaggle's process memory
USERS: dict[str, dict] = {}


def _public(u: dict) -> dict:
    """Return user dict without the password hash."""
    return {k: v for k, v in u.items() if k != "password_hash"}

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/users")
async def list_users(
    name:       str = "",
    email:      str = "",
    status:     str = "",
    role:       str = "",
    department: str = "",
):
    users = [_public(u) for u in USERS.values()]
    if name and len(name) >= 3:
        users = [u for u in users if name.lower() in u["name"].lower()]
    if email and len(email) >= 3:
        users = [u for u in users if email.lower() in u["email"].lower()]
    if status:
        users = [u for u in users if u["status"] == status]
    if role:
        users = [u for u in users if u["role"] == role]
    if department:
        users = [u for u in users if u.get("department", "") == department]
    return {"users": users, "total": len(users)}


@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    u = USERS.get(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return _public(u)


@app.post("/api/users")
async def create_user(req: Request):
    data = await req.json()
    name  = data.get("name", "").strip()
    email = data.get("email", "").strip()
    pw    = data.get("password", "").strip()
    role  = data.get("role", "User").strip()

    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    if not email:
        raise HTTPException(status_code=422, detail="Email is required")
    if not pw:
        raise HTTPException(status_code=422, detail="Password is required")

    # Check duplicate email
    for u in USERS.values():
        if u["email"].lower() == email.lower():
            raise HTTPException(status_code=409, detail="Email already in use")

    user = _make_user(
        name=name, email=email, password=pw, role=role,
        phone=data.get("phone", ""),
        address=data.get("address", ""),
        department=data.get("department", ""),
        designation=data.get("designation", ""),
        company=data.get("company", ""),
        time_zone=data.get("time_zone", "UTC"),
        status=data.get("status", "Active"),
    )
    USERS[user["id"]] = user
    return _public(user)


@app.put("/api/users/{user_id}")
async def update_user(user_id: str, req: Request):
    u = USERS.get(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    data = await req.json()

    # Update allowed fields (never overwrite id or created_at)
    for field in ["name", "email", "phone", "address", "role",
                  "department", "designation", "company", "time_zone", "status"]:
        if field in data:
            u[field] = data[field]

    # Optional password change
    if data.get("password"):
        u["password_hash"] = _hash_pw(data["password"])

    return _public(u)


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str):
    if user_id not in USERS:
        raise HTTPException(status_code=404, detail="User not found")
    # Soft-delete: mark inactive instead of removing
    USERS[user_id]["status"] = "Inactive"
    return {"message": "User deactivated"}
