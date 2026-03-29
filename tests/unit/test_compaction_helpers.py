"""Unit tests for pure helpers in app.services.compaction."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.services.compaction import (
    _get_compaction_interval,
    _get_compaction_keep_turns,
    _get_compaction_model,
    _is_compaction_enabled,
    _messages_for_summary,
    _stringify_message_content,
    format_section_index,
)


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
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_channel(**overrides):
    ch = MagicMock()
    ch.compaction_model = overrides.get("compaction_model", None)
    ch.compaction_interval = overrides.get("compaction_interval", None)
    ch.compaction_keep_turns = overrides.get("compaction_keep_turns", None)
    ch.context_compaction = overrides.get("context_compaction", True)
    ch.memory_knowledge_compaction_prompt = overrides.get("memory_knowledge_compaction_prompt", None)
    return ch


# ---------------------------------------------------------------------------
# _stringify_message_content
# ---------------------------------------------------------------------------

class TestStringifyMessageContent:
    def test_string_passthrough(self):
        assert _stringify_message_content("hello") == "hello"

    def test_none(self):
        assert _stringify_message_content(None) == ""

    def test_list_text_parts(self):
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "world"},
        ]
        assert _stringify_message_content(content) == "Hello world"

    def test_list_image_url(self):
        content = [{"type": "image_url", "image_url": {"url": "data:..."}}]
        assert _stringify_message_content(content) == "[image]"

    def test_list_input_audio(self):
        content = [{"type": "input_audio", "input_audio": {"data": "..."}}]
        assert _stringify_message_content(content) == "[audio]"

    def test_mixed_list(self):
        content = [
            {"type": "text", "text": "Look:"},
            {"type": "image_url", "image_url": {"url": "data:..."}},
        ]
        result = _stringify_message_content(content)
        assert "Look:" in result
        assert "[image]" in result

    def test_empty_list(self):
        assert _stringify_message_content([]) == "[multimodal message]"

    def test_json_encoded_multimodal(self):
        import json
        content = json.dumps([{"type": "text", "text": "decoded"}])
        result = _stringify_message_content(content)
        assert "decoded" in result


# ---------------------------------------------------------------------------
# _get_compaction_model
# ---------------------------------------------------------------------------

class TestGetCompactionModel:
    def test_channel_override(self):
        bot = _make_bot(compaction_model="bot-model")
        ch = _make_channel(compaction_model="channel-model")
        assert _get_compaction_model(bot, ch) == "channel-model"

    def test_bot_override(self):
        bot = _make_bot(compaction_model="bot-model")
        assert _get_compaction_model(bot) == "bot-model"

    def test_settings_override(self):
        bot = _make_bot(compaction_model=None)
        # When bot has no compaction_model, falls to settings.COMPACTION_MODEL
        from app.config import settings
        assert _get_compaction_model(bot) == settings.COMPACTION_MODEL

    def test_fallback_to_bot_model(self):
        from unittest.mock import patch
        bot = _make_bot(compaction_model=None)
        with patch("app.services.compaction.settings") as mock_settings:
            mock_settings.COMPACTION_MODEL = ""
            assert _get_compaction_model(bot) == "gpt-4"

    def test_channel_none_falls_to_bot(self):
        bot = _make_bot(compaction_model="bot-model")
        ch = _make_channel(compaction_model=None)
        assert _get_compaction_model(bot, ch) == "bot-model"


# ---------------------------------------------------------------------------
# _get_compaction_interval
# ---------------------------------------------------------------------------

class TestGetCompactionInterval:
    def test_channel_override(self):
        bot = _make_bot(compaction_interval=10)
        ch = _make_channel(compaction_interval=5)
        assert _get_compaction_interval(bot, ch) == 5

    def test_bot_value(self):
        bot = _make_bot(compaction_interval=8)
        assert _get_compaction_interval(bot) == 8

    def test_channel_none_falls_to_bot(self):
        bot = _make_bot(compaction_interval=8)
        ch = _make_channel(compaction_interval=None)
        assert _get_compaction_interval(bot, ch) == 8


# ---------------------------------------------------------------------------
# _get_compaction_keep_turns
# ---------------------------------------------------------------------------

class TestGetCompactionKeepTurns:
    def test_channel_override(self):
        bot = _make_bot(compaction_keep_turns=4)
        ch = _make_channel(compaction_keep_turns=2)
        assert _get_compaction_keep_turns(bot, ch) == 2

    def test_bot_value(self):
        bot = _make_bot(compaction_keep_turns=6)
        assert _get_compaction_keep_turns(bot) == 6


# ---------------------------------------------------------------------------
# _is_compaction_enabled
# ---------------------------------------------------------------------------

class TestIsCompactionEnabled:
    def test_channel_overrides(self):
        bot = _make_bot(context_compaction=True)
        ch = _make_channel(context_compaction=False)
        assert _is_compaction_enabled(bot, ch) is False

    def test_bot_level(self):
        bot = _make_bot(context_compaction=True)
        assert _is_compaction_enabled(bot) is True

    def test_bot_disabled(self):
        bot = _make_bot(context_compaction=False)
        assert _is_compaction_enabled(bot) is False


# ---------------------------------------------------------------------------
# _messages_for_summary — tool→assistant alignment
# ---------------------------------------------------------------------------

class TestMessagesForSummaryToolAlignment:
    """The period alignment bug: tool messages become assistant messages in
    _messages_for_summary output.  active_timestamps must include tool messages
    too, otherwise the timestamp index goes out of bounds."""

    def test_tool_messages_become_assistant(self):
        """Tool messages are converted to assistant role with compact summary."""
        msgs = [
            {"role": "user", "content": "search for X"},
            {"role": "assistant", "content": "I'll search.", "tool_calls": [
                {"function": {"name": "web_search", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "search results here", "name": "web_search"},
            {"role": "assistant", "content": "Here's what I found."},
        ]
        result = _messages_for_summary(msgs)
        roles = [m["role"] for m in result]
        # tool becomes assistant, so we get: user, assistant, assistant(tool), assistant
        assert roles == ["user", "assistant", "assistant", "assistant"]
        assert "Tool result from web_search" in result[2]["content"]

    def test_tool_count_matches_active_messages(self):
        """The number of active messages (user+assistant+tool-as-assistant)
        from _messages_for_summary must equal the count when we include
        tool in active_timestamps."""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "tool_calls": [
                {"function": {"name": "get_time", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "12:00", "name": "get_time"},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "welcome"},
        ]
        conversation = _messages_for_summary(msgs)
        ua_count = sum(1 for m in conversation if m["role"] in ("user", "assistant"))

        # Simulate the fixed active_timestamps logic (includes tool)
        ts_count = sum(1 for m in msgs if m["role"] in ("user", "assistant", "tool"))
        assert ua_count == ts_count, (
            f"conversation has {ua_count} u/a messages but timestamps has {ts_count} entries — "
            "period alignment will fail"
        )

    def test_tool_count_mismatch_without_tool_in_timestamps(self):
        """Demonstrates the bug: if timestamps only count user+assistant
        (not tool), the count is less than conversation's u/a count."""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "tool_calls": [
                {"function": {"name": "get_time", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "12:00", "name": "get_time"},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "welcome"},
        ]
        conversation = _messages_for_summary(msgs)
        ua_count = sum(1 for m in conversation if m["role"] in ("user", "assistant"))

        # OLD buggy logic: only counted user+assistant, not tool
        old_ts_count = sum(1 for m in msgs if m["role"] in ("user", "assistant"))
        assert old_ts_count < ua_count, (
            "Without tool in timestamps, count is short → period_end goes out of bounds"
        )

    def test_heartbeat_excluded_from_both(self):
        """Heartbeat messages must be excluded from both conversation and timestamps."""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "user", "content": "heartbeat ping", "_metadata": {"is_heartbeat": True}},
            {"role": "assistant", "content": "hi"},
        ]
        conversation = _messages_for_summary(msgs)
        assert len(conversation) == 2  # heartbeat excluded

        # Timestamps should also skip heartbeat
        ts_count = sum(
            1 for m in msgs
            if m["role"] in ("user", "assistant", "tool")
            and not (m.get("_metadata") or {}).get("is_heartbeat")
        )
        assert ts_count == 2


