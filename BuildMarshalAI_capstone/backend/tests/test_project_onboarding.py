"""Onboarding an existing project from its documents.

The rule the whole feature rests on is that analysis, editing, and selection
touch a draft and nothing else; only a confirmed commit writes a project, a
task, a user, a catalogue entry, or a role.  Most of what follows is there to
keep that true, and to keep the hierarchy honest on the way.
"""

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.project_onboarding import (
    response_key,
    pending_question,
    describe_entities_for_model,
    ITEM_KINDS,
    ITEM_KINDS,
    EXTRACTION_PASSES,
    add_item,
    ancestors_of,
    apply_operations,
    build_command_prompt,
    build_extraction_prompt,
    build_plan,
    cascade_deselect,
    commit_draft,
    delete_item,
    dependencies_of,
    descendants_of,
    describe_draft_for_model,
    draft_summary,
    draft_view,
    find_item,
    item_status,
    make_item,
    match_existing,
    merge_extraction,
    new_draft,
    normalise_fields,
    parse_command_response,
    parse_extraction,
    register_project_onboarding_routes,
    resolve_selection,
    set_selection,
    temporary_password,
    update_item,
    validate_item,
)
from backend.company_settings import catalog_entry
from backend.entity_schema import ENTITIES, missing_required
from backend.project_management import make_procurement_item
from backend.tasks import make_task
from backend.user_roles import make_role


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_project(data):
    """Stands in for the notebook's project constructor, field for field."""
    import uuid
    from datetime import datetime, timezone

    return {
        "id": str(uuid.uuid4()),
        "name": data.get("name", "").strip(),
        "project_code": data.get("project_code", "").strip(),
        "manager": data.get("manager", "").strip(),
        "type": data.get("type", "").strip(),
        "status": data.get("status", "Active").strip(),
        "start_date": data.get("start_date", ""),
        "end_date": data.get("end_date", ""),
        "description": data.get("description", "").strip(),
        "address_line1": data.get("address_line1", "").strip(),
        "address_line2": data.get("address_line2", "").strip(),
        "city": data.get("city", "").strip(),
        "state": data.get("state", "").strip(),
        "postal_code": data.get("postal_code", "").strip(),
        "country": data.get("country", "").strip(),
        "currency": str(data.get("currency") or "USD").strip().upper(),
        "archived": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def seeded_draft():
    """A small draft: one project, a parent task, a subtask, and a person."""
    draft = new_draft("Riverside")
    project = add_item(draft, "project", {"fields": {"name": "Riverside Tower", "project_code": "RVT"}})
    parent = add_item(draft, "task", {
        "fields": {"name": "Structure"}, "parent_ref": project["id"],
    })
    child = add_item(draft, "task", {
        "fields": {"name": "Pour slab"}, "parent_ref": project["id"], "parent_id": parent["id"],
    })
    person = add_item(draft, "user", {
        "fields": {"name": "Sam Okafor", "email": "sam@example.com"},
        "project_refs": [project["id"]],
    })
    return draft, project, parent, child, person


# ── field coercion ────────────────────────────────────────────────────────────

def test_only_the_live_records_fields_survive_normalisation():
    fields = normalise_fields("task", {
        "name": "  Pour slab  ", "status": "in progress", "priority": "urgent",
        "id": "hacked", "project_id": "elsewhere",
    })
    assert fields["name"] == "Pour slab"
    assert fields["status"] == "In Progress" and fields["priority"] == "Urgent"
    assert "id" not in fields and "project_id" not in fields
    # A cost is its own draft entity, so it is not a task field here.
    assert normalise_fields("task_cost", {"amount": "1200.5"})["amount"] == 1200.5


def test_an_unrecognised_status_is_refused_rather_than_guessed_at():
    """Settling for the nearest option is exactly the guessing to avoid."""
    with pytest.raises(HTTPException) as error:
        normalise_fields("task", {"name": "x", "status": "Nearly done"})
    assert "must be one of" in str(error.value.detail)
    with pytest.raises(HTTPException):
        normalise_fields("project", {"name": "x", "status": "??"})


def test_an_enum_the_document_wrote_in_another_case_still_lands():
    assert normalise_fields("task", {"status": "in progress"})["status"] == "In Progress"


@pytest.mark.parametrize("written,expected", [
    ("2027-03-01", "2027-03-01"),
    ("2027/3/1", "2027-03-01"),
    ("01/03/2027", "2027-03-01"),
    ("2027-03-01T08:00:00Z", "2027-03-01"),
    ("some time in spring", ""),
])
def test_dates_are_normalised_however_the_document_wrote_them(written, expected):
    assert normalise_fields("project", {"name": "x", "start_date": written})["start_date"] == expected


def test_a_role_keeps_only_permissions_this_build_defines():
    fields = normalise_fields("role_type", {
        "name": "Site Lead", "permissions": ["task.create", "not.a.permission"],
    })
    assert fields["permissions"] == ["task.create"]


def test_an_edit_leaves_the_fields_it_did_not_mention_alone():
    """A patch must not write the defaults of every field it never sent.

    "Set the due date" arriving from the command bar once reset the status
    and cleared the email, because creation defaults were applied to an edit.
    """
    draft = new_draft()
    person = add_item(draft, "user", {"fields": {
        "name": "Sam", "email": "sam@example.com", "status": "Inactive",
        "department": "Field",
    }})
    update_item(draft, person["id"], {"fields": {"department": "Operations"}})
    assert person["fields"]["email"] == "sam@example.com"
    assert person["fields"]["status"] == "Inactive"
    assert person["fields"]["department"] == "Operations"

    project = add_item(draft, "project", {"fields": {"name": "Riverside", "status": "On Hold"}})
    task = add_item(draft, "task", {
        "fields": {"name": "Pour slab", "status": "Blocked", "priority": "High"},
        "parent_ref": project["id"],
    })
    update_item(draft, task["id"], {"fields": {"due_date": "2027-03-01"}})
    assert task["fields"]["status"] == "Blocked" and task["fields"]["priority"] == "High"
    update_item(draft, project["id"], {"fields": {"manager": "Dana"}})
    assert project["fields"]["status"] == "On Hold"


def test_an_edit_still_snaps_an_enum_it_did_send():
    draft, _project, _parent, child, _person = seeded_draft()
    update_item(draft, child["id"], {"fields": {"status": "completed"}})
    assert child["fields"]["status"] == "Completed"


def test_a_negative_cost_is_refused():
    with pytest.raises(HTTPException) as error:
        normalise_fields("task_cost", {"amount": -5})
    assert error.value.status_code == 422


# ── validation ────────────────────────────────────────────────────────────────

def test_a_task_with_no_project_is_incomplete_and_says_so():
    draft = new_draft()
    orphan = add_item(draft, "task", {"fields": {"name": "Floating"}})
    status = item_status(draft, orphan)
    assert status["complete"] is False
    assert [row["label"] for row in status["missing"]] == ["Project"]


def test_a_task_pointed_at_something_that_is_not_a_project_is_refused():
    draft, _project, _parent, _child, person = seeded_draft()
    with pytest.raises(HTTPException) as error:
        add_item(draft, "task", {"fields": {"name": "Wrong"}, "parent_ref": person["id"]})
    assert "not in this draft" in str(error.value.detail)


def test_a_subtask_cannot_sit_under_a_task_in_another_project():
    draft, project, parent, _child, _person = seeded_draft()
    other = add_item(draft, "project", {"fields": {"name": "Harbour", "project_code": "HBR"}})
    with pytest.raises(HTTPException) as error:
        add_item(draft, "task", {
            "fields": {"name": "Cross"}, "parent_ref": other["id"], "parent_id": parent["id"],
        })
    assert "same project" in str(error.value.detail)


def test_a_move_that_would_loop_the_hierarchy_is_refused_and_rolled_back():
    draft, _project, parent, child, _person = seeded_draft()
    with pytest.raises(HTTPException) as error:
        update_item(draft, parent["id"], {"parent_id": child["id"]})
    assert "loop" in str(error.value.detail)
    # The refused edit must leave the item exactly as it was.
    assert draft["items"][parent["id"]]["parent_id"] is None


def test_a_user_needs_an_address_that_looks_like_an_email():
    """Not refused on the way in -- reported, so the draft can ask again."""
    draft = new_draft()
    person = add_item(draft, "user", {"fields": {"name": "Sam", "email": "sam-at-example"}})
    status = item_status(draft, person)
    assert status["complete"] is False
    assert "valid email" in status["issues"][0]


def test_an_item_with_no_name_is_incomplete_rather_than_rejected():
    draft = new_draft()
    project = add_item(draft, "project", {"fields": {"project_code": "X"}})
    assert [row["name"] for row in item_status(draft, project)["missing"]] == ["name"]


# ── hierarchy ─────────────────────────────────────────────────────────────────

def test_dependencies_are_the_single_definition_of_the_hierarchy():
    draft, project, parent, child, person = seeded_draft()
    assert dependencies_of(draft["items"][child["id"]]) == [project["id"], parent["id"]]
    assert dependencies_of(draft["items"][project["id"]]) == []
    # A person is an account member, not a child of anything.
    assert dependencies_of(draft["items"][person["id"]]) == []


def test_ancestors_and_descendants_walk_the_whole_chain():
    draft, project, parent, child, _person = seeded_draft()
    assert set(ancestors_of(draft["items"], child["id"])) == {project["id"], parent["id"]}
    assert set(descendants_of(draft["items"], project["id"])) == {parent["id"], child["id"]}
    assert descendants_of(draft["items"], child["id"]) == []


def test_selecting_a_subtask_pulls_in_its_parent_chain_and_project():
    draft, project, parent, child, _person = seeded_draft()
    resolved = resolve_selection(draft, [child["id"]])
    assert set(resolved["selection"]) == {project["id"], parent["id"], child["id"]}
    assert set(resolved["added_parents"]) == {project["id"], parent["id"]}


def test_selecting_something_that_is_not_in_the_draft_is_reported_not_ignored():
    draft, project, _parent, _child, _person = seeded_draft()
    resolved = resolve_selection(draft, [project["id"], "it-nonsense"])
    assert resolved["unknown"] == ["it-nonsense"]
    assert "it-nonsense" not in resolved["selection"]


def test_deselecting_a_project_takes_its_tasks_with_it():
    draft, project, parent, child, _person = seeded_draft()
    assert set(cascade_deselect(draft, [project["id"]])) == {parent["id"], child["id"]}


def test_deleting_a_project_removes_its_tasks_and_clears_memberships():
    draft, project, parent, child, person = seeded_draft()
    removed = delete_item(draft, project["id"])
    assert set(removed) == {project["id"], parent["id"], child["id"]}
    assert person["id"] in draft["items"]
    assert draft["items"][person["id"]]["project_refs"] == []
    assert draft["selection"] == [person["id"]]


# ── extraction parsing ────────────────────────────────────────────────────────

def test_a_fenced_reply_is_read_just_like_a_bare_one():
    payload = '```json\n{"projects": [{"name": "Riverside", "project_code": "RVT"}]}\n```'
    parsed = parse_extraction(payload)
    assert parsed["project"][0]["fields"]["name"] == "Riverside"


def test_an_unreadable_reply_yields_nothing_rather_than_raising():
    parsed = parse_extraction("I could not find anything useful in this document.")
    assert parsed == {kind: [] for kind in ITEM_KINDS}


def test_entries_without_a_name_are_dropped():
    parsed = parse_extraction(json.dumps({"tasks": [{"name": ""}, {"name": "Real"}, "junk"]}))
    assert [row["fields"]["name"] for row in parsed["task"]] == ["Real"]


def test_the_extraction_prompt_carries_page_numbers_and_the_permission_menu():
    document = {"name": "Schedule.pdf", "pages": [
        {"page_num": 1, "text_content": "Riverside Tower schedule"},
        {"page_num": 2, "text_content": "Pour slab 2027-03-01"},
    ]}
    prompt = build_extraction_prompt(EXTRACTION_PASSES[0], document, "focus on the structure")
    assert "[page 1]" in prompt and "[page 2]" in prompt
    assert "Schedule.pdf" in prompt
    assert "focus on the structure" in prompt
    assert "task.create" in prompt  # the permission catalogue the model may pick from


# ── merging an extraction into a draft ────────────────────────────────────────

EXTRACTED = {
    "projects": [{"name": "Riverside Tower", "project_code": "RVT", "manager": "Dana"}],
    "tasks": [
        {"name": "Pour slab", "parent": "Riverside Tower", "parent_task": "Structure"},
        {"name": "Structure", "parent": "Riverside Tower", "parent_task": ""},
        {"name": "Cure slab", "parent": "Riverside Tower", "parent_task": "Pour slab"},
    ],
    "users": [{"name": "Sam Okafor", "email": "SAM@example.com", "parent": "Riverside Tower"}],
    "task_types": [{"name": "Concrete"}],
    "role_types": [{"name": "Site Lead", "permissions": ["task.create"]}],
}


def test_a_merge_rebuilds_the_hierarchy_the_document_described():
    draft = new_draft()
    outcome = merge_extraction(draft, parse_extraction(json.dumps(EXTRACTED)),
                               {"doc_id": "d1", "doc_name": "Schedule.pdf", "page": 1})
    assert outcome["added"]["project"] == 1 and outcome["added"]["task"] == 3

    by_name = {item["fields"]["name"]: item for item in draft["items"].values()}
    project = by_name["Riverside Tower"]
    assert by_name["Structure"]["parent_id"] is None
    # A subtask listed before its parent still lands under it.
    assert by_name["Pour slab"]["parent_id"] == by_name["Structure"]["id"]
    assert by_name["Cure slab"]["parent_id"] == by_name["Pour slab"]["id"]
    assert all(by_name[name]["parent_ref"] == project["id"]
               for name in ("Structure", "Pour slab", "Cure slab"))
    assert by_name["Sam Okafor"]["project_refs"] == [project["id"]]
    # Stored as the document wrote it, which is what create_user does.
    assert by_name["Sam Okafor"]["fields"]["email"] == "SAM@example.com"


def test_a_second_document_fills_gaps_instead_of_duplicating_the_project():
    draft = new_draft()
    merge_extraction(draft, parse_extraction(json.dumps({
        "projects": [{"name": "Riverside Tower", "project_code": "RVT"}],
    })), {"doc_id": "d1", "doc_name": "Tender.pdf"})
    outcome = merge_extraction(draft, parse_extraction(json.dumps({
        "projects": [{"name": "riverside tower", "manager": "Dana", "project_code": "OTHER"}],
    })), {"doc_id": "d2", "doc_name": "Contract.pdf"})

    projects = [i for i in draft["items"].values() if i["kind"] == "project"]
    assert len(projects) == 1
    assert outcome["enriched"] == 1
    # A blank field is filled in; one the first document already stated is kept.
    assert projects[0]["fields"]["manager"] == "Dana"
    assert projects[0]["fields"]["project_code"] == "RVT"


def test_a_task_belongs_to_the_only_project_when_the_row_does_not_repeat_its_name():
    draft = new_draft()
    merge_extraction(draft, parse_extraction(json.dumps({
        "projects": [{"name": "Riverside Tower"}],
        "tasks": [{"name": "Pour slab"}],
    })), {"doc_id": "d1", "doc_name": "Schedule.xlsx"})
    by_name = {item["fields"]["name"]: item for item in draft["items"].values()}
    assert by_name["Pour slab"]["parent_ref"] == by_name["Riverside Tower"]["id"]


def test_a_task_with_no_project_at_all_is_dropped_rather_than_orphaned():
    draft = new_draft()
    merge_extraction(draft, parse_extraction(json.dumps({"tasks": [{"name": "Nowhere"}]})), {})
    assert draft["items"] == {}


def test_a_hierarchy_the_app_cannot_hold_leaves_the_task_at_the_project_root():
    draft = new_draft()
    merge_extraction(draft, parse_extraction(json.dumps({
        "projects": [{"name": "Riverside"}],
        # Two tasks naming each other as parent cannot both be satisfied.
        "tasks": [{"name": "A", "parent_task": "B"}, {"name": "B", "parent_task": "A"}],
    })), {})
    tasks = [i for i in draft["items"].values() if i["kind"] == "task"]
    assert len(tasks) == 2
    assert sum(1 for task in tasks if task["parent_id"] is None) >= 1


def test_extracted_items_carry_where_they_came_from():
    draft = new_draft()
    merge_extraction(draft, parse_extraction(json.dumps(EXTRACTED)),
                     {"doc_id": "d1", "doc_name": "Schedule.pdf", "page": 1})
    item = next(iter(draft["items"].values()))
    assert item["source"]["doc_name"] == "Schedule.pdf"
    assert item["origin"] == "extracted"


# ── natural-language editing ──────────────────────────────────────────────────

def test_a_command_reply_is_read_out_of_the_models_json():
    parsed = parse_command_response('{"operations": [{"op": "delete", "target": "Pour slab"}], '
                                    '"reply": "Removed it."}')
    assert parsed["reply"] == "Removed it."
    assert parsed["operations"][0]["op"] == "delete"


def test_a_target_resolves_by_id_then_name_then_email():
    draft, project, _parent, child, person = seeded_draft()
    assert find_item(draft, child["id"])["id"] == child["id"]
    assert find_item(draft, "pour SLAB", "task")["id"] == child["id"]
    assert find_item(draft, "sam@example.com")["id"] == person["id"]
    assert find_item(draft, "Pour slab", "project") is None


def test_an_ambiguous_name_resolves_to_nothing_rather_than_the_wrong_thing():
    draft, project, _parent, _child, _person = seeded_draft()
    add_item(draft, "task", {"fields": {"name": "Structure"}, "parent_ref": project["id"]})
    assert find_item(draft, "Structure") is None


def test_commands_add_edit_move_and_delete_the_draft():
    draft, project, parent, child, _person = seeded_draft()
    outcome = apply_operations(draft, [
        {"op": "update", "target": child["id"], "fields": {"priority": "High", "due_date": "2027-03-01"}},
        {"op": "create", "kind": "task", "fields": {"name": "Strip formwork"},
         "parent": "Riverside Tower", "parent_task": "Structure"},
        {"op": "move", "target": "Pour slab", "parent_task": ""},
        {"op": "delete", "target": "Sam Okafor"},
    ])
    assert [row["op"] for row in outcome["applied"]] == ["update", "create", "move", "delete"]
    assert outcome["skipped"] == []

    by_name = {item["fields"]["name"]: item for item in draft["items"].values()}
    assert by_name["Pour slab"]["fields"]["priority"] == "High"
    assert by_name["Pour slab"]["parent_id"] is None
    assert by_name["Strip formwork"]["parent_id"] == parent["id"]
    assert "Sam Okafor" not in by_name


def test_one_bad_operation_does_not_lose_the_good_ones():
    draft, _project, _parent, child, _person = seeded_draft()
    outcome = apply_operations(draft, [
        {"op": "delete", "target": "A task that was never there"},
        {"op": "update", "target": child["id"], "fields": {"trade": "Concrete"}},
        {"op": "teleport", "target": child["id"]},
        {"op": "create", "kind": "sandwich", "fields": {"name": "Lunch"}},
    ])
    assert [row["op"] for row in outcome["applied"]] == ["update"]
    assert len(outcome["skipped"]) == 3
    assert draft["items"][child["id"]]["fields"]["trade"] == "Concrete"


def test_a_command_that_would_break_the_hierarchy_is_skipped_with_a_reason():
    draft, _project, parent, child, _person = seeded_draft()
    outcome = apply_operations(draft, [
        {"op": "move", "target": parent["id"], "parent_task": "Pour slab"},
    ])
    assert outcome["applied"] == []
    assert "loop" in outcome["skipped"][0]["reason"]


def test_deselecting_a_project_by_command_deselects_its_tasks():
    draft, project, parent, child, _person = seeded_draft()
    apply_operations(draft, [{"op": "deselect", "target": project["id"]}])
    assert project["id"] not in draft["selection"]
    assert parent["id"] not in draft["selection"] and child["id"] not in draft["selection"]


def test_the_command_prompt_lists_the_draft_so_names_can_be_resolved():
    draft, _project, _parent, child, _person = seeded_draft()
    described = describe_draft_for_model(draft)
    assert "Pour slab" in described and child["id"] in described
    assert "project: Riverside Tower" in described
    assert "sam@example.com" in describe_draft_for_model(draft)
    assert "Riverside Tower" in build_command_prompt(draft, "rename it")


# ── matching what already exists ──────────────────────────────────────────────

def test_a_project_matches_on_its_code_before_its_name():
    projects = {"p1": {"id": "p1", "name": "Old name", "project_code": "RVT"}}
    match = match_existing("project", {"name": "Riverside Tower", "project_code": "rvt"},
                           projects=projects)
    assert match["id"] == "p1" and match["on"] == "project code"


def test_a_person_matches_on_email_whatever_the_document_called_them():
    users = [{"id": "u1", "name": "Samuel Okafor", "email": "Sam@Example.com"}]
    match = match_existing("user", {"name": "Sam O.", "email": "sam@example.com"},
                           projects={}, users=users)
    assert match["id"] == "u1"


def test_a_task_matches_only_under_the_same_parent():
    tasks = [{"id": "t1", "name": "Inspection", "parent_id": "t0"}]
    assert match_existing("task", {"name": "Inspection"}, projects={}, tasks=tasks,
                          parent_real_id="t0")["id"] == "t1"
    assert match_existing("task", {"name": "Inspection"}, projects={}, tasks=tasks) is None


def test_a_role_matches_the_builtins_so_super_admin_is_never_recreated():
    assert match_existing("role_type", {"name": "super admin"}, projects={}, roles=[]) is None
    from backend.permissions import BUILTIN_ROLES
    assert match_existing("role_type", {"name": "super admin"}, projects={},
                          roles=list(BUILTIN_ROLES))["label"] == "Head (Super Admin)"


def test_a_project_code_is_asked_for_rather_than_invented():
    """``create_project`` requires one, so making one up would be fabricating
    a mandatory identifier. The draft asks instead."""
    draft = new_draft()
    project = add_item(draft, "project", {"fields": {"name": "Riverside Tower"}})
    assert [row["label"] for row in item_status(draft, project)["missing"]] == ["Project code"]


# ── the confirmation plan ─────────────────────────────────────────────────────

def test_the_plan_says_create_or_reuse_for_every_selected_item():
    draft, project, parent, child, person = seeded_draft()
    plan = build_plan(
        draft,
        projects={"p1": {"id": "p1", "name": "Riverside Tower", "project_code": "RVT"}},
        tasks={"p1": [{"id": "t1", "name": "Structure", "parent_id": None}]},
        users=[], mgmt={}, roles=[],
    )
    rows = {row["name"]: row for row in plan["rows"]}
    # The project and the top-level task are already there; the rest is new.
    assert rows["Riverside Tower"]["action"] == "reuse"
    assert rows["Riverside Tower"]["match"]["on"] == "project code"
    assert rows["Structure"]["action"] == "reuse"
    assert rows["Pour slab"]["action"] == "create"
    assert rows["Pour slab"]["parent"] == "Riverside Tower"
    assert rows["Pour slab"]["nested_under"] == "Structure"
    assert rows["Sam Okafor"]["action"] == "create"
    assert plan["total_reusing"] == 2 and plan["total_creating"] == 2


def test_the_plan_blocks_a_task_whose_project_was_deselected():
    draft, project, parent, child, _person = seeded_draft()
    # Force an inconsistent selection the way only a stale client could.
    draft["selection"] = [parent["id"], child["id"]]
    plan = build_plan(draft, projects={}, tasks={}, users=[], mgmt={}, roles=[])
    assert {row["name"] for row in plan["blocked"]} == {"Structure", "Pour slab"}
    assert plan["rows"] == []


def test_the_plan_blocks_a_person_with_no_email_and_names_the_field():
    draft = new_draft()
    add_item(draft, "user", {"fields": {"name": "Unknown contact"}})
    plan = build_plan(draft, projects={}, tasks={}, users=[], mgmt={}, roles=[])
    blocked = plan["blocked"][0]
    assert blocked["reason"] == "required fields are missing"
    assert [row["label"] for row in blocked["missing"]] == ["Email"]
    # Nothing can be committed while anything selected is incomplete.
    assert plan["can_commit"] is False


def test_a_project_with_no_code_cannot_be_committed():
    draft = new_draft()
    add_item(draft, "project", {"fields": {"name": "Riverside Tower"}})
    plan = build_plan(draft, projects={}, tasks={}, users=[], mgmt={}, roles=[])
    assert plan["rows"] == [] and plan["can_commit"] is False
    assert [row["label"] for row in plan["blocked"][0]["missing"]] == ["Project code"]


# ── committing ────────────────────────────────────────────────────────────────

def commit(draft, context, **kwargs):
    registry = kwargs.pop("registry", context._registry)
    return commit_draft(
        draft, workspace=context.workspace, registry=registry,
        account_id=context.account_id, make_project=_make_project, make_task=make_task,
        catalog_entry=catalog_entry, make_role=make_role,
        make_procurement=make_procurement_item, **kwargs,
    )


@pytest.fixture
def admin(make_account, registry):
    context = make_account("owner@example.com")
    context._registry = registry
    return context


def test_committing_creates_the_whole_hierarchy_for_real(admin):
    draft = new_draft()
    merge_extraction(draft, parse_extraction(json.dumps(EXTRACTED)), {"doc_id": "d1"})
    set_selection(draft, list(draft["items"]))

    result = commit(draft, admin)

    projects = admin.workspace.load_projects()
    assert len(projects) == 1
    project_id, project = next(iter(projects.items()))
    assert project["name"] == "Riverside Tower" and project["project_code"] == "RVT"

    tasks = {task["name"]: task for task in admin.workspace.load_tasks()[project_id]}
    assert set(tasks) == {"Structure", "Pour slab", "Cure slab"}
    assert tasks["Structure"]["parent_id"] is None
    assert tasks["Pour slab"]["parent_id"] == tasks["Structure"]["id"]
    assert tasks["Cure slab"]["parent_id"] == tasks["Pour slab"]["id"]

    assert [entry["name"] for entry in admin.workspace.load_mgmt()["task_types"]
            if entry["name"] == "Concrete"] == ["Concrete"]
    assert [role["name"] for role in admin.workspace.load_roles()] == ["Site Lead"]

    people = {user["email"].lower(): user
              for user in admin._registry.users_for_account(admin.account_id)}
    assert "sam@example.com" in people
    # The person is on the project they were extracted from.
    assert result["memberships"] == 1
    members = admin.workspace.load_projects()[project_id]["members"]
    assert [entry["user_id"] for entry in members] == [people["sam@example.com"]["id"]]
    assert draft["status"] == "committed"


def test_a_persons_project_role_reaches_the_membership(admin):
    draft = new_draft()
    project = add_item(draft, "project", {"fields": {"name": "Riverside", "project_code": "RVT"}})
    add_item(draft, "user", {
        "fields": {"name": "Sam", "email": "sam@example.com", "project_role": "Site supervisor"},
        "project_refs": [project["id"]],
    })
    commit(draft, admin)
    members = next(iter(admin.workspace.load_projects().values()))["members"]
    assert members[0]["project_role"] == "Site supervisor"


def test_a_new_user_gets_a_password_returned_once_and_never_stored(admin):
    draft = new_draft()
    add_item(draft, "user", {"fields": {"name": "Sam", "email": "sam@example.com"}})
    result = commit(draft, admin)

    assert [row["email"] for row in result["credentials"]] == ["sam@example.com"]
    assert len(result["credentials"][0]["password"]) >= 12
    # The draft keeps the outcome, but never the secret.
    assert "credentials" not in draft["commit"]
    assert "password" not in json.dumps(draft)


def test_committing_the_same_documents_twice_reuses_instead_of_duplicating(admin):
    first = new_draft()
    merge_extraction(first, parse_extraction(json.dumps(EXTRACTED)), {"doc_id": "d1"})
    set_selection(first, list(first["items"]))
    commit(first, admin)

    second = new_draft()
    merge_extraction(second, parse_extraction(json.dumps(EXTRACTED)), {"doc_id": "d1"})
    set_selection(second, list(second["items"]))
    result = commit(second, admin)

    assert result["total_created"] == 0
    assert result["total_reused"] == len(second["items"])
    assert len(admin.workspace.load_projects()) == 1
    project_id = next(iter(admin.workspace.load_projects()))
    assert len(admin.workspace.load_tasks()[project_id]) == 3
    assert len(admin.workspace.load_roles()) == 1




def test_a_role_the_account_does_not_have_is_dropped_rather_than_stored(admin):
    draft = new_draft()
    add_item(draft, "user", {"fields": {"name": "Sam", "email": "sam@example.com",
                                        "role": "Chief Imaginary Officer"}})
    commit(draft, admin)
    user = next(u for u in admin._registry.users_for_account(admin.account_id)
                if u["email"] == "sam@example.com")
    assert user["role"] == ""


def test_a_role_created_in_the_same_commit_can_be_assigned_in_it(admin):
    draft = new_draft()
    add_item(draft, "role_type", {"fields": {"name": "Site Lead", "permissions": ["task.create"]}})
    add_item(draft, "user", {"fields": {"name": "Sam", "email": "sam@example.com",
                                        "role": "site lead"}})
    commit(draft, admin)
    user = next(u for u in admin._registry.users_for_account(admin.account_id)
                if u["email"] == "sam@example.com")
    assert user["role"] == "Site Lead"


def test_roles_are_skipped_when_the_caller_is_not_a_super_admin(admin):
    draft = new_draft()
    add_item(draft, "role_type", {"fields": {"name": "Site Lead"}})
    result = commit(draft, admin, allow_roles=False)
    assert admin.workspace.load_roles() == []
    assert result["skipped"][0]["reason"] == "only a Head (Super Admin) can create roles"


def test_an_item_the_plan_blocked_is_not_created(admin):
    draft, project, parent, child, _person = seeded_draft()
    draft["selection"] = [parent["id"], child["id"]]
    draft["_plan_blocked"] = build_plan(draft, projects={}, tasks={}, users=[],
                                        mgmt={}, roles=[])["blocked"]
    result = commit(draft, admin)
    assert result["total_created"] == 0
    assert admin.workspace.load_projects() == {}


def test_only_selected_items_are_created(admin):
    draft, project, parent, _child, person = seeded_draft()
    set_selection(draft, [project["id"], parent["id"]])
    commit(draft, admin)

    project_id = next(iter(admin.workspace.load_projects()))
    assert [task["name"] for task in admin.workspace.load_tasks()[project_id]] == ["Structure"]
    # The unselected subtask and person were left in the draft.
    assert {user["email"] for user in admin._registry.users_for_account(admin.account_id)} == {
        "owner@example.com"}


# ── routes ────────────────────────────────────────────────────────────────────

class FakeModel:
    """Stands in for ``vl_generate``; records prompts and replays replies."""

    def __init__(self, replies=()):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, messages, max_new_tokens=4096, model=None):
        self.prompts.append(messages[-1]["content"][0]["text"])
        return self.replies.pop(0) if self.replies else "{}"


