from __future__ import annotations

import uuid
from types import SimpleNamespace

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


def test_approve_plan_marks_first_step_in_progress(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(session, title="Build Widget Planner")

    plan = spm.approve_session_plan(session)

    assert plan.status == spm.PLAN_STATUS_EXECUTING
    assert plan.steps[0].status == spm.STEP_STATUS_IN_PROGRESS
    assert session.metadata_["plan_mode"] == spm.PLAN_MODE_EXECUTING
    assert session.metadata_["plan_accepted_revision"] == 1


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
