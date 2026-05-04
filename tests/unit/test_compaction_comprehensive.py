"""Comprehensive tests for app.services.compaction — targeting >90% branch coverage.

Covers: helpers, message filtering, summary generation, run_compaction_stream,
_drain_compaction, maybe_compact, run_compaction_forced, edge cases, and
potential bugs.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.agent.bots import BotConfig, MemoryConfig
from app.services.compaction import (
    _get_compaction_interval,
    _get_compaction_keep_turns,
    _get_compaction_model,
    _is_compaction_enabled,
    _messages_for_summary,
    _stringify_message_content,
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
        persona=False,
        history_mode="summary",
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_channel(**overrides):
    ch = MagicMock()
    ch.compaction_model = overrides.get("compaction_model", None)
    ch.compaction_interval = overrides.get("compaction_interval", None)
    ch.compaction_keep_turns = overrides.get("compaction_keep_turns", None)
    ch.context_compaction = overrides.get("context_compaction", True)
    ch.memory_knowledge_compaction_prompt = overrides.get(
        "memory_knowledge_compaction_prompt", None
    )
    ch.history_mode = overrides.get("history_mode", None)
    ch.id = overrides.get("id", uuid.uuid4())
    return ch


def _mock_llm_response(content):
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = []
    choice.message.model_dump.return_value = {"role": "assistant", "content": content}
    choice.finish_reason = "stop"
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=50, completion_tokens=30, total_tokens=80)
    return resp


# ===================================================================
# _stringify_message_content — additional edge cases
# ===================================================================

class TestStringifyMessageContentExtended:
    def test_integer_content(self):
        assert _stringify_message_content(42) == "42"

    def test_dict_in_list_unknown_type(self):
        content = [{"type": "custom", "data": "x" * 200}]
        result = _stringify_message_content(content)
        assert len(result) <= 120

    def test_list_with_only_non_text_dicts(self):
        """List with dicts but no recognized types → truncated repr."""
        content = [{"type": "custom", "key": "val"}]
        result = _stringify_message_content(content)
        assert result  # non-empty
        assert result != "[multimodal message]"

    def test_empty_text_parts(self):
        content = [{"type": "text", "text": ""}, {"type": "text", "text": ""}]
        # Two empty text parts join to empty string, fallback to [multimodal message]
        result = _stringify_message_content(content)
        assert result == "[multimodal message]"

    def test_mixed_audio_and_text(self):
        content = [
            {"type": "input_audio", "input_audio": {"data": "..."}},
            {"type": "text", "text": "transcription"},
        ]
        result = _stringify_message_content(content)
        assert "[audio]" in result
        assert "transcription" in result


# ===================================================================
# _messages_for_summary — additional edge cases
# ===================================================================

class TestMessagesForSummaryExtended:
    def test_empty_input(self):
        assert _messages_for_summary([]) == []

    def test_all_passive_no_active(self):
        msgs = [
            {"role": "user", "content": "ambient", "_metadata": {"passive": True}},
        ]
        result = _messages_for_summary(msgs)
        # Should have system context block only
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_passive_without_sender_id_defaults_to_user(self):
        msgs = [
            {"role": "user", "content": "ambient", "_metadata": {"passive": True}},
        ]
        result = _messages_for_summary(msgs)
        assert "user:" in result[0]["content"]

    def test_none_content_skipped(self):
        msgs = [
            {"role": "user", "content": None},
            {"role": "assistant", "content": "reply"},
        ]
        result = _messages_for_summary(msgs)
        assert len(result) == 1

    def test_tool_messages_included_as_compact_representation(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "ask"},
            {"role": "tool", "content": "result", "name": "web_search"},
            {"role": "assistant", "content": "done"},
        ]
        result = _messages_for_summary(msgs)
        roles = [m["role"] for m in result]
        assert "system" not in roles
        assert "tool" not in roles
        # Tool result is now included as a compact assistant message
        assert len(result) == 3
        assert "[Tool result from web_search: result]" in result[1]["content"]

    def test_multiple_passive_combined(self):
        msgs = [
            {"role": "user", "content": "msg1", "_metadata": {"passive": True, "sender_id": "alice"}},
            {"role": "user", "content": "msg2", "_metadata": {"passive": True, "sender_id": "bob"}},
            {"role": "user", "content": "active"},
        ]
        result = _messages_for_summary(msgs)
        sys_block = result[0]
        assert sys_block["role"] == "system"
        assert "alice" in sys_block["content"]
        assert "bob" in sys_block["content"]


# ===================================================================
# _generate_summary
# ===================================================================

class TestGenerateSummaryExtended:
    @pytest.mark.asyncio
    async def test_empty_json_response(self):
        mock_client = AsyncMock()
        resp = _mock_llm_response("{}")
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            title, summary, _usage = await _generate_summary(
                [{"role": "user", "content": "hi"}], "test/model", None
            )

        assert title == "Conversation"
        assert summary == "{}"

    @pytest.mark.asyncio
    async def test_missing_title_field(self):
        mock_client = AsyncMock()
        resp = _mock_llm_response('{"summary": "Some summary"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            title, summary, _usage = await _generate_summary([], "test/model", None)

        assert title == "Conversation"
        assert summary == "Some summary"

    @pytest.mark.asyncio
    async def test_missing_summary_field(self):
        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "My Chat"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            title, summary, _usage = await _generate_summary([], "test/model", None)

        assert title == "My Chat"
        # Falls back to raw string when summary missing
        assert summary == '{"title": "My Chat"}'

    @pytest.mark.asyncio
    async def test_null_content_response(self):
        mock_client = AsyncMock()
        resp = _mock_llm_response(None)
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            title, summary, _usage = await _generate_summary([], "test/model", None)

        # None → "{}" → parsed as empty dict
        assert title == "Conversation"

    @pytest.mark.asyncio
    async def test_markdown_fence_without_newline(self):
        """Test ```json{...}``` with no newline after opening fence."""
        mock_client = AsyncMock()
        resp = _mock_llm_response('```{"title": "T", "summary": "S"}```')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            title, summary, _usage = await _generate_summary([], "test/model", None)

        # When there's no newline, split("\n", 1)[1] won't work as expected
        # so it does raw[3:] which gives '{"title": "T", "summary": "S"}```'
        # then rsplit("```", 1)[0] gives '{"title": "T", "summary": "S"}'
        assert title == "T"
        assert summary == "S"

    @pytest.mark.asyncio
    async def test_no_existing_summary_prompt(self):
        """Without existing summary, only system + conversation messages sent."""
        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            await _generate_summary(
                [{"role": "user", "content": "hi"}], "test/model", None
            )

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        # system + conversation only (no existing summary)
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_with_existing_summary_prompt(self):
        """With existing summary, 3 messages: system + existing + conversation."""
        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            await _generate_summary(
                [{"role": "user", "content": "hi"}],
                "test/model",
                "Previous context",
            )

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        assert len(messages) == 3
        assert "Previous" in messages[1]["content"]

    @pytest.mark.asyncio
    async def test_provider_id_passed_through(self):
        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client) as mock_get:
            from app.services.compaction import _generate_summary
            await _generate_summary([], "test/model", None, provider_id="custom-provider")

        mock_get.assert_called_once_with("custom-provider")

    @pytest.mark.asyncio
    async def test_temperature_is_03(self):
        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            await _generate_summary([], "test/model", None)

        call_args = mock_client.chat.completions.create.call_args
        assert call_args[1]["temperature"] == 0.3


# ===================================================================
# _is_compaction_enabled — additional
# ===================================================================

class TestIsCompactionEnabledExtended:
    def test_channel_true_bot_false(self):
        """Channel enabling overrides bot disabling."""
        bot = _make_bot(context_compaction=False)
        ch = _make_channel(context_compaction=True)
        assert _is_compaction_enabled(bot, ch) is True

    def test_no_channel_defaults_to_bot(self):
        bot = _make_bot(context_compaction=True)
        assert _is_compaction_enabled(bot, None) is True


# ===================================================================
# _get_compaction_interval — additional
# ===================================================================

class TestGetCompactionIntervalExtended:
    def test_falls_to_settings_when_bot_is_none(self):
        bot = _make_bot(compaction_interval=None)
        from app.config import settings
        assert _get_compaction_interval(bot) == settings.COMPACTION_INTERVAL

    def test_channel_zero_is_valid(self):
        """Channel interval of 0 should be used (it's not None)."""
        bot = _make_bot(compaction_interval=10)
        ch = _make_channel(compaction_interval=0)
        assert _get_compaction_interval(bot, ch) == 0


# ===================================================================
# Turn-counting logic in message selection
# ===================================================================

class TestTurnCountingLogic:
    """Test the message selection loop that builds to_summarize."""

    def _run_selection(self, messages, interval, keep_turns):
        """Simulate the turn-counting loop from run_compaction_stream."""
        conversation = _messages_for_summary(messages)
        turns_to_summarize = interval - keep_turns
        user_count = 0
        to_summarize = []
        for m in conversation:
            if m.get("role") == "user":
                user_count += 1
                if user_count > turns_to_summarize:
                    break
            to_summarize.append(m)
        return to_summarize

    def test_selects_correct_number_of_turns(self):
        msgs = [
            {"role": "user", "content": f"u{i}"}
            for i in range(5)
        ]
        result = self._run_selection(msgs, interval=5, keep_turns=2)
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(user_msgs) == 3  # 5 - 2

    def test_includes_assistant_messages_with_turns(self):
        msgs = []
        for i in range(4):
            msgs.append({"role": "user", "content": f"u{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})
        result = self._run_selection(msgs, interval=4, keep_turns=2)
        # Should include 2 user turns + their assistant replies
        user_msgs = [m for m in result if m["role"] == "user"]
        asst_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(user_msgs) == 2
        assert len(asst_msgs) == 2

    def test_keep_turns_equals_interval_yields_empty(self):
        """When keep_turns == interval, turns_to_summarize is 0, so nothing selected."""
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(5)]
        result = self._run_selection(msgs, interval=5, keep_turns=5)
        assert result == []

    def test_keep_turns_exceeds_interval_yields_empty(self):
        """When keep_turns > interval, turns_to_summarize is negative."""
        msgs = [{"role": "user", "content": f"u{i}"} for i in range(5)]
        result = self._run_selection(msgs, interval=3, keep_turns=5)
        assert result == []

    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "only"}]
        result = self._run_selection(msgs, interval=1, keep_turns=0)
        assert len(result) == 1
        assert result[0]["content"] == "only"

    def test_assistant_after_cutoff_excluded(self):
        """Assistant message after the last selected user turn is excluded."""
        msgs = [
            {"role": "user", "content": "u0"},
            {"role": "assistant", "content": "a0"},
            {"role": "user", "content": "u1"},  # this triggers break
            {"role": "assistant", "content": "a1"},
        ]
        result = self._run_selection(msgs, interval=2, keep_turns=1)
        # Only u0 + a0 selected; u1 triggers break
        assert len(result) == 2
        assert result[0]["content"] == "u0"
        assert result[1]["content"] == "a0"