def build_app(context, registry, model=None, documents=None):
    app = FastAPI()
    model = model or FakeModel()
    documents = documents if documents is not None else {}

    async def require_account():
        return context

    def ingest_document(file_path, doc_id, workspace, display_name=None, origin=None):
        """Stands in for the ColPali pipeline: records pages, no embeddings."""
        pages = documents.get(display_name or file_path.name, [
            {"page_num": 1, "text_content": file_path.read_text(encoding="utf-8", errors="replace")},
        ])
        meta = workspace.load_metadata()
        record = {"id": doc_id, "name": display_name or file_path.name,
                  "pages": pages, "page_count": len(pages), "status": "indexed"}
        meta.setdefault("documents", {})[doc_id] = record
        workspace.save_metadata(meta)
        return record

    register_project_onboarding_routes({
        "app": app, "require_account": require_account,
        "ingest_document": ingest_document, "vl_generate": model,
        "_make_project": _make_project, "ACCOUNT_REGISTRY": registry,
        "make_task": make_task, "catalog_entry": catalog_entry, "make_role": make_role,
        "make_procurement_item": make_procurement_item,
    })
    return TestClient(app), model


@pytest.fixture
def onboarding(admin, registry):
    client, model = build_app(admin, registry)
    return admin, client, model


def test_the_whole_flow_from_upload_to_onboard(onboarding, registry, admin):
    client, model = build_app(admin, registry, FakeModel([json.dumps(EXTRACTED)]))

    draft = client.post("/api/onboarding/drafts", json={"name": "Riverside"}).json()
    assert draft["status"] == "draft"

    uploaded = client.post(
        f"/api/onboarding/drafts/{draft['id']}/documents",
        files={"file": ("Schedule.txt", b"Riverside Tower schedule", "text/plain")},
    )
    assert uploaded.status_code == 200 and uploaded.json()["pages"] == 1

    analyzed = client.post(f"/api/onboarding/drafts/{draft['id']}/analyze", json={}).json()
    assert analyzed["summary"]["counts"]["project"] == 1
    assert analyzed["summary"]["counts"]["task"] == 3
    # Analysis is draft-only: nothing exists yet.
    assert admin.workspace.load_projects() == {}

    plan = client.get(f"/api/onboarding/drafts/{draft['id']}/plan").json()
    assert plan["total_creating"] == analyzed["summary"]["total_selected"]

    # A commit without confirmation reports and creates nothing.
    proposed = client.post(f"/api/onboarding/drafts/{draft['id']}/commit", json={}).json()
    assert proposed["confirmation_required"] is True
    assert admin.workspace.load_projects() == {}

    committed = client.post(f"/api/onboarding/drafts/{draft['id']}/commit",
                            json={"confirm": True}).json()
    assert committed["confirmation_required"] is False
    assert committed["counts"]["project"] == 1 and committed["counts"]["task"] == 3
    assert len(admin.workspace.load_projects()) == 1
    assert committed["draft"]["status"] == "committed"
    # The document it was onboarded from is now one of the project's documents.
    (project_id,) = admin.workspace.load_projects()
    source = admin.workspace.load_metadata()["documents"][uploaded.json()["doc_id"]]
    assert source["project_ids"] == [project_id] and committed["documents_linked"] == 1

    # A committed draft cannot be replayed into a second set of records.
    again = client.post(f"/api/onboarding/drafts/{draft['id']}/commit", json={"confirm": True})
    assert again.status_code == 409


