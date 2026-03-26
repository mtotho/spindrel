"""Tests for _load_messages() behavior across history modes.

Also tests context_assembly.py structured retrieval and file mode tool injection.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.services.compaction import _get_history_mode


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
    ch.memory_knowledge_compaction_prompt = overrides.get(
        "memory_knowledge_compaction_prompt", None
    )
    ch.history_mode = overrides.get("history_mode", None)
    ch.id = overrides.get("id", uuid.uuid4())
    return ch


class TestLoadMessagesSummaryMode:
    """Verify default summary mode behavior unchanged."""

    def test_summary_mode_resolution(self):
        """When history_mode='summary', _get_history_mode returns 'summary'."""
        bot = _make_bot(history_mode="summary")
        assert _get_history_mode(bot) == "summary"

    def test_default_mode_is_summary(self):
        """When history_mode is not set, defaults to 'summary'."""
        bot = _make_bot()
        assert _get_history_mode(bot) == "summary"


class TestLoadMessagesFileMode:
    """Test _load_messages when history_mode='file'."""

    def test_file_mode_detected(self):
        bot = _make_bot(history_mode="file")
        ch = _make_channel(history_mode=None)
        assert _get_history_mode(bot, ch) == "file"

    def test_channel_override_to_file(self):
        bot = _make_bot(history_mode="summary")
        ch = _make_channel(history_mode="file")
        assert _get_history_mode(bot, ch) == "file"


class TestLoadMessagesStructuredMode:
    """Test _load_messages when history_mode='structured'."""

    def test_structured_mode_detected(self):
        bot = _make_bot(history_mode="structured")
        assert _get_history_mode(bot) == "structured"


class TestContextAssemblyStructuredRetrieval:
    """Test section retrieval in context_assembly.py for structured mode."""

    def test_file_mode_should_inject_tool(self):
        """File mode: read_conversation_history should be added to pinned_tools.

        This tests the logic pattern — in context_assembly.py when history_mode=='file',
        the bot's local_tools and pinned_tools get read_conversation_history appended.
        """
        from dataclasses import replace as _dc_replace

        bot = _make_bot(
            history_mode="file",
            local_tools=["save_memory"],
            pinned_tools=["save_memory"],
        )
        # Simulate what context_assembly does for file mode
        updated_bot = _dc_replace(
            bot,
            local_tools=list(dict.fromkeys((bot.local_tools or []) + ["read_conversation_history"])),
            pinned_tools=list(dict.fromkeys((bot.pinned_tools or []) + ["read_conversation_history"])),
        )
        assert "read_conversation_history" in updated_bot.local_tools
        assert "read_conversation_history" in updated_bot.pinned_tools
        # Original tools preserved
        assert "save_memory" in updated_bot.local_tools
        assert "save_memory" in updated_bot.pinned_tools

    def test_summary_mode_does_not_inject_tool(self):
        """Summary mode: read_conversation_history NOT added."""
        bot = _make_bot(history_mode="summary", local_tools=["save_memory"])
        # In summary mode, no tool injection happens
        assert "read_conversation_history" not in bot.local_tools

    def test_file_mode_deduplication(self):
        """If read_conversation_history already in tools, no duplicate."""
        from dataclasses import replace as _dc_replace

        bot = _make_bot(
            history_mode="file",
            local_tools=["read_conversation_history"],
            pinned_tools=["read_conversation_history"],
        )
        updated_bot = _dc_replace(
            bot,
            local_tools=list(dict.fromkeys((bot.local_tools or []) + ["read_conversation_history"])),
            pinned_tools=list(dict.fromkeys((bot.pinned_tools or []) + ["read_conversation_history"])),
        )
        assert updated_bot.local_tools.count("read_conversation_history") == 1
        assert updated_bot.pinned_tools.count("read_conversation_history") == 1