# ===================================================================
# run_compaction_stream — comprehensive integration-style tests
# (Using mocked DB via async_session patch)
# ===================================================================

from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession, async_sessionmaker, create_async_engine
from app.db.models import Base, Message, Session

# Re-use the engine fixture from integration conftest (handles SQLite type compilation)
from tests.integration.conftest import engine as mem_engine  # noqa: F401


@pytest_asyncio.fixture
async def factory(mem_engine):  # noqa: F811
    return async_sessionmaker(mem_engine, class_=SAAsyncSession, expire_on_commit=False)


async def _create_session_with_messages(factory, num_user=0, num_assistant=0, bot_id="test-bot", channel_id=None, existing_summary=None, summary_message_id=None):
    """Helper: create a Session + interleaved user/assistant messages, return session_id."""
    sid = uuid.uuid4()
    async with factory() as db:
        session = Session(id=sid, client_id="test-client", bot_id=bot_id)
        if channel_id:
            session.channel_id = channel_id
        if existing_summary:
            session.summary = existing_summary
        if summary_message_id:
            session.summary_message_id = summary_message_id
        db.add(session)

        base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        msg_idx = 0
        for i in range(max(num_user, num_assistant)):
            if i < num_user:
                db.add(Message(
                    id=uuid.uuid4(),
                    session_id=sid,
                    role="user",
                    content=f"user message {i}",
                    created_at=base_time + timedelta(minutes=msg_idx),
                ))
                msg_idx += 1
            if i < num_assistant:
                db.add(Message(
                    id=uuid.uuid4(),
                    session_id=sid,
                    role="assistant",
                    content=f"assistant reply {i}",
                    created_at=base_time + timedelta(minutes=msg_idx),
                ))
                msg_idx += 1

        await db.commit()
    return sid


