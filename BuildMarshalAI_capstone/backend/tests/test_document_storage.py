"""Document storage: what it costs, and what can safely be taken back.

The thing this file mostly guards is that reclaiming never reaches something
unrecoverable.  Originals are untouchable, the plan and the sweep agree, and
nothing is removed without a confirmation.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.document_storage import (
    AREAS,
    DEFAULT_POLICY,
    DEFAULT_SWEEP_ACTIONS,
    SWEEP_ACTIONS,
    area_usage,
    cold_documents,
    compact_page,
    digest_of,
    directory_size,
    document_files,
    document_rows,
    duplicate_groups,
    find_by_digest,
    find_orphans,
    human_bytes,
    note_access,
    plan_sweep,
    policy_of,
    register_document_storage_routes,
    run_sweep,
    save_policy,
    storage_report,
)


def page(workspace, doc_id, number, size=4096):
    """Write a page image and the two caches the pipeline derives from it."""
    image = Path(workspace.pages_dir) / f"{doc_id}_page_{number}.png"
    image.write_bytes(b"\x89PNG" + b"0" * size)
    stem = image.stem
    (Path(workspace.multivector_dir) / f"{stem}.npy").write_bytes(b"v" * (size * 4))
    (Path(workspace.vision_cache_dir) / f"{stem}_512.jpg").write_bytes(b"j" * (size // 2))
    return {"page_num": number, "image_path": str(image), "text_content": "x"}


def add_document(workspace, doc_id, *, name="Doc.pdf", pages=2, body=b"pdf bytes",
                 digest=None, created="2027-01-01T00:00:00+00:00", accessed=None):
    original = Path(workspace.docs_dir) / f"{doc_id}.pdf"
    original.write_bytes(body)
    metadata = workspace.load_metadata()
    record = {
        "id": doc_id, "name": name, "type": ".pdf", "size": len(body),
        "digest": digest if digest is not None else digest_of(original),
        "pages": [page(workspace, doc_id, number + 1) for number in range(pages)],
        "page_count": pages, "status": "indexed", "created_at": created,
    }
    if accessed:
        record["accessed_at"] = accessed
    metadata.setdefault("documents", {})[doc_id] = record
    workspace.save_metadata(metadata)
    return record


@pytest.fixture
def workspace(make_workspace):
    return make_workspace("owner@example.com")


# ── measuring ─────────────────────────────────────────────────────────────────

def test_sizes_are_written_the_way_a_person_reads_them():
    assert human_bytes(0) == "0 B"
    assert human_bytes(900) == "900 B"
    assert human_bytes(1536) == "1.5 KB"
    assert human_bytes(5 * 1024 ** 3) == "5.0 GB"


def test_a_directory_that_is_not_there_measures_zero(tmp_path):
    assert directory_size(tmp_path / "nothing") == (0, 0)


def test_every_area_of_the_workspace_is_accounted_for(workspace):
    add_document(workspace, "d1")
    rows = {row["key"]: row for row in area_usage(workspace)}
    assert set(rows) == {area.key for area in AREAS}
    assert rows["docs_dir"]["bytes"] > 0 and rows["pages_dir"]["bytes"] > 0
    assert rows["multivector_dir"]["bytes"] > 0
    # Largest first, so the expensive thing is the first thing read.
    sizes = [row["bytes"] for row in area_usage(workspace)]
    assert sizes == sorted(sizes, reverse=True)


def test_only_the_rebuildable_areas_are_offered_as_reclaimable():
    natures = {area.key: area.nature for area in AREAS}
    assert natures["docs_dir"] == "source"
    assert {key for key, nature in natures.items() if nature == "derived"} == {
        "pages_dir", "multivector_dir", "vision_cache_dir"}


def test_a_document_row_breaks_its_cost_down_by_what_it_is(workspace):
    add_document(workspace, "d1", pages=3)
    row = document_rows(workspace)[0]
    assert row["pages"] == 3
    assert set(row["breakdown"]) == {"originals", "pages", "vectors", "tiles"}
    assert row["breakdown"]["vectors"]["files"] == 3
    # Only the caches count as reclaimable; the original and the page images do not.
    assert row["reclaimable"] == (row["breakdown"]["vectors"]["bytes"]
                                  + row["breakdown"]["tiles"]["bytes"])


def test_document_files_finds_everything_one_document_owns(workspace):
    record = add_document(workspace, "d1", pages=2)
    files = document_files(workspace, "d1", record)
    assert len(files["originals"]) == 1 and len(files["pages"]) == 2
    assert len(files["vectors"]) == 2 and len(files["tiles"]) == 2


# ── the leak ──────────────────────────────────────────────────────────────────

def test_caches_left_behind_by_a_deleted_document_are_found(workspace):
    """Deleting a document used to leave its ColPali cache and vision tiles
    behind for good: they are keyed by page filename, not by document."""
    add_document(workspace, "keep", pages=1)
    add_document(workspace, "gone", pages=2)

    # Remove the document the way the old delete did -- metadata and images only.
    metadata = workspace.load_metadata()
    for entry in metadata["documents"]["gone"]["pages"]:
        Path(entry["image_path"]).unlink()
    del metadata["documents"]["gone"]
    workspace.save_metadata(metadata)

    orphans = find_orphans(workspace)
    names = {row["name"] for row in orphans["files"]}
    assert names == {"gone_page_1.npy", "gone_page_2.npy",
                     "gone_page_1_512.jpg", "gone_page_2_512.jpg"}
    assert orphans["bytes"] > 0
    # Nothing belonging to the surviving document is touched.
    assert not any("keep" in name for name in names)


def test_a_page_image_whose_document_is_gone_is_an_orphan_too(workspace):
    add_document(workspace, "d1", pages=1)
    stray = Path(workspace.pages_dir) / "someone_elses_page_1.png"
    stray.write_bytes(b"0" * 100)
    names = {row["name"] for row in find_orphans(workspace)["files"]}
    assert "someone_elses_page_1.png" in names
    assert "d1_page_1.png" not in names


def test_nothing_is_an_orphan_in_a_tidy_workspace(workspace):
    add_document(workspace, "d1", pages=2)
    assert find_orphans(workspace)["count"] == 0


# ── duplicates ────────────────────────────────────────────────────────────────

def test_the_same_bytes_indexed_twice_are_found(workspace):
    add_document(workspace, "first", name="Tender.pdf", body=b"identical",
                 created="2027-01-01T00:00:00+00:00")
    add_document(workspace, "second", name="Tender (copy).pdf", body=b"identical",
                 created="2027-02-01T00:00:00+00:00")
    add_document(workspace, "other", name="Schedule.pdf", body=b"different")

    groups = duplicate_groups(workspace)
    assert groups["count"] == 1
    group = groups["groups"][0]
    # The first one indexed is the one kept.
    assert group["keep"]["id"] == "first"
    assert [row["id"] for row in group["copies"]] == ["second"]
    assert groups["bytes"] > 0


def test_a_document_with_no_digest_is_never_called_a_duplicate(workspace):
    add_document(workspace, "a", body=b"same", digest="")
    add_document(workspace, "b", body=b"same", digest="")
    assert duplicate_groups(workspace)["count"] == 0


def test_an_upload_can_be_matched_against_what_is_already_indexed(workspace, tmp_path):
    record = add_document(workspace, "first", body=b"identical")
    incoming = tmp_path / "again.pdf"
    incoming.write_bytes(b"identical")

    found = find_by_digest(workspace, digest_of(incoming))
    assert found and found["id"] == "first"
    assert find_by_digest(workspace, digest_of(incoming), exclude="first") is None
    assert find_by_digest(workspace, "") is None


def test_the_digest_is_the_content_not_the_name(tmp_path):
    one, two = tmp_path / "a.pdf", tmp_path / "b.pdf"
    one.write_bytes(b"same bytes")
    two.write_bytes(b"same bytes")
    assert digest_of(one) == digest_of(two)


# ── cold and warm ─────────────────────────────────────────────────────────────

def test_a_document_read_recently_is_never_evicted(workspace):
    now = datetime.now(timezone.utc)
    add_document(workspace, "warm", accessed=(now - timedelta(days=2)).isoformat())
    add_document(workspace, "cold", accessed=(now - timedelta(days=200)).isoformat())
    chosen = cold_documents(workspace, keep_warm_days=30)
    assert [row["id"] for row in chosen] == ["cold"]


def test_coldest_first_so_eviction_takes_the_right_things(workspace):
    now = datetime.now(timezone.utc)
    add_document(workspace, "older", accessed=(now - timedelta(days=300)).isoformat())
    add_document(workspace, "old", accessed=(now - timedelta(days=100)).isoformat())
    assert [row["id"] for row in cold_documents(workspace, keep_warm_days=30)] == ["older", "old"]


def test_a_read_is_recorded_so_warm_can_be_told_from_cold(workspace):
    add_document(workspace, "d1", created="2020-01-01T00:00:00+00:00")
    assert cold_documents(workspace, keep_warm_days=30)
    note_access(workspace, ["d1"])
    assert workspace.load_metadata()["documents"]["d1"]["accessed_at"]
    assert cold_documents(workspace, keep_warm_days=30) == []


def test_noting_a_document_that_is_not_there_changes_nothing(workspace):
    add_document(workspace, "d1")
    before = workspace.load_metadata()
    note_access(workspace, ["ghost", ""])
    assert workspace.load_metadata() == before


# ── policy ────────────────────────────────────────────────────────────────────

def test_the_policy_starts_at_the_defaults_and_survives_a_change(workspace):
    assert policy_of(workspace) == DEFAULT_POLICY
    saved = save_policy(workspace, {"budget_mb": 512, "deduplicate": False})
    assert saved["budget_mb"] == 512 and saved["deduplicate"] is False
    assert policy_of(workspace)["budget_mb"] == 512
    # Everything else keeps its default.
    assert policy_of(workspace)["page_quality"] == DEFAULT_POLICY["page_quality"]


def test_a_policy_value_that_makes_no_sense_is_refused(workspace):
    from fastapi import HTTPException

    for change in ({"budget_mb": -1}, {"page_quality": 5}, {"page_max_edge": 10},
                   {"budget_mb": "lots"}):
        with pytest.raises(HTTPException):
            save_policy(workspace, change)


def test_a_setting_nobody_defined_is_ignored_rather_than_stored(workspace):
    save_policy(workspace, {"delete_everything": True})
    assert "delete_everything" not in policy_of(workspace)


# ── planning and sweeping ─────────────────────────────────────────────────────

def test_the_plan_describes_every_action_and_totals_them(workspace):
    add_document(workspace, "d1")
    plan = plan_sweep(workspace)
    assert {row["key"] for row in plan["actions"]} == {key for key, _ in SWEEP_ACTIONS}
    assert plan["bytes"] == sum(row["bytes"] for row in plan["actions"])
    # Only removing files nobody owns is offered as safe.
    assert [row["key"] for row in plan["actions"] if row["safe"]] == ["orphans"]


def test_planning_removes_nothing(workspace):
    add_document(workspace, "gone", pages=1)
    metadata = workspace.load_metadata()
    del metadata["documents"]["gone"]
    workspace.save_metadata(metadata)

    before = directory_size(Path(workspace.multivector_dir))
    plan = plan_sweep(workspace, actions=["orphans"])
    assert plan["bytes"] > 0
    assert directory_size(Path(workspace.multivector_dir)) == before


def test_a_sweep_removes_exactly_what_the_plan_said(workspace):
    add_document(workspace, "keep", pages=1)
    add_document(workspace, "gone", pages=2)
    metadata = workspace.load_metadata()
    del metadata["documents"]["gone"]
    workspace.save_metadata(metadata)

    planned = plan_sweep(workspace, actions=["orphans"])["bytes"]
    outcome = run_sweep(workspace, actions=["orphans"])
    assert outcome["bytes"] == planned
    assert find_orphans(workspace)["count"] == 0
    # The surviving document keeps everything it owns.
    row = next(row for row in document_rows(workspace) if row["id"] == "keep")
    assert row["breakdown"]["vectors"]["files"] == 1


def test_an_original_is_never_removed_by_any_sweep(workspace):
    add_document(workspace, "d1", pages=2)
    original = Path(workspace.docs_dir) / "d1.pdf"
    run_sweep(workspace, actions=["orphans", "compact", "evict"],
              policy={**DEFAULT_POLICY, "budget_mb": 0, "keep_warm_days": 0})
    assert original.exists()


def test_eviction_drops_only_the_rebuildable_caches(workspace):
    now = datetime.now(timezone.utc)
    add_document(workspace, "cold", pages=2, accessed=(now - timedelta(days=400)).isoformat())
    files = document_files(workspace, "cold", workspace.load_metadata()["documents"]["cold"])
    pages_before = [path for path in files["pages"]]

    outcome = run_sweep(workspace, actions=["evict"],
                        policy={**DEFAULT_POLICY, "budget_mb": 0, "keep_warm_days": 30})
    dropped = next(row for row in outcome["performed"] if row["key"] == "evict")
    assert dropped["count"] == 1 and dropped["bytes"] > 0
    assert not any(path.exists() for path in files["vectors"])
    assert not any(path.exists() for path in files["tiles"])
    # The page image stays: it is what the caches are rebuilt from.
    assert all(path.exists() for path in pages_before)


def test_nothing_is_evicted_while_the_workspace_is_inside_its_budget(workspace):
    now = datetime.now(timezone.utc)
    add_document(workspace, "cold", accessed=(now - timedelta(days=400)).isoformat())
    plan = plan_sweep(workspace, policy={**DEFAULT_POLICY, "budget_mb": 4096})
    evict = next(row for row in plan["actions"] if row["key"] == "evict")
    assert evict["bytes"] == 0
    assert "Within budget" in evict["detail"]["note"]


def test_a_sweep_that_is_asked_for_nothing_only_does_the_safe_thing(workspace):
    add_document(workspace, "d1")
    outcome = run_sweep(workspace)
    assert [row["key"] for row in outcome["performed"]] == ["orphans"]


# ── compaction ────────────────────────────────────────────────────────────────

def test_a_large_page_image_is_rewritten_smaller(workspace):
    from PIL import Image

    source = Path(workspace.pages_dir) / "big_page_1.png"
    Image.new("RGB", (2000, 1500), (200, 120, 60)).save(source, "PNG")
    before = source.stat().st_size

    outcome = compact_page(source, max_edge=1400, quality=80)
    assert outcome["saved"] > 0
    assert not source.exists()
    rewritten = Path(outcome["new_path"])
    assert rewritten.suffix == ".webp" and rewritten.stat().st_size < before
    with Image.open(rewritten) as image:
        assert max(image.size) <= 1400


def test_a_page_that_would_not_shrink_is_left_exactly_as_it_was(workspace):
    """Rewriting a page that is already small would cost bytes, not save them."""
    import random

    from PIL import Image

    random.seed(7)
    source = Path(workspace.pages_dir) / "noisy_page_1.webp"
    noisy = Image.new("RGB", (200, 200))
    noisy.putdata([(random.randrange(256), random.randrange(256), random.randrange(256))
                   for _ in range(200 * 200)])
    noisy.save(source, "WEBP", quality=20)
    before = source.read_bytes()

    # Re-encoding noise at full quality can only make it bigger, so the rewrite
    # has to be abandoned and the original left untouched.
    outcome = compact_page(source, max_edge=1400, quality=100)
    assert outcome["saved"] == 0 and outcome.get("skipped") == "already compact"
    assert source.exists() and source.read_bytes() == before
    assert not list(Path(workspace.pages_dir).glob("*.compacting.webp"))


def test_compaction_follows_the_rename_in_the_metadata(workspace):
    from PIL import Image

    add_document(workspace, "d1", pages=1)
    stored = workspace.load_metadata()["documents"]["d1"]["pages"][0]["image_path"]
    Image.new("RGB", (2000, 1500), (90, 140, 200)).save(stored, "PNG")

    run_sweep(workspace, actions=["compact"], policy={**DEFAULT_POLICY, "page_max_edge": 800})
    after = workspace.load_metadata()["documents"]["d1"]["pages"][0]["image_path"]
    assert after.endswith(".webp") and Path(after).exists()
    # Which is what keeps the page endpoint and ColPali able to find it.
    assert workspace.resolve_page_path(after)


def test_a_file_that_is_not_an_image_is_not_offered_for_compaction(workspace):
    (Path(workspace.pages_dir) / "notes.txt").write_text("not an image", encoding="utf-8")
    from backend.document_storage import oversized_pages

    assert oversized_pages(workspace, max_edge=800)["count"] == 0


# ── the report ────────────────────────────────────────────────────────────────

def test_the_report_answers_what_the_panel_asks(workspace):
    add_document(workspace, "d1", pages=2)
    report = storage_report(workspace)
    assert report["total_bytes"] > 0 and report["document_count"] == 1
    assert report["budget_bytes"] == DEFAULT_POLICY["budget_mb"] * 1024 * 1024
    assert report["over_budget"] is False
    assert {row["key"] for row in report["actions"]} == {key for key, _ in SWEEP_ACTIONS}


# ── routes ────────────────────────────────────────────────────────────────────

def build_app(context, remover=None):
    app = FastAPI()

    async def require_account():
        return context

    namespace = {"app": app, "require_account": require_account}
    if remover is not None:
        namespace["delete_document_files"] = remover
    register_document_storage_routes(namespace)
    return TestClient(app)


@pytest.fixture
def admin(make_account):
    context = make_account("owner@example.com")
    add_document(context.workspace, "d1", pages=2)
    return context


def test_reading_storage_needs_no_special_standing(admin):
    body = build_app(admin).get("/api/storage").json()
    assert body["document_count"] == 1
    assert body["areas"] and body["policy"]["budget_mb"] == DEFAULT_POLICY["budget_mb"]


def test_the_plan_route_reads_only(admin):
    before = storage_report(admin.workspace)["total_bytes"]
    body = build_app(admin).get("/api/storage/plan?actions=orphans").json()
    assert [row["key"] for row in body["actions"]] == ["orphans"]
    assert storage_report(admin.workspace)["total_bytes"] == before


def test_an_action_nobody_defined_is_refused(admin):
    client = build_app(admin)
    assert client.get("/api/storage/plan?actions=rm_-rf").status_code == 422
    assert client.post("/api/storage/sweep", json={"actions": ["rm_-rf"]}).status_code == 422


def test_a_sweep_without_confirmation_removes_nothing(admin):
    metadata = admin.workspace.load_metadata()
    del metadata["documents"]["d1"]
    admin.workspace.save_metadata(metadata)

    body = build_app(admin).post("/api/storage/sweep", json={"actions": ["orphans"]}).json()
    assert body["confirmation_required"] is True and body["bytes"] > 0
    assert find_orphans(admin.workspace)["count"] > 0


def test_a_sweep_naming_no_action_plans_and_runs_the_same_safe_default(admin):
    metadata = admin.workspace.load_metadata()
    del metadata["documents"]["d1"]
    admin.workspace.save_metadata(metadata)
    client = build_app(admin)

    plan = client.post("/api/storage/sweep", json={"actions": []}).json()
    assert [row["key"] for row in plan["actions"]] == list(DEFAULT_SWEEP_ACTIONS) == ["orphans"]
    done = client.post("/api/storage/sweep", json={"actions": [], "confirm": True}).json()
    assert [row["key"] for row in done["performed"]] == [row["key"] for row in plan["actions"]]
    assert done["bytes"] == plan["bytes"]


def test_a_confirmed_sweep_reclaims_and_reports_the_new_position(admin):
    metadata = admin.workspace.load_metadata()
    del metadata["documents"]["d1"]
    admin.workspace.save_metadata(metadata)

    body = build_app(admin).post("/api/storage/sweep",
                                 json={"actions": ["orphans"], "confirm": True}).json()
    assert body["confirmation_required"] is False and body["bytes"] > 0
    assert body["storage"]["reclaimable_bytes"] == 0


def test_a_duplicate_is_collapsed_through_the_applications_own_delete(admin):
    """The sweep must not grow a second, divergent way to remove a document."""
    add_document(admin.workspace, "copy", name="Doc (copy).pdf", body=b"pdf bytes",
                 created="2027-06-01T00:00:00+00:00")
    removed = []

    def remover(workspace, doc_id):
        removed.append(doc_id)
        metadata = workspace.load_metadata()
        del metadata["documents"][doc_id]
        workspace.save_metadata(metadata)

    body = build_app(admin, remover).post(
        "/api/storage/sweep", json={"actions": ["duplicates"], "confirm": True}).json()
    assert removed == ["copy"]
    assert body["performed"][0]["ids"] == ["copy"]


def test_sweeping_and_policy_changes_are_administrator_work(make_account):
    context = make_account("member@example.com")
    context.user = {**context.user, "is_owner": False, "role": "Viewer"}
    client = build_app(context)
    assert client.get("/api/storage").status_code == 200
    assert client.post("/api/storage/sweep", json={"confirm": True}).status_code == 403
    assert client.put("/api/storage/policy", json={"budget_mb": 1}).status_code == 403


def test_the_policy_route_stores_and_returns_the_defaults_alongside(admin):
    body = build_app(admin).put("/api/storage/policy", json={"budget_mb": 256}).json()
    assert body["policy"]["budget_mb"] == 256
    assert body["defaults"] == DEFAULT_POLICY
    assert policy_of(admin.workspace)["budget_mb"] == 256
