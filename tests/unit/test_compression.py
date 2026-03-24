"""Tests for app.services.compression — config resolution, message splitting, formatting."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.compression import (
    _is_compression_enabled,
    _get_compression_model,
    _get_compression_threshold,
    _get_compression_keep_turns,
    _format_message,
    _stringify_tool_calls,
    compress_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bot(**cc_overrides) -> MagicMock:
    bot = MagicMock()
    bot.compression_config = cc_overrides or {}
    bot.model = "gemini/gemini-2.5-flash"
    bot.model_provider_id = None
    return bot


def _channel(**overrides) -> MagicMock:
    ch = MagicMock()
    ch.context_compression = overrides.get("context_compression", None)
    ch.compression_model = overrides.get("compression_model", None)
    ch.compression_threshold = overrides.get("compression_threshold", None)
    ch.compression_keep_turns = overrides.get("compression_keep_turns", None)
    return ch


def _make_messages(user_turns: int = 10, with_tools: bool = False) -> list[dict]:
    """Build a message list with system header + N user/assistant turns + user tail."""
    msgs = [{"role": "system", "content": "You are a helpful bot."}]
    for i in range(user_turns):
        msgs.append({"role": "user", "content": f"User message {i} " + "x" * 200})
        if with_tools:
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"tc_{i}",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": json.dumps({"q": f"query {i}"})},
                }],
            })
            msgs.append({
                "role": "tool",
                "tool_call_id": f"tc_{i}",
                "content": f"Search result for query {i} " + "y" * 100,
            })
        msgs.append({"role": "assistant", "content": f"Response {i} " + "z" * 200})
    # Final user message (the current question)
    msgs.append({"role": "user", "content": "What was the first thing we discussed?"})
    return msgs


# ---------------------------------------------------------------------------
# Config resolution: _is_compression_enabled
# ---------------------------------------------------------------------------

class TestIsCompressionEnabled:
    def test_global_disabled_by_default(self):
        bot = _bot()
        assert not _is_compression_enabled(bot)

    @patch("app.services.compression.settings")
    def test_global_enabled(self, mock_settings):
        mock_settings.CONTEXT_COMPRESSION_ENABLED = True
        bot = _bot()
        assert _is_compression_enabled(bot)

    def test_bot_overrides_global(self):
        bot = _bot(enabled=True)
        assert _is_compression_enabled(bot)

    def test_bot_disabled_overrides_global(self):
        with patch("app.services.compression.settings") as mock_settings:
            mock_settings.CONTEXT_COMPRESSION_ENABLED = True
            bot = _bot(enabled=False)
            assert not _is_compression_enabled(bot)

    def test_channel_overrides_bot(self):
        bot = _bot(enabled=True)
        ch = _channel(context_compression=False)
        assert not _is_compression_enabled(bot, ch)

    def test_channel_none_falls_to_bot(self):
        bot = _bot(enabled=True)
        ch = _channel(context_compression=None)
        assert _is_compression_enabled(bot, ch)


# ---------------------------------------------------------------------------
# Config resolution: _get_compression_model
# ---------------------------------------------------------------------------

class TestGetCompressionModel:
    @patch("app.services.compression.settings")
    def test_global_fallback_to_compaction_model(self, mock_settings):
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = "gemini/gemini-flash"
        bot = _bot()
        assert _get_compression_model(bot) == "gemini/gemini-flash"

    @patch("app.services.compression.settings")
    def test_global_fallback_to_bot_model(self, mock_settings):
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = ""
        bot = _bot()
        bot.model = "my-model"
        assert _get_compression_model(bot) == "my-model"

    @patch("app.services.compression.settings")
    def test_global_explicit(self, mock_settings):
        mock_settings.CONTEXT_COMPRESSION_MODEL = "custom-model"
        bot = _bot()
        assert _get_compression_model(bot) == "custom-model"

    def test_bot_override(self):
        bot = _bot(model="bot-compression-model")
        assert _get_compression_model(bot) == "bot-compression-model"

    def test_channel_override(self):
        bot = _bot(model="bot-model")
        ch = _channel(compression_model="channel-model")
        assert _get_compression_model(bot, ch) == "channel-model"


# ---------------------------------------------------------------------------
# Config resolution: _get_compression_threshold
# ---------------------------------------------------------------------------

class TestGetCompressionThreshold:
    @patch("app.services.compression.settings")
    def test_global_default(self, mock_settings):
        mock_settings.CONTEXT_COMPRESSION_THRESHOLD = 20000
        bot = _bot()
        assert _get_compression_threshold(bot) == 20000

    def test_bot_override(self):
        bot = _bot(threshold=5000)
        assert _get_compression_threshold(bot) == 5000

    def test_channel_override(self):
        bot = _bot(threshold=5000)
        ch = _channel(compression_threshold=3000)
        assert _get_compression_threshold(bot, ch) == 3000


# ---------------------------------------------------------------------------
# Config resolution: _get_compression_keep_turns
# ---------------------------------------------------------------------------

class TestGetCompressionKeepTurns:
    @patch("app.services.compression.settings")
    def test_global_default(self, mock_settings):
        mock_settings.CONTEXT_COMPRESSION_KEEP_TURNS = 2
        bot = _bot()
        assert _get_compression_keep_turns(bot) == 2

    def test_bot_override(self):
        bot = _bot(keep_turns=4)
        assert _get_compression_keep_turns(bot) == 4

    def test_channel_override(self):
        bot = _bot(keep_turns=4)
        ch = _channel(compression_keep_turns=1)
        assert _get_compression_keep_turns(bot, ch) == 1


# ---------------------------------------------------------------------------
# _format_message
# ---------------------------------------------------------------------------

class TestFormatMessage:
    def test_user_message(self):
        msg = {"role": "user", "content": "Hello world"}
        result = _format_message(0, msg)
        assert result == "[msg:0] user: Hello world"

    def test_assistant_message(self):
        msg = {"role": "assistant", "content": "Sure, I can help."}
        result = _format_message(3, msg)
        assert result == "[msg:3] assistant: Sure, I can help."

    def test_assistant_with_tool_calls(self):
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "tc1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"q": "test"}'},
            }],
        }
        result = _format_message(5, msg)
        assert "[msg:5] assistant:" in result
        assert "web_search" in result

    def test_tool_message(self):
        msg = {"role": "tool", "tool_call_id": "tc1", "content": "Search results here"}
        result = _format_message(6, msg)
        assert "[msg:6] tool(tc1):" in result
        assert "Search results here" in result

    def test_tool_message_long_content_truncated(self):
        msg = {"role": "tool", "tool_call_id": "tc1", "content": "a" * 600}
        result = _format_message(0, msg)
        assert len(result) < 600


# ---------------------------------------------------------------------------
# _stringify_tool_calls
# ---------------------------------------------------------------------------

class TestStringifyToolCalls:
    def test_single_tool_call(self):
        tcs = [{"function": {"name": "web_search", "arguments": '{"q": "test"}'}}]
        result = _stringify_tool_calls(tcs)
        assert "web_search" in result
        assert "test" in result

    def test_long_arguments_truncated(self):
        tcs = [{"function": {"name": "fn", "arguments": "x" * 400}}]
        result = _stringify_tool_calls(tcs)
        assert len(result) < 400

    def test_multiple_tool_calls(self):
        tcs = [
            {"function": {"name": "fn1", "arguments": "a"}},
            {"function": {"name": "fn2", "arguments": "b"}},
        ]
        result = _stringify_tool_calls(tcs)
        assert "fn1" in result
        assert "fn2" in result


# ---------------------------------------------------------------------------
# compress_context — integration (with mocked LLM call)
# ---------------------------------------------------------------------------

class TestCompressContext:
    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self):
        bot = _bot()
        result = await compress_context(
            _make_messages(3), bot, "question",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_below_threshold(self):
        bot = _bot(enabled=True, threshold=999999)
        result = await compress_context(
            _make_messages(3), bot, "question",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_older_messages(self):
        """If all messages are within keep_turns, nothing to compress."""
        bot = _bot(enabled=True, threshold=1, keep_turns=100)
        result = await compress_context(
            _make_messages(3), bot, "question",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_compression(self):
        """Mock the LLM call and verify compressed output structure."""
        bot = _bot(enabled=True, threshold=100, keep_turns=1)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "**Key Context**: User asked about things. (see [msg:0]-[msg:5])"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await compress_context(
                _make_messages(10), bot, "What was the first thing?",
            )

        assert result is not None
        compressed_msgs, drilldown = result

        # Should have: header system msg + summary system msg + kept turns + tail user msg
        roles = [m["role"] for m in compressed_msgs]
        assert roles[0] == "system"  # original header
        assert roles[1] == "system"  # summary
        assert "Compressed conversation summary" in compressed_msgs[1]["content"]
        assert roles[-1] == "user"   # tail user message

        # Drilldown should be the older messages
        assert len(drilldown) > 0

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        """If the cheap model call fails, fall through gracefully."""
        bot = _bot(enabled=True, threshold=100, keep_turns=1)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API error"))

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await compress_context(
                _make_messages(10), bot, "question",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_summary_returns_none(self):
        """If the cheap model returns empty, fall through."""
        bot = _bot(enabled=True, threshold=100, keep_turns=1)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await compress_context(
                _make_messages(10), bot, "question",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_message_splitting_preserves_header_and_tail(self):
        """Verify the message split: header system msgs, conversation, tail."""
        bot = _bot(enabled=True, threshold=100, keep_turns=0)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary here."

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        msgs = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "msg1 " + "x" * 300},
            {"role": "assistant", "content": "resp1 " + "y" * 300},
            {"role": "user", "content": "msg2 " + "x" * 300},
            {"role": "assistant", "content": "resp2 " + "y" * 300},
            {"role": "system", "content": "Injected context"},  # trailing system
            {"role": "user", "content": "Current question"},
        ]

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await compress_context(msgs, bot, "Current question")

        assert result is not None
        compressed, drilldown = result
        # Header: first system msg
        assert compressed[0]["content"] == "System prompt"
        # Summary: second msg
        assert "Compressed conversation summary" in compressed[1]["content"]
        # Tail: injected context + current question
        assert compressed[-2]["content"] == "Injected context"
        assert compressed[-1]["content"] == "Current question"

    @pytest.mark.asyncio
    async def test_keep_turns_preserves_recent(self):
        """Verify that keep_turns recent user turns are preserved verbatim."""
        bot = _bot(enabled=True, threshold=100, keep_turns=2)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary."

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        msgs = _make_messages(10)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await compress_context(msgs, bot, "What was discussed?")

        assert result is not None
        compressed, _ = result

        # The kept portion should include the last 2 user turns' messages verbatim
        # (between summary and tail)
        non_system_non_tail = [m for m in compressed[2:-1]]  # skip header+summary and tail
        user_msgs = [m for m in non_system_non_tail if m.get("role") == "user"]
        assert len(user_msgs) >= 2