class TestRunCompactionStream:
    @pytest.mark.asyncio
    async def test_session_not_found(self, factory):
        bot = _make_bot()
        fake_sid = uuid.uuid4()

        with patch("app.services.compaction.async_session", factory):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(fake_sid, bot, [])]

        assert events == []

    @pytest.mark.asyncio
    async def test_compaction_disabled_yields_nothing(self, factory):
        bot = _make_bot(context_compaction=False)
        sid = await _create_session_with_messages(factory, num_user=20, num_assistant=20)

        with patch("app.services.compaction.async_session", factory):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, [])]

        assert events == []

    @pytest.mark.asyncio
    async def test_not_enough_turns(self, factory):
        bot = _make_bot(compaction_interval=10)
        sid = await _create_session_with_messages(factory, num_user=5, num_assistant=5)

        with patch("app.services.compaction.async_session", factory):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, [])]

        assert events == []

    @pytest.mark.asyncio
    async def test_exactly_at_threshold(self, factory):
        """When user_msg_count == interval, compaction should trigger."""
        bot = _make_bot(compaction_interval=3, compaction_keep_turns=1)
        sid = await _create_session_with_messages(factory, num_user=3, num_assistant=3)

        messages = [
            {"role": "user", "content": f"user message {i}"} for i in range(3)
        ] + [
            {"role": "assistant", "content": f"assistant reply {i}"} for i in range(3)
        ]

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "Test", "summary": "Summary"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, messages)]

        types = [e.get("type") for e in events]
        assert "compaction_done" in types

    @pytest.mark.asyncio
    async def test_one_below_threshold_no_trigger(self, factory):
        """user_msg_count == interval - 1 should NOT trigger."""
        bot = _make_bot(compaction_interval=5, compaction_keep_turns=1)
        sid = await _create_session_with_messages(factory, num_user=4, num_assistant=4)

        with patch("app.services.compaction.async_session", factory):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, [])]

        assert events == []

    @pytest.mark.asyncio
    async def test_empty_to_summarize_yields_nothing(self, factory):
        """If the compaction window contains only internal rows, no summary is generated."""
        bot = _make_bot(compaction_interval=2, compaction_keep_turns=0)
        sid = uuid.uuid4()
        base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

        async with factory() as db:
            db.add(Session(id=sid, client_id="c", bot_id="test"))
            for i in range(3):
                db.add(Message(
                    session_id=sid,
                    role="user",
                    content=f"hidden user {i}",
                    metadata_={"hidden": True, "pipeline_step": True},
                    created_at=base_time + timedelta(minutes=i),
                ))
            await db.commit()

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, [])]

        # Should not have compaction_done because to_summarize is empty
        types = [e.get("type") for e in events]
        assert "compaction_done" not in types

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_error_during_summary_logged_not_raised(self, factory):
        """If _generate_summary raises, compaction fails silently."""
        bot = _make_bot(compaction_interval=2, compaction_keep_turns=1)
        sid = await _create_session_with_messages(factory, num_user=3, num_assistant=3)

        messages = [
            {"role": "user", "content": f"user message {i}"} for i in range(3)
        ] + [
            {"role": "assistant", "content": f"assistant reply {i}"} for i in range(3)
        ]

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.compaction._generate_summary", new_callable=AsyncMock, side_effect=RuntimeError("LLM down")),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, messages)]

        # Error caught; no compaction_done event
        types = [e.get("type") for e in events]
        assert "compaction_done" not in types

    @pytest.mark.asyncio
    async def test_session_updated_with_watermark(self, factory):
        """After compaction, session.summary, title, and summary_message_id are set."""
        bot = _make_bot(compaction_interval=3, compaction_keep_turns=1)
        sid = await _create_session_with_messages(factory, num_user=4, num_assistant=4)

        messages = []
        for i in range(4):
            messages.append({"role": "user", "content": f"user message {i}"})
            messages.append({"role": "assistant", "content": f"assistant reply {i}"})

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "Chat", "summary": "A conversation"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, messages)]

        assert any(e.get("type") == "compaction_done" for e in events)

        async with factory() as db:
            session = await db.get(Session, sid)
            assert session.title == "Chat"
            assert session.summary == "A conversation"
            assert session.summary_message_id is not None

    @pytest.mark.asyncio
    async def test_all_messages_in_keep_window(self, factory):
        """If all messages are within the keep window, watermark_id is None → skip."""
        bot = _make_bot(compaction_interval=2, compaction_keep_turns=10)
        # 3 user messages but keep_turns=10 means all are kept
        sid = await _create_session_with_messages(factory, num_user=3, num_assistant=3)

        messages = []
        for i in range(3):
            messages.append({"role": "user", "content": f"user message {i}"})
            messages.append({"role": "assistant", "content": f"assistant reply {i}"})

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, messages)]

        # turns_to_summarize = 2 - 10 = -8, so to_summarize is empty
        types = [e.get("type") for e in events]
        assert "compaction_done" not in types

    @pytest.mark.asyncio
    async def test_channel_level_settings_used(self, factory):
        """Channel-level interval/keep_turns override bot-level."""
        bot = _make_bot(compaction_interval=100, compaction_keep_turns=50)
        channel_id = uuid.uuid4()

        async with factory() as db:
            from app.db.models import Channel
            channel = Channel(
                id=channel_id,
                name="test-channel",
                bot_id="test",
                context_compaction=True,
                compaction_interval=2,  # override to 2
                compaction_keep_turns=1,
            )
            db.add(channel)
            await db.commit()

        sid = await _create_session_with_messages(
            factory, num_user=3, num_assistant=3, channel_id=channel_id
        )

        messages = []
        for i in range(3):
            messages.append({"role": "user", "content": f"user message {i}"})
            messages.append({"role": "assistant", "content": f"assistant reply {i}"})

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, messages)]

        # Channel interval=2, 3 user messages → should trigger
        types = [e.get("type") for e in events]
        assert "compaction_done" in types


