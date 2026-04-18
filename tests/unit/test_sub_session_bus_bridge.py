"""Sub-session → parent-channel bus bridge.

Phase 1 of the pipeline-as-chat refactor relies on sub-session events
reaching the parent channel's bus so the run-view modal (subscribed via
the parent channel's SSE stream) can filter them in by ``session_id``.

Covers:
1. ``resolve_bus_channel_id`` walks ``parent_session_id`` to the first
   ancestor with ``channel_id`` set.
2. ``emit_step_output_message`` publishes the persisted Message on the
   resolved parent channel's bus.
3. The Message row's ``session_id`` is still the sub-session (the modal
   and parent-UI discriminate by it, but the DB storage is unchanged).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import Channel, Message, Session, Task
from app.domain.channel_events import ChannelEventKind
from app.services.channel_events import _next_seq, _replay_buffer, _subscribers
from app.services.sub_session_bus import resolve_bus_channel_id
from app.services.sub_sessions import SESSION_TYPE_PIPELINE_RUN, emit_step_output_message


@pytest.fixture(autouse=True)
def _clean_bus():
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()


async def _make_chain(db_session):
    """Build channel → parent_session → sub_session → task.

    Returns (channel, parent_session, sub_session, task).
    """
    channel_id = uuid.uuid4()
    channel = Channel(
        id=channel_id,
        client_id="web",
        bot_id="b",
        name="t",
    )
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
    )
    db_session.add_all([parent, sub])
    await db_session.flush()

    task = Task(
        id=uuid.uuid4(),
        bot_id="b",
        prompt="p",
        status="running",
        task_type="pipeline",
        dispatch_type="none",
        run_isolation="sub_session",
        run_session_id=sub.id,
    )
    db_session.add(task)
    await db_session.flush()
    return channel, parent, sub, task


@pytest.mark.asyncio
class TestResolveBusChannelId:
    async def test_channel_session_returns_own_channel_id(self, db_session):
        ch_id = uuid.uuid4()
        ch = Channel(id=ch_id, client_id="web", bot_id="b", name="t")
        s = Session(
            id=uuid.uuid4(), client_id="web", bot_id="b", channel_id=ch_id,
            depth=0, session_type="channel",
        )
        db_session.add_all([ch, s])
        await db_session.flush()

        assert await resolve_bus_channel_id(db_session, s.id) == ch_id

    async def test_sub_session_walks_up_to_parent_channel(self, db_session):
        _, parent, sub, _ = await _make_chain(db_session)
        assert await resolve_bus_channel_id(db_session, sub.id) == parent.channel_id

    async def test_nested_sub_session_resolves_through_chain(self, db_session):
        _, parent, sub, _ = await _make_chain(db_session)
        nested = Session(
            id=uuid.uuid4(), client_id="task", bot_id="b", channel_id=None,
            parent_session_id=sub.id, root_session_id=parent.id, depth=2,
            session_type=SESSION_TYPE_PIPELINE_RUN,
        )
        db_session.add(nested)
        await db_session.flush()

        assert await resolve_bus_channel_id(db_session, nested.id) == parent.channel_id

    async def test_orphan_session_returns_none(self, db_session):
        s = Session(
            id=uuid.uuid4(), client_id="task", bot_id="b", channel_id=None,
            depth=0, session_type=SESSION_TYPE_PIPELINE_RUN,
        )
        db_session.add(s)
        await db_session.flush()

        assert await resolve_bus_channel_id(db_session, s.id) is None

    async def test_missing_session_returns_none(self, db_session):
        assert await resolve_bus_channel_id(db_session, uuid.uuid4()) is None


@pytest.mark.asyncio
class TestEmitStepOutputPublishesToParentBus:
    async def test_step_output_reaches_parent_channel_bus(self, db_session):
        channel, parent, sub, task = await _make_chain(db_session)

        step_def = {"type": "tool", "tool_name": "fetch_traces", "name": "Fetch traces"}
        state = {"status": "done", "result": '{"traces": [1, 2]}'}

        await emit_step_output_message(
            task=task, step_def=step_def, step_index=0, state=state, db=db_session,
        )

        # Bus got a NEW_MESSAGE event on the PARENT channel id.
        buf = list(_replay_buffer.get(channel.id, ()))
        assert len(buf) == 1
        ev = buf[0]
        assert ev.kind == ChannelEventKind.NEW_MESSAGE
        assert ev.channel_id == channel.id
        # Payload carries the sub-session's session_id so UI subscribers
        # can discriminate: modal keeps by session_id == run_session_id;
        # parent chat drops.
        assert ev.payload.message.session_id == sub.id

    async def test_message_row_session_id_unchanged(self, db_session):
        _, _, sub, task = await _make_chain(db_session)

        step_def = {"type": "tool", "tool_name": "x", "name": "x"}
        state = {"status": "done", "result": "ok"}

        await emit_step_output_message(
            task=task, step_def=step_def, step_index=0, state=state, db=db_session,
        )

        rows = (await db_session.execute(
            select(Message).where(Message.session_id == sub.id)
        )).scalars().all()
        assert len(rows) == 1
        # Row's session_id is the sub-session — the parent-session message
        # listing endpoint filters by session_id so sub-session messages
        # never leak into the parent transcript.
        assert rows[0].session_id == sub.id

    async def test_orphan_sub_session_does_not_error(self, db_session):
        """A sub-session with no channel ancestor just skips the publish."""
        sub = Session(
            id=uuid.uuid4(), client_id="task", bot_id="b", channel_id=None,
            depth=0, session_type=SESSION_TYPE_PIPELINE_RUN,
        )
        db_session.add(sub)
        await db_session.flush()

        task = Task(
            id=uuid.uuid4(), bot_id="b", prompt="p", status="running",
            task_type="pipeline", dispatch_type="none",
            run_isolation="sub_session", run_session_id=sub.id,
        )
        db_session.add(task)
        await db_session.flush()

        step_def = {"type": "tool", "tool_name": "x"}
        state = {"status": "done", "result": "ok"}

        # Doesn't raise.
        await emit_step_output_message(
            task=task, step_def=step_def, step_index=0, state=state, db=db_session,
        )