# ---------------------------------------------------------------------------
# format_section_index
# ---------------------------------------------------------------------------

class TestFormatSectionIndex:
    """Tests for format_section_index including the total_sections parameter."""

    @staticmethod
    def _make_section(sequence=1, title="Test", summary="A summary.",
                      period_start=None, period_end=None, tags=None,
                      message_count=4):
        s = MagicMock()
        s.sequence = sequence
        s.title = title
        s.summary = summary
        s.period_start = period_start or datetime(2026, 3, 20, tzinfo=timezone.utc)
        s.period_end = period_end or datetime(2026, 3, 20, tzinfo=timezone.utc)
        s.tags = tags or []
        s.message_count = message_count
        return s

    def test_standard_format(self):
        sections = [self._make_section(sequence=2, title="Second"), self._make_section(sequence=1, title="First")]
        result = format_section_index(sections)
        assert "#2: Second" in result
        assert "#1: First" in result
        assert "A summary." in result

    def test_compact_format(self):
        sections = [self._make_section(sequence=1, title="Chat")]
        result = format_section_index(sections, verbosity="compact")
        assert "- #1: Chat" in result
        # compact should NOT include summary
        assert "A summary." not in result

    def test_detailed_format(self):
        sections = [self._make_section(sequence=1, title="Chat", message_count=8)]
        result = format_section_index(sections, verbosity="detailed")
        assert "8 msgs" in result

    def test_total_sections_not_shown_when_equal(self):
        """When total == displayed, no 'Showing N of M' message."""
        sections = [self._make_section(sequence=1)]
        result = format_section_index(sections, total_sections=1)
        assert "Showing" not in result

    def test_total_sections_shown_when_greater(self):
        """When total > displayed, show 'Showing N most recent of M'."""
        sections = [self._make_section(sequence=10), self._make_section(sequence=9)]
        result = format_section_index(sections, total_sections=10)
        assert "Showing 2 most recent of 10 total sections" in result
        assert "search:<query>" in result  # hint to search older

    def test_total_sections_none(self):
        """When total_sections is None, no 'Showing' message."""
        sections = [self._make_section(sequence=1)]
        result = format_section_index(sections, total_sections=None)
        assert "Showing" not in result

    def test_total_sections_zero(self):
        """total_sections=0 (falsy) should not show 'Showing' message."""
        sections = [self._make_section(sequence=1)]
        result = format_section_index(sections, total_sections=0)
        assert "Showing" not in result

    def test_tags_included(self):
        sections = [self._make_section(sequence=1, tags=["debug", "config"])]
        result = format_section_index(sections)
        assert "[debug, config]" in result

    def test_header_instructions(self):
        sections = [self._make_section()]
        result = format_section_index(sections)
        assert "read_conversation_history" in result
        assert "search:<query>" in result
        assert "messages:<query>" in result
        assert "tool:<id>" in result
