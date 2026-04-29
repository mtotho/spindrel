import uuid

import pytest

import app.tools.local.exec_command  # noqa: F401 - register safety tier for semantic review tests.
import app.tools.local.file_ops  # noqa: F401 - register safety tier for semantic review tests.
import app.tools.local.record_plan_progress  # noqa: F401 - register safety tier for semantic review tests.
import app.tools.local.request_plan_replan  # noqa: F401 - register safety tier for semantic review tests.
import app.tools.local.skills  # noqa: F401 - register safety tier for semantic review tests.
from app.db.models import Message, Session, ToolCall
from app.services import session_plan_mode as spm
from app.services.plan_semantic_review import (
    _deterministic_assessment,
    _step_is_execution_oriented,
    review_plan_adherence,
)


def _bundle(*, outcome: str, features: dict, step_label: str = "Implement the change") -> dict:
    return {
        "outcome": {"outcome": outcome},
        "features": features,
        "step": {
            "id": "step-1",
            "label": step_label,
            "note": None,
            "execution_oriented": _step_is_execution_oriented(step_label, None),
        },
    }


def test_step_orientation_treats_audit_as_read_only():
    assert _step_is_execution_oriented("Audit current behavior", None) is False
    assert _step_is_execution_oriented("Implement the fix", None) is True


def test_deterministic_assessment_flags_replan_conflict():
    flags, review = _deterministic_assessment(
        _bundle(
            outcome="step_done",
            features={
                "had_successful_tool": True,
                "had_any_error": False,
                "all_tool_calls_failed": False,
                "read_only_only": False,
                "had_mutation": True,
                "had_verification_signal": False,
                "requested_replan": True,
            },
        )
    )

    assert "requested_replan_conflicts_with_success_claim" in flags
    assert review is not None
    assert review["verdict"] == "needs_replan"


def test_deterministic_assessment_flags_read_only_step_done():
    flags, review = _deterministic_assessment(
        _bundle(
            outcome="step_done",
            features={
                "had_successful_tool": True,
                "had_any_error": False,
                "all_tool_calls_failed": False,
                "read_only_only": True,
                "had_mutation": False,
                "had_verification_signal": False,
                "requested_replan": False,
            },
            step_label="Implement the fix",
        )
    )

    assert "step_done_from_read_only_turn" in flags
    assert review is not None
    assert review["verdict"] == "weak_support"


def test_deterministic_assessment_supports_successful_verification():
    flags, review = _deterministic_assessment(
        _bundle(
            outcome="verification",
            features={
                "had_successful_tool": True,
                "had_supporting_successful_tool": True,
                "had_any_error": False,
                "all_tool_calls_failed": False,
                "read_only_only": False,
                "had_mutation": True,
                "had_supporting_mutation": True,
                "had_verification_signal": True,
                "requested_replan": False,
            },
            step_label="Verify the planned change",
        )
    )

    assert "verification_supported_by_successful_check" in flags
    assert review is not None
    assert review["verdict"] == "supported"


def test_deterministic_assessment_supports_mutating_step_done_with_evidence_path():
    flags, review = _deterministic_assessment(
        {
            **_bundle(
                outcome="step_done",
                features={
                    "had_successful_tool": True,
                    "had_supporting_successful_tool": True,
                    "had_any_error": False,
                    "all_tool_calls_failed": False,
                    "read_only_only": False,
                    "had_mutation": True,
                    "had_supporting_mutation": True,
                    "had_verification_signal": False,
                    "requested_replan": False,
                    "touched_paths": [".spindrel-plan-parity/adherence-marker.txt"],
                },
                step_label="Create the planned marker file",
            ),
            "outcome": {
                "outcome": "step_done",
                "summary": "Created .spindrel-plan-parity/adherence-marker.txt.",
                "evidence": ".spindrel-plan-parity/adherence-marker.txt",
            },
        }
    )

    assert "step_done_supported_by_mutation" in flags
    assert review is not None
    assert review["verdict"] == "supported"