def test_analysis_is_refused_until_a_document_is_attached(onboarding):
    _admin, client, _model = onboarding
    draft = client.post("/api/onboarding/drafts", json={}).json()
    response = client.post(f"/api/onboarding/drafts/{draft['id']}/analyze", json={})
    assert response.status_code == 422


def test_editing_a_draft_item_through_the_api_never_touches_live_data(onboarding):
    admin, client, _model = onboarding
    draft = client.post("/api/onboarding/drafts", json={}).json()
    created = client.post(f"/api/onboarding/drafts/{draft['id']}/items", json={
        "kind": "project", "fields": {"name": "Riverside Tower", "project_code": "RVT"},
    })
    assert created.status_code == 201
    item_id = created.json()["item_id"]

    patched = client.patch(f"/api/onboarding/drafts/{draft['id']}/items/{item_id}",
                           json={"fields": {"manager": "Dana"}}).json()
    row = next(item for item in patched["items"] if item["id"] == item_id)
    assert row["fields"]["manager"] == "Dana"
    assert admin.workspace.load_projects() == {}

    removed = client.delete(f"/api/onboarding/drafts/{draft['id']}/items/{item_id}").json()
    assert removed["removed"] == [item_id] and removed["items"] == []


def test_the_selection_route_closes_over_the_hierarchy(onboarding):
    admin, client, _model = onboarding
    draft = client.post("/api/onboarding/drafts", json={}).json()
    project = client.post(f"/api/onboarding/drafts/{draft['id']}/items", json={
        "kind": "project", "fields": {"name": "Riverside"}}).json()["item_id"]
    task = client.post(f"/api/onboarding/drafts/{draft['id']}/items", json={
        "kind": "task", "fields": {"name": "Structure"}, "parent_ref": project,
    }).json()["item_id"]

    response = client.put(f"/api/onboarding/drafts/{draft['id']}/selection",
                          json={"selection": [task]}).json()
    assert set(response["selection"]) == {project, task}
    assert response["added_parents"] == [project]

    # Deselecting the project must leave a task that cannot be created behind.
    dropped = client.put(f"/api/onboarding/drafts/{draft['id']}/selection",
                         json={"selection": []}).json()
    assert dropped["selection"] == []
    rows = {row["id"]: row for row in dropped["items"]}
    assert rows[task]["blocked_by"] == [project]