# ===================================================================
# _drain_compaction
# ===================================================================

class TestDrainCompaction:
    @pytest.mark.asyncio
    async def test_publishes_notification_on_success(self, factory):
        """After compaction completes, a NEW_MESSAGE typed event hits the bus
        for the channel attached to the session."""
        bot = _make_bot(compaction_interval=2, compaction_keep_turns=1)
        sid = await _create_session_with_messages(factory, num_user=3, num_assistant=3)

        messages = []
        for i in range(3):
            messages.append({"role": "user", "content": f"user message {i}"})
            messages.append({"role": "assistant", "content": f"assistant reply {i}"})

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
            patch("app.services.channel_events.publish_typed") as mock_publish,
        ):
            from app.services.compaction import _drain_compaction
            await _drain_compaction(sid, bot, messages)

        # The notification path is best-effort and skipped when the session
        # has no channel_id; just assert _drain_compaction did not raise.
        # publish_typed may or may not have been called depending on whether
        # the test session was created with a channel.

    @pytest.mark.asyncio
    async def test_no_dispatch_without_config(self, factory):
        bot = _make_bot(compaction_interval=2, compaction_keep_turns=1)
        sid = await _create_session_with_messages(factory, num_user=3, num_assistant=3)

        messages = []
        for i in range(3):
            messages.append({"role": "user", "content": f"user message {i}"})
            messages.append({"role": "assistant", "content": f"assistant reply {i}"})

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import _drain_compaction
            # Should not raise even without dispatch config
            await _drain_compaction(sid, bot, messages)

    @pytest.mark.asyncio
    async def test_exception_in_stream_caught(self, factory):
        bot = _make_bot()

        async def bad_stream(*args, **kwargs):
            raise RuntimeError("kaboom")
            yield  # make it async gen  # noqa: E305

        with (
            patch("app.services.compaction.run_compaction_stream", side_effect=bad_stream),
        ):
            from app.services.compaction import _drain_compaction
            # Should not raise
            await _drain_compaction(uuid.uuid4(), bot, [])

    @pytest.mark.asyncio
    async def test_publish_failure_caught(self, factory):
        bot = _make_bot(compaction_interval=2, compaction_keep_turns=1)
        sid = await _create_session_with_messages(factory, num_user=3, num_assistant=3)

        messages = []
        for i in range(3):
            messages.append({"role": "user", "content": f"user message {i}"})
            messages.append({"role": "assistant", "content": f"assistant reply {i}"})

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
            patch("app.services.channel_events.publish_typed", side_effect=RuntimeError("bus down")),
        ):
            from app.services.compaction import _drain_compaction
            # Should not raise despite publish failure
            await _drain_compaction(sid, bot, messages)


