"""Unit tests for sub-session spawn + step-output emission.

Phase 0 of the pipeline-as-chat refactor. Covers:

1. ``spawn_sub_session`` creates a Session with correct parent/root/depth
   linkage, session_type derived from task_type, and mutates
   ``task.run_session_id``.
2. ``emit_step_output_message`` writes a Message to the run session only
   for ``run_isolation='sub_session'`` tasks and skips agent/bot_invoke
   steps.
3. ``_build_metadata`` emits the slim shape (run_session_id +
   awaiting_count, no steps[]) for sub_session tasks and the legacy
   shape for inline tasks.
4. ``_fallback_text`` appends a truncated summary for sub_session tasks
   so the parent-session bot sees a usable result line without the
   sub-session's Messages being spliced into its prompt.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import Message, Session, Task
from app.services.sub_sessions import (
    SESSION_TYPE_EVAL,
    SESSION_TYPE_PIPELINE_RUN,
    emit_step_output_message,
    resolve_sub_session,
    spawn_sub_session,
)
from app.services.task_run_anchor import _build_metadata, _fallback_text


# ---------------------------------------------------------------------------
# spawn_sub_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSpawnSubSession:
    async def test_creates_session_with_parent_linkage_and_sets_run_session_id(
        self, db_session
    ):
        parent = Session(
            id=uuid.uuid4(),
            client_id="web",
            bot_id="user-bot",
            channel_id=None,
            depth=0,
            session_type="channel",
        )
        db_session.add(parent)
        await db_session.flush()

        task = Task(
            id=uuid.uuid4(),
            bot_id="orchestrator",
            prompt="p",
            status="pending",
            task_type="pipeline",
            dispatch_type="none",
            run_isolation="sub_session",
        )
        db_session.add(task)
        await db_session.flush()

        sub = await spawn_sub_session(db_session, task=task, parent_session_id=parent.id)
        await db_session.flush()

        assert sub.parent_session_id == parent.id
        assert sub.root_session_id == parent.id  # parent has no root → uses parent.id
        assert sub.depth == 1
        assert sub.session_type == SESSION_TYPE_PIPELINE_RUN
        assert sub.source_task_id == task.id
        assert sub.channel_id is None  # sub-sessions are never directly channel-bound
        assert task.run_session_id == sub.id

    async def test_eval_task_yields_eval_session_type(self, db_session):
        task = Task(
            id=uuid.uuid4(),
            bot_id="evaluator",
            prompt="p",
            status="pending",
            task_type="eval",
            dispatch_type="none",
            run_isolation="sub_session",
        )
        db_session.add(task)
        await db_session.flush()

        sub = await spawn_sub_session(db_session, task=task, parent_session_id=None)
        assert sub.session_type == SESSION_TYPE_EVAL
        assert sub.depth == 0  # no parent

    async def test_resolve_returns_none_for_inline_task(self, db_session):
        task = Task(
            id=uuid.uuid4(), bot_id="b", prompt="p", status="pending",
            task_type="pipeline", dispatch_type="none", run_isolation="inline",
        )
        db_session.add(task)
        await db_session.flush()
        assert await resolve_sub_session(db_session, task) is None


# ---------------------------------------------------------------------------
# emit_step_output_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEmitStepOutputMessage:
    async def _make_task_with_sub(self, db_session) -> Task:
        parent = Session(
            id=uuid.uuid4(), client_id="web", bot_id="b", channel_id=None,
            depth=0, session_type="channel",
        )
        sub = Session(
            id=uuid.uuid4(), client_id="task", bot_id="b", channel_id=None,
            depth=1, session_type=SESSION_TYPE_PIPELINE_RUN,
            parent_session_id=parent.id,
        )
        db_session.add_all([parent, sub])
        await db_session.flush()

        task = Task(
            id=uuid.uuid4(), bot_id="b", prompt="p", status="running",
            task_type="pipeline", dispatch_type="none",
            run_isolation="sub_session", run_session_id=sub.id,
        )
        db_session.add(task)
        await db_session.flush()
        return task

    async def test_writes_message_for_tool_step(self, db_session):
        task = await self._make_task_with_sub(db_session)
        step_def = {"type": "tool", "tool_name": "fetch_traces", "name": "Fetch traces"}
        state = {
            "status": "done",
            "result": '{"traces": [{"id": 1}, {"id": 2}]}',
            "started_at": "2026-04-18T10:00:00+00:00",
            "completed_at": "2026-04-18T10:00:00.056000+00:00",
        }

        await emit_step_output_message(
            task=task, step_def=step_def, step_index=0, state=state, db=db_session,
        )

        rows = (await db_session.execute(
            select(Message).where(Message.session_id == task.run_session_id)
        )).scalars().all()
        assert len(rows) == 1
        m = rows[0]
        assert m.role == "assistant"
        assert "traces" in m.content
        assert m.metadata_["kind"] == "step_output"
        assert m.metadata_["tool_name"] == "fetch_traces"
        assert m.metadata_["step_type"] == "tool"
        assert m.metadata_["step_index"] == 0
        assert m.metadata_["status"] == "done"
        assert m.metadata_["duration_ms"] == 56

    async def test_skips_agent_step_to_avoid_duplicate_with_child_turn(self, db_session):
        task = await self._make_task_with_sub(db_session)
        step_def = {"type": "agent", "name": "analyze"}
        state = {"status": "done", "result": "noop"}

        await emit_step_output_message(
            task=task, step_def=step_def, step_index=0, state=state, db=db_session,
        )

        rows = (await db_session.execute(
            select(Message).where(Message.session_id == task.run_session_id)
        )).scalars().all()
        assert rows == []

    async def test_no_op_for_inline_task(self, db_session):
        task = Task(
            id=uuid.uuid4(), bot_id="b", prompt="p", status="running",
            task_type="workflow", dispatch_type="none",
            run_isolation="inline",
        )
        db_session.add(task)
        await db_session.flush()

        step_def = {"type": "tool", "tool_name": "x"}
        state = {"status": "done", "result": "y"}

        # Should not raise even though task.run_session_id is None.
        await emit_step_output_message(
            task=task, step_def=step_def, step_index=0, state=state, db=db_session,
        )

    async def test_writes_error_envelope_on_failure(self, db_session):
        task = await self._make_task_with_sub(db_session)
        step_def = {"type": "tool", "tool_name": "call_api", "name": "API"}
        state = {"status": "failed", "result": None, "error": "connection refused"}

        await emit_step_output_message(
            task=task, step_def=step_def, step_index=2, state=state, db=db_session,
        )

        row = (await db_session.execute(
            select(Message).where(Message.session_id == task.run_session_id)
        )).scalar_one()
        assert row.metadata_["status"] == "failed"
        assert row.metadata_["error"] == "connection refused"
        assert "error" in row.content


# ---------------------------------------------------------------------------
# _build_metadata — shape discrimination by run_isolation
# ---------------------------------------------------------------------------


def _mk_task(**kw):
    """SimpleNamespace with the superset of fields _build_metadata reads."""
    defaults = dict(
        id=uuid.uuid4(),
        parent_task_id=None,
        task_type="pipeline",
        bot_id="orchestrator",
        title="Analyze Discovery",
        status="complete",
        scheduled_at=None,
        completed_at=None,
        steps=[],
        step_states=[],
        execution_config={},
        result=None,
        error=None,
        run_isolation="inline",
        run_session_id=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_build_metadata_inline_carries_steps_array():
    task = _mk_task(
        run_isolation="inline",
        steps=[{"id": "s1", "type": "tool"}],
        step_states=[{"status": "done", "result": "ok"}],
    )
    meta = _build_metadata(task)
    assert "steps" in meta
    assert len(meta["steps"]) == 1
    assert "run_session_id" not in meta
    assert "awaiting_count" not in meta
    assert meta["run_isolation"] == "inline"


def test_build_metadata_sub_session_drops_steps_and_carries_run_session_id():
    run_sid = uuid.uuid4()
    task = _mk_task(
        run_isolation="sub_session",
        run_session_id=run_sid,
        step_states=[
            {"status": "done"},
            {"status": "awaiting_user_input"},
            {"status": "running"},
        ],
    )
    meta = _build_metadata(task)
    assert meta["run_isolation"] == "sub_session"
    assert meta["run_session_id"] == str(run_sid)
    assert meta["step_count"] == 3
    assert meta["awaiting_count"] == 1
    assert "steps" not in meta  # slim shape — modal reads sub-session directly


def test_build_metadata_sub_session_without_spawned_session_yet():
    task = _mk_task(run_isolation="sub_session", run_session_id=None)
    meta = _build_metadata(task)
    assert meta["run_session_id"] is None


# ---------------------------------------------------------------------------
# _fallback_text — summary injection for sub-session parent-session context
# ---------------------------------------------------------------------------


def test_fallback_text_inline_is_header_only():
    task = _mk_task(
        run_isolation="inline",
        status="complete",
        result="a long result that should NOT appear because this is inline",
    )
    steps_summary = [{"status": "done"}, {"status": "done"}]
    out = _fallback_text(task, "complete", steps_summary)
    assert out == "[Analyze Discovery · complete · 2/2 steps]"


def test_fallback_text_sub_session_appends_task_result_summary():
    task = _mk_task(
        run_isolation="sub_session",
        status="complete",
        result="Recommended lowering tool_similarity_threshold from 0.5 → 0.3",
    )
    steps_summary = [{"status": "done"}] * 5
    out = _fallback_text(task, "complete", steps_summary)
    assert out.startswith("[Analyze Discovery · complete · 5/5 steps]")
    assert "tool_similarity_threshold" in out


def test_fallback_text_sub_session_truncates_long_summary():
    long_result = "x" * 800
    task = _mk_task(
        run_isolation="sub_session",
        status="complete",
        result=long_result,
    )
    out = _fallback_text(task, "complete", [{"status": "done"}])
    # Truncation sentinel + capped length
    assert out.endswith("…")
    assert len(out) < 500  # header is short; summary capped near 400


def test_fallback_text_sub_session_falls_back_to_step_preview_when_no_task_result():
    task = _mk_task(run_isolation="sub_session", status="running", result=None)
    steps_summary = [
        {"status": "done", "result_preview": "fetched 42 traces"},
        {"status": "running"},
    ]
    out = _fallback_text(task, "running", steps_summary)
    assert "fetched 42 traces" in out


def test_fallback_text_sub_session_shows_error_when_no_result():
    task = _mk_task(
        run_isolation="sub_session",
        status="failed",
        result=None,
        error="provider unreachable",
    )
    out = _fallback_text(task, "failed", [{"status": "failed"}])
    assert "provider unreachable" in out