def test_a_commit_with_nothing_selected_is_refused(onboarding):
    _admin, client, _model = onboarding
    draft = client.post("/api/onboarding/drafts", json={}).json()
    client.post(f"/api/onboarding/drafts/{draft['id']}/items", json={
        "kind": "project", "fields": {"name": "Riverside"}})
    client.put(f"/api/onboarding/drafts/{draft['id']}/selection", json={"selection": []})
    response = client.post(f"/api/onboarding/drafts/{draft['id']}/commit", json={"confirm": True})
    assert response.status_code == 422


def test_a_chat_command_edits_the_draft_and_answers(admin, registry):
    model = FakeModel([json.dumps({
        "operations": [{"op": "add", "kind": "task", "fields": {"name": "Strip formwork"},
                        "project": "Riverside"}],
        "reply": "Added Strip formwork.",
    })])
    client, _ = build_app(admin, registry, model)
    draft = client.post("/api/onboarding/drafts", json={}).json()
    client.post(f"/api/onboarding/drafts/{draft['id']}/items", json={
        "kind": "project", "fields": {"name": "Riverside"}})

    response = client.post(f"/api/onboarding/drafts/{draft['id']}/command",
                           json={"text": "add a task called Strip formwork"}).json()
    assert response["reply"] == "Added Strip formwork."
    assert [row["name"] for row in response["applied"]] == ["Strip formwork"]
    assert "Strip formwork" in {item["fields"]["name"] for item in response["items"]}
    # The interpreter was shown the draft so it could resolve "Riverside".
    assert "Riverside" in model.prompts[0]


