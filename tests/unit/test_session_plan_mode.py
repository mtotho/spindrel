from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.db.models import Session
from app.domain.errors import DomainError
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


def _professional_fields() -> dict:
    return {
        "key_changes": ["Implement the requested plan-mode behavior in the owning subsystem."],
        "interfaces": ["No public API changes beyond the session plan response shape under test."],
        "assumptions_and_defaults": ["Use existing session plan defaults unless a test overrides them."],
        "test_plan": ["Run the focused session plan mode regression tests."],
        "risks": ["Keep unrelated session-plan state transitions unchanged."],
    }


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
    artifact_context = spm.build_plan_artifact_context(session)
    assert artifact_context is not None
    assert "Plan runtime capsule" in artifact_context
    assert "Planning state capsule" in artifact_context
    assert "Next action: clarify_scope" in artifact_context


def test_planning_state_records_question_answers_and_enters_context(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.enter_session_plan_mode(session)

    state = spm.record_plan_question_answers(
        session,
        title="Scope choices",
        answers=[
            {"question_id": "strictness", "label": "Strictness", "answer": "Guardrail-first"},
            {"question_id": "subagents", "label": "Subagents", "answer": "Default off"},
        ],
        source_message_id="msg-1",
    )

    assert len(state["decisions"]) == 2
    assert state["decisions"][0]["text"] == "Strictness: Guardrail-first"
    plan_state = spm.get_session_plan_state(session)
    assert plan_state["planning_state"]["decisions"][1]["answer"] == "Default off"
    context = spm.build_plan_artifact_context(session)
    assert context is not None
    assert "Planning state capsule" in context
    assert "Strictness: Guardrail-first" in context


def test_plan_artifact_context_summarizes_canonical_plan(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.publish_session_plan(
        session,
        title="Build Context Profiles",
        summary="Keep planning lean while retaining durable decisions.",
        scope="Context management policy and reporting.",
        assumptions=["history_mode=file remains the default"],
        open_questions=["Do evals prove planning needs more than two live turns?"],
        steps=[
            {"id": "policy", "label": "Make admission policy mode-aware"},
            {"id": "reporting", "label": "Expose gross/current/cached prompt usage"},
        ],
        acceptance_criteria=["Planning can recover older decisions from the plan artifact"],
    )

    text = spm.build_plan_artifact_context(session)

    assert text is not None
    assert "Active plan artifact" in text
    assert "Build Context Profiles" in text
    assert "Keep planning lean" in text
    assert "history_mode=file remains the default" in text
    assert "[pending] policy | Make admission policy mode-aware" in text
    assert "Planning can recover older decisions" in text


def test_plan_validation_warns_when_planning_decision_missing_from_draft(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.enter_session_plan_mode(session)
    spm.update_planning_state(session, decisions=["Use default-off subagent guidance"], reason="test")

    plan = spm.publish_session_plan(
        session,
        title="Plan Runtime",
        summary="Improve runtime state.",
        scope="Plan context only.",
        acceptance_criteria=["Runtime state is visible."],
        steps=[{"id": "runtime", "label": "Expose runtime state"}],
    )
    validation = spm.validate_plan_for_approval(plan, planning_state=spm.get_planning_state(session))

    assert any(issue["code"] == "planning_state_not_reflected" for issue in validation["issues"])


def test_approve_plan_marks_first_step_in_progress(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Build Widget Planner",
        summary="Build a transcript-first widget planner.",
        scope="Plan artifact approval and execution.",
        acceptance_criteria=["The first step starts after approval."],
        **_professional_fields(),
    )

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
        summary="Ship the widget in two verified steps.",
        scope="Widget implementation and verification.",
        acceptance_criteria=["Both steps complete in order."],
        **_professional_fields(),
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
    spm.create_session_plan(
        session,
        title="Ship Widget",
        summary="Ship the widget change.",
        scope="Widget implementation only.",
        acceptance_criteria=["The change is verified."],
    )

    with pytest.raises(DomainError) as excinfo:
        spm.update_plan_step_status(session, step_id="clarify-scope", status=spm.STEP_STATUS_DONE)

    assert excinfo.value.http_status == 409
    assert "approved" in str(excinfo.value.detail).lower()


def test_approval_rejects_thin_plan_and_state_reports_validation(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(session, title="Thin Plan")

    state = spm.get_session_plan_state(session)
    assert state["validation"]["ok"] is False
    assert any(issue["code"] == "missing_acceptance_criteria" for issue in state["validation"]["issues"])

    with pytest.raises(DomainError) as excinfo:
        spm.approve_session_plan(session)

    assert excinfo.value.http_status == 422
    assert "acceptance criterion" in str(excinfo.value.detail).lower()


def test_approval_rejects_plan_missing_professional_contract(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    plan = spm.create_session_plan(
        session,
        title="Thin Professional Plan",
        summary="Improve the plan mode mechanics.",
        scope="Plan validation only; no UI changes.",
        acceptance_criteria=["Approval rejects weak professional plans."],
        steps=[{"id": "implement", "label": "Implement changes"}],
    )

    validation = spm.validate_plan_for_approval(plan)
    codes = {issue["code"] for issue in validation["issues"]}

    assert validation["ok"] is False
    assert "missing_key_changes" in codes
    assert "missing_interfaces" in codes
    assert "missing_assumptions_and_defaults" in codes
    assert "missing_test_plan" in codes
    assert "vague_step_label" in codes


def test_professional_plan_markdown_round_trips_new_sections(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    plan = spm.create_session_plan(
        session,
        title="Professional Plan",
        summary="Exercise the richer plan artifact.",
        scope="Artifact round-trip only; no execution.",
        acceptance_criteria=["The richer sections survive parse/render."],
        **_professional_fields(),
        steps=[{"id": "round-trip", "label": "Round-trip the richer plan sections"}],
    )

    parsed = spm.parse_plan_markdown(spm.render_plan_markdown(plan), path=plan.path)

    assert parsed.key_changes == plan.key_changes
    assert parsed.interfaces == plan.interfaces
    assert parsed.assumptions_and_defaults == plan.assumptions_and_defaults
    assert parsed.test_plan == plan.test_plan
    assert parsed.risks == plan.risks


def test_first_publish_requires_readiness_signal(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.enter_session_plan_mode(session)

    readiness = spm.validate_plan_for_publish(
        session,
        assumptions=[],
        assumptions_and_defaults=[],
        open_questions=[],
    )

    assert readiness["ok"] is False
    assert any(issue["code"] == "publish_missing_readiness" for issue in readiness["issues"])


def test_first_publish_allows_explicit_assumptions(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.enter_session_plan_mode(session)

    readiness = spm.validate_plan_for_publish(
        session,
        assumptions=[],
        assumptions_and_defaults=["Proceed with the user's requested defaults for the first draft."],
        open_questions=[],
    )

    assert readiness["ok"] is True


def test_first_publish_blocks_carried_open_questions(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.enter_session_plan_mode(session)
    spm.update_planning_state(session, decisions=["Use backend validation"], reason="test")

    readiness = spm.validate_plan_for_publish(
        session,
        assumptions=[],
        assumptions_and_defaults=["Proceed with backend validation."],
        open_questions=["Which subsystem should own the validation?"],
    )

    assert readiness["ok"] is False
    assert any(issue["code"] == "publish_has_open_questions" for issue in readiness["issues"])


def test_legacy_plan_markdown_without_professional_sections_still_parses(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    markdown = f"""# Legacy Plan

Status: draft
Revision: 1
Session: {session.id}
Task: legacy-plan

## Summary
Legacy summary.

## Scope
Legacy scope.

## Assumptions
- None

## Open Questions
- None

## Execution Checklist
- [pending] inspect | Inspect legacy behavior

## Artifacts
- None

## Acceptance Criteria
- Legacy plan parses.

## Outcome
Pending execution.
"""

    parsed = spm.parse_plan_markdown(markdown)

    assert parsed.key_changes == []
    assert parsed.interfaces == []
    assert parsed.assumptions_and_defaults == []
    assert parsed.test_plan == []
    assert parsed.risks == []


def test_runtime_capsule_tracks_current_step_and_compaction_watermark(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    session.summary_message_id = uuid.uuid4()
    spm.create_session_plan(
        session,
        title="Runtime Capsule",
        summary="Track durable plan execution state.",
        scope="Plan runtime metadata.",
        acceptance_criteria=["Runtime identifies the active step."],
        **_professional_fields(),
        steps=[
            {"id": "audit", "label": "Audit runtime fields"},
            {"id": "ship", "label": "Ship runtime fields"},
        ],
    )
    spm.approve_session_plan(session)

    runtime = session.metadata_["plan_runtime"]

    assert runtime["mode"] == spm.PLAN_MODE_EXECUTING
    assert runtime["plan_revision"] == 1
    assert runtime["accepted_revision"] == 1
    assert runtime["current_step_id"] == "audit"
    assert runtime["next_action"] == "execute_current_step"
    assert runtime["adherence_status"] in {"unknown", "ok"}
    assert runtime["compaction_watermark_message_id"] == str(session.summary_message_id)


def test_execution_evidence_updates_adherence_and_runtime(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Evidence Loop",
        summary="Capture execution evidence.",
        scope="Plan adherence metadata.",
        acceptance_criteria=["Tool evidence is durable."],
        **_professional_fields(),
        steps=[{"id": "run-tests", "label": "Run focused tests"}],
    )
    spm.approve_session_plan(session)

    adherence = spm.record_plan_execution_evidence(
        session,
        tool_name="exec_command",
        tool_kind="local",
        status="done",
        tool_call_id="call-1",
        record_id="record-1",
        arguments={"cmd": "pytest tests/unit/test_session_plan_mode.py -q"},
        result_summary="16 passed",
    )

    assert adherence is not None
    assert adherence["status"] == "ok"
    assert adherence["latest_evidence"]["step_id"] == "run-tests"
    runtime = spm.build_plan_runtime_capsule(session, spm.load_session_plan(session, required=True))
    assert runtime["adherence_status"] == "ok"
    assert runtime["latest_evidence"]["summary"] == "16 passed"


def test_missing_turn_outcome_marks_pending_and_blocks_mutation(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Outcome Gate",
        summary="Require an execution turn outcome.",
        scope="Plan supervisor metadata.",
        acceptance_criteria=["Missing outcomes block further mutation."],
        **_professional_fields(),
        steps=[{"id": "audit", "label": "Audit turn state"}],
    )
    spm.approve_session_plan(session)

    pending = spm.mark_plan_turn_outcome_pending(
        session,
        turn_id="turn-1",
        correlation_id="turn-1",
        assistant_summary="I inspected the repo but did not record an outcome.",
    )

    assert pending is not None
    assert pending["step_id"] == "audit"
    runtime = spm.build_plan_runtime_capsule(session, spm.load_session_plan(session, required=True))
    assert runtime["pending_turn_outcome"]["turn_id"] == "turn-1"
    assert spm.tool_allowed_in_plan_mode(
        session,
        tool_name="record_plan_progress",
        tool_kind="local",
        safety_tier="mutating",
    )
    assert not spm.tool_allowed_in_plan_mode(
        session,
        tool_name="exec_command",
        tool_kind="local",
        safety_tier="exec_capable",
    )
    reason = spm.plan_mode_tool_denial_reason(
        session,
        tool_name="exec_command",
        tool_kind="local",
        safety_tier="exec_capable",
    )
    assert reason is not None
    assert "missing a plan outcome" in reason


def test_record_plan_progress_clears_pending_outcome(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Progress Gate",
        summary="Clear pending execution outcome.",
        scope="Plan progress metadata.",
        acceptance_criteria=["Progress clears pending turn outcome."],
        **_professional_fields(),
        steps=[{"id": "audit", "label": "Audit turn state"}],
    )
    spm.approve_session_plan(session)
    spm.mark_plan_turn_outcome_pending(
        session,
        turn_id="turn-1",
        correlation_id="turn-1",
        assistant_summary="Need explicit outcome.",
    )

    outcome = spm.record_plan_progress_outcome(
        session,
        outcome=spm.PLAN_PROGRESS_OUTCOME_PROGRESS,
        summary="Audited the current turn state.",
        step_id="audit",
        evidence="Focused test added.",
        turn_id="turn-2",
        correlation_id="turn-2",
    )

    assert outcome["outcome"] == "progress"
    assert outcome["turn_id"] == "turn-1"
    runtime = spm.build_plan_runtime_capsule(session, spm.load_session_plan(session, required=True))
    assert runtime.get("pending_turn_outcome") is None
    assert runtime["latest_outcome"]["summary"] == "Audited the current turn state."
    assert runtime["adherence_status"] == "ok"
    assert spm.tool_allowed_in_plan_mode(
        session,
        tool_name="exec_command",
        tool_kind="local",
        safety_tier="exec_capable",
    )


def test_record_plan_progress_step_done_advances_plan(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Step Outcome",
        summary="Step done outcome advances the checklist.",
        scope="Plan progress tool behavior.",
        acceptance_criteria=["Step done updates the active step."],
        **_professional_fields(),
        steps=[
            {"id": "audit", "label": "Audit turn state"},
            {"id": "ship", "label": "Ship supervisor state"},
        ],
    )
    spm.approve_session_plan(session)

    spm.record_plan_progress_outcome(
        session,
        outcome=spm.PLAN_PROGRESS_OUTCOME_STEP_DONE,
        summary="Audit completed.",
        step_id="audit",
        turn_id="turn-2",
        correlation_id="turn-2",
    )

    plan = spm.load_session_plan(session, required=True)
    assert plan.steps[0].status == spm.STEP_STATUS_DONE
    assert plan.steps[1].status == spm.STEP_STATUS_IN_PROGRESS
    assert session.metadata_["plan_adherence"]["latest_outcome"]["outcome"] == "step_done"


def test_executing_guard_blocks_mutating_tools_when_replan_pending(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Guard Loop",
        summary="Guard stale execution.",
        scope="Tool dispatch guard.",
        acceptance_criteria=["Replan blocks mutation."],
        **_professional_fields(),
        steps=[{"id": "audit", "label": "Audit current state"}],
    )
    spm.approve_session_plan(session)
    assert spm.tool_allowed_in_plan_mode(
        session,
        tool_name="exec_command",
        tool_kind="local",
        safety_tier="exec_capable",
    )
    spm.request_plan_replan(session, reason="Scope changed", affected_step_ids=["audit"], revision=1)

    reason = spm.plan_mode_tool_denial_reason(
        session,
        tool_name="exec_command",
        tool_kind="local",
        safety_tier="exec_capable",
    )

    assert reason is not None
    assert "disabled" in reason.lower() or "plan mode" in reason.lower()


def test_blocked_plan_still_allows_replan_tool(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Blocked Replan",
        summary="Allow the replan escape hatch.",
        scope="Blocked execution tool guard.",
        acceptance_criteria=["Blocked plans can request a replan."],
        **_professional_fields(),
        steps=[{"id": "audit", "label": "Audit blocked state"}],
    )
    spm.approve_session_plan(session)
    spm.update_plan_step_status(session, step_id="audit", status=spm.STEP_STATUS_BLOCKED, note="Need a new path")

    assert spm.tool_allowed_in_plan_mode(
        session,
        tool_name="request_plan_replan",
        tool_kind="local",
        safety_tier="mutating",
    )
    assert spm.plan_mode_tool_denial_reason(
        session,
        tool_name="request_plan_replan",
        tool_kind="local",
        safety_tier="mutating",
    ) is None


def test_request_replan_preserves_accepted_revision_and_returns_to_planning(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Replan Flow",
        summary="Exercise replan transitions.",
        scope="Accepted revision handling.",
        acceptance_criteria=["A replan creates a new draft revision."],
        **_professional_fields(),
        steps=[
            {"id": "audit", "label": "Audit the accepted plan"},
            {"id": "ship", "label": "Ship the accepted plan"},
        ],
    )
    spm.approve_session_plan(session)

    plan = spm.request_plan_replan(
        session,
        reason="The audit uncovered a missing acceptance gate.",
        affected_step_ids=["audit"],
        evidence="runtime trace",
        revision=1,
    )

    assert plan.revision == 2
    assert plan.status == spm.PLAN_STATUS_DRAFT
    assert session.metadata_["plan_mode"] == spm.PLAN_MODE_PLANNING
    assert session.metadata_["plan_accepted_revision"] == 1
    assert session.metadata_["plan_runtime"]["replan"]["from_revision"] == 1
    assert session.metadata_["plan_runtime"]["current_step_id"] is None
    assert session.metadata_["plan_runtime"]["next_action"] == "resolve_open_questions"
    assert any("Replan required" in item for item in plan.open_questions)


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
    spm.create_session_plan(
        session,
        title="Ship Widget",
        summary="Ship a widget revision.",
        scope="Widget revision artifact tracking.",
        acceptance_criteria=["The artifact is recorded."],
        **_professional_fields(),
    )
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
    spm.create_session_plan(
        session,
        title="Build Widget Planner",
        summary="Draft one",
        scope="Initial scope",
        acceptance_criteria=["The plan can be approved."],
        **_professional_fields(),
    )
    spm.publish_session_plan(
        session,
        title="Build Widget Planner",
        summary="Draft two",
        scope="Updated scope",
        acceptance_criteria=["The plan can be approved."],
        **_professional_fields(),
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
    spm.create_session_plan(
        session,
        title="Build Widget Planner",
        summary="Draft one",
        scope="Initial scope",
        acceptance_criteria=["The plan can be approved."],
        **_professional_fields(),
    )
    spm.publish_session_plan(
        session,
        title="Build Widget Planner",
        summary="Draft two",
        scope="Updated scope",
        acceptance_criteria=["The plan can be approved."],
        **_professional_fields(),
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


def test_record_plan_semantic_review_updates_runtime_and_adherence(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    session = _make_session()
    spm.create_session_plan(
        session,
        title="Semantic Review",
        summary="Track semantic adherence separately from protocol adherence.",
        scope="Plan runtime metadata and review surfaces.",
        acceptance_criteria=["Semantic review is visible in runtime and adherence state."],
        **_professional_fields(),
        steps=[{"id": "ship", "label": "Wire semantic review runtime state"}],
    )
    spm.approve_session_plan(session)

    review = spm.record_plan_semantic_review(
        session,
        {
            "correlation_id": str(uuid.uuid4()),
            "step_id": "ship",
            "outcome": "verification",
            "verdict": spm.PLAN_SEMANTIC_REVIEW_SUPPORTED,
            "confidence": 0.88,
            "reason": "The turn included the expected verification command and outcome.",
            "recommended_action": "continue",
        },
    )

    assert review["semantic_status"] == spm.PLAN_SEMANTIC_STATUS_OK
    runtime = spm.build_plan_runtime_capsule(session, spm.load_session_plan(session, required=True))
    adherence = spm.build_plan_adherence_state(session, spm.load_session_plan(session, required=True))
    assert runtime["semantic_status"] == spm.PLAN_SEMANTIC_STATUS_OK
    assert runtime["latest_semantic_review"]["verdict"] == spm.PLAN_SEMANTIC_REVIEW_SUPPORTED
    assert adherence["latest_semantic_review"]["reason"].startswith("The turn included")
    assert adherence["semantic_reviews"][-1]["recommended_action"] == "continue"
