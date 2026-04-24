"""Unit tests for app.tools.local.sub_sessions — list + read discovery tools.

Both tools are read-only and exercise the real DB via `db_session` +
`patched_async_sessions`. `agent_context` drives the ContextVar default-
channel path for `list_sub_sessions`.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Channel, Message, Session, Task
from app.tools.local.sub_sessions import list_sub_sessions, read_sub_session


async def _seed_sub_session(
    db,
    *,
    channel: Channel,
    status: str = "complete",
    title: str = "Analyze memory",
    task_type: str = "pipeline",
    follow_ups: int = 0,
    pipeline_prompts: int = 0,
) -> tuple[Task, Session]:
    parent = Session(
        id=uuid.uuid4(), client_id="web", bot_id=channel.bot_id,
        channel_id=channel.id, depth=0, session_type="channel",
    )
    sub = Session(
        id=uuid.uuid4(), client_id="task", bot_id=channel.bot_id,
        channel_id=None, parent_session_id=parent.id, root_session_id=parent.id,
        depth=1, session_type="pipeline_run",
    )
    db.add_all([parent, sub])
    await db.flush()
    task = Task(
        id=uuid.uuid4(), bot_id=channel.bot_id, prompt="prompt",
        title=title, status=status, task_type=task_type,
        dispatch_type="none", run_isolation="sub_session",
        run_session_id=sub.id, channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(task)
    await db.flush()
    sub.source_task_id = task.id

    for i in range(pipeline_prompts):
        db.add(Message(
            session_id=sub.id, role="user",
            content=f"step {i} prompt",
            metadata_={"sender_type": "pipeline", "pipeline_step_index": i},
            created_at=datetime.now(timezone.utc),
        ))
    for i in range(follow_ups):
        db.add(Message(
            session_id=sub.id, role="user",
            content=f"follow-up {i}",
            metadata_={},
            created_at=datetime.now(timezone.utc),
        ))
    await db.flush()
    return task, sub


class TestListSubSessions:
    @pytest.mark.asyncio
    async def test_when_channel_has_no_sub_sessions_then_returns_empty_message(
        self, db_session, patched_async_sessions, agent_context
    ):
        channel_id = uuid.uuid4()
        agent_context(bot_id="bot", session_id=uuid.uuid4(), channel_id=channel_id,
                      client_id="web", dispatch_type="none", dispatch_config={})

        out = await list_sub_sessions()
        assert "No sub-sessions" in out

    @pytest.mark.asyncio
    async def test_when_channel_has_runs_then_lists_them_with_metadata(
        self, db_session, patched_async_sessions, agent_context
    ):
        ch = Channel(id=uuid.uuid4(), client_id="web", bot_id="bot", name="main")
        db_session.add(ch)
        await db_session.flush()
        task, _ = await _seed_sub_session(
            db_session, channel=ch, follow_ups=2, pipeline_prompts=3,
        )
        await db_session.commit()

        agent_context(bot_id="bot", session_id=uuid.uuid4(), channel_id=ch.id,
                      client_id="web", dispatch_type="none", dispatch_config={})

        out = await list_sub_sessions()

        assert str(task.id) in out
        assert "follow_ups=2" in out  # pipeline prompts excluded
        assert "Analyze memory" in out

    @pytest.mark.asyncio
    async def test_when_only_with_follow_ups_then_drops_zero_follow_up_rows(
        self, db_session, patched_async_sessions, agent_context
    ):
        ch = Channel(id=uuid.uuid4(), client_id="web", bot_id="bot", name="main")
        db_session.add(ch)
        await db_session.flush()
        task_no_fu, _ = await _seed_sub_session(
            db_session, channel=ch, follow_ups=0, title="no-follow-up",
        )
        task_with_fu, _ = await _seed_sub_session(
            db_session, channel=ch, follow_ups=1, title="has-follow-up",
        )
        await db_session.commit()

        agent_context(bot_id="bot", session_id=uuid.uuid4(), channel_id=ch.id,
                      client_id="web", dispatch_type="none", dispatch_config={})

        out = await list_sub_sessions(only_with_follow_ups=True)

        assert str(task_with_fu.id) in out
        assert str(task_no_fu.id) not in out


class TestReadSubSession:
    @pytest.mark.asyncio
    async def test_when_session_missing_then_returns_not_found(
        self, db_session, patched_async_sessions
    ):
        out = await read_sub_session(str(uuid.uuid4()))
        assert "not found" in out.lower()

    @pytest.mark.asyncio
    async def test_when_session_is_a_channel_session_then_refuses(
        self, db_session, patched_async_sessions
    ):
        ch = Channel(id=uuid.uuid4(), client_id="web", bot_id="bot", name="main")
        sess = Session(
            id=uuid.uuid4(), client_id="web", bot_id="bot",
            channel_id=ch.id, depth=0, session_type="channel",
        )
        db_session.add_all([ch, sess])
        await db_session.commit()

        out = await read_sub_session(str(sess.id))
        assert "channel session" in out.lower()

    @pytest.mark.asyncio
    async def test_when_sub_session_exists_then_renders_header_and_messages(
        self, db_session, patched_async_sessions
    ):
        ch = Channel(id=uuid.uuid4(), client_id="web", bot_id="bot", name="main")
        db_session.add(ch)
        await db_session.flush()
        task, sub = await _seed_sub_session(
            db_session, channel=ch, follow_ups=1, pipeline_prompts=1,
        )
        task.result = "All good, no issues detected."
        await db_session.commit()

        out = await read_sub_session(str(sub.id))

        assert str(sub.id) in out
        assert str(task.id) in out
        assert "All good" in out  # result excerpt
        assert "pipeline-step" in out
        assert "follow-up 0" in out

    @pytest.mark.asyncio
    async def test_when_invalid_uuid_then_returns_clear_error(
        self, db_session, patched_async_sessions
    ):
        out = await read_sub_session("not-a-uuid")
        assert "Invalid session_id" in out


class TestListSubSessionsMultiChannel:
    """channel_ids=[...] loops the single-channel path and concatenates
    per-channel markdown — one iteration for the hygiene per-channel
    sweep instead of N."""

    @pytest.mark.asyncio
    async def test_whitespace_only_channel_ids_rejected(self):
        out = await list_sub_sessions(channel_ids=[" ", "", None])  # type: ignore[list-item]
        assert "empty" in out.lower()

    @pytest.mark.asyncio
    async def test_too_many_channels_rejected(self):
        out = await list_sub_sessions(
            channel_ids=[str(uuid.uuid4()) for _ in range(11)],
        )
        assert "too large" in out

    @pytest.mark.asyncio
    async def test_fanout_returns_per_channel_sections(
        self, db_session, patched_async_sessions,
    ):
        # Two channels, neither seeded → each gets the "No sub-sessions" line.
        ids = [uuid.uuid4(), uuid.uuid4()]
        for cid in ids:
            ch = Channel(id=cid, client_id=f"web-{cid}", bot_id="bot", name=f"c-{cid}")
            db_session.add(ch)
        await db_session.commit()

        out = await list_sub_sessions(channel_ids=[str(c) for c in ids])

        for cid in ids:
            assert f"### Channel {cid}" in out
        # Each per-channel body is its own section — verify we got two,
        # not a single concatenated block.
        assert out.count("### Channel ") == 2