def test_a_command_the_model_could_not_interpret_says_so(admin, registry):
    client, _ = build_app(admin, registry, FakeModel(["I am not sure what you mean."]))
    draft = client.post("/api/onboarding/drafts", json={}).json()
    response = client.post(f"/api/onboarding/drafts/{draft['id']}/command",
                           json={"text": "do the thing"}).json()
    assert response["applied"] == []
    assert "could not tell" in response["reply"]


def test_drafts_are_listed_newest_first_and_can_be_deleted(onboarding):
    _admin, client, _model = onboarding
    first = client.post("/api/onboarding/drafts", json={"name": "One"}).json()
    second = client.post("/api/onboarding/drafts", json={"name": "Two"}).json()

    listed = client.get("/api/onboarding/drafts").json()
    assert listed["total"] == 2
    assert {row["id"] for row in listed["drafts"]} == {first["id"], second["id"]}
    assert "items" not in listed["drafts"][0]

    assert client.delete(f"/api/onboarding/drafts/{first['id']}").status_code == 200
    assert client.get("/api/onboarding/drafts").json()["total"] == 1
    assert client.get(f"/api/onboarding/drafts/{first['id']}").status_code == 404


def test_onboarding_is_closed_to_anyone_who_is_not_an_administrator(make_account, registry):
    context = make_account("member@example.com")
    context.user = {**context.user, "is_owner": False, "role": "Viewer"}
    client, _ = build_app(context, registry)
    assert client.get("/api/onboarding/drafts").status_code == 403
    assert client.post("/api/onboarding/drafts", json={}).status_code == 403


