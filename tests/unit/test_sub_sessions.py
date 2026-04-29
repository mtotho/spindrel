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

from app.db.models import Channel, Message, Session, Task
from app.services.sub_session_bus import resolve_sub_session_entry
from app.services.sub_sessions import (
    SESSION_TYPE_EPHEMERAL,
    SESSION_TYPE_EVAL,
    SESSION_TYPE_PIPELINE_RUN,
    emit_step_output_message,
    resolve_sub_session,
    spawn_ephemeral_session,
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
# spawn_ephemeral_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSpawnEphemeralSession:
    async def test_creates_ephemeral_session_without_parent(self, db_session):
        """spawn_ephemeral_session with no parent creates a standalone session."""
        sub = await spawn_ephemeral_session(db_session, bot_id="test-bot")
        await db_session.flush()

        assert sub.session_type == SESSION_TYPE_EPHEMERAL
        assert sub.source_task_id is None
        assert sub.channel_id is None
        assert sub.parent_session_id is None
        assert sub.bot_id == "test-bot"

    async def test_creates_ephemeral_session_with_parent_channel(self, db_session):
        """spawn_ephemeral_session links to parent channel's active session."""
        # Create a parent session first
        parent_session = Session(
            id=uuid.uuid4(),
            client_id="web",
            bot_id="test-bot",
            channel_id=None,
            depth=0,
            session_type="channel",
        )
        db_session.add(parent_session)
        await db_session.flush()

        channel = Channel(
            id=uuid.uuid4(),
            name="test",
            bot_id="test-bot",
            active_session_id=parent_session.id,
        )
        # Link parent session to channel
        parent_session.channel_id = channel.id
        db_session.add(channel)
        await db_session.flush()

        sub = await spawn_ephemeral_session(
            db_session, bot_id="test-bot", parent_channel_id=channel.id
        )
        await db_session.flush()

        assert sub.session_type == SESSION_TYPE_EPHEMERAL
        assert sub.parent_session_id == parent_session.id
        assert sub.source_task_id is None

    async def test_creates_context_message_when_context_provided(self, db_session):
        """spawn_ephemeral_session persists context as ephemeral_context system message."""
        sub = await spawn_ephemeral_session(
            db_session,
            bot_id="test-bot",
            context={"page_name": "widget_dashboard", "url": "/widgets"},
        )
        await db_session.flush()

        msgs = (await db_session.execute(
            select(Message).where(Message.session_id == sub.id)
        )).scalars().all()

        assert len(msgs) == 1
        assert msgs[0].role == "system"
        assert msgs[0].metadata_["kind"] == "ephemeral_context"

    async def test_no_context_message_when_context_is_none(self, db_session):
        """spawn_ephemeral_session with no context produces no messages."""
        sub = await spawn_ephemeral_session(db_session, bot_id="test-bot")
        await db_session.flush()

        msgs = (await db_session.execute(
            select(Message).where(Message.session_id == sub.id)
        )).scalars().all()

        assert len(msgs) == 0


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

    async def test_tool_step_stamps_envelope_for_rich_ui(self, db_session):
        """Tool step results must carry a ``ToolResultEnvelope`` on
        ``metadata.envelope`` so ``MessageBubble`` → ``RichToolResult``
        dispatches to the JSON/markdown/diff/etc. renderers instead of
        falling back to a raw MarkdownContent dump."""
        task = await self._make_task_with_sub(db_session)
        step_def = {"type": "tool", "tool_name": "call_api", "name": "Fetch bot"}
        state = {
            "status": "done",
            "result": '{"status": 200, "body": {"id": "olivia-bot", "name": "Sprout"}}',
            "started_at": "2026-04-18T10:00:00+00:00",
            "completed_at": "2026-04-18T10:00:00.050000+00:00",
        }

        await emit_step_output_message(
            task=task, step_def=step_def, step_index=2, state=state, db=db_session,
        )

        row = (await db_session.execute(
            select(Message).where(Message.session_id == task.run_session_id)
        )).scalar_one()
        env = row.metadata_.get("envelope")
        assert env is not None, "tool step must populate metadata.envelope"
        assert env["content_type"] == "application/json"
        assert env["tool_name"] == "call_api"
        assert env["display"] == "inline"
        assert "olivia-bot" in (env.get("body") or "")
        # `source` drives the header chip in MessageBubble's rich-envelope path.
        assert row.metadata_["source"] == "call_api"

    async def test_failed_tool_step_omits_envelope(self, db_session):
        """Failed steps render via the plain error-text path — no
        envelope means MessageBubble falls back to MarkdownContent
        (which shows the `[error] ...` string)."""
        task = await self._make_task_with_sub(db_session)
        step_def = {"type": "tool", "tool_name": "call_api"}
        state = {"status": "failed", "result": None, "error": "boom"}

        await emit_step_output_message(
            task=task, step_def=step_def, step_index=0, state=state, db=db_session,
        )

        row = (await db_session.execute(
            select(Message).where(Message.session_id == task.run_session_id)
        )).scalar_one()
        assert "envelope" not in row.metadata_

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


# ---------------------------------------------------------------------------
# resolve_sub_session_entry — chat router's sub-session detector
# ---------------------------------------------------------------------------


async def _build_chain(db_session, *, task_status: str = "complete", bot_id: str = "orch"):
    """Build channel → parent_session → sub_session → task chain."""
    channel_id = uuid.uuid4()
    channel = Channel(
        id=channel_id,
        client_id="web",
        bot_id=bot_id,
        name="t",
    )
    db_session.add(channel)
    parent = Session(
        id=uuid.uuid4(),
        client_id="web",
        bot_id=bot_id,
        channel_id=channel_id,
        depth=0,
        session_type="channel",
    )
    sub = Session(
        id=uuid.uuid4(),
        client_id="task",
        bot_id=bot_id,
        channel_id=None,
        parent_session_id=parent.id,
        root_session_id=parent.id,
        depth=1,
        session_type=SESSION_TYPE_PIPELINE_RUN,
    )
    db_session.add_all([parent, sub])
    await db_session.flush()

    task = Task(
        id=uuid.uuid4(),
        bot_id=bot_id,
        prompt="p",
        status=task_status,
        task_type="pipeline",
        dispatch_type="none",
        run_isolation="sub_session",
        run_session_id=sub.id,
        channel_id=channel_id,
    )
    db_session.add(task)
    await db_session.flush()
    # Back-reference
    sub.source_task_id = task.id
    await db_session.flush()
    return channel, parent, sub, task


@pytest.mark.asyncio
class TestResolveSubSessionEntry:
    async def test_returns_entry_for_terminal_sub_session(self, db_session):
        channel, parent, sub, task = await _build_chain(db_session, task_status="complete")
        entry = await resolve_sub_session_entry(db_session, sub.id)
        assert entry is not None
        assert entry.session.id == sub.id
        assert entry.parent_channel_id == channel.id
        assert entry.source_task.id == task.id

    async def test_returns_none_for_channel_session(self, db_session):
        """A normal channel session is not a sub-session entry — falls through
        to the regular chat path."""
        channel_id = uuid.uuid4()
        channel = Channel(id=channel_id, client_id="web", bot_id="b", name="t")
        db_session.add(channel)
        sess = Session(
            id=uuid.uuid4(),
            client_id="web",
            bot_id="b",
            channel_id=channel_id,
            depth=0,
            session_type="channel",
        )
        db_session.add(sess)
        await db_session.flush()
        assert await resolve_sub_session_entry(db_session, sess.id) is None

    async def test_returns_none_when_source_task_missing(self, db_session):
        """A sub-session with no source_task_id is an orphan — don't accept a
        follow-up turn against it (we can't resolve the bot or the status)."""
        channel_id = uuid.uuid4()
        channel = Channel(id=channel_id, client_id="web", bot_id="b", name="t")
        db_session.add(channel)
        parent = Session(
            id=uuid.uuid4(),
            client_id="web",
            bot_id="b",
            channel_id=channel_id,
            depth=0,
            session_type="channel",
        )
        sub = Session(
            id=uuid.uuid4(),
            client_id="task",
            bot_id="b",
            channel_id=None,
            parent_session_id=parent.id,
            root_session_id=parent.id,
            depth=1,
            session_type=SESSION_TYPE_PIPELINE_RUN,
            source_task_id=None,
        )
        db_session.add_all([parent, sub])
        await db_session.flush()
        assert await resolve_sub_session_entry(db_session, sub.id) is None

    async def test_returns_none_for_missing_session(self, db_session):
        assert await resolve_sub_session_entry(db_session, uuid.uuid4()) is None

    async def test_walks_through_nested_sub_session(self, db_session):
        """An eval spawned inside a pipeline_run still resolves to the original
        parent channel."""
        channel, parent, sub, task = await _build_chain(db_session)
        nested_task = Task(
            id=uuid.uuid4(),
            bot_id="orch",
            prompt="nested",
            status="complete",
            task_type="eval",
            dispatch_type="none",
            run_isolation="sub_session",
        )
        db_session.add(nested_task)
        nested_sub = Session(
            id=uuid.uuid4(),
            client_id="task",
            bot_id="orch",
            channel_id=None,
            parent_session_id=sub.id,
            root_session_id=parent.id,
            depth=2,
            session_type=SESSION_TYPE_EVAL,
            source_task_id=nested_task.id,
        )
        db_session.add(nested_sub)
        nested_task.run_session_id = nested_sub.id
        await db_session.flush()

        entry = await resolve_sub_session_entry(db_session, nested_sub.id)
        assert entry is not None
        assert entry.parent_channel_id == channel.id

    async def test_resolves_ephemeral_session_without_task(self, db_session):
        """An ephemeral session resolves even with no source_task_id."""
        ephemeral = Session(
            id=uuid.uuid4(),
            client_id="ephemeral",
            bot_id="test-bot",
            channel_id=None,
            depth=0,
            session_type=SESSION_TYPE_EPHEMERAL,
            source_task_id=None,
        )
        db_session.add(ephemeral)
        await db_session.flush()

        entry = await resolve_sub_session_entry(db_session, ephemeral.id)
        assert entry is not None
        assert entry.session.id == ephemeral.id
        assert entry.source_task is None
        # No parent channel since there is no parent_session_id chain
        assert entry.parent_channel_id is None

    async def test_resolves_ephemeral_session_with_parent_channel(self, db_session):
        """An ephemeral session with a parent resolves to the parent's channel."""
        channel, parent, _, _ = await _build_chain(db_session)
        ephemeral = Session(
            id=uuid.uuid4(),
            client_id="ephemeral",
            bot_id="test-bot",
            channel_id=None,
            parent_session_id=parent.id,
            root_session_id=parent.id,
            depth=1,
            session_type=SESSION_TYPE_EPHEMERAL,
            source_task_id=None,
        )
        db_session.add(ephemeral)
        await db_session.flush()

        entry = await resolve_sub_session_entry(db_session, ephemeral.id)
        assert entry is not None
        assert entry.source_task is None
        assert entry.parent_channel_id == channel.id


# ---------------------------------------------------------------------------
# _try_resolve_sub_session_chat — terminal/auth gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSubSessionChatResolver:
    async def test_resolves_and_normalizes_bot_id(self, db_session):
        from app.routers.chat._helpers import _try_resolve_sub_session_chat
        from app.schemas.chat import ChatRequest

        channel, parent, sub, task = await _build_chain(
            db_session, task_status="complete", bot_id="orchestrator",
        )
        # Seed a couple of Messages on the sub-session so history load is real.
        db_session.add_all([
            Message(
                id=uuid.uuid4(), session_id=sub.id, role="assistant",
                content="step output", metadata_={"kind": "step_output"},
            ),
            Message(
                id=uuid.uuid4(), session_id=sub.id, role="assistant",
                content="final result", metadata_={},
            ),
        ])
        await db_session.flush()

        req = ChatRequest(
            message="follow-up question",
            session_id=sub.id,
            bot_id="default",  # will be normalized to task.bot_id
            client_id="web",
        )
        chat_entry = await _try_resolve_sub_session_chat(db_session, req, user=None)

        assert chat_entry is not None
        assert chat_entry.parent_channel.id == channel.id
        assert req.bot_id == "orchestrator"
        # Loaded Messages from the sub-session (both, in created order)
        assert len(chat_entry.messages) == 2

    async def test_rejects_non_terminal_run_with_409(self, db_session):
        from fastapi import HTTPException

        from app.routers.chat._helpers import _try_resolve_sub_session_chat
        from app.schemas.chat import ChatRequest

        _, _, sub, _ = await _build_chain(db_session, task_status="running")
        req = ChatRequest(
            message="can't interrupt", session_id=sub.id, bot_id="orch", client_id="web",
        )
        with pytest.raises(HTTPException) as exc:
            await _try_resolve_sub_session_chat(db_session, req, user=None)
        assert exc.value.status_code == 409

    async def test_returns_none_for_normal_channel_session(self, db_session):
        """A channel session_id → the resolver short-circuits so the regular
        chat path runs."""
        from app.routers.chat._helpers import _try_resolve_sub_session_chat
        from app.schemas.chat import ChatRequest

        channel_id = uuid.uuid4()
        channel = Channel(id=channel_id, client_id="web", bot_id="b", name="t")
        db_session.add(channel)
        sess = Session(
            id=uuid.uuid4(), client_id="web", bot_id="b",
            channel_id=channel_id, depth=0, session_type="channel",
        )
        db_session.add(sess)
        await db_session.flush()

        req = ChatRequest(
            message="normal chat", session_id=sess.id, bot_id="b", client_id="web",
        )
        assert await _try_resolve_sub_session_chat(db_session, req, user=None) is None

    async def test_non_member_user_forbidden(self, db_session):
        from types import SimpleNamespace

        from fastapi import HTTPException

        from app.routers.chat._helpers import _try_resolve_sub_session_chat
        from app.schemas.chat import ChatRequest

        channel, _, sub, _ = await _build_chain(db_session)
        # Make parent channel private to user_id=42
        channel.user_id = 42
        await db_session.flush()

        req = ChatRequest(
            message="hi", session_id=sub.id, bot_id="orch", client_id="web",
        )
        other_user = SimpleNamespace(id=999, display_name="Stranger")
        with pytest.raises(HTTPException) as exc:
            await _try_resolve_sub_session_chat(db_session, req, user=other_user)
        assert exc.value.status_code == 403