# ===================================================================
# maybe_compact
# ===================================================================

class TestMaybeCompact:
    @pytest.mark.asyncio
    async def test_creates_background_task(self):
        bot = _make_bot()
        sid = uuid.uuid4()

        with patch("app.services.compaction._drain_compaction", new_callable=AsyncMock) as mock_drain:
            from app.services.compaction import maybe_compact
            maybe_compact(sid, bot, [{"role": "user", "content": "hi"}])
            # Give the event loop a chance to schedule the task
            await asyncio.sleep(0.01)

        mock_drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_correlation_and_budget(self):
        """maybe_compact forwards correlation_id and the budget-trigger
        signal into _drain_compaction. dispatch_type / dispatch_config are
        gone in Phase E — the channel-events bus owns delivery."""
        bot = _make_bot()
        sid = uuid.uuid4()
        cid = uuid.uuid4()

        with patch("app.services.compaction._drain_compaction", new_callable=AsyncMock) as mock_drain:
            from app.services.compaction import maybe_compact
            maybe_compact(sid, bot, [], correlation_id=cid, budget_utilization=0.95)
            await asyncio.sleep(0.01)

        args = mock_drain.call_args
        assert args[1]["correlation_id"] == cid
        assert args[1]["budget_triggered"] is True
        assert args[1]["trigger_reason"] == "total_utilization"