def test_a_draft_belongs_to_one_account_only(make_account, registry):
    first = make_account("one@example.com")
    second = make_account("two@example.com")
    client_one, _ = build_app(first, registry)
    client_two, _ = build_app(second, registry)

    draft = client_one.post("/api/onboarding/drafts", json={"name": "Mine"}).json()
    assert client_two.get(f"/api/onboarding/drafts/{draft['id']}").status_code == 404
    assert client_two.get("/api/onboarding/drafts").json()["total"] == 0


# ── presentation ──────────────────────────────────────────────────────────────

def test_the_view_spells_out_what_blocks_each_checkbox():
    draft, project, parent, child, _person = seeded_draft()
    set_selection(draft, [project["id"]])
    rows = {row["id"]: row for row in draft_view(draft)["items"]}
    assert rows[project["id"]]["selected"] is True
    assert rows[child["id"]]["blocked_by"] == [parent["id"]]
    assert set(rows[project["id"]]["dependents"]) == {parent["id"], child["id"]}


def test_the_summary_counts_what_is_there_and_what_is_ticked():
    draft, project, parent, _child, _person = seeded_draft()
    set_selection(draft, [project["id"], parent["id"]])
    summary = draft_summary(draft)
    assert summary["counts"]["task"] == 2 and summary["selected"]["task"] == 1
    assert summary["total"] == 4 and summary["total_selected"] == 2


def test_a_generated_password_is_different_every_time():
    assert temporary_password() != temporary_password()


# ── creating in conversation ──────────────────────────────────────────────────

def test_a_creation_with_nothing_but_a_name_lands_incomplete_and_is_asked_about():
    """The example from the brief: "create a task called Database Migration"."""
    draft = new_draft()
    outcome = apply_operations(draft, [
        {"op": "create", "kind": "task", "fields": {"name": "Database Migration"}},
    ])
    assert [row["op"] for row in outcome["applied"]] == ["create"]

    item = next(iter(draft["items"].values()))
    status = item_status(draft, item)
    assert status["complete"] is False
    assert [row["label"] for row in status["missing"]] == ["Project"]
    # The conversation is now pointed at it.
    assert draft["pending"]["item_id"] == item["id"]


def test_the_follow_up_question_is_built_from_the_schema_not_the_model():
    draft = new_draft()
    apply_operations(draft, [{"op": "create", "kind": "project",
                              "fields": {"name": "Website Redesign"}}])
    question = pending_question(draft, {"project_type": [{"id": "pt1", "label": "Commercial"}]})
    assert "Website Redesign" in question and "Project code" in question


def test_a_question_about_a_reference_field_offers_the_records_that_exist():
    draft, project, _parent, _child, _person = seeded_draft()
    apply_operations(draft, [{"op": "create", "kind": "task_cost", "fields": {"amount": 50000}}])
    question = pending_question(draft, {})
    # Its task was not named, so the draft's own tasks are offered as the answer.
    assert "**Task**" in question
    assert "Structure" in question and "Pour slab" in question


def test_a_question_says_so_when_there_is_nothing_to_choose_from_yet():
    draft = new_draft()
    apply_operations(draft, [{"op": "create", "kind": "task", "fields": {"name": "Orphan"}}])
    assert "add one first" in pending_question(draft, {})


def test_the_conversation_carries_the_missing_fields_across_messages():
    draft = new_draft()
    apply_operations(draft, [{"op": "create", "kind": "project",
                              "fields": {"name": "Website Redesign"}}])
    pending_id = draft["pending"]["item_id"]

    # Second message answers the question.
    apply_operations(draft, [{"op": "update", "target": pending_id,
                              "fields": {"project_code": "WEB-1"}}])
    assert item_status(draft, draft["items"][pending_id])["complete"] is True
    # Nothing left to ask, so the conversation lets go.
    assert draft["pending"] is None
    assert pending_question(draft, {}) == ""


def test_a_creation_that_names_its_parent_is_wired_up_immediately():
    draft, project, parent, _child, _person = seeded_draft()
    apply_operations(draft, [
        {"op": "create", "kind": "task", "fields": {"name": "Strip formwork"},
         "parent": "Riverside Tower", "parent_task": "Structure"},
    ])
    added = next(item for item in draft["items"].values()
                 if item["fields"].get("name") == "Strip formwork")
    assert added["parent_ref"] == project["id"] and added["parent_id"] == parent["id"]
    assert item_status(draft, added)["complete"] is True
    assert draft["pending"] is None


