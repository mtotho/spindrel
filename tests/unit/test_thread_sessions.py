"""Unit tests for `spawn_thread_session` — message-anchored sub-sessions.

Covers:
1. Parent linkage + walk-up — the new thread inherits `parent_session_id`,
   `root_session_id`, and `depth+1` from the parent message's session.
2. `parent_message_id` + `session_type="thread"` stamped correctly.
3. Context seeding — a system message with `metadata.kind="thread_context"`
   includes the parent message plus up to 5 preceding user/assistant
   messages in chronological order.
4. Edge cases — zero preceding messages, non-channel parent session,
   truncation of long content.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import Channel, Message, Session
from app.services.sub_sessions import (
    SESSION_TYPE_THREAD,
    THREAD_CONTEXT_PRECEDING,
    spawn_thread_session,
)


pytestmark = pytest.mark.asyncio


async def _make_channel_with_session(db_session, bot_id: str = "test-bot"):
    parent_session = Session(
        id=uuid.uuid4(),
        client_id="web",
        bot_id=bot_id,
        channel_id=None,
        depth=0,
        session_type="channel",
    )
    db_session.add(parent_session)
    await db_session.flush()

    channel = Channel(
        id=uuid.uuid4(),
        name="test-channel",
        bot_id=bot_id,
        active_session_id=parent_session.id,
    )
    parent_session.channel_id = channel.id
    db_session.add(channel)
    await db_session.flush()
    return channel, parent_session


async def _add_message(
    db_session,
    *,
    session_id: uuid.UUID,
    role: str,
    content: str,
    created_at: datetime,
    metadata: dict | None = None,
) -> Message:
    msg = Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        metadata_=metadata or {},
        created_at=created_at,
    )
    db_session.add(msg)
    await db_session.flush()
    return msg


class TestSpawnThreadSession:
    async def test_sets_parent_message_id_and_session_type(self, db_session):
        _, parent_session = await _make_channel_with_session(db_session)
        now = datetime.now(timezone.utc)
        parent_msg = await _add_message(
            db_session,
            session_id=parent_session.id,
            role="user",
            content="original message",
            created_at=now,
        )

        sub = await spawn_thread_session(
            db_session,
            parent_message_id=parent_msg.id,
            bot_id="test-bot",
        )
        await db_session.flush()

        assert sub.parent_message_id == parent_msg.id
        assert sub.session_type == SESSION_TYPE_THREAD
        assert sub.channel_id is None
        assert sub.source_task_id is None
        assert sub.bot_id == "test-bot"

    async def test_inherits_parent_linkage_from_message_session(self, db_session):
        _, parent_session = await _make_channel_with_session(db_session)
        parent_session.depth = 0
        await db_session.flush()

        parent_msg = await _add_message(
            db_session,
            session_id=parent_session.id,
            role="assistant",
            content="bot response",
            created_at=datetime.now(timezone.utc),
        )
        sub = await spawn_thread_session(
            db_session,
            parent_message_id=parent_msg.id,
            bot_id="test-bot",
        )
        await db_session.flush()

        assert sub.parent_session_id == parent_session.id
        # parent_session.root_session_id is None → defaults to parent.id
        assert sub.root_session_id == parent_session.id
        assert sub.depth == 1

    async def test_context_message_includes_parent_plus_preceding(self, db_session):
        _, parent_session = await _make_channel_with_session(db_session)
        base = datetime.now(timezone.utc) - timedelta(minutes=20)

        # 3 preceding messages, then the parent.
        for idx, (role, content) in enumerate(
            [
                ("user", "msg-minus-3"),
                ("assistant", "msg-minus-2"),
                ("user", "msg-minus-1"),
            ]
        ):
            await _add_message(
                db_session,
                session_id=parent_session.id,
                role=role,
                content=content,
                created_at=base + timedelta(minutes=idx),
            )
        parent_msg = await _add_message(
            db_session,
            session_id=parent_session.id,
            role="user",
            content="the anchor",
            created_at=base + timedelta(minutes=10),
        )

        sub = await spawn_thread_session(
            db_session,
            parent_message_id=parent_msg.id,
            bot_id="test-bot",
        )
        await db_session.flush()

        ctx_msgs = (
            await db_session.execute(
                select(Message).where(Message.session_id == sub.id)
            )
        ).scalars().all()
        assert len(ctx_msgs) == 1
        ctx = ctx_msgs[0]
        assert ctx.role == "system"
        assert ctx.metadata_["kind"] == "thread_context"
        assert ctx.metadata_["parent_message_id"] == str(parent_msg.id)
        assert ctx.metadata_["seeded_messages"] == 3
        body = ctx.content
        assert "msg-minus-3" in body
        assert "msg-minus-2" in body
        assert "msg-minus-1" in body
        assert "the anchor" in body
        # Chronological order — oldest preceding appears before newer.
        assert body.index("msg-minus-3") < body.index("msg-minus-2")
        assert body.index("msg-minus-2") < body.index("msg-minus-1")
        # Parent appears AFTER the preceding block.
        assert body.index("msg-minus-1") < body.index("the anchor")

    async def test_caps_preceding_at_limit(self, db_session):
        _, parent_session = await _make_channel_with_session(db_session)
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        # Add 8 preceding messages — limit is 5.
        for idx in range(8):
            await _add_message(
                db_session,
                session_id=parent_session.id,
                role="user",
                content=f"old-{idx}",
                created_at=base + timedelta(minutes=idx),
            )
        parent_msg = await _add_message(
            db_session,
            session_id=parent_session.id,
            role="user",
            content="anchor",
            created_at=base + timedelta(minutes=100),
        )

        sub = await spawn_thread_session(
            db_session, parent_message_id=parent_msg.id, bot_id="test-bot"
        )
        await db_session.flush()
        ctx = (
            await db_session.execute(select(Message).where(Message.session_id == sub.id))
        ).scalar_one()
        assert ctx.metadata_["seeded_messages"] == THREAD_CONTEXT_PRECEDING
        # The 5 most-recent-preceding should appear; "old-0" and "old-1" should not.
        assert "old-0" not in ctx.content
        assert "old-1" not in ctx.content
        assert "old-3" in ctx.content
        assert "old-7" in ctx.content

    async def test_no_preceding_messages_still_seeds_parent(self, db_session):
        _, parent_session = await _make_channel_with_session(db_session)
        parent_msg = await _add_message(
            db_session,
            session_id=parent_session.id,
            role="user",
            content="lonely anchor",
            created_at=datetime.now(timezone.utc),
        )
        sub = await spawn_thread_session(
            db_session, parent_message_id=parent_msg.id, bot_id="test-bot"
        )
        await db_session.flush()
        ctx = (
            await db_session.execute(select(Message).where(Message.session_id == sub.id))
        ).scalar_one()
        assert ctx.metadata_["seeded_messages"] == 0
        assert "lonely anchor" in ctx.content

    async def test_missing_parent_raises(self, db_session):
        with pytest.raises(ValueError):
            await spawn_thread_session(
                db_session, parent_message_id=uuid.uuid4(), bot_id="test-bot"
            )

    async def test_skips_system_messages_in_preceding_context(self, db_session):
        _, parent_session = await _make_channel_with_session(db_session)
        base = datetime.now(timezone.utc) - timedelta(minutes=30)
        await _add_message(
            db_session,
            session_id=parent_session.id,
            role="system",
            content="system-should-not-appear",
            created_at=base,
        )
        await _add_message(
            db_session,
            session_id=parent_session.id,
            role="user",
            content="real-user-msg",
            created_at=base + timedelta(minutes=1),
        )
        parent_msg = await _add_message(
            db_session,
            session_id=parent_session.id,
            role="user",
            content="anchor",
            created_at=base + timedelta(minutes=2),
        )
        sub = await spawn_thread_session(
            db_session, parent_message_id=parent_msg.id, bot_id="test-bot"
        )
        await db_session.flush()
        ctx = (
            await db_session.execute(select(Message).where(Message.session_id == sub.id))
        ).scalar_one()
        assert "system-should-not-appear" not in ctx.content
        assert "real-user-msg" in ctx.content
        assert ctx.metadata_["seeded_messages"] == 1

    async def test_truncates_long_preceding_content(self, db_session):
        _, parent_session = await _make_channel_with_session(db_session)
        base = datetime.now(timezone.utc) - timedelta(minutes=10)
        long_body = "X" * 2000
        await _add_message(
            db_session,
            session_id=parent_session.id,
            role="user",
            content=long_body,
            created_at=base,
        )
        parent_msg = await _add_message(
            db_session,
            session_id=parent_session.id,
            role="user",
            content="anchor",
            created_at=base + timedelta(minutes=1),
        )
        sub = await spawn_thread_session(
            db_session, parent_message_id=parent_msg.id, bot_id="test-bot"
        )
        await db_session.flush()
        ctx = (
            await db_session.execute(select(Message).where(Message.session_id == sub.id))
        ).scalar_one()
        # Preceding truncated to 800 + ellipsis; parent truncated to 2000 + ellipsis.
        assert "…" in ctx.content
        # 800 X's from the preceding + 2000-char cap is impossible here (parent is "anchor").
        assert ctx.content.count("X") < 1000