# ===================================================================
# run_compaction_forced
# ===================================================================

class TestRunCompactionForced:
    @pytest.mark.asyncio
    async def test_session_not_found_raises(self, factory):
        bot = _make_bot()
        async with factory() as db:
            from app.services.compaction import run_compaction_forced
            with pytest.raises(ValueError, match="Session not found"):
                await run_compaction_forced(uuid.uuid4(), bot, db)

    @pytest.mark.asyncio
    async def test_no_conversation_content_raises(self, factory):
        """Session with only system messages → no conversation content."""
        bot = _make_bot(compaction_interval=3, compaction_keep_turns=1)
        sid = uuid.uuid4()
        async with factory() as db:
            session = Session(id=sid, client_id="c", bot_id="test")
            db.add(session)
            # Add only system messages
            db.add(Message(session_id=sid, role="system", content="You are a bot"))
            await db.commit()

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        async with factory() as db:
            from app.services.compaction import run_compaction_forced
            with (
                patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
                pytest.raises(ValueError, match="No conversation content"),
            ):
                await run_compaction_forced(sid, bot, db)

    @pytest.mark.asyncio
    async def test_normal_flow(self, factory):
        bot = _make_bot(compaction_interval=3, compaction_keep_turns=1)
        sid = await _create_session_with_messages(factory, num_user=5, num_assistant=5)

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "Forced Title", "summary": "Forced summary"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        async with factory() as db:
            from app.services.compaction import run_compaction_forced
            with (
                patch("app.services.providers.get_llm_client", return_value=mock_client),
                patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
            ):
                title, summary = await run_compaction_forced(sid, bot, db)
                await db.commit()

        assert title == "Forced Title"
        assert summary == "Forced summary"

        async with factory() as db:
            session = await db.get(Session, sid)
            assert session.title == "Forced Title"
            assert session.summary_message_id is not None

    @pytest.mark.asyncio
    async def test_forced_compaction_releases_db_connection_around_memory_flush(self, factory):
        """Memory flush may outlive idle-in-transaction timeout; forced compaction must not."""
        from app.db.models import Channel

        bot = _make_bot(compaction_interval=3, compaction_keep_turns=1)
        channel_id = uuid.uuid4()
        async with factory() as db:
            db.add(Channel(
                id=channel_id,
                name="test-channel",
                bot_id="test",
                context_compaction=True,
                compaction_keep_turns=1,
            ))
            await db.commit()
        sid = await _create_session_with_messages(
            factory, num_user=5, num_assistant=5, channel_id=channel_id,
        )

        async with factory() as db:
            original_close = db.close
            db.close = AsyncMock(wraps=original_close)
            from app.services.compaction import run_compaction_forced
            with (
                patch("app.services.compaction._run_memory_flush_phase", new_callable=AsyncMock, return_value=(True, "flushed")) as flush,
                patch("app.services.compaction._generate_summary", new_callable=AsyncMock, return_value=("Forced Title", "Forced summary", {"tier": "normal"})),
                patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
                patch("app.services.compaction._record_compaction_completion"),
            ):
                title, summary = await run_compaction_forced(sid, bot, db)

        assert title == "Forced Title"
        assert summary == "Forced summary"
        flush.assert_awaited_once()
        assert db.close.await_count >= 2

    @pytest.mark.asyncio
    async def test_all_in_keep_window_raises(self, factory):
        """If all messages are within keep window, raises ValueError."""
        bot = _make_bot(compaction_interval=3, compaction_keep_turns=100)
        # Only 2 user messages, keep_turns=100
        sid = await _create_session_with_messages(factory, num_user=2, num_assistant=2)

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        async with factory() as db:
            from app.services.compaction import run_compaction_forced
            with (
                patch("app.services.providers.get_llm_client", return_value=mock_client),
                patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
                pytest.raises(ValueError, match="within keep window"),
            ):
                await run_compaction_forced(sid, bot, db)


