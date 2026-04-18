"""Unit tests for the task-run anchor step-summary builder and update_anchor.

Focus: when a step is `awaiting_user_input`, the anchor payload must carry
the step's `widget_envelope`, `response_schema`, and step `title` so the web
client can render the approval UI inline in chat without a second fetch.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Message, Session
from app.services.task_run_anchor import (
    ANCHOR_MSG_KEY,
    _build_metadata,
    _step_summary,
    ensure_anchor_message,
    update_anchor,
)
from tests.factories import build_channel, build_task


def _make_task(steps, step_states):
    return SimpleNamespace(steps=steps, step_states=step_states)


def test_step_summary_passes_through_awaiting_user_input_payload():
    steps = [
        {"id": "review", "type": "user_prompt", "title": "Review tuning proposals"},
    ]
    envelope = {
        "template": {"kind": "approval_review", "title": "Tuning"},
        "args": {"proposals": [{"id": "p1"}, {"id": "p2"}]},
    }
    schema = {"type": "multi_item", "items": [{"id": "p1"}, {"id": "p2"}]}
    states = [
        {
            "status": "awaiting_user_input",
            "widget_envelope": envelope,
            "response_schema": schema,
        },
    ]

    out = _step_summary(_make_task(steps, states))

    assert len(out) == 1
    entry = out[0]
    assert entry["status"] == "awaiting_user_input"
    assert entry["widget_envelope"] == envelope
    assert entry["response_schema"] == schema
    assert entry["title"] == "Review tuning proposals"


def test_step_summary_omits_envelope_for_non_awaiting_steps():
    steps = [
        {"id": "fetch", "type": "tool"},
        {"id": "analyze", "type": "agent"},
    ]
    states = [
        {"status": "done", "result": "ok"},
        {"status": "running"},
    ]

    out = _step_summary(_make_task(steps, states))

    for entry in out:
        assert "widget_envelope" not in entry
        assert "response_schema" not in entry
        assert "title" not in entry


def test_step_summary_awaiting_without_envelope_degrades_gracefully():
    """If a step pauses but state somehow lacks the envelope, don't crash."""
    steps = [{"id": "review", "type": "user_prompt"}]
    states = [{"status": "awaiting_user_input"}]

    out = _step_summary(_make_task(steps, states))

    assert out[0]["status"] == "awaiting_user_input"
    # No envelope was present → not attached; no title on step def → not attached.
    assert "widget_envelope" not in out[0]
    assert "response_schema" not in out[0]
    assert "title" not in out[0]


def test_build_metadata_surfaces_parent_task_id_for_runs():
    """Runs are children of definitions — UI uses parent_task_id to offer
    a 'View runs' link back to the definition's Runs tab."""
    parent_id = uuid.uuid4()
    task = SimpleNamespace(
        id=uuid.uuid4(),
        parent_task_id=parent_id,
        task_type="pipeline",
        bot_id="orchestrator",
        title="Analyze Discovery",
        status="running",
        scheduled_at=None,
        completed_at=None,
        steps=[],
        step_states=[],
        execution_config={},
        result=None,
        error=None,
    )
    meta = _build_metadata(task)
    assert meta["parent_task_id"] == str(parent_id)


def test_build_metadata_parent_task_id_null_for_definitions():
    task = SimpleNamespace(
        id=uuid.uuid4(),
        parent_task_id=None,
        task_type="pipeline",
        bot_id="orchestrator",
        title="Definition",
        status="pending",
        scheduled_at=None,
        completed_at=None,
        steps=[],
        step_states=[],
        execution_config={},
        result=None,
        error=None,
    )
    meta = _build_metadata(task)
    assert meta["parent_task_id"] is None


def test_step_summary_envelope_not_leaked_when_status_is_done():
    """Old envelope lingering in state after resolve must not be forwarded."""
    steps = [{"id": "review", "type": "user_prompt"}]
    states = [
        {
            "status": "done",
            "widget_envelope": {"template": {"kind": "approval_review"}},
            "response_schema": {"type": "multi_item"},
            "result": '{"decision": "approve"}',
        },
    ]

    out = _step_summary(_make_task(steps, states))

    assert out[0]["status"] == "done"
    assert "widget_envelope" not in out[0]
    assert "response_schema" not in out[0]


