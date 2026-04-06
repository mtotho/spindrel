"""Integration tests for read_conversation_history tool — messages: and tool: modes."""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Channel, Message, Session, ToolCall
from tests.integration.conftest import engine, db_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now(**delta_kw):
    return datetime.now(timezone.utc) + timedelta(**delta_kw) if delta_kw else datetime.now(timezone.utc)


async def _create_channel_with_messages(db: AsyncSession, messages: list[tuple[str, str]]):
    """Create a channel, session, and messages. Returns (channel_id, session_id)."""
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()

    channel = Channel(
        id=channel_id,
        name="test-channel",
        client_id="test-client",
        bot_id="test-bot",
        active_session_id=session_id,
    )
    db.add(channel)

    session = Session(
        id=session_id,
        client_id="test-client",
        bot_id="test-bot",
        channel_id=channel_id,
    )
    db.add(session)
    await db.flush()

    for i, (role, content) in enumerate(messages):
        msg = Message(
            id=uuid.uuid4(),
            session_id=session_id,
            role=role,
            content=content,
            created_at=_now(seconds=i),
        )
        db.add(msg)

    await db.commit()
    return channel_id, session_id


# ---------------------------------------------------------------------------
# Phase 4: messages:<query> search
# ---------------------------------------------------------------------------

class TestMessageSearch:
    @pytest.mark.asyncio
    async def test_messages_search_finds_matching(self, engine, db_session):
        """search: query returns matching sections."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        channel_id, session_id = await _create_channel_with_messages(db_session, [
            ("user", "ERROR: connection refused on port 5432"),
            ("assistant", "Let me check the database connection."),
            ("user", "The postgres service is down."),
            ("assistant", "I'll restart the service."),
        ])

        from app.tools.local.conversation_history import read_conversation_history

        with (
            patch("app.tools.local.conversation_history.current_channel_id") as mock_ctx,
            patch("app.tools.local.conversation_history.async_session", return_value=factory()),
        ):
            mock_ctx.get.return_value = channel_id
            result = await read_conversation_history(section="search:5432")

        assert "5432" in result

    @pytest.mark.asyncio
    async def test_messages_search_no_results(self, engine, db_session):
        """search: query returns helpful message when nothing matches."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        channel_id, session_id = await _create_channel_with_messages(db_session, [
            ("user", "Hello there"),
            ("assistant", "Hi!"),
        ])

        from app.tools.local.conversation_history import read_conversation_history

        with (
            patch("app.tools.local.conversation_history.current_channel_id") as mock_ctx,
            patch("app.tools.local.conversation_history.async_session", return_value=factory()),
        ):
            mock_ctx.get.return_value = channel_id
            result = await read_conversation_history(section="search:nonexistent_xyz")

        assert "No sections found" in result

    @pytest.mark.asyncio
    async def test_messages_search_empty_query(self, engine, db_session):
        """search: with empty query returns help text."""
        from app.tools.local.conversation_history import read_conversation_history

        with patch("app.tools.local.conversation_history.current_channel_id") as mock_ctx:
            mock_ctx.get.return_value = uuid.uuid4()
            result = await read_conversation_history(section="search:")

        assert "Please provide a search query" in result


# ---------------------------------------------------------------------------
# Phase 5: tool:<id> retrieval
# ---------------------------------------------------------------------------

class TestToolCallRetrieval:
    @pytest.mark.asyncio
    async def test_tool_retrieval_finds_result(self, engine, db_session):
        """tool: retrieval returns full tool call output."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        tc_id = uuid.uuid4()
        tc = ToolCall(
            id=tc_id,
            session_id=uuid.uuid4(),
            bot_id="test-bot",
            client_id="test-client",
            tool_name="web_search",
            tool_type="local",
            iteration=1,
            arguments={"query": "test"},
            result="Full search results with lots of data here...",
            duration_ms=150,
            created_at=_now(),
        )
        db_session.add(tc)
        await db_session.commit()

        from app.tools.local.conversation_history import read_conversation_history

        with (
            patch("app.tools.local.conversation_history.current_channel_id") as mock_ctx,
            patch("app.tools.local.conversation_history.async_session", return_value=factory()),
        ):
            mock_ctx.get.return_value = uuid.uuid4()
            result = await read_conversation_history(section=f"tool:{tc_id}")

        assert "web_search" in result
        assert "Full search results" in result
        assert "150ms" in result

    @pytest.mark.asyncio
    async def test_tool_retrieval_not_found(self, engine, db_session):
        """tool: retrieval with nonexistent ID returns error."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        fake_id = uuid.uuid4()

        from app.tools.local.conversation_history import read_conversation_history

        with (
            patch("app.tools.local.conversation_history.current_channel_id") as mock_ctx,
            patch("app.tools.local.conversation_history.async_session", return_value=factory()),
        ):
            mock_ctx.get.return_value = uuid.uuid4()
            result = await read_conversation_history(section=f"tool:{fake_id}")

        assert "not found" in result

    @pytest.mark.asyncio
    async def test_tool_retrieval_invalid_uuid(self, engine, db_session):
        """tool: retrieval with invalid UUID returns error."""
        from app.tools.local.conversation_history import read_conversation_history

        with patch("app.tools.local.conversation_history.current_channel_id") as mock_ctx:
            mock_ctx.get.return_value = uuid.uuid4()
            result = await read_conversation_history(section="tool:not-a-uuid")

        assert "Invalid tool call ID" in result
