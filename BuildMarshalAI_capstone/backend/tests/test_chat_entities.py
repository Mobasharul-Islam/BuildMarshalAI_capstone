"""Marshal Chat creating a project or a user from a sentence.

The behaviour worth protecting is what it *refuses* to do: read a value that
was never given, accept a project type or a role that does not exist, or treat
"generate a project document" as a request for a new project.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(BACKEND.parent) not in sys.path:
    sys.path.insert(0, str(BACKEND.parent))

from backend import chat_entities as ce  # noqa: E402

ROLES = [{"label": "Site Supervisor", "value": "Site Supervisor"},
         {"label": "Project Manager", "value": "Project Manager"}]
TYPES = [{"label": "Healthcare", "value": "Healthcare"},
         {"label": "Education", "value": "Education"}]
CHOICES = {"role": ROLES, "type": TYPES}


# ── What counts as a creation request ────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("create a project called Riverside Tower", "project"),
    ("set up a Healthcare project \"Mill Lane Clinic\"", "project"),
    ("create a new commercial project for the trust", "project"),
    ("start a job called Bridge Deck Repairs", "project"),
    ("add a new user Dana Whitfield as a Site Supervisor", "user"),
    ("register an employee named Callum Byrne", "user"),
    ("add a user to the project", "user"),
    ("create a task for the slab pour", "task"),
    ("make a new vendor called Aquaseal", "vendor"),
    ("create a task type called Survey", "task_type"),
])
def test_detects_the_record_being_asked_for(text: str, expected: str) -> None:
    assert ce.detect_kind(text) == expected


@pytest.mark.parametrize("text", [
    "generate a project document for Harbour Point",
    "create a report on the project",
    "add a note to the project",
    "assign Dana to the project",
    "what is the RFI response period?",
    "schedule a google meet tomorrow at 10",
    "how many projects are there?",
    "draft an email to the architect about the project",
    "",
])
def test_leaves_everything_else_to_document_search(text: str) -> None:
    """A false positive here steals a question from retrieval, so it must not."""
    assert ce.detect_kind(text) == ""


def test_a_noun_reached_through_a_preposition_is_not_the_thing_being_created() -> None:
    assert ce.detect_kind("add a photo to the project") == ""
    assert ce.detect_kind("create a project") == "project"


# ── Reading fields without a model ───────────────────────────────────────

def test_reads_a_project_from_a_sentence() -> None:
    found = ce.read_plainly(
        "project",
        'create a project called Riverside Tower with code RVT-2027 starting 2027-01-11',
        CHOICES)
    assert found["name"] == "Riverside Tower"
    assert found["project_code"] == "RVT-2027"
    assert found["start_date"] == "2027-01-11"


def test_reads_a_person_named_without_the_word_called() -> None:
    found = ce.read_plainly(
        "user",
        "add a new user Dana Whitfield d.whitfield@x.example as a Site Supervisor",
        CHOICES)
    assert found == {"name": "Dana Whitfield",
                     "email": "d.whitfield@x.example",
                     "role": "Site Supervisor"}


def test_a_quoted_name_wins_over_the_rest_of_the_sentence() -> None:
    found = ce.read_plainly("project", 'set up a project "Harbour Point Phase 2"', CHOICES)
    assert found["name"] == "Harbour Point Phase 2"


def test_the_sentence_tail_is_not_part_of_the_name() -> None:
    found = ce.read_plainly(
        "project", "create a project called Mill Lane with code ML-2027", CHOICES)
    assert found["name"] == "Mill Lane"


def test_nothing_is_read_when_nothing_is_given() -> None:
    assert ce.read_plainly("project", "create a project", CHOICES) == {}


# ── Refusing to invent ───────────────────────────────────────────────────

def test_a_role_that_does_not_exist_is_dropped_not_guessed() -> None:
    """The nearest match is still a guess, and guessing is the whole problem."""
    kept = ce.clean_fields("user", {"name": "A", "role": "Site Supervisior"}, CHOICES)
    assert "role" not in kept
    assert kept["name"] == "A"


def test_a_project_type_that_does_not_exist_is_dropped() -> None:
    kept = ce.clean_fields("project", {"name": "A", "type": "Hospitality"}, CHOICES)
    assert "type" not in kept


def test_a_reference_that_exists_is_kept_with_the_stored_spelling() -> None:
    kept = ce.clean_fields("project", {"name": "A", "type": "healthcare"}, CHOICES)
    assert kept["type"] == "Healthcare"


def test_a_value_outside_an_enum_is_dropped() -> None:
    kept = ce.clean_fields("project", {"name": "A", "status": "Nearly done"}, CHOICES)
    assert "status" not in kept
    assert ce.clean_fields("project", {"status": "on hold"}, CHOICES)["status"] == "On Hold"


def test_fields_the_schema_does_not_have_are_dropped() -> None:
    kept = ce.clean_fields("project", {"name": "A", "invented_field": "x"}, CHOICES)
    assert kept == {"name": "A"}


# ── What the form still has to collect ───────────────────────────────────

def test_missing_comes_from_the_schema_then_from_what_chat_insists_on() -> None:
    """The schema's required fields first, then the ones chat will not skip."""
    gaps = [row["name"] for row in ce.outstanding("project", {})]
    assert gaps == ["name", "project_code", "manager", "start_date"]