# ---------------------------------------------------------------------------
# update_anchor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestUpdateAnchor:
    async def test_when_channel_id_none_then_no_op(self):
        task = build_task(channel_id=None)

        result = await update_anchor(task)

        assert result is None

    async def test_when_task_not_in_db_then_returns_silently(self, db_session, patched_async_sessions):
        task = build_task(channel_id=uuid.uuid4())

        await update_anchor(task)  # task not committed — service gets None, returns

    async def test_when_anchor_exists_then_metadata_refreshed(self, db_session, patched_async_sessions):
        session_id = uuid.uuid4()
        channel_id = uuid.uuid4()
        msg_id = uuid.uuid4()

        channel = build_channel(id=channel_id)
        session_row = Session(id=session_id, client_id="test")
        task = build_task(
            channel_id=channel_id,
            session_id=session_id,
            status="complete",
            steps=[{"type": "agent", "label": "Step 1"}],
            step_states=[{"status": "done"}],
            execution_config={ANCHOR_MSG_KEY: str(msg_id)},
        )
        msg = Message(
            id=msg_id,
            session_id=session_id,
            role="assistant",
            content="old content",
            metadata_={"kind": "task_run", "task_id": str(task.id)},
        )
        db_session.add_all([channel, session_row, task, msg])
        await db_session.commit()

        with patch("app.services.task_run_anchor._publish_message_updated", new_callable=AsyncMock):
            await update_anchor(task)

        await db_session.refresh(msg)
        assert msg.metadata_["status"] == "complete"
        assert msg.metadata_["task_id"] == str(task.id)

    async def test_when_no_existing_anchor_then_ensure_anchor_message_called(self, db_session, patched_async_sessions):
        session_id = uuid.uuid4()
        channel_id = uuid.uuid4()

        channel = build_channel(id=channel_id)
        session_row = Session(id=session_id, client_id="test")
        task = build_task(
            channel_id=channel_id,
            session_id=session_id,
            execution_config={},
        )
        db_session.add_all([channel, session_row, task])
        await db_session.commit()

        ensure_mock = AsyncMock()
        with patch("app.services.task_run_anchor.ensure_anchor_message", ensure_mock):
            await update_anchor(task)

        ensure_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# ensure_anchor_message — sub-session spawn propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEnsureAnchorMessageSubSession:
    async def test_sub_session_spawn_mirrors_run_session_id_to_caller(
        self, db_session, patched_async_sessions
    ):
        """Regression: ``run_task_pipeline`` passes its in-memory Task through
        ``ensure_anchor_message`` and then hands the SAME object to
        ``_advance_pipeline`` → ``_spawn_agent_step`` /
        ``emit_step_output_message``. The sub-session spawn happens inside
        its own db session on a refetched Task row, so without explicit
        mirroring the caller's object kept ``run_session_id=None`` and
        downstream agent-step children were spawned with ``session_id=None``,
        creating an orphan throwaway session via ``load_or_create``. The
        run-view modal then rendered empty because every Message landed on
        a different session than the one linked on ``task.run_session_id``.
        """
        parent_session_id = uuid.uuid4()
        channel_id = uuid.uuid4()
        channel = build_channel(id=channel_id, active_session_id=parent_session_id)
        parent_session = Session(
            id=parent_session_id,
            client_id="web",
            bot_id="user-bot",
            channel_id=channel_id,
            depth=0,
            session_type="channel",
        )
        task = build_task(
            channel_id=channel_id,
            session_id=parent_session_id,
            task_type="pipeline",
            run_isolation="sub_session",
            run_session_id=None,
            status="running",
            steps=[{"type": "agent", "name": "analyze"}],
            step_states=[{"status": "pending"}],
            execution_config={},
        )
        db_session.add_all([channel, parent_session, task])
        await db_session.commit()

        assert task.run_session_id is None  # precondition

        with patch(
            "app.services.task_run_anchor._publish_new_message",
            new_callable=AsyncMock,
        ):
            await ensure_anchor_message(task)

        # The caller's in-memory Task object must reflect the spawned
        # sub-session id so _spawn_agent_step / emit_step_output_message
        # thread it into child tasks and step-output Messages.
        assert task.run_session_id is not None
        # And the DB row agrees.
        await db_session.refresh(task)
        assert task.run_session_id is not None
