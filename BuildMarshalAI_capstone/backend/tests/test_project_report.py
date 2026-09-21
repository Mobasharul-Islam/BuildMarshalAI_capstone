"""The project report: what it contains at each stage, and what it will not claim.

A report is only worth anything if it is honest about its own basis, so the
tests here care as much about the caveats and the sections that are *left out*
as about the ones that are printed.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.project_analytics import build_statistics, rule_based_summary
from backend.project_report import (
    BUILDERS,
    PHASE_SECTIONS,
    PHASE_TITLES,
    SECTIONS,
    build_sections,
    register_project_report_routes,
    report_template,
    report_title,
)

PROJECT = {
    "id": "p1", "name": "Riverside Tower", "project_code": "RVT", "status": "Active",
    "manager": "Dana", "start_date": "2027-01-01", "end_date": "2027-06-30",
    "baseline_cost": 100000,
}
TODAY = date(2027, 4, 1)


def task(name, status, **extra):
    return {"id": name, "name": name, "status": status, "cost": 1000,
            "start_time": "2027-01-01", "end_time": "2027-02-01", **extra}


def stats_for(tasks, project=None, procurement=(), today=TODAY):
    return build_statistics(project=project or PROJECT, tasks=tasks,
                            procurement=list(procurement), today=today)


def sections_for(tasks, insights=None, **kwargs):
    stats = stats_for(tasks, **kwargs)
    return stats, build_sections(stats, insights or rule_based_summary(stats))


# ── shape ─────────────────────────────────────────────────────────────────────

def test_every_phase_has_a_section_list_and_every_section_has_a_builder():
    for phase, keys in PHASE_SECTIONS.items():
        assert phase in PHASE_TITLES
        for key in keys:
            assert key in SECTIONS and key in BUILDERS, f"{phase}/{key}"


def test_every_report_explains_its_own_basis():
    """Figures nobody can check are figures nobody should act on."""
    for keys in PHASE_SECTIONS.values():
        assert "basis" in keys


def test_the_title_follows_the_phase():
    _, planning = sections_for([task(str(i), "Open") for i in range(3)],
                               project={**PROJECT, "start_date": "2027-09-01"})
    stats = stats_for([task(str(i), "Open") for i in range(3)],
                      project={**PROJECT, "start_date": "2027-09-01"})
    assert "Baseline Report" in report_title(stats)
    finished = stats_for([task(str(i), "Completed") for i in range(3)])
    assert "Final Report" in report_title(finished)
    assert report_title(finished, "My own title") == "My own title"


def test_a_planning_report_does_not_report_on_delivery():
    """There is nothing to say about throughput before anything has been done."""
    stats, built = sections_for([task(str(i), "Open") for i in range(3)],
                                project={**PROJECT, "start_date": "2027-09-01"})
    keys = [section.key for section in built]
    assert stats["phase"]["key"] == "planning"
    assert "delivery" not in keys and "closeout" not in keys
    assert "summary" in keys and "basis" in keys


def test_a_closeout_report_leads_with_what_is_outstanding():
    tasks = [task(str(i), "Completed") for i in range(9)] + [task("last", "In Progress")]
    _, built = sections_for(tasks)
    keys = [section.key for section in built]
    assert "closeout" in keys
    closeout = next(section for section in built if section.key == "closeout")
    assert "remain open" in closeout.paragraphs[0]


def test_a_section_with_nothing_to_say_is_left_out_rather_than_printed_empty():
    _, built = sections_for([task("a", "Open")])
    keys = [section.key for section in built]
    # No procurement was recorded, and the fallback narrative proposes no actions.
    assert "procurement" not in keys and "actions" not in keys


def test_a_section_appears_once_it_has_something_to_say():
    procurement = [{"name": "Rebar", "quantity": 10, "unit_cost": 100, "status": "Ordered"}]
    _, built = sections_for([task("a", "In Progress")], procurement=procurement)
    assert "procurement" in [section.key for section in built]


def test_the_requested_sections_win_over_the_phase_default():
    stats = stats_for([task("a", "In Progress")])
    built = build_sections(stats, rule_based_summary(stats), ["phase", "basis"])
    assert [section.key for section in built] == ["phase", "basis"]


def test_the_template_matches_the_sections_that_were_actually_built():
    stats, built = sections_for([task("a", "In Progress")])
    template = report_template(stats, built)
    assert [spec.key for spec in template.sections] == [section.key for section in built]
    assert stats["as_of"] in template.description


# ── content ───────────────────────────────────────────────────────────────────

def test_the_summary_carries_the_headline_figures():
    stats, built = sections_for([task("a", "Completed"), task("b", "Open")])
    summary = next(section for section in built if section.key == "summary")
    assert summary.table_columns == ["Measure", "Value"]
    labels = [row[0] for row in summary.table_rows]
    assert "Value earned" in labels and "Schedule index" in labels


def test_the_cost_section_says_why_there_is_no_cost_index():
    _, built = sections_for([task("a", "Completed", cost=5000)])
    cost = next(section for section in built if section.key == "cost")
    assert "actual spend" in cost.warning


def test_the_progress_section_names_the_rule_it_credited_progress_by():
    _, built = sections_for([task("a", "In Progress"), task("b", "Open"), task("c", "Open")])
    progress = next(section for section in built if section.key == "progress")
    assert "fixed formula 50/50" in progress.paragraphs[0]


def test_the_basis_section_lists_what_the_figures_do_not_cover():
    tasks = [task("a", "Completed"),
             {"id": "b", "name": "b", "status": "Open"}]  # no dates
    _, built = sections_for(tasks)
    basis = next(section for section in built if section.key == "basis")
    joined = " ".join(basis.bullets)
    assert "no dates" in joined
    assert "fixed formula 50/50" in joined
    assert "without a language model" in joined


def test_an_unpriced_programme_says_its_figures_are_counts_not_money():
    tasks = [{"id": str(i), "name": str(i), "status": "Open",
              "start_time": "2027-01-01", "end_time": "2027-02-01"} for i in range(3)]
    _, built = sections_for(tasks)
    basis = next(section for section in built if section.key == "basis")
    assert any("counts of work rather than money" in line for line in basis.bullets)


def test_a_written_narrative_reaches_the_summary_and_the_actions():
    insights = {
        "summary": "Behind on the glazing package.",
        "highlights": ["Foundations closed out on plan."],
        "concerns": ["Glazing is blocked."],
        "actions": [{"title": "Unblock glazing", "why": "It is the only blocker."}],
        "outlook": "Late without intervention.", "available": True,
    }
    _, built = sections_for([task("a", "In Progress")], insights)
    summary = next(section for section in built if section.key == "summary")
    assert summary.paragraphs[0] == "Behind on the glazing package."
    assert any("Going well" in line for line in summary.bullets)
    assert summary.warning is None

    actions = next(section for section in built if section.key == "actions")
    assert actions.table_rows == [["Unblock glazing", "It is the only blocker."]]


def test_a_report_written_without_a_model_says_so_on_its_face():
    _, built = sections_for([task("a", "In Progress")])
    summary = next(section for section in built if section.key == "summary")
    assert summary.warning and "figures alone" in summary.warning


def test_the_risks_section_says_so_when_there_is_nothing_to_flag():
    tasks = [task(str(i), "Completed", assignee="Sam") for i in range(5)]
    stats = stats_for(tasks)
    stats["risks"] = []
    built = build_sections(stats, rule_based_summary(stats), ["risks"])
    assert "No rule-based risk flags" in built[0].paragraphs[0]


# ── rendering ─────────────────────────────────────────────────────────────────

def test_a_report_renders_to_a_readable_pdf(tmp_path):
    from backend.document_generation import PdfDocumentRenderer

    tasks = [task("Excavate", "Completed", trade="Earthworks", assignee="Sam", cost=42000),
             task("Slab pour", "In Progress", trade="Concrete", assignee="Priya", cost=61000),
             task("Glazing", "Blocked", due_date="2027-03-01", cost=24000)]
    stats, built = sections_for(tasks)
    output = tmp_path / "report.pdf"
    PdfDocumentRenderer().render(
        output_path=output, title=report_title(stats),
        template=report_template(stats, built), project=PROJECT,
        sections=built, generated_at="1 April 2027",
        evidence_policy="Computed from this workspace's records.",
        footer_note="BuildMarshalAI - project report",
    )
    assert output.exists()
    reader = PdfReader(str(output))
    text = " ".join(page.extract_text() or "" for page in reader.pages)
    assert "Riverside Tower" in text
    assert "Executive Summary" in text
    # The cover no longer claims the document is grounded in source PDFs.
    assert "Computed from this workspace" in text
    assert "source PDFs" not in text


# ── routes ────────────────────────────────────────────────────────────────────

def build_app(context, model=None):
    app = FastAPI()

    async def require_account():
        return context

    namespace = {"app": app, "require_account": require_account, "ACCOUNT_REGISTRY": None}
    if model is not None:
        namespace["vl_generate"] = model
    register_project_report_routes(namespace)
    return TestClient(app)


@pytest.fixture
def project(make_account):
    context = make_account("owner@example.com")
    context.workspace.save_projects({"p1": {**PROJECT}})
    today = date.today()
    context.workspace.save_tasks({"p1": [
        task("Excavate", "Completed", start_time=(today - timedelta(days=40)).isoformat(),
             end_time=(today - timedelta(days=30)).isoformat(), trade="Earthworks", cost=42000),
        task("Slab pour", "In Progress", start_time=(today - timedelta(days=20)).isoformat(),
             end_time=(today + timedelta(days=20)).isoformat(), trade="Concrete", cost=61000),
    ]})
    return context


def test_the_preview_says_what_the_report_would_contain_without_writing_one(project):
    client = build_app(project)
    body = client.get("/api/projects/p1/report/preview").json()
    assert body["title"].startswith("Riverside Tower")
    assert body["phase"]["key"]
    assert [row["key"] for row in body["sections"]]
    assert len(body["available_sections"]) == len(SECTIONS)
    # Nothing was written.
    assert not list(Path(project.workspace.generated_dir).glob("*.pdf"))


def test_generating_a_report_writes_a_pdf_and_registers_it(project):
    body = build_app(project).post("/api/projects/p1/report", json={}).json()
    assert body["doc_kind"] == "project_report"
    assert body["download_url"].endswith("/download")
    assert body["size_bytes"] > 0
    assert "file_path" not in body

    written = list(Path(project.workspace.generated_dir).glob("*.pdf"))
    assert len(written) == 1
    registry = project.workspace.generated_registry
    assert registry.exists() and body["id"] in registry.read_text(encoding="utf-8")


def test_the_report_is_listed_against_its_project(project):
    client = build_app(project)
    created = client.post("/api/projects/p1/report", json={}).json()
    listed = client.get("/api/projects/p1/reports").json()
    assert listed["total"] == 1 and listed["reports"][0]["id"] == created["id"]
    assert "file_path" not in listed["reports"][0]


def test_a_narrative_can_be_declined_and_the_report_still_lands(project):
    body = build_app(project).post("/api/projects/p1/report",
                                   json={"narrative": False}).json()
    assert body["narrative"] is False
    assert body["insights"]["available"] is False


def test_the_model_writes_the_narrative_when_it_answers(project):
    def model(messages, max_new_tokens=1800, model=None):
        return '{"summary": "Steady, with the slab pour under way."}'

    body = build_app(project, model).post("/api/projects/p1/report", json={}).json()
    assert body["narrative"] is True
    assert body["insights"]["summary"] == "Steady, with the slab pour under way."


def test_a_model_that_fails_does_not_lose_the_report(project):
    def model(messages, max_new_tokens=1800, model=None):
        raise RuntimeError("the proxy is down")

    body = build_app(project, model).post("/api/projects/p1/report", json={}).json()
    assert body["size_bytes"] > 0
    assert body["narrative"] is False
    assert "could not be reached" in body["insights"]["note"]


def test_an_unknown_section_or_rule_is_refused(project):
    client = build_app(project)
    assert client.post("/api/projects/p1/report",
                       json={"sections": ["astrology"]}).status_code == 422
    assert client.post("/api/projects/p1/report", json={"rule": "vibes"}).status_code == 422


def test_a_project_that_is_not_there_has_no_report(project):
    assert build_app(project).post("/api/projects/nope/report", json={}).status_code == 404


def test_a_project_with_nothing_on_it_still_reports_rather_than_failing(make_account):
    context = make_account("owner@example.com")
    context.workspace.save_projects({"p1": {**PROJECT}})
    body = build_app(context).post("/api/projects/p1/report", json={}).json()
    # A baseline report of an empty project is a short report, not an error.
    assert body["phase"] == "planning"
    assert body["size_bytes"] > 0