def test_every_gap_says_who_collects_it() -> None:
    for kind in ce.CHAT_KINDS:
        for row in ce.outstanding(kind, {}):
            assert row["asked_in"] in ("chat", "form"), (kind, row)


def test_a_user_is_asked_for_a_password_and_a_role() -> None:
    """Neither is in the user schema, but POST /api/users requires both."""
    gaps = [row["name"] for row in ce.outstanding("user", {"name": "A", "email": "a@b.co"})]
    assert gaps == ["password", "role"]


def test_nothing_is_asked_for_twice() -> None:
    gaps = [row["name"] for row in ce.outstanding("user", {})]
    assert len(gaps) == len(set(gaps))


def test_a_complete_project_asks_for_nothing() -> None:
    assert ce.outstanding("project", {"name": "A", "project_code": "A-1",
                                      "manager": "Dana", "start_date": "2027-01-11"}) == []


# ── Parsing what a model returns ─────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    '{"fields": {"name": "Riverside"}}',
    '```json\n{"fields": {"name": "Riverside"}}\n```',
    'Here you go:\n{"fields": {"name": "Riverside"}}\nHope that helps.',
    '{"name": "Riverside"}',
])
def test_reads_the_json_a_model_actually_sends(raw: str) -> None:
    assert ce.parse_model_fields(raw)["name"] == "Riverside"


@pytest.mark.parametrize("raw", ["", "I could not work that out.", "[1, 2, 3]", "null"])
def test_an_unusable_reply_reads_as_nothing_rather_than_raising(raw: str) -> None:
    assert ce.parse_model_fields(raw) == {}


def test_the_prompt_lists_only_records_that_exist() -> None:
    prompt = ce.build_prompt("project", "create a project", {}, CHOICES)
    assert "Healthcare" in prompt and "Education" in prompt
    assert "Never invent" in prompt
    # Every schema field is described, so the model is never asked to guess one.
    assert "project_code" in prompt and "REQUIRED" in prompt


def test_the_prompt_names_a_reference_with_no_records_yet() -> None:
    prompt = ce.build_prompt("user", "create a user", {}, {"role": []})
    assert "(none exist yet)" in prompt


# ── The route ────────────────────────────────────────────────────────────

PROJECT_ID = "p-padma"
PROJECT_NAME = "Padma View Specialised Hospital Extension"


