"""To-do lists: what goes on one, who receives it, and what it takes to send."""

import csv
import io

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.accounts import AccountContext
from backend.todo_lists import (
    TodoFilter,
    as_csv,
    as_pdf,
    as_text,
    collect_tasks,
    matches,
    register_todo_list_routes,
    resolve_recipients,
    tasks_for,
)

TASKS = [
    {"id": "t1", "name": "Pour slab", "status": "Open", "priority": "High",
     "assignee": "Sam Field", "due_date": "2026-09-10"},
    {"id": "t2", "name": "Order rebar", "status": "In Progress", "priority": "Normal",
     "assignee": "Alex Other", "due_date": "2026-09-08"},
    {"id": "t3", "name": "Sign off", "status": "Completed", "priority": "Low",
     "assignee": "Sam Field", "due_date": "2026-09-01"},
    {"id": "t4", "name": "Old job", "status": "Open", "priority": "Low",
     "assignee": "Sam Field", "archived": True},
    {"id": "t5", "name": "No deadline", "status": "Open", "priority": "Normal",
     "assignee": "", "due_date": ""},
]


@pytest.fixture
def workspace(make_account):
    context = make_account("owner@example.com")
    context.workspace.save_projects({"p1": {"id": "p1", "name": "Tower"}})
    context.workspace.save_tasks({"p1": TASKS})
    return context


# ── what goes on the list ─────────────────────────────────────────────────────

def test_only_outstanding_work_is_collected(workspace):
    names = [row["name"] for row in collect_tasks(workspace.workspace, TodoFilter())]
    assert "Sign off" not in names, "completed work is not a to-do"
    assert "Old job" not in names, "archived work is not a to-do"
    assert {"Pour slab", "Order rebar", "No deadline"} == set(names)


def test_dated_work_comes_first_in_date_order(workspace):
    rows = collect_tasks(workspace.workspace, TodoFilter())
    assert [row["name"] for row in rows] == ["Order rebar", "Pour slab", "No deadline"]


def test_the_project_name_travels_with_each_task(workspace):
    rows = collect_tasks(workspace.workspace, TodoFilter())
    assert all(row["project_name"] == "Tower" for row in rows)


def test_filtering_by_assignee_and_due_date(workspace):
    only_sam = collect_tasks(workspace.workspace, TodoFilter(assignee="sam field"))
    assert [row["name"] for row in only_sam] == ["Pour slab"]

    soon = collect_tasks(workspace.workspace, TodoFilter(due_before="2026-09-09"))
    assert [row["name"] for row in soon] == ["Order rebar"]


def test_a_task_with_no_due_date_is_never_due_before_a_day():
    assert not matches({"status": "Open", "due_date": ""},
                       TodoFilter(due_before="2026-09-09"))


def test_archived_work_can_be_asked_for_explicitly(workspace):
    rows = collect_tasks(workspace.workspace, TodoFilter(include_archived=True))
    assert "Old job" in [row["name"] for row in rows]


def test_an_empty_account_produces_an_empty_list(make_account):
    context = make_account("empty@example.com")
    assert collect_tasks(context.workspace, TodoFilter()) == []


# ── who receives it ───────────────────────────────────────────────────────────

USERS = [
    {"id": "u1", "name": "Sam Field", "email": "sam@example.com",
     "role": "Site Lead", "status": "Active"},
    {"id": "u2", "name": "Alex Other", "email": "alex@example.com",
     "role": "Site Lead", "status": "Active"},
    {"id": "u3", "name": "Gone Away", "email": "gone@example.com",
     "role": "Site Lead", "status": "Inactive"},
    {"id": "u4", "name": "Dana Boss", "email": "dana@example.com",
     "role": "Head (Super Admin)", "status": "Active"},
]


def test_recipients_come_from_the_roles_picked():
    chosen = resolve_recipients(USERS, ["Site Lead"], [])
    assert {p["email"] for p in chosen} == {"sam@example.com", "alex@example.com"}


def test_deactivated_members_are_never_mailed():
    """A to-do list to someone who cannot sign in helps nobody."""
    chosen = resolve_recipients(USERS, ["Site Lead"], ["u3"])
    assert "gone@example.com" not in {p["email"] for p in chosen}


def test_role_matching_ignores_case_and_a_person_is_listed_once():
    chosen = resolve_recipients(USERS, ["site lead"], ["u1"])
    assert len(chosen) == 2 and len({p["email"] for p in chosen}) == 2