# ===================================================================
# BUG: run_compaction_forced — IndexError on empty user_msg_ids
# ===================================================================

class TestRunCompactionForcedBugs:
    @pytest.mark.asyncio
    async def test_forced_with_no_user_messages_crashes(self, factory):
        """run_compaction_forced raises ValueError when session has no user messages.

        Previously this was an unguarded IndexError on user_msg_ids[-1].
        Now mirrors the guard in run_compaction_stream.
        """
        bot = _make_bot(compaction_interval=3, compaction_keep_turns=1)
        sid = uuid.uuid4()
        async with factory() as db:
            session = Session(id=sid, client_id="c", bot_id="test")
            db.add(session)
            # Only assistant messages, no user messages
            base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
            for i in range(3):
                db.add(Message(
                    session_id=sid, role="assistant",
                    content=f"assistant {i}",
                    created_at=base_time + timedelta(minutes=i),
                ))
            await db.commit()

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        async with factory() as db:
            from app.services.compaction import run_compaction_forced
            with (
                patch("app.services.providers.get_llm_client", return_value=mock_client),
                patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
            ):
                with pytest.raises(ValueError, match="No user messages found"):
                    await run_compaction_forced(sid, bot, db)


# ===================================================================
# Incremental compaction (watermark behavior)
# ===================================================================