def test_a_single_candidate_parent_is_taken_but_several_are_asked_about():
    draft, project, _parent, _child, _person = seeded_draft()
    apply_operations(draft, [{"op": "create", "kind": "project_cost",
                              "fields": {"name": "Site hoarding", "amount": 12000}}])
    cost = next(item for item in draft["items"].values() if item["kind"] == "project_cost")
    assert cost["parent_ref"] == project["id"]

    add_item(draft, "project", {"fields": {"name": "Harbour", "project_code": "HBR"}})
    apply_operations(draft, [{"op": "create", "kind": "project_cost",
                              "fields": {"name": "Crane hire", "amount": 8000}}])
    ambiguous = next(item for item in draft["items"].values()
                     if item["fields"].get("name") == "Crane hire")
    # Two projects, and the instruction named neither: it is asked, not guessed.
    assert ambiguous["parent_ref"] is None
    assert [row["label"] for row in item_status(draft, ambiguous)["missing"]] == ["Project"]


def test_a_parent_the_draft_does_not_have_is_left_for_the_admin():
    draft = new_draft()
    apply_operations(draft, [{"op": "create", "kind": "task",
                              "fields": {"name": "Database Migration"},
                              "parent": "A project nobody made"}])
    task = next(iter(draft["items"].values()))
    assert task["parent_ref"] is None
    assert [row["label"] for row in item_status(draft, task)["missing"]] == ["Project"]


def test_the_command_prompt_carries_the_schema_the_choices_and_the_open_question():
    draft, _project, _parent, _child, _person = seeded_draft()
    apply_operations(draft, [{"op": "create", "kind": "task", "fields": {"name": "Snagging"},
                              "parent": "nothing"}])
    prompt = build_command_prompt(draft, "the project is Riverside Tower", {
        "project": [{"id": "p1", "label": "Harbour Works", "detail": "HBR"}],
    })
    # What may be created, and which fields are mandatory.
    assert "tasks: name*" in prompt
    assert "project_costs: name*, amount*" in prompt
    # What already exists, so nothing has to be invented.
    assert "Harbour Works" in prompt
    # The draft, and the question left open.
    assert "Riverside Tower" in prompt
    assert "You last asked the administrator for: Project" in prompt
    assert "NEVER invent a value" in prompt


def test_a_field_the_model_made_up_a_value_for_is_dropped_not_stored():
    draft, _project, _parent, child, _person = seeded_draft()
    outcome = apply_operations(draft, [
        {"op": "update", "target": child["id"], "fields": {"status": "Probably done"}},
    ])
    assert outcome["applied"] == []
    assert "must be one of" in outcome["skipped"][0]["reason"]
    # A draft item holds only what was actually supplied; the record
    # constructor fills the defaults in at commit time.
    assert "status" not in child["fields"]


# ── the new entities ──────────────────────────────────────────────────────────

def test_a_cost_hangs_off_what_it_is_a_cost_of():
    draft, project, parent, child, _person = seeded_draft()
    project_cost = add_item(draft, "project_cost", {
        "fields": {"name": "Site hoarding", "amount": 12000}, "parent_ref": project["id"]})
    task_cost = add_item(draft, "task_cost", {
        "fields": {"amount": 50000}, "parent_ref": child["id"]})

    assert dependencies_of(project_cost) == [project["id"]]
    assert dependencies_of(task_cost) == [child["id"]]
    # Deselecting the task takes its cost with it; so does deselecting the project.
    assert task_cost["id"] in cascade_deselect(draft, [child["id"]])
    assert {project_cost["id"], task_cost["id"]} <= set(cascade_deselect(draft, [project["id"]]))


def test_a_task_cost_cannot_be_onboarded_without_its_task():
    draft, project, parent, child, _person = seeded_draft()
    cost = add_item(draft, "task_cost", {"fields": {"amount": 50000}, "parent_ref": child["id"]})
    resolved = resolve_selection(draft, [cost["id"]])
    # Its task, that task's parent, and the project all come along.
    assert set(resolved["selection"]) == {project["id"], parent["id"], child["id"], cost["id"]}


def test_costs_and_procurement_are_created_against_the_right_records(admin):
    draft = new_draft()
    project = add_item(draft, "project", {"fields": {
        "name": "Riverside Tower", "project_code": "RVT", "baseline_cost": 250000}})
    task = add_item(draft, "task", {"fields": {"name": "Pour slab"}, "parent_ref": project["id"]})
    add_item(draft, "task_cost", {"fields": {"amount": 48000}, "parent_ref": task["id"]})
    add_item(draft, "project_cost", {
        "fields": {"name": "Site hoarding", "amount": 12000, "details": "6 months"},
        "parent_ref": project["id"]})
    add_item(draft, "procurement", {
        "fields": {"name": "Rebar 12mm", "quantity": 400, "unit_cost": 18, "status": "Ordered"},
        "parent_ref": project["id"]})

    result = commit(draft, admin)
    assert result["total_created"] == 5

    project_id, stored = next(iter(admin.workspace.load_projects().items()))
    assert stored["baseline_cost"] == 250000
    assert [row["name"] for row in stored["additional_costs"]] == ["Site hoarding"]
    assert stored["additional_costs"][0]["amount"] == 12000
    assert admin.workspace.load_tasks()[project_id][0]["cost"] == 48000
    line = admin.workspace.load_procurement()[project_id][0]
    assert line["name"] == "Rebar 12mm" and line["status"] == "Ordered" and line["quantity"] == 400


def test_a_cost_the_task_already_carries_is_reused_rather_than_written_again(admin):
    draft = new_draft()
    project = add_item(draft, "project", {"fields": {"name": "Riverside", "project_code": "RVT"}})
    task = add_item(draft, "task", {"fields": {"name": "Pour slab"}, "parent_ref": project["id"]})
    add_item(draft, "task_cost", {"fields": {"amount": 48000}, "parent_ref": task["id"]})
    commit(draft, admin)

    again = new_draft()
    project = add_item(again, "project", {"fields": {"name": "Riverside", "project_code": "RVT"}})
    task = add_item(again, "task", {"fields": {"name": "Pour slab"}, "parent_ref": project["id"]})
    add_item(again, "task_cost", {"fields": {"amount": 48000}, "parent_ref": task["id"]})
    result = commit(again, admin)
    assert result["total_created"] == 0 and result["total_reused"] == 3


def test_trades_and_external_companies_land_in_the_management_catalogues(admin):
    draft = new_draft()
    add_item(draft, "trade", {"fields": {"name": "Curtain walling", "description": "Facade"}})
    add_item(draft, "vendor", {"fields": {"name": "Glass Co", "vendorType": "Subcontractor"}})
    commit(draft, admin)
    mgmt = admin.workspace.load_mgmt()
    assert "Curtain walling" in [row["name"] for row in mgmt["trades"]]
    vendor = next(row for row in mgmt["vendors"] if row["name"] == "Glass Co")
    assert vendor["vendorType"] == "Subcontractor" and vendor["activeProjects"] == 0


def test_the_extraction_contract_covers_every_entity():
    described = describe_entities_for_model()
    for kind in ITEM_KINDS:
        assert f"{response_key(kind)}:" in described, kind
    # The mandatory ones are marked, and the links are explained.
    assert "name*" in described
    assert "[belongs to a project: give \"parent\"]" in described


