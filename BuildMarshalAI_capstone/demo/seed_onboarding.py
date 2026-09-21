"""Build an onboarding draft through the real API, for the demonstration.

The draft is what an analysis of a second project's documents would leave
behind: a project, the types and roles it needs, its people, a two-level task
tree, costs and procurement -- none of it created yet.

Two items are deliberately left incomplete, because the point of a draft is
that it can hold work that is not ready. The plan refuses to onboard them and
says which field is missing.

    python demo/seed_onboarding.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
EMAIL = "rafiqul.islam@purbachalcon.example"
PASSWORD = "PadmaView2026!"


def call(path: str, token: str = "", data: object = None, method: str = "") -> dict:
    request = urllib.request.Request(
        BASE + path, method=method or ("POST" if data is not None else "GET"),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(request, timeout=25) as response:
        body = response.read()
    return json.loads(body) if body else {}


#: (kind, ref, fields, parent_ref, parent_id) -- ref is how later items point here.
ITEMS: list[tuple[str, str, dict, str, str]] = [
    # -- the catalogues the project needs before anything can reference them --
    ("project_type", "type-health", {
        "name": "Healthcare",
        "description": "Hospitals, clinics and diagnostic centres"}, "", ""),
    ("task_type", "type-approval", {
        "name": "Approval",
        "description": "Government approvals and clearances"}, "", ""),
    ("role_type", "role-package", {
        "name": "Package Manager",
        "description": "Runs one trade package end to end",
        "permissions": ["project.view", "task.view", "task.edit", "task.create"]}, "", ""),

    # -- the project itself --------------------------------------------------
    ("project", "proj-savar", {
        "name": "Savar Diagnostic Centre",
        "project_code": "SDC-2027",
        "type": "Healthcare",
        "manager": "Nusrat Jahan",
        "status": "Active",
        "start_date": "2027-02-01",
        "end_date": "2028-03-31",
        "description": "Three-storey diagnostic centre of 2,400 m2 with MRI and CT "
                       "facilities.",
        "address_line1": "Bus Stand Road, Savar",
        "city": "Savar", "postal_code": "1340",
        "country": "Bangladesh"}, "", ""),

    # -- the people ----------------------------------------------------------
    ("user", "user-ashraful", {
        "name": "Md. Ashraful Alam", "email": "ashraful.alam@purbachalcon.example",
        "role": "Project Manager", "department": "Operations",
        "designation": "Project Manager"}, "", ""),
    ("user", "user-taslima", {
        "name": "Taslima Begum", "email": "taslima.begum@purbachalcon.example",
        "role": "Site Supervisor", "department": "Operations",
        "designation": "Site Engineer"}, "", ""),
    # Deliberately incomplete: the brief named a surveyor but gave no email,
    # which is mandatory. It stays in the draft, unonboardable.
    ("user", "user-unknown", {
        "name": "S. Rahman",
        "designation": "Quantity Surveyor", "department": "Commercial"}, "", ""),

    # -- the programme, two levels deep -------------------------------------
    ("task", "task-approval", {
        "name": "Approvals & Clearances", "task_type": "Phase", "trade": "General",
        "assignee": "Md. Ashraful Alam", "start_time": "2027-02-01",
        "end_time": "2027-04-30", "priority": "High", "status": "Open"},
     "proj-savar", ""),
    ("task", "task-rajuk", {
        "name": "RAJUK plan approval", "task_type": "Approval", "trade": "General",
        "assignee": "Md. Ashraful Alam", "start_time": "2027-02-01",
        "end_time": "2027-03-19", "priority": "Urgent", "status": "Open"},
     "proj-savar", "task-approval"),
    ("task", "task-fire", {
        "name": "Fire Service clearance", "task_type": "Approval", "trade": "General",
        "assignee": "Taslima Begum", "start_time": "2027-03-01",
        "end_time": "2027-04-30", "priority": "High", "status": "Open"},
     "proj-savar", "task-approval"),
    ("task", "task-substructure", {
        "name": "Substructure", "task_type": "Phase", "trade": "Concrete",
        "assignee": "Taslima Begum", "start_time": "2027-05-03",
        "end_time": "2027-08-27", "priority": "High", "status": "Open"},
     "proj-savar", ""),
    ("task", "task-piling", {
        "name": "Piling - 140 piles", "task_type": "Construction", "trade": "Piling",
        "assignee": "Taslima Begum", "start_time": "2027-05-03",
        "end_time": "2027-06-25", "priority": "High", "status": "Open"},
     "proj-savar", "task-substructure"),
    ("task", "task-caps", {
        "name": "Pile caps and grade beams", "task_type": "Construction",
        "trade": "Concrete", "assignee": "Taslima Begum", "start_time": "2027-06-28",
        "end_time": "2027-08-27", "priority": "High", "status": "Open"},
     "proj-savar", "task-substructure"),
    ("task", "task-super", {
        "name": "Superstructure", "task_type": "Phase", "trade": "Concrete",
        "assignee": "Md. Ashraful Alam", "start_time": "2027-08-30",
        "end_time": "2027-12-31", "priority": "High", "status": "Open"},
     "proj-savar", ""),

    # -- money ---------------------------------------------------------------
    ("project_cost", "cost-prelims", {
        "name": "Preliminaries", "amount": 9_800_000,
        "details": "Site establishment, management and security"}, "proj-savar", ""),
    ("project_cost", "cost-contingency", {
        "name": "Contingency", "amount": 6_500_000,
        "details": "Design development and risk allowance"}, "proj-savar", ""),
    ("task_cost", "cost-piling", {
        "name": "Piling package", "amount": 21_400_000}, "task-piling", ""),
    ("task_cost", "cost-caps", {
        "name": "Pile caps", "amount": 8_600_000}, "task-caps", ""),

    # -- procurement ---------------------------------------------------------
    ("procurement", "proc-mri", {
        "name": "MRI room shielding package", "supplier": "Rupsha Building Products",
        "trade": "General", "quantity": 1, "unit": "package",
        "unit_cost": 14_500_000, "status": "Quoted", "needed_by": "2027-11-01"},
     "proj-savar", ""),
    # Deliberately incomplete: the schedule listed the item by reference only.
    ("procurement", "proc-unknown", {
        "supplier": "Karnaphuli Electricals",
        "trade": "Electrical", "quantity": 1, "unit": "unit",
        "status": "Quoted"}, "proj-savar", ""),
]


def main() -> None:
    token = call("/api/auth/login",
                 data={"email": EMAIL, "password": PASSWORD})["token"]

    draft = call("/api/onboarding/drafts", token,
                 {"name": "Savar Diagnostic Centre - from the tender pack"})
    draft_id = draft["id"]
    print(f"draft {draft_id}")

    refs: dict[str, str] = {}
    for kind, ref, fields, parent_ref, parent_id in ITEMS:
        payload = {"kind": kind, "fields": fields}
        if parent_ref:
            payload["parent_ref"] = refs.get(parent_ref, parent_ref)
        if parent_id:
            payload["parent_id"] = refs.get(parent_id, parent_id)
        result = call(f"/api/onboarding/drafts/{draft_id}/items", token, payload)
        refs[ref] = result["item_id"]
        print(f"  {kind:<13} {fields.get('name', fields.get('amount', '(unnamed)'))}")

    # Select everything that is complete; the plan will refuse the rest.
    current = call(f"/api/onboarding/drafts/{draft_id}", token)
    every = [item["id"] for item in current.get("items", [])]
    call(f"/api/onboarding/drafts/{draft_id}/selection", token,
         {"selection": every}, method="PUT")

    plan = call(f"/api/onboarding/drafts/{draft_id}/plan", token)
    ready = plan.get("ready", plan.get("create", []))
    blocked = plan.get("blocked", plan.get("incomplete", []))
    print(f"\nplan: {len(ready)} ready, {len(blocked)} blocked")
    for entry in blocked:
        missing = entry.get("missing") or entry.get("problems") or []
        label = entry.get("label") or entry.get("name") or entry.get("id")
        print(f"  blocked  {label}: {missing}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        sys.exit(f"{error.code} {error.reason}: {error.read().decode()[:400]}")
    except urllib.error.URLError as error:
        sys.exit(f"The demonstration backend is not answering on {BASE}: {error}")
