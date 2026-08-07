"""Tests for the coverage artifact assembled in strix.report.coverage."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from strix.report.coverage import (
    build_coverage_document,
    read_agent_graph,
    render_coverage_markdown,
    write_coverage,
)


if TYPE_CHECKING:
    from pathlib import Path


def _entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "surface": "POST /api/orders/{id}",
        "risk_area": "object-level authorization",
        "outcome": "no_issue_found",
        "evidence": "Two tenants tested; both received 403.",
        "agent_id": "agent-1",
        "agent_name": "authz-tester",
        "created_at": "2026-07-02 10:00:00 UTC",
    }
    base.update(overrides)
    return base


def _graph(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "statuses": {"agent-1": "completed"},
        "names": {"agent-1": "authz-tester"},
        "metadata": {"agent-1": {"skills": ["idor"], "task": "authz review"}},
    }
    base.update(overrides)
    return base


def _document(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "run_record": {"run_id": "r1", "run_name": "run-1", "status": "completed"},
        "entries": [_entry()],
        "agent_graph": _graph(),
        "vulnerability_reports": [],
    }
    kwargs.update(overrides)
    return build_coverage_document(**kwargs)


def test_document_reports_surfaces_and_outcomes() -> None:
    doc = _document()

    assert doc["summary"]["surfaces_reviewed"] == 1
    assert doc["summary"]["outcomes"] == {"no_issue_found": 1}
    assert doc["entries"][0]["outcome_label"] == "No issue identified"
    assert doc["entries"][0]["recorded_by"] == "authz-tester"


def test_ledger_entries_are_labelled_as_agent_reported() -> None:
    """A reader has to be able to tell a self-report from an observation."""
    doc = _document()

    assert doc["entries"][0]["source"] == "agent_reported"
    assert doc["machine_observed"]["source"] == "runtime"
    assert doc["machine_observed"]["skills_exercised"] == ["idor"]


def test_assigned_risk_skill_without_coverage_becomes_a_gap() -> None:
    """An agent carrying the sql_injection skill that records nothing about it
    leaves the class unexamined, not clean."""
    doc = _document(
        agent_graph=_graph(
            metadata={"agent-1": {"skills": ["idor", "sql_injection"], "task": "review"}}
        )
    )

    gaps = [gap for gap in doc["gaps"] if gap["kind"] == "unrecorded_risk_class"]
    assert [gap["risk_area"] for gap in gaps] == ["sql injection"]


def test_recorded_risk_class_is_not_reported_as_a_gap() -> None:
    doc = _document(
        entries=[_entry(risk_area="SQL injection", surface="GET /search?q=")],
        agent_graph=_graph(metadata={"agent-1": {"skills": ["sql_injection"]}}),
    )

    assert not [gap for gap in doc["gaps"] if gap["kind"] == "unrecorded_risk_class"]


def test_synonym_phrasing_counts_as_recorded_coverage() -> None:
    """The ledger says "object-level authorization"; the skill is called idor."""
    doc = _document(agent_graph=_graph(metadata={"agent-1": {"skills": ["idor"]}}))

    assert not [gap for gap in doc["gaps"] if gap["kind"] == "unrecorded_risk_class"]


def test_non_risk_skills_carry_no_coverage_obligation() -> None:
    """Tooling skills describe how an agent works, not what it hunts."""
    doc = _document(agent_graph=_graph(metadata={"agent-1": {"skills": ["idor", "caido"]}}))

    assert not [gap for gap in doc["gaps"] if gap.get("risk_area") == "caido"]


def test_agent_that_recorded_nothing_is_a_gap() -> None:
    doc = _document(
        agent_graph=_graph(
            statuses={"agent-1": "completed", "agent-2": "completed"},
            names={"agent-1": "authz-tester", "agent-2": "recon"},
            metadata={},
        )
    )

    silent = [gap for gap in doc["gaps"] if gap["kind"] == "agent_recorded_no_coverage"]
    assert [gap["agent_name"] for gap in silent] == ["recon"]


def test_needs_follow_up_is_carried_as_an_open_gap() -> None:
    doc = _document(
        entries=[_entry(outcome="needs_follow_up", evidence="Auth wall blocked testing.")]
    )

    assert doc["gaps"][0]["kind"] == "needs_follow_up"
    assert doc["gaps"][0]["detail"] == "Auth wall blocked testing."


def test_completed_run_with_finished_agents_is_complete() -> None:
    doc = _document(exit_reason="finished_by_tool")

    assert doc["completeness"]["complete"] is True
    assert doc["completeness"]["caveats"] == []


def test_budget_exhausted_run_is_not_a_complete_record() -> None:
    """A truncated scan must not read like a clean one."""
    doc = _document(exit_reason="budget_exhausted")

    assert doc["completeness"]["complete"] is False
    assert "budget_exhausted" in doc["completeness"]["caveats"][0]


def test_unfinished_agent_makes_the_record_partial() -> None:
    doc = _document(
        agent_graph=_graph(statuses={"agent-1": "crashed"}),
        exit_reason="finished_by_tool",
    )

    assert doc["completeness"]["complete"] is False
    assert "authz-tester" in doc["completeness"]["caveats"][0]


def test_failed_run_status_makes_the_record_partial() -> None:
    doc = _document(
        run_record={"run_id": "r1", "status": "failed"},
        exit_reason="finished_by_tool",
    )

    assert doc["completeness"]["complete"] is False


def test_write_coverage_emits_a_top_level_artifact(tmp_path: Path) -> None:
    path = write_coverage(tmp_path, _document())

    assert path == tmp_path / "coverage.json"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_markdown_renders_a_surface_table() -> None:
    markdown = render_coverage_markdown(_document())

    assert "# Coverage" in markdown
    assert "| POST /api/orders/{id} | object-level authorization | No issue identified |" in (
        markdown
    )


def test_markdown_says_so_when_nothing_was_recorded() -> None:
    markdown = render_coverage_markdown(_document(entries=[], agent_graph={}))

    assert "cannot be read as evidence" in markdown


def test_markdown_cell_escapes_pipes() -> None:
    markdown = render_coverage_markdown(_document(entries=[_entry(surface="a|b")]))

    assert "| a\\|b |" in markdown


def test_read_agent_graph_tolerates_a_missing_or_corrupt_snapshot(tmp_path: Path) -> None:
    assert read_agent_graph(tmp_path) == {}

    (tmp_path / "agents.json").write_text("{not json", encoding="utf-8")
    assert read_agent_graph(tmp_path) == {}


def test_read_agent_graph_loads_a_snapshot(tmp_path: Path) -> None:
    (tmp_path / "agents.json").write_text(json.dumps(_graph()), encoding="utf-8")

    assert read_agent_graph(tmp_path)["names"] == {"agent-1": "authz-tester"}