def _professional_fields() -> dict:
    return {
        "key_changes": ["Implement the requested plan adherence behavior."],
        "interfaces": ["No public API changes beyond plan adherence state."],
        "assumptions_and_defaults": ["Use the active accepted plan revision."],
        "test_plan": ["Run focused plan semantic review tests."],
        "risks": ["Avoid marking unsupported work as complete."],
    }


def _make_session(tmp_path, monkeypatch, *, step_label: str = "Implement the planned change") -> Session:
    monkeypatch.setattr(spm, "get_bot", lambda _bot_id: type("Bot", (), {"id": "test-bot"})())
    monkeypatch.setattr(spm, "ensure_channel_workspace", lambda _channel_id, _bot: str(tmp_path))
    session = Session(
        id=uuid.uuid4(),
        client_id=f"semantic-review-{uuid.uuid4().hex[:8]}",
        bot_id="test-bot",
        channel_id=uuid.uuid4(),
        metadata_={},
    )
    spm.create_session_plan(
        session,
        title="Semantic Review Fixture",
        summary="Review whether execution evidence supports the recorded outcome.",
        scope="Plan adherence review only.",
        acceptance_criteria=["Semantic review records a deterministic verdict."],
        **_professional_fields(),
        steps=[{"id": "ship", "label": step_label}],
    )
    spm.approve_session_plan(session)
    return session


async def _record_turn(
    db_session,
    session: Session,
    *,
    correlation_id: uuid.UUID,
    tool_name: str,
    status: str,
    error: str | None = None,
    arguments: dict | None = None,
) -> None:
    db_session.add(Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content="Recorded the planned outcome.",
        correlation_id=correlation_id,
        metadata_={},
    ))
    db_session.add(ToolCall(
        id=uuid.uuid4(),
        session_id=session.id,
        bot_id=session.bot_id,
        client_id=session.client_id,
        tool_name=tool_name,
        tool_type="local",
        arguments=arguments
        if arguments is not None
        else {"cmd": "pytest tests/unit/test_plan_semantic_review.py -q"} if tool_name == "exec_command" else {},
        status=status,
        error=error,
        result="" if error else "ok",
        correlation_id=correlation_id,
    ))
    await db_session.flush()


@pytest.mark.asyncio
async def test_review_plan_adherence_flags_failed_tool_claim_without_mock(db_session, monkeypatch, tmp_path):
    session = _make_session(tmp_path, monkeypatch, step_label="Run semantic review verification")
    correlation_id = uuid.uuid4()
    db_session.add(session)
    await db_session.flush()
    spm.record_plan_progress_outcome(
        session,
        outcome=spm.PLAN_PROGRESS_OUTCOME_VERIFICATION,
        summary="Claimed verification passed.",
        step_id="ship",
        turn_id="turn-1",
        correlation_id=str(correlation_id),
    )
    await _record_turn(
        db_session,
        session,
        correlation_id=correlation_id,
        tool_name="exec_command",
        status="error",
        error="pytest failed",
    )

    review = await review_plan_adherence(db_session, session, correlation_id=str(correlation_id))

    assert "all_tools_failed" in review["deterministic_flags"]
    assert review["verdict"] == spm.PLAN_SEMANTIC_REVIEW_UNSUPPORTED
    assert review["semantic_status"] == spm.PLAN_SEMANTIC_STATUS_WARNING


@pytest.mark.asyncio
async def test_review_plan_adherence_supports_successful_verification_without_mock(db_session, monkeypatch, tmp_path):
    session = _make_session(tmp_path, monkeypatch, step_label="Run semantic review verification")
    correlation_id = uuid.uuid4()
    db_session.add(session)
    await db_session.flush()
    spm.record_plan_progress_outcome(
        session,
        outcome=spm.PLAN_PROGRESS_OUTCOME_VERIFICATION,
        summary="Verification passed.",
        step_id="ship",
        turn_id="turn-1",
        correlation_id=str(correlation_id),
    )
    await _record_turn(
        db_session,
        session,
        correlation_id=correlation_id,
        tool_name="exec_command",
        status="done",
        arguments={"cmd": "pytest tests/unit/test_plan_semantic_review.py -q"},
    )

    review = await review_plan_adherence(db_session, session, correlation_id=str(correlation_id))

    assert "verification_supported_by_successful_check" in review["deterministic_flags"]
    assert review["verdict"] == spm.PLAN_SEMANTIC_REVIEW_SUPPORTED
    assert review["semantic_status"] == spm.PLAN_SEMANTIC_STATUS_OK