class Workspace:
    def load_mgmt(self):
        return {"project_types": [{"id": "1", "name": "Healthcare"}],
                "task_types": [{"id": "t1", "name": "Survey"}],
                "trades": [], "vendors": []}

    def load_roles(self):
        return [{"id": "r1", "name": "Site Supervisor", "permissions": []}]

    def load_projects(self):
        return {PROJECT_ID: {"id": PROJECT_ID, "name": PROJECT_NAME,
                             "project_code": "PVH-2026"},
                "p-other": {"id": "p-other", "name": "Mill Lane Clinic",
                            "project_code": "MLC-2027"}}

    def load_tasks(self):
        return {PROJECT_ID: [{"id": "t-1", "name": "Piling stage 1"}]}


#: Everything the create routes guard on, so a context can be built that is
#: allowed to do the thing under test without being allowed to do all of them.
ALL_PERMISSIONS = ("project.create", "task.create", "task_type.manage",
                   "project_type.manage", "project.cost.additional",
                   "project.cost.task")


class Context:
    def __init__(self, admin: bool = True, super_admin: bool = True,
                 permissions=ALL_PERMISSIONS) -> None:
        self.workspace = Workspace()
        self.account_id = "acct"
        self.user_id = "user"
        self._admin = admin
        self._super_admin = super_admin
        self._permissions = set(permissions)

    def can(self, permission: str) -> bool:
        return permission in self._permissions

    def require_admin(self) -> None:
        if not self._admin:
            raise HTTPException(403, "This action requires an account administrator")

    def require_super_admin(self) -> None:
        if not self._super_admin:
            raise HTTPException(403, "This action requires a Super Admin")


def build_client(context: Context, reply: str = "") -> TestClient:
    app = FastAPI()

    async def vl_generate(prompt, max_tokens=0):
        return reply

    ce.register_chat_entity_routes({
        "app": app, "require_account": lambda: context, "vl_generate": vl_generate,
    })
    return TestClient(app)


def test_a_question_is_reported_as_no_intent() -> None:
    response = build_client(Context()).post(
        "/api/assistant/entities/interpret", json={"text": "what is the RFI period?"})
    assert response.status_code == 200
    assert response.json() == {"supported": False, "kind": "", "reason": "no_intent"}


def test_a_task_cost_hangs_off_a_task() -> None:
    """It is the cost field of a task, so the task is what it needs first."""
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": "add a task cost of 5000 taka"}).json()
    assert body["supported"] is True
    assert body["kind"] == "task_cost"
    assert body["parent"]["kind"] == "task"
    assert body["chat_missing"][0]["name"] == ce.PARENT_FIELD


# ── The kinds chat can now create ────────────────────────────────────────

@pytest.mark.parametrize("kind", [
    "project", "user", "task", "task_type", "project_type",
    "role_type", "trade", "vendor", "project_cost", "procurement",
])
def test_every_supported_kind_has_a_create_route_behind_it(kind: str) -> None:
    """The list is only honest if the application can actually create each one."""
    assert kind in ce.CHAT_KINDS


def test_a_task_names_the_project_it_was_given() -> None:
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": f'create a task "Initial site visit" under {PROJECT_NAME}'}).json()
    assert body["supported"] is True
    assert body["kind"] == "task"
    assert body["parent"]["id"] == PROJECT_ID
    assert body["parent"]["name"] == PROJECT_NAME
    assert body["fields"]["name"] == "Initial site visit"
    # The parent is settled, so it is not asked for again.
    assert ce.PARENT_FIELD not in [row["name"] for row in body["missing"]]


def test_a_task_falls_back_to_the_project_already_open() -> None:
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": 'create a task called Site induction',
              "parent_id": PROJECT_ID}).json()
    assert body["parent"]["id"] == PROJECT_ID


def test_a_named_project_beats_the_one_that_is_open() -> None:
    """Naming one is the more deliberate act of the two."""
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a task for Mill Lane Clinic",
              "parent_id": PROJECT_ID}).json()
    assert body["parent"]["id"] == "p-other"


