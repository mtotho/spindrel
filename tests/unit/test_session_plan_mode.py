from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.db.models import Session
from app.services import session_plan_mode as spm


def _make_session() -> Session:
    return Session(
        id=uuid.uuid4(),
        client_id=f"client-{uuid.uuid4().hex[:6]}",
        bot_id="test-bot",
        channel_id=uuid.uuid4(),
        metadata_={},
    )


def _patch_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(spm, "get_bot", lambda _bot_id: SimpleNamespace(id="test-bot"))
    monkeypatch.setattr(spm, "ensure_channel_workspace", lambda _channel_id, _bot: str(tmp_path))


def test_create_plan_writes_markdown_and_metadata(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()

    plan = spm.create_session_plan(session, title="Build Widget Planner")

    assert plan.status == spm.PLAN_STATUS_DRAFT
    assert session.metadata_["plan_mode"] == spm.PLAN_MODE_PLANNING
    assert plan.path is not None
    assert plan.path.endswith("build-widget-planner.md")
    assert "## Execution Checklist" in tmp_path.joinpath(".sessions", str(session.id), "plans", "build-widget-planner.md").read_text()


def test_enter_plan_mode_does_not_create_plan_file(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()

    spm.enter_session_plan_mode(session)

    assert session.metadata_["plan_mode"] == spm.PLAN_MODE_PLANNING
    assert session.metadata_.get("plan_active_path") is None
    assert spm.load_session_plan(session, required=False) is None
    assert not tmp_path.joinpath(".sessions", str(session.id), "plans").exists()


def test_planning_context_exists_before_first_plan(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.enter_session_plan_mode(session)

    lines = spm.build_plan_mode_system_context(session)

    assert lines
    assert any("Plan mode is active" in line for line in lines)
    assert any("publish" in line.lower() for line in lines)
    assert any("ask_plan_questions" in line for line in lines)
    assert all("Canonical plan file:" not in line for line in lines)


def test_approve_plan_marks_first_step_in_progress(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(session, title="Build Widget Planner")

    plan = spm.approve_session_plan(session)

    assert plan.status == spm.PLAN_STATUS_EXECUTING
    assert plan.steps[0].status == spm.STEP_STATUS_IN_PROGRESS
    assert session.metadata_["plan_mode"] == spm.PLAN_MODE_EXECUTING
    assert session.metadata_["plan_accepted_revision"] == 1


def test_publish_plan_creates_first_artifact(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.enter_session_plan_mode(session)

    plan = spm.publish_session_plan(
        session,
        title="Build Widget Planner",
        summary="Plan the widget work.",
        scope="Transcript-first plan mode",
        steps=[
            {"id": "gather", "label": "Gather constraints"},
            {"id": "publish", "label": "Publish the first draft"},
        ],
    )

    assert plan.revision == 1
    assert plan.path is not None
    assert plan.steps[0].label == "Gather constraints"
    assert session.metadata_["plan_active_path"].endswith("build-widget-planner.md")


def test_done_step_auto_advances_and_finishes(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Ship Widget",
        steps=[
            {"id": "step-one", "label": "Step one"},
            {"id": "step-two", "label": "Step two"},
        ],
    )
    spm.approve_session_plan(session)

    first = spm.update_plan_step_status(session, step_id="step-one", status=spm.STEP_STATUS_DONE, note="step one complete")
    assert first.status == spm.PLAN_STATUS_EXECUTING
    assert first.steps[0].status == spm.STEP_STATUS_DONE
    assert first.steps[1].status == spm.STEP_STATUS_IN_PROGRESS

    second = spm.update_plan_step_status(session, step_id="step-two", status=spm.STEP_STATUS_DONE, note="all done")
    assert second.status == spm.PLAN_STATUS_DONE
    assert second.outcome == "all done"
    assert session.metadata_["plan_mode"] == spm.PLAN_MODE_DONE


def test_cannot_update_step_status_before_plan_approval(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(session, title="Ship Widget")

    with pytest.raises(spm.HTTPException) as excinfo:
        spm.update_plan_step_status(session, step_id="clarify-scope", status=spm.STEP_STATUS_DONE)

    assert excinfo.value.status_code == 409
    assert "approved" in str(excinfo.value.detail).lower()


def test_plan_context_only_mentions_subagents_when_enabled(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.enter_session_plan_mode(session)

    monkeypatch.setattr(spm.settings, "PLAN_MODE_SUBAGENT_GUIDANCE_ENABLED", False)
    lines = spm.build_plan_mode_system_context(session)
    assert all("spawn_subagents" not in line for line in lines)
    assert all("delegate_to_agent" not in line for line in lines)

    monkeypatch.setattr(spm.settings, "PLAN_MODE_SUBAGENT_GUIDANCE_ENABLED", True)
    lines = spm.build_plan_mode_system_context(session)
    assert any("spawn_subagents" in line for line in lines)
    assert all("delegate_to_agent" not in line for line in lines)


def test_publish_plan_writes_revision_snapshot(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(session, title="Build Widget Planner")

    plan = spm.publish_session_plan(
        session,
        title="Build Widget Planner",
        summary="Revision two",
    )

    snapshot = tmp_path.joinpath(
        ".sessions",
        str(session.id),
        "plans",
        ".revisions",
        "build-widget-planner.r2.md",
    )
    assert plan.revision == 2
    assert snapshot.exists()
    assert "Revision: 2" in snapshot.read_text()


def test_append_plan_artifact_persists(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(session, title="Ship Widget")
    spm.approve_session_plan(session)

    updated = spm.append_plan_artifact(
        session,
        kind="widget_revision",
        label="widget bot/home_control @ abc1234",
        ref="bot/home_control",
        metadata={"revision": "abc1234", "operation": "create"},
    )

    assert len(updated.artifacts) == 1
    artifact = updated.artifacts[0]
    assert artifact.kind == "widget_revision"
    assert artifact.ref == "bot/home_control"
    assert artifact.metadata["revision"] == "abc1234"

    reloaded = spm.load_session_plan(session, required=True)
    assert reloaded is not None
    assert len(reloaded.artifacts) == 1
    assert reloaded.artifacts[0].label == "widget bot/home_control @ abc1234"


def test_list_plan_revisions_includes_snapshots_and_current(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(session, title="Build Widget Planner", summary="Draft one")
    spm.publish_session_plan(
        session,
        title="Build Widget Planner",
        summary="Draft two",
        scope="Updated scope",
        steps=[
            {"id": "audit", "label": "Audit the current plan flow"},
            {"id": "ship", "label": "Ship the hardening"},
        ],
    )
    spm.approve_session_plan(session)

    revisions = spm.list_session_plan_revisions(session)

    assert [entry["revision"] for entry in revisions] == [2, 1]
    assert revisions[0]["is_active"] is True
    assert revisions[0]["is_accepted"] is True
    assert revisions[0]["source"] == "current"
    assert revisions[1]["source"] == "snapshot"
    assert revisions[0]["changed_sections"]


def test_build_plan_revision_diff_uses_snapshot_content(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(session, title="Build Widget Planner", summary="Draft one", scope="Initial scope")
    spm.publish_session_plan(
        session,
        title="Build Widget Planner",
        summary="Draft two",
        scope="Updated scope",
        steps=[
            {"id": "audit", "label": "Audit the current plan flow"},
            {"id": "ship", "label": "Ship the hardening"},
        ],
    )
    spm.approve_session_plan(session)
    spm.update_plan_step_status(session, step_id="audit", status=spm.STEP_STATUS_DONE, note="execution changed current file")

    diff = spm.build_session_plan_revision_diff(session, from_revision=1, to_revision=2)

    assert diff["from_revision"] == 1
    assert diff["to_revision"] == 2
    assert "scope" in diff["changed_sections"]
    assert "steps" in diff["changed_sections"]
    assert "Execution started." not in diff["diff"]
    assert "Updated scope" in diff["diff"]