def test_naming_someone_directly_adds_them():
    chosen = resolve_recipients(USERS, [], ["u4"])
    assert [p["email"] for p in chosen] == ["dana@example.com"]


def test_no_roles_and_no_names_selects_nobody():
    assert resolve_recipients(USERS, [], []) == []


def test_a_persons_own_slice_is_matched_by_name_or_email(workspace):
    rows = collect_tasks(workspace.workspace, TodoFilter())
    by_name = tasks_for(rows, {"name": "Sam Field", "email": "sam@example.com"})
    assert [row["name"] for row in by_name] == ["Pour slab"]
    assert tasks_for(rows, {"name": "Nobody", "email": "nobody@example.com"}) == []


# ── rendering ─────────────────────────────────────────────────────────────────

def test_the_email_body_lists_every_task_and_its_deadline(workspace):
    rows = collect_tasks(workspace.workspace, TodoFilter())
    text = as_text("Site to-do", "Please review.", rows, greeting="Sam")
    assert text.startswith("Hello Sam,")
    assert "Please review." in text
    assert "Pour slab" in text and "due 2026-09-10" in text
    assert "3 items." in text


def test_an_empty_list_says_so_rather_than_looking_broken():
    assert "Nothing outstanding." in as_text("Site to-do", "", [])


def test_the_csv_has_a_header_and_one_row_per_task(workspace):
    rows = collect_tasks(workspace.workspace, TodoFilter())
    parsed = list(csv.reader(io.StringIO(as_csv(rows))))
    assert parsed[0] == ["Task", "Project", "Assignee", "Priority", "Status", "Due"]
    assert len(parsed) == len(rows) + 1
    assert parsed[1][0] == "Order rebar"


def test_the_pdf_is_a_pdf(workspace):
    rows = collect_tasks(workspace.workspace, TodoFilter())
    data = as_pdf("Site to-do", "Please review.", rows)
    assert data.startswith(b"%PDF") and len(data) > 800


def test_the_pdf_survives_characters_outside_latin_1(workspace):
    """FPDF's core fonts are latin-1; a stray em dash must not raise."""
    workspace.workspace.save_tasks({"p1": [
        {"id": "t1", "name": "Pour slab — level 2 ✓", "status": "Open",
         "priority": "High", "assignee": "Sam", "due_date": "2026-09-10"}]})
    rows = collect_tasks(workspace.workspace, TodoFilter())
    assert as_pdf("Site to-do", "", rows).startswith(b"%PDF")


# ── routes ────────────────────────────────────────────────────────────────────

def build_app(context: AccountContext, registry, sender=None) -> TestClient:
    app = FastAPI()

    async def require_account():
        return context

    namespace = {"app": app, "require_account": require_account,
                 "ACCOUNT_REGISTRY": registry}
    if sender is not None:
        namespace["MAIL_SENDERS"] = {"google": sender}
    register_todo_list_routes(namespace)
    return TestClient(app)


def with_role(context: AccountContext, role: str) -> AccountContext:
    return AccountContext(user={**context.user, "is_owner": False, "role": role},
                          account=context.account, workspace=context.workspace,
                          token=context.token)


def define_role(context, name, permissions):
    roles = context.workspace.load_roles()
    roles.append({"id": f"role-{name}", "name": name, "permissions": list(permissions)})
    context.workspace.save_roles(roles)


@pytest.fixture
def account(workspace, registry):
    registry.create_user(account_id=workspace.account_id, name="Sam Field",
                         email="sam@example.com", password="Passw0rd!123", role="Site Lead")
    define_role(workspace, "Site Lead", [])
    define_role(workspace, "Sender", ["todo.send"])
    return workspace


def test_preview_builds_the_list_and_names_the_recipients(account, registry):
    client = build_app(account, registry)
    body = client.post("/api/todo-list/preview", json={"roles": ["Site Lead"]}).json()
    assert body["total"] == 3
    assert [p["email"] for p in body["recipients"]] == ["sam@example.com"]
    assert body["can_send"] is True, "the owner is a Head (Super Admin)"


def test_preview_reports_each_persons_share_when_personalised(account, registry):
    client = build_app(account, registry)
    body = client.post("/api/todo-list/preview",
                       json={"roles": ["Site Lead"], "per_recipient": True}).json()
    assert body["breakdown"] == [{"id": body["recipients"][0]["id"], "name": "Sam Field",
                                  "email": "sam@example.com", "role": "Site Lead",
                                  "count": 1}]


