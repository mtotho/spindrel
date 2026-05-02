"""Unit tests for the live config audit helper.

We do not hit any live server; every HTTP call is monkeypatched. Goals:
- audit_project() classifies blocking vs suggested correctly
- apply_workflow() respects existing files (no clobber) and missing host_path
- render_report() produces stable text the user can scan
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import spindrel_live_config_audit as mod


@pytest.fixture
def patched_request(monkeypatch):
    calls: list[tuple[str, str, str | None]] = []
    responses: dict[tuple[str, str], tuple[int, object]] = {}

    def fake(host: str, path: str, api_key: str, *, method: str = "GET", body=None):
        calls.append((method, path, body and "body" or None))
        return responses.get((method, path), (200, {}))

    monkeypatch.setattr(mod, "_request", fake)
    return calls, responses


def test_audit_project_flags_factory_500_as_blocking(patched_request):
    calls, responses = patched_request
    project = {"id": "p1", "slug": "spindrel", "name": "Spindrel"}
    responses[("GET", "/api/v1/projects/p1/factory-state")] = (500, {"detail": "boom"})
    responses[("GET", "/api/v1/projects/p1/orchestration-policy")] = (
        200,
        {
            "concurrency": {"max_concurrent_runs": 2},
            "intake": {"configured": True, "kind": "repo_file"},
            "repo_workflow": {"present": True, "relative_path": ".spindrel/WORKFLOW.md"},
            "timeouts": {"turn_timeout_seconds": 1800},
            "canonical_repo": {},
        },
    )

    finding = mod.audit_project("http://x", "key", project)

    assert any("factory-state" in note for note in finding.blocking)
    assert finding.suggested == []
    assert finding.apply_actions == []


def test_audit_project_suggests_intake_and_workflow_when_unset(patched_request):
    _, responses = patched_request
    project = {"id": "p2", "slug": "demo", "name": "Demo"}
    responses[("GET", "/api/v1/projects/p2/factory-state")] = (200, {})
    responses[("GET", "/api/v1/projects/p2/orchestration-policy")] = (
        200,
        {
            "concurrency": {"max_concurrent_runs": None},
            "intake": {"configured": False, "kind": "unset"},
            "repo_workflow": {"present": False, "relative_path": ".spindrel/WORKFLOW.md"},
            "timeouts": {"turn_timeout_seconds": None},
            "canonical_repo": {"host_path": "/tmp/notreal"},
        },
    )

    finding = mod.audit_project("http://x", "key", project)

    assert finding.blocking == []
    actions = finding.apply_actions
    assert "patch_intake" in actions
    assert "write_workflow" in actions
    assert any("max_concurrent_runs" in s for s in finding.suggested)
    assert any("intake.kind" in s for s in finding.suggested)


def test_audit_project_clean_when_everything_set(patched_request):
    _, responses = patched_request
    project = {"id": "p3", "slug": "ok", "name": "OK"}
    responses[("GET", "/api/v1/projects/p3/factory-state")] = (200, {})
    responses[("GET", "/api/v1/projects/p3/orchestration-policy")] = (
        200,
        {
            "concurrency": {"max_concurrent_runs": 4},
            "intake": {"configured": True, "kind": "repo_file"},
            "repo_workflow": {"present": True, "relative_path": ".spindrel/WORKFLOW.md"},
            "timeouts": {"turn_timeout_seconds": 1800},
            "canonical_repo": {"host_path": "/repo"},
        },
    )

    finding = mod.audit_project("http://x", "key", project)
    assert finding.blocking == []
    assert finding.suggested == []
    assert finding.apply_actions == []


def test_apply_workflow_skips_when_file_present(tmp_path):
    target = tmp_path / ".spindrel" / "WORKFLOW.md"
    target.parent.mkdir(parents=True)
    target.write_text("existing", encoding="utf-8")
    project = {"id": "p", "slug": "s"}
    policy = {"canonical_repo": {"host_path": str(tmp_path)}}

    result = mod.apply_workflow("http://x", "key", project, policy)

    assert "skip" in result and str(target) in result
    assert target.read_text() == "existing"


def test_apply_workflow_writes_starter_when_missing(tmp_path):
    project = {"id": "p", "slug": "s"}
    policy = {"canonical_repo": {"host_path": str(tmp_path)}}

    result = mod.apply_workflow("http://x", "key", project, policy)

    target = tmp_path / ".spindrel" / "WORKFLOW.md"
    assert target.exists()
    assert "## intake" in target.read_text()
    assert "wrote starter" in result


def test_apply_workflow_skips_without_canonical_host_path():
    result = mod.apply_workflow("http://x", "key", {"id": "p"}, {"canonical_repo": {}})
    assert "no canonical repo host_path" in result


def test_render_report_marks_blocking_and_suggested(patched_request):
    finding = mod.ProjectFinding(
        project_id="p1", slug="spindrel", name="Spindrel",
        blocking=["factory-state endpoint returns 500"],
        suggested=["intake.kind unset"],
    )
    text = mod.render_report([finding], {"codex": 200, "claude_code": 404})
    assert "BLOCKING" in text and "factory-state" in text
    assert "suggest:" in text and "intake.kind" in text
    assert "codex: ok" in text
    assert "claude_code: HTTP 404" in text


def test_render_report_handles_empty_findings():
    text = mod.render_report([], {"codex": 200, "claude_code": 200})
    assert "no projects found" in text