def test_costs_are_extracted_against_their_parents():
    draft = new_draft()
    merge_extraction(draft, parse_extraction(json.dumps({
        "projects": [{"name": "Riverside Tower", "project_code": "RVT"}],
        "tasks": [{"name": "Pour slab", "parent": "Riverside Tower"}],
        "task_costs": [{"amount": 48000, "parent": "Pour slab"}],
        "project_costs": [{"name": "Site hoarding", "amount": 12000, "parent": "Riverside Tower"}],
        "procurement": [{"name": "Rebar 12mm", "parent": "Riverside Tower", "quantity": 400}],
    })), {"doc_id": "d1", "doc_name": "Cost-plan.xlsx"})

    by_kind = {}
    for item in draft["items"].values():
        by_kind.setdefault(item["kind"], []).append(item)
    task_cost = by_kind["task_cost"][0]
    assert task_cost["parent_ref"] == by_kind["task"][0]["id"]
    assert task_cost["fields"]["amount"] == 48000
    assert by_kind["project_cost"][0]["parent_ref"] == by_kind["project"][0]["id"]
    assert by_kind["procurement"][0]["parent_ref"] == by_kind["project"][0]["id"]


def test_a_cost_with_no_amount_is_not_a_cost():
    draft = new_draft()
    merge_extraction(draft, parse_extraction(json.dumps({
        "projects": [{"name": "Riverside"}],
        "task_costs": [{"parent": "Riverside"}],
    })), {})
    assert [item["kind"] for item in draft["items"].values()] == ["project"]


# ── incomplete records cannot be onboarded ────────────────────────────────────

def test_the_summary_says_when_the_draft_is_not_ready():
    draft = new_draft()
    add_item(draft, "project", {"fields": {"name": "Website Redesign"}})
    summary = draft_summary(draft)
    assert summary["incomplete"] == 1 and summary["incomplete_selected"] == 1
    assert summary["ready_to_onboard"] is False

    update_item(draft, next(iter(draft["items"])), {"fields": {"project_code": "WEB-1"}})
    assert draft_summary(draft)["ready_to_onboard"] is True


def test_the_commit_route_refuses_a_draft_with_an_incomplete_selected_item(onboarding):
    _admin, client, _model = onboarding
    draft = client.post("/api/onboarding/drafts", json={}).json()
    client.post(f"/api/onboarding/drafts/{draft['id']}/items", json={
        "kind": "project", "fields": {"name": "Website Redesign"}})

    plan = client.get(f"/api/onboarding/drafts/{draft['id']}/plan").json()
    assert plan["can_commit"] is False
    assert plan["blocked"][0]["missing"][0]["label"] == "Project code"

    refused = client.post(f"/api/onboarding/drafts/{draft['id']}/commit", json={"confirm": True})
    assert refused.status_code == 422
    assert "not ready to onboard" in refused.json()["detail"]


def test_the_view_tells_the_page_exactly_what_each_item_still_needs(onboarding):
    _admin, client, _model = onboarding
    draft = client.post("/api/onboarding/drafts", json={}).json()
    created = client.post(f"/api/onboarding/drafts/{draft['id']}/items", json={
        "kind": "task", "fields": {"name": "Database Migration"}}).json()
    row = next(item for item in created["items"] if item["id"] == created["item_id"])
    assert row["complete"] is False
    assert [entry["label"] for entry in row["missing"]] == ["Project"]
    assert row["label"] == "Task"


def test_the_schema_route_serves_the_forms_and_the_live_choices(onboarding):
    admin, client, _model = onboarding
    admin.workspace.save_projects({"p1": {"id": "p1", "name": "Tower", "project_code": "TWR"}})
    served = client.get("/api/onboarding/schema").json()
    kinds = {row["kind"]: row for row in served["entities"]}
    assert set(kinds) == set(ITEM_KINDS)
    assert kinds["project"]["required"] == ["name", "project_code"]
    assert served["choices"]["project"] == [{"id": "p1", "label": "Tower", "detail": "TWR"}]
    assert any(row["key"] == "task.create" for row in served["permissions"])


# ── the commit is one unit of work ────────────────────────────────────────────

def test_a_failure_part_way_through_leaves_nothing_behind(admin, monkeypatch):
    """A commit that dies after creating a project and a user must undo both."""
    draft = new_draft()
    project = add_item(draft, "project", {"fields": {"name": "Riverside", "project_code": "RVT"}})
    add_item(draft, "user", {"fields": {"name": "Sam", "email": "sam@example.com"},
                             "project_refs": [project["id"]]})
    add_item(draft, "task", {"fields": {"name": "Pour slab"}, "parent_ref": project["id"]})

    def explode(*_args, **_kwargs):
        raise RuntimeError("the disk went away")

    monkeypatch.setattr("backend.project_onboarding.make_item", make_item)  # untouched
    with pytest.raises(RuntimeError):
        commit_draft(
            draft, workspace=admin.workspace, registry=admin._registry,
            account_id=admin.account_id, make_project=_make_project, make_task=explode,
            catalog_entry=catalog_entry, make_role=make_role,
            make_procurement=make_procurement_item,
        )

    assert admin.workspace.load_projects() == {}
    assert admin.workspace.load_tasks() == {}
    assert [user["email"] for user in admin._registry.users_for_account(admin.account_id)] \
        == ["owner@example.com"]
    assert draft["status"] == "draft"


def test_onboarded_managers_and_assignees_become_user_references():
    """Names the documents gave are matched to users; anyone given a task joins its project."""
    from types import SimpleNamespace

    from backend.project_onboarding import _bind_people

    users = [{"id": "u-sam", "name": "Sam Field", "email": "sam@example.com"},
             {"id": "u-jo1", "name": "Jo Twin", "email": "jo1@example.com"},
             {"id": "u-jo2", "name": "Jo Twin", "email": "jo2@example.com"}]
    work = SimpleNamespace(
        projects={"p1": {"id": "p1", "name": "Tower", "manager": "sam field", "members": []},
                  "p2": {"id": "p2", "name": "Annex", "manager": "Nobody Known", "members": []},
                  "old": {"id": "old", "name": "Old", "manager": "Sam Field"}},
        tasks={"p1": [{"id": "t1", "name": "Pour", "assignee": "Sam Field"},
                      {"id": "t2", "name": "Tie", "assignee": "Jo Twin"}]},
    )
    real_id = {"dp1": "p1", "dp2": "p2", "dt1": "t1", "dt2": "t2"}
    notes = _bind_people(work, real_id, {}, ["dp1", "dp2", "dt1", "dt2"], users)

    assert work.projects["p1"]["manager_id"] == "u-sam"
    assert work.projects["p2"]["manager"] == "" and "manager_id" not in work.projects["p2"]
    assert "manager_id" not in work.projects["old"]             # not created by this commit
    t1, t2 = work.tasks["p1"]
    assert t1["assignee_id"] == "u-sam"
    assert t2["assignee"] == "" and "assignee_id" not in t2     # an ambiguous name names nobody
    # The manager is already on the project, so no membership is added for Sam.
    assert work.projects["p1"]["members"] == []
    assert any("Nobody Known" in note for note in notes) and any("Jo Twin" in note for note in notes)


def test_a_drafted_task_outside_its_drafted_projects_dates_is_an_issue():
    """The review shows it before commit; the commit would refuse it anyway."""
    draft = new_draft()
    project = add_item(draft, "project", {"fields": {"name": "Tower", "project_code": "TWR",
                                                      "start_date": "2027-03-01", "end_date": "2027-06-30"}})
    inside = add_item(draft, "task", {"fields": {"name": "Pour", "start_time": "2027-04-01T08:00",
                                                 "end_time": "2027-04-02T08:00"}, "parent_ref": project["id"]})
    outside = add_item(draft, "task", {"fields": {"name": "Snag", "start_time": "2027-07-01T08:00"},
                                       "parent_ref": project["id"]})
    assert item_status(draft, inside)["complete"] is True
    status = item_status(draft, outside)
    assert status["complete"] is False and "after Tower ends on 2027-06-30" in status["issues"][0]