def test_a_task_with_no_project_asks_for_one_first() -> None:
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a task called Site induction"}).json()
    assert body["ready"] is False
    assert body["missing"][0]["name"] == ce.PARENT_FIELD
    assert body["missing"][0]["reference"] == "project"
    assert body["parent"]["id"] == ""
    # And it offers the projects that exist, rather than a free text box.
    assert {row["id"] for row in body["parent"]["options"]} == {PROJECT_ID, "p-other"}


def test_a_project_that_does_not_exist_is_never_accepted_as_a_parent() -> None:
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a task under Harbour Point Phase 9"}).json()
    assert body["parent"]["id"] == ""
    assert body["missing"][0]["name"] == ce.PARENT_FIELD


def test_a_task_type_is_created_from_chat() -> None:
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": 'create a task type called "Structural Inspection"'}).json()
    assert body["supported"] is True
    assert body["kind"] == "task_type"
    assert body["fields"]["name"] == "Structural Inspection"
    assert body["ready"] is True


def test_a_task_type_without_a_name_is_asked_for_it() -> None:
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret", json={"text": "create a task type"}).json()
    assert body["ready"] is False
    assert [row["name"] for row in body["missing"]] == ["name"]


def test_managing_catalogues_is_still_a_permission() -> None:
    context = Context(permissions=("project.create",))
    response = build_client(context).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a task type called Survey"})
    assert response.status_code == 403


def test_only_a_super_admin_is_offered_the_role_form() -> None:
    response = build_client(Context(super_admin=False)).post(
        "/api/assistant/entities/interpret",
        json={"text": 'create a role called "Site Engineer"'})
    assert response.status_code == 403


def test_the_form_is_described_by_the_schema() -> None:
    """The client renders from this, so it has to carry every field."""
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a task", "parent_id": PROJECT_ID}).json()
    names = [field["name"] for field in body["spec"]["fields"]]
    assert "name" in names and "priority" in names and "due_date" in names
    priority = next(f for f in body["spec"]["fields"] if f["name"] == "priority")
    assert priority["options"] == ["Low", "Normal", "High", "Urgent"]


def test_a_project_is_read_and_reported_complete() -> None:
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a project called Riverside Tower with code RVT-2027"}).json()
    assert body["supported"] is True
    assert body["fields"]["name"] == "Riverside Tower"
    assert body["fields"]["project_code"] == "RVT-2027"


def test_a_project_without_a_code_names_what_is_missing() -> None:
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": 'create a project called "Mill Lane Clinic"'}).json()
    assert body["ready"] is False
    assert [row["name"] for row in body["missing"]] == [
        "project_code", "manager", "start_date"]
    assert body["missing"][0]["label"]


def test_the_model_fills_what_the_patterns_cannot() -> None:
    reply = '{"fields": {"name": "Bridge Deck", "project_code": "BDR-2027"}}'
    body = build_client(Context(), reply).post(
        "/api/assistant/entities/interpret",
        json={"text": "open a job for the bridge deck repairs, reference BDR-2027"}).json()
    assert body["fields"]["name"] == "Bridge Deck"
    assert body["source"] == "model"


def test_a_model_inventing_a_project_type_is_ignored() -> None:
    reply = '{"fields": {"name": "X", "project_code": "X-1", "type": "Hospitality"}}'
    body = build_client(Context(), reply).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a project called X code X-1"}).json()
    assert "type" not in body["fields"]


def test_an_unreachable_model_falls_back_to_the_patterns() -> None:
    app = FastAPI()
    context = Context()

    async def broken(prompt, max_tokens=0):
        raise RuntimeError("no model here")

    ce.register_chat_entity_routes(
        {"app": app, "require_account": lambda: context, "vl_generate": broken})
    body = TestClient(app).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a project called Riverside Tower code RVT-2027"}).json()
    assert body["fields"]["name"] == "Riverside Tower"
    assert body["source"] == "text"