@pytest.mark.asyncio
async def test_review_plan_adherence_supports_mutating_step_done_without_mock(db_session, monkeypatch, tmp_path):
    session = _make_session(tmp_path, monkeypatch, step_label="Create the planned marker file")
    correlation_id = uuid.uuid4()
    marker_path = ".spindrel-plan-parity/adherence-marker.txt"
    db_session.add(session)
    await db_session.flush()
    spm.record_plan_progress_outcome(
        session,
        outcome=spm.PLAN_PROGRESS_OUTCOME_STEP_DONE,
        summary=f"Created {marker_path}.",
        evidence=marker_path,
        step_id="ship",
        turn_id="turn-1",
        correlation_id=str(correlation_id),
    )
    await _record_turn(
        db_session,
        session,
        correlation_id=correlation_id,
        tool_name="file",
        status="done",
        arguments={"path": marker_path, "content": "native plan adherence marker"},
    )

    review = await review_plan_adherence(db_session, session, correlation_id=str(correlation_id))

    assert "step_done_supported_by_mutation" in review["deterministic_flags"]
    assert review["verdict"] == spm.PLAN_SEMANTIC_REVIEW_SUPPORTED
    assert review["semantic_status"] == spm.PLAN_SEMANTIC_STATUS_OK


@pytest.mark.asyncio
async def test_review_plan_adherence_flags_read_only_step_done_without_mock(db_session, monkeypatch, tmp_path):
    session = _make_session(tmp_path, monkeypatch, step_label="Implement the planned change")
    correlation_id = uuid.uuid4()
    db_session.add(session)
    await db_session.flush()
    spm.record_plan_progress_outcome(
        session,
        outcome=spm.PLAN_PROGRESS_OUTCOME_STEP_DONE,
        summary="Claimed implementation is done.",
        step_id="ship",
        turn_id="turn-1",
        correlation_id=str(correlation_id),
    )
    await _record_turn(
        db_session,
        session,
        correlation_id=correlation_id,
        tool_name="get_skill",
        status="done",
    )

    review = await review_plan_adherence(db_session, session, correlation_id=str(correlation_id))

    assert "step_done_from_read_only_turn" in review["deterministic_flags"]
    assert review["verdict"] == spm.PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT
    assert review["recommended_action"] == "review_manually"


@pytest.mark.asyncio
async def test_review_plan_adherence_flags_replan_conflict_without_mock(db_session, monkeypatch, tmp_path):
    session = _make_session(tmp_path, monkeypatch, step_label="Ship the accepted plan")
    correlation_id = uuid.uuid4()
    db_session.add(session)
    await db_session.flush()
    spm.record_plan_progress_outcome(
        session,
        outcome=spm.PLAN_PROGRESS_OUTCOME_STEP_DONE,
        summary="Claimed the step completed even though the turn requested replan.",
        step_id="ship",
        turn_id="turn-1",
        correlation_id=str(correlation_id),
    )
    await _record_turn(
        db_session,
        session,
        correlation_id=correlation_id,
        tool_name="request_plan_replan",
        status="done",
    )

    review = await review_plan_adherence(db_session, session, correlation_id=str(correlation_id))

    assert "requested_replan_conflicts_with_success_claim" in review["deterministic_flags"]
    assert review["verdict"] == spm.PLAN_SEMANTIC_REVIEW_NEEDS_REPLAN
    assert review["semantic_status"] == spm.PLAN_SEMANTIC_STATUS_NEEDS_REPLAN
