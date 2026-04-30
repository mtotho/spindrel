"""Integration tests for app.services.sessions — load/create, persist, passive messages."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import Message, Session
from tests.integration.conftest import engine, db_session, TEST_BOT, DEFAULT_BOT, _TEST_REGISTRY


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bot():
    return TEST_BOT


# ---------------------------------------------------------------------------
# load_or_create
# ---------------------------------------------------------------------------

class TestLoadOrCreate:
    @pytest.mark.asyncio
    async def test_creates_new_session(self, db_session, bot):
        with (
            patch("app.services.sessions.get_bot", return_value=bot),
            patch("app.services.sessions.get_persona", return_value=None),
        ):
            from app.services.sessions import load_or_create
            sid, messages = await load_or_create(db_session, None, "client-1", bot.id)

        assert isinstance(sid, uuid.UUID)
        assert len(messages) >= 1
        assert messages[0]["role"] == "system"
        assert "test bot" in messages[0]["content"].lower()

        # Verify session persisted
        session = await db_session.get(Session, sid)
        assert session is not None
        assert session.bot_id == bot.id

    @pytest.mark.asyncio
    async def test_creates_with_persona(self, db_session, bot):
        bot_with_persona = BotConfig(
            id="persona-bot", name="Persona Bot", model="test/model",
            system_prompt="System prompt.", persona=True,
            memory=MemoryConfig(enabled=False),
        )
        with (
            patch("app.services.sessions.get_bot", return_value=bot_with_persona),
            patch("app.services.sessions.get_persona", return_value="I speak formally."),
        ):
            from app.services.sessions import load_or_create
            sid, messages = await load_or_create(db_session, None, "client-2", bot_with_persona.id)

        persona_msgs = [m for m in messages if "[PERSONA]" in m.get("content", "")]
        assert len(persona_msgs) == 1
        assert "I speak formally" in persona_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_reloads_existing_session(self, db_session, bot):
        # Create a session first
        sid = uuid.uuid4()
        session = Session(id=sid, client_id="client-3", bot_id=bot.id)
        db_session.add(session)
        msg = Message(session_id=sid, role="system", content="System prompt.")
        db_session.add(msg)
        user_msg = Message(session_id=sid, role="user", content="Hello")
        db_session.add(user_msg)
        await db_session.commit()

        with (
            patch("app.services.sessions.get_bot", return_value=bot),
            patch("app.services.sessions.get_persona", return_value=None),
        ):
            from app.services.sessions import load_or_create
            returned_sid, messages = await load_or_create(db_session, sid, "client-3", bot.id)

        assert returned_sid == sid
        # Should include system + user message
        assert any(m.get("content") == "Hello" for m in messages)


# ---------------------------------------------------------------------------
# persist_turn
# ---------------------------------------------------------------------------

class TestPersistTurn:
    @pytest.mark.asyncio
    async def test_persists_new_messages(self, db_session, bot):
        sid = uuid.uuid4()
        session = Session(id=sid, client_id="c", bot_id=bot.id)
        db_session.add(session)
        await db_session.commit()

        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

        from app.services.sessions import persist_turn
        await persist_turn(db_session, sid, bot, messages, from_index=1)

        result = await db_session.execute(
            select(Message).where(Message.session_id == sid).order_by(Message.created_at)
        )
        persisted = result.scalars().all()
        # Should have user + assistant (system is skipped since it's ephemeral filtering,
        # but from_index=1 starts from user anyway)
        roles = [m.role for m in persisted]
        assert "user" in roles
        assert "assistant" in roles

    @pytest.mark.asyncio
    async def test_skips_system_messages(self, db_session, bot):
        sid = uuid.uuid4()
        session = Session(id=sid, client_id="c", bot_id=bot.id)
        db_session.add(session)
        await db_session.commit()

        messages = [
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "Current time: now"},  # ephemeral
            {"role": "assistant", "content": "hello"},
        ]

        from app.services.sessions import persist_turn
        await persist_turn(db_session, sid, bot, messages, from_index=0)

        result = await db_session.execute(
            select(Message).where(Message.session_id == sid)
        )
        persisted = result.scalars().all()
        roles = [m.role for m in persisted]
        assert "system" not in roles

    @pytest.mark.asyncio
    async def test_redacts_data_url_images(self, db_session, bot):
        sid = uuid.uuid4()
        session = Session(id=sid, client_id="c", bot_id=bot.id)
        db_session.add(session)
        await db_session.commit()

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "check this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
                ],
            },
        ]

        from app.services.sessions import persist_turn
        await persist_turn(db_session, sid, bot, messages, from_index=0)

        result = await db_session.execute(
            select(Message).where(Message.session_id == sid)
        )
        persisted = result.scalars().all()
        assert len(persisted) == 1
        content = persisted[0].content
        assert "data:image" not in content
        assert "not available" in content

    @pytest.mark.asyncio
    async def test_attaches_metadata_to_first_user(self, db_session, bot):
        sid = uuid.uuid4()
        session = Session(id=sid, client_id="c", bot_id=bot.id)
        db_session.add(session)
        await db_session.commit()

        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "second"},
        ]

        from app.services.sessions import persist_turn
        meta = {"source": "test"}
        await persist_turn(db_session, sid, bot, messages, from_index=0, msg_metadata=meta)

        result = await db_session.execute(
            select(Message).where(Message.session_id == sid).where(Message.role == "user").order_by(Message.created_at)
        )
        users = result.scalars().all()
        # First user gets metadata, second doesn't
        assert users[0].metadata_.get("source") == "test"
        assert users[1].metadata_.get("source") is None


# ---------------------------------------------------------------------------
# store_passive_message
# ---------------------------------------------------------------------------

class TestStorePassiveMessage:
    @pytest.mark.asyncio
    async def test_stores_passive_with_metadata(self, db_session, bot):
        sid = uuid.uuid4()
        session = Session(id=sid, client_id="c", bot_id=bot.id)
        db_session.add(session)
        await db_session.commit()

        from app.services.sessions import store_passive_message
        meta = {"passive": True, "sender_id": "U123"}
        await store_passive_message(db_session, sid, "ambient chat", meta)

        result = await db_session.execute(
            select(Message).where(Message.session_id == sid)
        )
        msg = result.scalars().first()
        assert msg is not None
        assert msg.content == "ambient chat"
        assert msg.metadata_.get("passive") is True
        assert msg.metadata_.get("sender_id") == "U123"

    @pytest.mark.asyncio
    async def test_stores_passive_with_requested_role(self, db_session, bot):
        sid = uuid.uuid4()
        session = Session(id=sid, client_id="c", bot_id=bot.id)
        db_session.add(session)
        await db_session.commit()

        from app.services.sessions import store_passive_message

        await store_passive_message(db_session, sid, "review result", role="assistant")
        await store_passive_message(db_session, sid, "bad role", role="invalid")

        result = await db_session.execute(
            select(Message).where(Message.session_id == sid).order_by(Message.created_at)
        )
        messages = result.scalars().all()
        assert [msg.role for msg in messages] == ["assistant", "user"]
        assert messages[0].content == "review result"
        assert messages[1].content == "bad role"


# ---------------------------------------------------------------------------
# Channel-events integration: per-row publish from persist_turn
# ---------------------------------------------------------------------------


class TestPersistTurnChannelEvents:
    """persist_turn should publish one channel event per persisted row,
    with the serialized Message in the payload."""

    @pytest.mark.asyncio
    async def test_publishes_one_event_per_persisted_row(self, db_session, bot):
        from app.db.models import Channel
        from app.services import channel_events
        from app.services.sessions import persist_turn

        # Set up a channel + session
        channel_id = uuid.uuid4()
        sid = uuid.uuid4()
        channel = Channel(
            id=channel_id, name="test-channel-1", client_id="test:c1", bot_id=bot.id,
            active_session_id=sid,
        )
        db_session.add(channel)
        session = Session(id=sid, client_id="test:c1", bot_id=bot.id, channel_id=channel_id)
        db_session.add(session)
        await db_session.commit()

        # Reset bus state for the channel to start clean
        channel_events.reset_channel_state(channel_id)

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi back"},
        ]

        await persist_turn(
            db_session, sid, bot, messages, from_index=0, channel_id=channel_id,
        )

        # Two events should be in the replay buffer (one per row).
        # persist_turn publishes via ``publish_typed(NEW_MESSAGE, ...)``
        # so the buffer holds typed ``ChannelEvent`` instances directly.
        from app.domain.channel_events import ChannelEventKind

        buf = list(channel_events._replay_buffer.get(channel_id, ()))
        new_msg_events = [e for e in buf if e.kind == ChannelEventKind.NEW_MESSAGE]
        assert len(new_msg_events) == 2

        first_payload = new_msg_events[0].payload
        second_payload = new_msg_events[1].payload
        assert first_payload.message.role == "user"
        assert first_payload.message.content == "hello"
        assert second_payload.message.role == "assistant"
        assert second_payload.message.content == "hi back"

        # Sequence numbers must be monotonic
        assert new_msg_events[0].seq < new_msg_events[1].seq

        # Cleanup
        channel_events.reset_channel_state(channel_id)

    @pytest.mark.asyncio
    async def test_skips_publish_when_no_channel_id(self, db_session, bot):
        """Without a channel_id, persist_turn must not publish anything."""
        from app.services import channel_events
        from app.services.sessions import persist_turn

        sid = uuid.uuid4()
        session = Session(id=sid, client_id="c", bot_id=bot.id)
        db_session.add(session)
        await db_session.commit()

        # Snapshot all current channel ids in the bus
        before = set(channel_events._replay_buffer.keys())

        await persist_turn(
            db_session, sid, bot,
            [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
            from_index=0,
        )

        after = set(channel_events._replay_buffer.keys())
        assert before == after  # no new channels in the buffer

    @pytest.mark.asyncio
    async def test_passive_message_publishes_row(self, db_session, bot):
        from app.db.models import Channel
        from app.services import channel_events
        from app.services.sessions import store_passive_message

        channel_id = uuid.uuid4()
        sid = uuid.uuid4()
        channel = Channel(
            id=channel_id, name="test-channel-2", client_id="test:c2", bot_id=bot.id,
            active_session_id=sid,
        )
        db_session.add(channel)
        session = Session(id=sid, client_id="test:c2", bot_id=bot.id, channel_id=channel_id)
        db_session.add(session)
        await db_session.commit()

        channel_events.reset_channel_state(channel_id)

        await store_passive_message(
            db_session, sid, "ambient", {"passive": True}, channel_id=channel_id,
        )

        from app.domain.channel_events import ChannelEventKind

        buf = list(channel_events._replay_buffer.get(channel_id, ()))
        new_msg_events = [e for e in buf if e.kind == ChannelEventKind.NEW_MESSAGE]
        assert len(new_msg_events) == 1
        message = new_msg_events[0].payload.message
        assert message.content == "ambient"
        assert message.metadata == {"passive": True}

        channel_events.reset_channel_state(channel_id)


# ---------------------------------------------------------------------------
# _content_for_db
# ---------------------------------------------------------------------------

class TestContentForDb:
    def test_plain_string_passthrough(self):
        from app.services.sessions import _content_for_db
        assert _content_for_db({"content": "hello"}) == "hello"

    def test_none_passthrough(self):
        from app.services.sessions import _content_for_db
        assert _content_for_db({"content": None}) is None

    def test_list_serialized_to_json(self):
        from app.services.sessions import _content_for_db
        parts = [{"type": "text", "text": "hi"}]
        result = _content_for_db({"content": parts})
        parsed = json.loads(result)
        assert parsed[0]["type"] == "text"

    def test_data_url_images_redacted(self):
        from app.services.sessions import _content_for_db
        parts = [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]
        result = _content_for_db({"content": parts})
        parsed = json.loads(result)
        assert parsed[1]["type"] == "text"  # replaced with text placeholder
        assert "not available" in parsed[1]["text"]

    def test_http_url_images_kept(self):
        from app.services.sessions import _content_for_db
        parts = [{"type": "image_url", "image_url": {"url": "https://example.com/img.png"}}]
        result = _content_for_db({"content": parts})
        parsed = json.loads(result)
        assert parsed[0]["type"] == "image_url"


# ---------------------------------------------------------------------------
# _sanitize_tool_messages
# ---------------------------------------------------------------------------

class TestSanitizeToolMessages:
    def test_no_problems_returns_same(self):
        from app.services.sessions import _sanitize_tool_messages
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "echo"}}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        result = _sanitize_tool_messages(msgs)
        assert result == msgs

    def test_strips_orphan_tool_results(self):
        from app.services.sessions import _sanitize_tool_messages
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "orphan_tc", "content": "stale result"},
            {"role": "assistant", "content": "ok"},
        ]
        result = _sanitize_tool_messages(msgs)
        assert not any(m.get("tool_call_id") == "orphan_tc" for m in result)