def test_creating_a_project_needs_the_permission() -> None:
    response = build_client(Context(permissions=())).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a project called X"})
    assert response.status_code == 403


def test_creating_a_user_needs_an_administrator() -> None:
    response = build_client(Context(admin=False)).post(
        "/api/assistant/entities/interpret",
        json={"text": "add a user called Dana"})
    assert response.status_code == 403


def test_known_fields_carry_across_turns() -> None:
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": "the code is MLC-2027", "kind": "project",
              "known": {"name": "Mill Lane Clinic"}}).json()
    assert body["fields"]["name"] == "Mill Lane Clinic"


def test_interpretation_creates_nothing() -> None:
    """The route reads; the ordinary create routes write."""
    context = Context()
    before = dict(context.workspace.load_projects())
    build_client(context).post(
        "/api/assistant/entities/interpret",
        json={"text": "create a project called Riverside code RVT-1"})
    assert context.workspace.load_projects() == before


# ── Reading the sentence for the kinds that were added ───────────────────

def test_a_date_written_in_words_is_read() -> None:
    """Site offices write "4th May 2026" far more often than 04/05/2026."""
    found = ce.read_plainly(
        "task", 'create a task "Initial site visit" starting 4th May 2026 '
                'ending 8th May 2026', {})
    assert found["start_time"] == "2026-05-04"
    assert found.get("archived") is None


def test_both_ways_round_are_read() -> None:
    assert ce.read_any_date("May 8th, 2026") == "2026-05-08"
    assert ce.read_any_date("8 May 2026") == "2026-05-08"
    assert ce.read_any_date("2026-05-08") == "2026-05-08"
    assert ce.read_any_date("08/05/2026") == "2026-05-08"
    assert ce.read_any_date("sometime in spring") == ""


def test_a_priority_is_only_taken_when_it_is_written() -> None:
    found = ce.read_plainly("task", "create an urgent task called Slab pour", {})
    assert found["priority"] == "Urgent"
    assert ce.read_plainly("task", "create a task called Slab pour", {}) == {
        "name": "Slab pour"}


def test_an_amount_needs_to_look_like_money() -> None:
    marked = ce.read_plainly("project_cost", "add a cost called Crane hire of 45,000 taka", {})
    assert marked["amount"] == "45000"
    # A bare number is far more often a quantity or a floor level.
    bare = ce.read_plainly("project_cost", "add a cost called Crane hire 45000", {})
    assert "amount" not in bare


def test_one_person_does_not_fill_every_field_that_names_a_person() -> None:
    """A task has both an assignee and an on-site worker; one name is one answer."""
    people = [{"id": "u1", "label": "Dana Whitfield", "detail": ""}]
    found = ce.read_plainly("task", "create a task for Dana Whitfield",
                            {"assignee": people, "field_worker": people})
    assert found.get("assignee") == "Dana Whitfield"
    assert "field_worker" not in found


def test_a_record_that_exists_is_matched_and_one_that_does_not_is_not() -> None:
    rows = [{"id": "1", "label": "Healthcare"}, {"id": "2", "label": "Education"}]
    assert ce.match_existing_record("a Healthcare project", rows)["id"] == "1"
    assert ce.match_existing_record("a Hospitality project", rows) == {}


def test_the_longest_matching_name_wins() -> None:
    rows = [{"id": "short", "label": "Padma View"},
            {"id": "long", "label": "Padma View Specialised Hospital Extension"}]
    found = ce.match_existing_record(
        "a task under Padma View Specialised Hospital Extension", rows)
    assert found["id"] == "long"


def test_a_word_inside_the_name_is_not_also_a_field() -> None:
    """"Rebar inspection" is a task called that, not a task in the Rebar trade."""
    trades = [{"id": "t1", "label": "Rebar", "detail": ""}]
    found = ce.read_plainly("task", "create a task called Rebar inspection",
                            {"trade": trades})
    assert found["name"] == "Rebar inspection"
    assert "trade" not in found