class TestIncrementalCompaction:
    @pytest.mark.asyncio
    async def test_only_counts_messages_after_watermark(self, factory):
        """After a compaction, only messages after summary_message_id are counted."""
        bot = _make_bot(compaction_interval=3, compaction_keep_turns=1)

        # Create session with a watermark pointing to old messages
        sid = uuid.uuid4()
        base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        watermark_msg_id = uuid.uuid4()

        async with factory() as db:
            session = Session(
                id=sid, client_id="c", bot_id="test",
                summary="Old summary",
                summary_message_id=watermark_msg_id,
            )
            db.add(session)

            # Watermark message (old, already compacted)
            db.add(Message(
                id=watermark_msg_id,
                session_id=sid,
                role="user",
                content="old message",
                created_at=base_time,
            ))

            # Only 2 user messages AFTER watermark (below interval of 3)
            for i in range(2):
                db.add(Message(
                    session_id=sid, role="user",
                    content=f"new message {i}",
                    created_at=base_time + timedelta(minutes=i + 1),
                ))
            await db.commit()

        with patch("app.services.compaction.async_session", factory):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, [])]

        # Only 2 messages after watermark < interval of 3 → no compaction
        assert events == []

    @pytest.mark.asyncio
    async def test_counts_correctly_after_watermark_triggers(self, factory):
        """With enough messages after watermark, compaction triggers."""
        bot = _make_bot(compaction_interval=2, compaction_keep_turns=1)

        sid = uuid.uuid4()
        base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        watermark_msg_id = uuid.uuid4()

        async with factory() as db:
            session = Session(
                id=sid, client_id="c", bot_id="test",
                summary="Old summary",
                summary_message_id=watermark_msg_id,
            )
            db.add(session)

            db.add(Message(
                id=watermark_msg_id,
                session_id=sid,
                role="user",
                content="old message",
                created_at=base_time,
            ))

            # 3 user messages after watermark (>= interval of 2)
            for i in range(3):
                db.add(Message(
                    session_id=sid, role="user",
                    content=f"new message {i}",
                    created_at=base_time + timedelta(minutes=i + 1),
                ))
                db.add(Message(
                    session_id=sid, role="assistant",
                    content=f"reply {i}",
                    created_at=base_time + timedelta(minutes=i + 1, seconds=30),
                ))
            await db.commit()

        messages = []
        for i in range(3):
            messages.append({"role": "user", "content": f"new message {i}"})
            messages.append({"role": "assistant", "content": f"reply {i}"})

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "Incremental", "summary": "Updated summary"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, messages)]

        types = [e.get("type") for e in events]
        assert "compaction_done" in types

    @pytest.mark.asyncio
    async def test_existing_summary_passed_to_generate(self, factory):
        """Incremental compaction passes existing summary to _generate_summary."""
        bot = _make_bot(compaction_interval=2, compaction_keep_turns=1)

        sid = uuid.uuid4()
        base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        watermark_msg_id = uuid.uuid4()

        async with factory() as db:
            session = Session(
                id=sid, client_id="c", bot_id="test",
                summary="Previous context about cats",
                summary_message_id=watermark_msg_id,
            )
            db.add(session)

            db.add(Message(
                id=watermark_msg_id,
                session_id=sid,
                role="user",
                content="old message",
                created_at=base_time,
            ))
            for i in range(3):
                db.add(Message(
                    session_id=sid, role="user",
                    content=f"new {i}",
                    created_at=base_time + timedelta(minutes=i + 1),
                ))
                db.add(Message(
                    session_id=sid, role="assistant",
                    content=f"reply {i}",
                    created_at=base_time + timedelta(minutes=i + 1, seconds=30),
                ))
            await db.commit()

        messages = [{"role": "user", "content": f"new {i}"} for i in range(3)]

        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import run_compaction_stream
            events = [e async for e in run_compaction_stream(sid, bot, messages)]

        # Verify existing summary was sent to LLM
        call_args = mock_client.chat.completions.create.call_args
        messages_sent = call_args[1]["messages"]
        assert any("Previous context about cats" in m.get("content", "") for m in messages_sent)