@pytest.mark.parametrize("fmt, prefix", [("pdf", b"%PDF"), ("csv", b"\xef\xbb\xbfTask,")])
def test_anyone_may_download_their_own_accounts_list(account, registry, fmt, prefix):
    client = build_app(with_role(account, "Site Lead"), registry)
    response = client.post(f"/api/todo-list/download?fmt={fmt}", json={})
    assert response.status_code == 200
    assert response.content.startswith(prefix)
    assert "attachment" in response.headers["content-disposition"]


def test_an_unknown_download_format_is_refused(account, registry):
    client = build_app(account, registry)
    assert client.post("/api/todo-list/download?fmt=docx", json={}).status_code == 422


def test_sending_needs_the_permission(account, registry):
    sent = []
    client = build_app(with_role(account, "Site Lead"), registry,
                       sender=lambda *a: sent.append(a))
    blocked = client.post("/api/todo-list/send", json={
        "roles": ["Site Lead"], "account_id": "acct", "confirm": True})
    assert blocked.status_code == 403
    assert not sent, "nothing may be sent without the permission"


def test_sending_requires_an_explicit_confirmation(account, registry):
    sent = []
    client = build_app(account, registry, sender=lambda *a: sent.append(a))
    body = client.post("/api/todo-list/send", json={
        "roles": ["Site Lead"], "account_id": "acct"}).json()
    assert body["confirmation_required"] is True
    assert [p["email"] for p in body["recipients"]] == ["sam@example.com"]
    assert not sent, "an unconfirmed send must write nothing"


def test_a_confirmed_send_mails_each_recipient(account, registry):
    sent = []
    client = build_app(account, registry,
                       sender=lambda ws, acct, to, subject, text: sent.append((to, subject, text)))
    body = client.post("/api/todo-list/send", json={
        "roles": ["Site Lead"], "account_id": "acct", "title": "Site to-do",
        "confirm": True}).json()
    assert body["sent"] == 1 and body["failed"] == 0
    assert sent[0][0] == "sam@example.com" and sent[0][1] == "Site to-do"
    assert "Pour slab" in sent[0][2]


def test_a_personalised_send_skips_people_with_nothing_assigned(account, registry):
    registry.create_user(account_id=account.account_id, name="Idle Person",
                         email="idle@example.com", password="Passw0rd!123", role="Site Lead")
    sent = []
    client = build_app(account, registry,
                       sender=lambda ws, acct, to, *rest: sent.append(to))
    body = client.post("/api/todo-list/send", json={
        "roles": ["Site Lead"], "account_id": "acct",
        "per_recipient": True, "confirm": True}).json()
    assert body["sent"] == 1 and body["skipped"] == 1
    assert sent == ["sam@example.com"]


def test_one_bad_address_does_not_lose_the_rest(account, registry):
    registry.create_user(account_id=account.account_id, name="Second Person",
                         email="second@example.com", password="Passw0rd!123", role="Site Lead")

    def flaky(ws, acct, to, subject, text):
        if to == "sam@example.com":
            raise HTTPException(400, "Recipient rejected")
        return {"sent": True}

    body = build_app(account, registry, sender=flaky).post("/api/todo-list/send", json={
        "roles": ["Site Lead"], "account_id": "acct", "confirm": True}).json()
    assert body["sent"] == 1 and body["failed"] == 1
    assert body["details"]["failed"][0]["email"] == "sam@example.com"
    assert "Recipient rejected" in body["details"]["failed"][0]["reason"]


def test_sending_without_a_connected_account_is_refused(account, registry):
    client = build_app(account, registry)  # no MAIL_SENDERS published
    refused = client.post("/api/todo-list/send", json={
        "roles": ["Site Lead"], "account_id": "acct", "confirm": True})
    assert refused.status_code == 503
    assert "Connect a Google or Microsoft account" in refused.json()["detail"]


def test_sending_to_nobody_is_refused(account, registry):
    client = build_app(account, registry, sender=lambda *a: None)
    refused = client.post("/api/todo-list/send", json={
        "roles": ["Nobody Has This"], "account_id": "acct", "confirm": True})
    assert refused.status_code == 422
    assert "No active users" in refused.json()["detail"]


def test_a_custom_role_with_the_permission_may_send(account, registry):
    sent = []
    client = build_app(with_role(account, "Sender"), registry,
                       sender=lambda ws, acct, to, *rest: sent.append(to))
    body = client.post("/api/todo-list/send", json={
        "roles": ["Site Lead"], "account_id": "acct", "confirm": True}).json()
    assert body["sent"] == 1 and sent == ["sam@example.com"]