def test_a_trade_stated_outside_the_name_is_still_read() -> None:
    trades = [{"id": "t1", "label": "Rebar", "detail": ""}]
    found = ce.read_plainly("task", 'create a task "Slab pour" for the Rebar trade',
                            {"trade": trades})
    assert found["name"] == "Slab pour"
    assert found["trade"] == "Rebar"


def test_an_end_date_closes_what_the_start_opened() -> None:
    found = ce.read_plainly(
        "task", 'create a task "Site visit" starting 4th May 2026 ending 8th May 2026', {})
    assert found["start_time"] == "2026-05-04"
    assert found["end_time"] == "2026-05-08"
    assert "due_date" not in found


def test_a_due_date_is_read_as_the_due_date() -> None:
    found = ce.read_plainly("task", 'create a task "Site visit" due 8th May 2026', {})
    assert found["due_date"] == "2026-05-08"
    assert "end_time" not in found


def test_for_names_the_record_when_it_names_nothing_else() -> None:
    found = ce.read_plainly("task", "create a task for Initial Survey", {})
    assert found["name"] == "Initial Survey"


def test_the_name_stops_before_the_amount() -> None:
    found = ce.read_plainly("project_cost", "add a cost called Crane hire of 45,000 taka", {})
    assert found["name"] == "Crane hire"
    assert found["amount"] == "45000"


# ── Collecting across turns ──────────────────────────────────────────────
#
# The two flows the specification describes, driven through the route the way
# the client drives it: each turn sends what is settled and what was asked.


def converse(client, messages, kind="", parent_id=""):
    """Run a collection the way the client does, returning every reply."""
    known: dict = {}
    asking: list = []
    replies = []
    for message in messages:
        body = client.post("/api/assistant/entities/interpret", json={
            "text": message, "kind": kind or "", "known": known,
            "asking": asking, "parent_id": parent_id}).json()
        if body.get("supported"):
            kind = body["kind"]
            known = body["fields"]
            asking = [row["name"] for row in body.get("chat_missing", [])]
        replies.append(body)
    return replies


def test_flow_one_information_provided_together() -> None:
    replies = converse(build_client(Context()), [
        'Create a project called "Website Redesign".',
        "Project manager is John and start date is October 1 2027, code WR-2027",
    ])
    first, second = replies
    # Nothing is ready yet, so no form would open.
    assert first["ready"] is False
    assert [row["name"] for row in first["chat_missing"]] == [
        "project_code", "manager", "start_date"]
    # And now everything is known, from one further message.
    assert second["ready"] is True
    assert second["fields"]["name"] == "Website Redesign"
    assert second["fields"]["manager"] == "John"
    assert second["fields"]["start_date"] == "2027-10-01"
    assert second["fields"]["project_code"] == "WR-2027"


def test_flow_two_information_provided_piece_by_piece() -> None:
    replies = converse(build_client(Context()), [
        'Create a project called "Website Redesign".',
        "WR-2027",
        "John is the project manager",
        "October 1 2027",
    ])
    assert [reply["ready"] for reply in replies] == [False, False, False, True]
    # Each turn keeps what the ones before it settled.
    assert [row["name"] for row in replies[1]["chat_missing"]] == ["manager", "start_date"]
    assert [row["name"] for row in replies[2]["chat_missing"]] == ["start_date"]
    final = replies[-1]["fields"]
    assert final["name"] == "Website Redesign"
    assert final["project_code"] == "WR-2027"
    assert final["manager"] == "John"
    assert final["start_date"] == "2027-10-01"


