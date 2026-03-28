"""Tests for backfill_sections service function.

Tests chunking logic, watermark filtering, sequence numbering,
history_mode validation, and empty channel handling.
"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.services.compaction import (
    _messages_for_summary,
    _msg_to_dict,
    backfill_sections,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        local_tools=[], mcp_servers=[], client_tools=[], skills=[],
        pinned_tools=[],
        tool_retrieval=True,
        context_compaction=True,
        compaction_interval=10,
        compaction_keep_turns=4,
        compaction_model=None,
        memory=MemoryConfig(),
        knowledge=KnowledgeConfig(),
        persona=False,
        history_mode="file",
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_channel(**overrides):
    ch = MagicMock()
    ch.id = overrides.get("id", uuid.uuid4())
    ch.bot_id = overrides.get("bot_id", "test")
    ch.active_session_id = overrides.get("active_session_id", uuid.uuid4())
    ch.compaction_model = overrides.get("compaction_model", None)
    ch.compaction_interval = overrides.get("compaction_interval", None)
    ch.compaction_keep_turns = overrides.get("compaction_keep_turns", None)
    ch.context_compaction = overrides.get("context_compaction", True)
    ch.memory_knowledge_compaction_prompt = overrides.get(
        "memory_knowledge_compaction_prompt", None
    )
    ch.compaction_prompt_template_id = overrides.get("compaction_prompt_template_id", None)
    ch.history_mode = overrides.get("history_mode", "file")
    return ch


def _make_session(**overrides):
    s = MagicMock()
    s.id = overrides.get("id", uuid.uuid4())
    s.channel_id = overrides.get("channel_id", uuid.uuid4())
    s.client_id = overrides.get("client_id", "test-client")
    s.bot_id = overrides.get("bot_id", "test")
    s.summary = overrides.get("summary", None)
    s.summary_message_id = overrides.get("summary_message_id", None)
    return s


def _make_message(role="user", content="hello", created_at=None, session_id=None, **kwargs):
    m = MagicMock()
    m.id = kwargs.get("id", uuid.uuid4())
    m.role = role
    m.content = content
    m.created_at = created_at or datetime.now(timezone.utc)
    m.session_id = session_id or uuid.uuid4()
    m.tool_calls = kwargs.get("tool_calls", None)
    m.tool_call_id = kwargs.get("tool_call_id", None)
    m.metadata_ = kwargs.get("metadata_", None)
    return m


def _mock_llm_response(content):
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# Chunking logic tests
# ---------------------------------------------------------------------------

class TestChunkingLogic:
    """Test that messages are correctly chunked by chunk_size."""

    def test_messages_for_summary_filters_correctly(self):
        """_messages_for_summary keeps user/assistant and includes tool results as compact summaries."""
        msgs = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "tool", "content": "result", "name": "web_search"},
            {"role": "user", "content": "bye"},
        ]
        result = _messages_for_summary(msgs)
        roles = [m["role"] for m in result]
        assert "system" not in roles
        assert "tool" not in roles
        # Tool results are now included as compact assistant messages
        assert len(result) == 4  # user, assistant, tool-as-assistant, user
        assert "[Tool result from web_search: result]" in result[2]["content"]

    def test_msg_to_dict_basic(self):
        """_msg_to_dict converts ORM message to dict."""
        m = _make_message(role="user", content="test content")
        d = _msg_to_dict(m)
        assert d["role"] == "user"
        assert d["content"] == "test content"

    def test_msg_to_dict_with_metadata(self):
        """_msg_to_dict includes metadata when present."""
        m = _make_message(role="user", content="test", metadata_={"passive": True})
        d = _msg_to_dict(m)
        assert d["_metadata"] == {"passive": True}

    def test_msg_to_dict_no_optional_fields(self):
        """_msg_to_dict excludes None tool_calls/tool_call_id."""
        m = _make_message(role="assistant", content="response")
        d = _msg_to_dict(m)
        assert "tool_calls" not in d
        assert "tool_call_id" not in d


# ---------------------------------------------------------------------------
# backfill_sections integration tests (mocked DB + LLM)
# ---------------------------------------------------------------------------

def _setup_mocks(channel, session, messages, existing_sections_max_seq=0):
    """Build mock DB session context manager for backfill_sections tests."""

    async def mock_get(model_cls, id_val):
        from app.db.models import Channel as ChannelModel, Session as SessionModel, Message as MessageModel
        if model_cls is ChannelModel or model_cls.__name__ == "Channel":
            return channel if id_val == channel.id else None
        if model_cls is SessionModel or model_cls.__name__ == "Session":
            return session if id_val == session.id else None
        if model_cls is MessageModel or model_cls.__name__ == "Message":
            for m in messages:
                if m.id == id_val:
                    return m
            return None
        return None

    call_count = [0]

    async def mock_execute(stmt):
        call_count[0] += 1
        result = MagicMock()
        # Determine what query this is by inspecting the stmt
        # We rely on call ordering within each async_session block
        stmt_str = str(stmt)
        if "conversation_sections" in stmt_str.lower() and "max" in stmt_str.lower():
            result.scalar.return_value = existing_sections_max_seq
            return result
        if "messages" in stmt_str.lower() or "Message" in str(type(stmt)):
            result.scalars.return_value.all.return_value = messages
            return result
        result.scalar.return_value = existing_sections_max_seq
        return result

    mock_db = AsyncMock()
    mock_db.get = mock_get
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    return mock_db


class TestBackfillSections:
    """Test backfill_sections service function."""

    @pytest.mark.asyncio
    async def test_rejects_summary_mode(self):
        """Should raise ValueError when channel is in summary mode."""
        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        channel = _make_channel(
            id=channel_id, active_session_id=session_id, history_mode="summary"
        )
        session = _make_session(id=session_id, channel_id=channel_id)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=lambda cls, id_val: (
            channel if id_val == channel_id else
            session if id_val == session_id else None
        ))

        with patch("app.services.compaction.async_session") as mock_session, \
             patch("app.services.compaction.get_bot", return_value=_make_bot(history_mode="summary")) \
                    if hasattr(__import__("app.services.compaction", fromlist=["get_bot"]), "get_bot") else \
             patch("app.agent.bots.get_bot", return_value=_make_bot(history_mode="summary")):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            events = []
            with pytest.raises(ValueError, match="file or structured"):
                async for event in backfill_sections(channel_id, history_mode="summary"):
                    events.append(event)

    @pytest.mark.asyncio
    async def test_rejects_empty_channel(self):
        """Should raise ValueError when no messages exist."""
        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        channel = _make_channel(
            id=channel_id, active_session_id=session_id, history_mode="file"
        )
        session = _make_session(
            id=session_id, channel_id=channel_id, summary_message_id=None
        )

        call_count = [0]

        async def mock_get(cls, id_val):
            if id_val == channel_id:
                return channel
            if id_val == session_id:
                return session
            return None

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            return result

        mock_db = AsyncMock()
        mock_db.get = mock_get
        mock_db.execute = mock_execute

        with patch("app.services.compaction.async_session") as mock_session, \
             patch("app.agent.bots.get_bot", return_value=_make_bot()):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="No messages to backfill"):
                async for _ in backfill_sections(channel_id):
                    pass

    @pytest.mark.asyncio
    async def test_chunking_10_messages_chunk_size_3(self):
        """10 messages with chunk_size=3 should produce 4 chunks (3+3+3+1)."""
        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        channel = _make_channel(
            id=channel_id, active_session_id=session_id, history_mode="file"
        )
        session = _make_session(
            id=session_id, channel_id=channel_id, summary_message_id=None
        )

        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        messages = []
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append(_make_message(
                role=role,
                content=f"msg {i}",
                created_at=base_time + timedelta(minutes=i),
                session_id=session_id,
            ))

        section_json = json.dumps({
            "title": "Test Section",
            "summary": "A test summary.",
            "transcript": "[USER]: hello",
        })

        async def mock_get(cls, id_val):
            if id_val == channel_id:
                return channel
            if id_val == session_id:
                return session
            return None

        async def mock_execute(stmt):
            result = MagicMock()
            stmt_str = str(stmt)
            if "conversation_sections" in stmt_str.lower():
                # count() query from _generate_section
                result.scalar.return_value = 0
                result.scalar_one_or_none.return_value = None
                # Resume path: return empty list (no existing sections)
                result.scalars.return_value.all.return_value = []
                return result
            # Messages query
            result.scalars.return_value.all.return_value = messages
            return result

        sections_added = []

        mock_db = AsyncMock()
        mock_db.get = mock_get
        mock_db.execute = mock_execute
        mock_db.add = lambda s: sections_added.append(s)
        mock_db.commit = AsyncMock()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(section_json)
        )

        with patch("app.services.compaction.async_session") as mock_session, \
             patch("app.agent.bots.get_bot", return_value=_make_bot()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.compaction._regenerate_executive_summary", new_callable=AsyncMock, return_value="Executive summary"):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            events = []
            async for event in backfill_sections(channel_id, chunk_size=3):
                events.append(event)

        progress_events = [e for e in events if e["type"] == "backfill_progress"]
        done_events = [e for e in events if e["type"] == "backfill_done"]

        # 10 user+assistant messages, chunk_size=3 → ceil(10/3) = 4 chunks
        assert len(progress_events) == 4
        assert progress_events[0]["section"] == 1
        assert progress_events[0]["total_chunks"] == 4
        assert progress_events[-1]["section"] == 4

        assert len(done_events) == 1
        assert done_events[0]["sections_created"] == 4

    @pytest.mark.asyncio
    async def test_sequence_starts_after_existing(self):
        """Resume backfill should start sequence after existing sections."""
        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        channel = _make_channel(
            id=channel_id, active_session_id=session_id, history_mode="file"
        )
        session = _make_session(
            id=session_id, channel_id=channel_id, summary_message_id=None
        )

        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # 8 messages total: 3 existing sections cover 6 messages, 2 remaining
        messages = []
        for i in range(8):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append(_make_message(
                role=role,
                content=f"msg {i}",
                created_at=base_time + timedelta(minutes=i),
                session_id=session_id,
            ))

        # 3 existing sections, each covering 2 u+a messages
        existing_sections = [
            MagicMock(sequence=1, message_count=2, chunk_size=2),
            MagicMock(sequence=2, message_count=2, chunk_size=2),
            MagicMock(sequence=3, message_count=2, chunk_size=2),
        ]

        section_json = json.dumps({
            "title": "Test",
            "summary": "Summary.",
            "transcript": "[USER]: hello",
        })

        async def mock_get(cls, id_val):
            if id_val == channel_id:
                return channel
            if id_val == session_id:
                return session
            return None

        async def mock_execute(stmt):
            result = MagicMock()
            stmt_str = str(stmt)
            if "conversation_sections" in stmt_str.lower():
                # count() query from _generate_section
                result.scalar.return_value = len(existing_sections)
                if existing_sections:
                    result.scalar_one_or_none.return_value = existing_sections[-1]
                else:
                    result.scalar_one_or_none.return_value = None
                # Resume path: return existing sections
                result.scalars.return_value.all.return_value = existing_sections
                return result
            result.scalars.return_value.all.return_value = messages
            return result

        added_sections = []
        mock_db = AsyncMock()
        mock_db.get = mock_get
        mock_db.execute = mock_execute
        mock_db.add = lambda s: added_sections.append(s)
        mock_db.commit = AsyncMock()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(section_json)
        )

        with patch("app.services.compaction.async_session") as mock_session, \
             patch("app.agent.bots.get_bot", return_value=_make_bot()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.compaction._regenerate_executive_summary", new_callable=AsyncMock, return_value="Exec"):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            events = []
            async for event in backfill_sections(channel_id, chunk_size=50):
                events.append(event)

        # Section should have sequence 4 (max existing was 3)
        assert len(added_sections) == 1
        assert added_sections[0].sequence == 4

    @pytest.mark.asyncio
    async def test_watermark_filtering(self):
        """Only messages at or before watermark should be processed."""
        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        watermark_id = uuid.uuid4()

        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        watermark_time = base_time + timedelta(minutes=5)

        watermark_msg = _make_message(
            id=watermark_id, role="assistant", content="watermark",
            created_at=watermark_time, session_id=session_id,
        )

        channel = _make_channel(
            id=channel_id, active_session_id=session_id, history_mode="file"
        )
        session = _make_session(
            id=session_id, channel_id=channel_id,
            summary_message_id=watermark_id,
        )

        # Messages before watermark
        pre_watermark = [
            _make_message(role="user", content="before 1", created_at=base_time, session_id=session_id),
            _make_message(role="assistant", content="before 2", created_at=base_time + timedelta(minutes=1), session_id=session_id),
        ]
        # Messages after watermark (should be excluded)
        post_watermark = [
            _make_message(role="user", content="after 1", created_at=base_time + timedelta(minutes=10), session_id=session_id),
            _make_message(role="assistant", content="after 2", created_at=base_time + timedelta(minutes=11), session_id=session_id),
        ]

        section_json = json.dumps({
            "title": "Before Watermark",
            "summary": "Pre-watermark conversation.",
            "transcript": "[USER]: before 1",
        })

        async def mock_get(cls, id_val):
            if id_val == channel_id:
                return channel
            if id_val == session_id:
                return session
            if id_val == watermark_id:
                return watermark_msg
            return None

        async def mock_execute(stmt):
            result = MagicMock()
            stmt_str = str(stmt)
            if "conversation_sections" in stmt_str.lower():
                result.scalar.return_value = 0
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                return result
            # Messages query — only return pre-watermark (the real DB would filter by created_at <= watermark)
            result.scalars.return_value.all.return_value = pre_watermark
            return result

        added_sections = []
        mock_db = AsyncMock()
        mock_db.get = mock_get
        mock_db.execute = mock_execute
        mock_db.add = lambda s: added_sections.append(s)
        mock_db.commit = AsyncMock()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(section_json)
        )

        with patch("app.services.compaction.async_session") as mock_session, \
             patch("app.agent.bots.get_bot", return_value=_make_bot()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.compaction._regenerate_executive_summary", new_callable=AsyncMock, return_value="Exec"):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            events = []
            async for event in backfill_sections(channel_id, chunk_size=50):
                events.append(event)

        # Should only create 1 section from the 2 pre-watermark messages
        assert len(added_sections) == 1
        done = [e for e in events if e["type"] == "backfill_done"]
        assert done[0]["sections_created"] == 1

    @pytest.mark.asyncio
    async def test_channel_not_found(self):
        """Should raise ValueError for non-existent channel."""
        async def mock_get(cls, id_val):
            return None

        mock_db = AsyncMock()
        mock_db.get = mock_get

        with patch("app.services.compaction.async_session") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="Channel not found"):
                async for _ in backfill_sections(uuid.uuid4()):
                    pass

    @pytest.mark.asyncio
    async def test_no_active_session(self):
        """Should raise ValueError when channel has no active session."""
        channel_id = uuid.uuid4()
        channel = _make_channel(id=channel_id, active_session_id=None)

        async def mock_get(cls, id_val):
            if id_val == channel_id:
                return channel
            return None

        mock_db = AsyncMock()
        mock_db.get = mock_get

        with patch("app.services.compaction.async_session") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="no active session"):
                async for _ in backfill_sections(channel_id):
                    pass

    @pytest.mark.asyncio
    async def test_explicit_history_mode_override(self):
        """Explicit history_mode param should override channel/bot defaults."""
        channel_id = uuid.uuid4()
        session_id = uuid.uuid4()
        # Channel is in summary mode, but we pass history_mode="file"
        channel = _make_channel(
            id=channel_id, active_session_id=session_id, history_mode="summary"
        )
        session = _make_session(
            id=session_id, channel_id=channel_id, summary_message_id=None
        )

        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        messages = [
            _make_message(role="user", content="hello", created_at=base_time, session_id=session_id),
            _make_message(role="assistant", content="hi", created_at=base_time + timedelta(minutes=1), session_id=session_id),
        ]

        section_json = json.dumps({
            "title": "Override Test",
            "summary": "Summary.",
            "transcript": "[USER]: hello",
        })

        async def mock_get(cls, id_val):
            if id_val == channel_id:
                return channel
            if id_val == session_id:
                return session
            return None

        async def mock_execute(stmt):
            result = MagicMock()
            stmt_str = str(stmt)
            if "conversation_sections" in stmt_str.lower():
                result.scalar.return_value = 0
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
                return result
            result.scalars.return_value.all.return_value = messages
            return result

        mock_db = AsyncMock()
        mock_db.get = mock_get
        mock_db.execute = mock_execute
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(section_json)
        )

        with patch("app.services.compaction.async_session") as mock_session, \
             patch("app.agent.bots.get_bot", return_value=_make_bot(history_mode="summary")), \
             patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.compaction._regenerate_executive_summary", new_callable=AsyncMock, return_value="Exec"):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            events = []
            # Pass history_mode="file" to override the summary default
            async for event in backfill_sections(channel_id, history_mode="file"):
                events.append(event)

        done = [e for e in events if e["type"] == "backfill_done"]
        assert len(done) == 1
        assert done[0]["sections_created"] == 1