def test_nothing_settled_is_ever_asked_for_again() -> None:
    replies = converse(build_client(Context()), [
        'Create a project called "Website Redesign".', "WR-2027", "John"])
    for reply in replies[1:]:
        asked = [row["name"] for row in reply["chat_missing"]]
        assert "name" not in asked
    assert "project_code" not in [row["name"] for row in replies[2]["chat_missing"]]


def test_an_unreadable_answer_is_asked_for_again_rather_than_invented() -> None:
    replies = converse(build_client(Context()), [
        'Create a project called "Website Redesign".', "WR-2027", "John",
        "sometime in the spring"])
    last = replies[-1]
    assert last["ready"] is False
    assert [row["name"] for row in last["chat_missing"]] == ["start_date"]
    assert "start_date" not in last["fields"]


def test_a_role_nobody_has_is_not_accepted_as_an_answer() -> None:
    """The answer names a record, so a name that names nothing is no answer."""
    replies = converse(build_client(Context()), [
        "add a user Dana Whitfield dana@x.example", "Site Engineer"])
    assert "role" not in replies[-1]["fields"]
    assert "role" in [row["name"] for row in replies[-1]["chat_missing"]]


def test_a_password_is_the_forms_to_collect_not_chat_s() -> None:
    """Nobody should be asked to type a password into a conversation."""
    body = build_client(Context()).post(
        "/api/assistant/entities/interpret",
        json={"text": "add a user Dana Whitfield dana@x.example as a Site Supervisor"}).json()
    assert "password" in [row["name"] for row in body["missing"]]
    assert "password" not in [row["name"] for row in body["chat_missing"]]
    # So there is nothing left to ask, and the form can open.
    assert body["ready"] is True


def test_a_date_with_no_year_is_read_as_the_next_one() -> None:
    from datetime import date
    settled = ce.read_loose_date("October 1")
    assert settled.endswith("-10-01")
    assert date.fromisoformat(settled) >= date.today()


def test_a_bare_answer_goes_to_the_one_field_that_can_hold_it() -> None:
    """"John" is no date, so with a manager and a start date open it is the manager."""
    assert ce.read_answer("project", "John", ["manager", "start_date"], {}) == {"manager": "John"}
    assert ce.read_answer("project", "October 1 2027", ["manager", "start_date"], {}) == {
        "start_date": "2027-10-01"}


def test_a_bare_answer_two_fields_could_hold_is_refused() -> None:
    """Two free-text fields open, and a bare phrase names neither of them."""
    assert ce.read_answer("project", "Riverside", ["manager", "description"], {}) == {}


def test_the_parents_name_is_not_also_the_records_name() -> None:
    """Answering "which project?" names the project, and nothing else."""
    client = build_client(Context())
    first = client.post("/api/assistant/entities/interpret",
                        json={"text": "Create a task"}).json()
    assert first["chat_missing"][0]["name"] == ce.PARENT_FIELD
    second = client.post("/api/assistant/entities/interpret", json={
        "text": PROJECT_NAME, "kind": "task", "known": first["fields"],
        "asking": [row["name"] for row in first["chat_missing"]]}).json()
    assert second["parent"]["id"] == PROJECT_ID
    assert "name" not in second["fields"]
    assert second["ready"] is False
    assert [row["name"] for row in second["chat_missing"]] == ["name"]


def test_the_task_name_then_completes_it() -> None:
    client = build_client(Context())
    known: dict = {}
    asking: list = []
    parent_id = ""
    body: dict = {}
    for message in ("Create a task", PROJECT_NAME, "Site mobilisation"):
        body = client.post("/api/assistant/entities/interpret", json={
            "text": message, "kind": "task", "known": known,
            "asking": asking, "parent_id": parent_id}).json()
        known = body["fields"]
        asking = [row["name"] for row in body["chat_missing"]]
        parent_id = (body.get("parent") or {}).get("id", "")
    assert body["ready"] is True
    assert body["fields"]["name"] == "Site mobilisation"
    assert parent_id == PROJECT_ID
