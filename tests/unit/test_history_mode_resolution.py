"""Tests for _get_history_mode() and its effect on compaction routing."""
import uuid
from unittest.mock import MagicMock

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
    ch.history_mode = overrides.get("history_mode", None)
    ch.compaction_model = overrides.get("compaction_model", None)
    ch.compaction_interval = overrides.get("compaction_interval", None)
    ch.compaction_keep_turns = overrides.get("compaction_keep_turns", None)
    ch.context_compaction = overrides.get("context_compaction", True)
    ch.memory_knowledge_compaction_prompt = overrides.get(
        "memory_knowledge_compaction_prompt", None
    )
    ch.id = overrides.get("id", uuid.uuid4())
    return ch


class TestGetHistoryMode:
    def test_channel_overrides_bot(self):
        bot = _make_bot(history_mode="summary")
        ch = _make_channel(history_mode="file")
        assert _get_history_mode(bot, ch) == "file"

    def test_channel_none_inherits_bot(self):
        bot = _make_bot(history_mode="structured")
        ch = _make_channel(history_mode=None)
        assert _get_history_mode(bot, ch) == "structured"

    def test_no_channel_uses_bot(self):
        bot = _make_bot(history_mode="file")
        assert _get_history_mode(bot, None) == "file"

    def test_both_none_defaults_file(self):
        bot = _make_bot(history_mode=None)
        ch = _make_channel(history_mode=None)
        assert _get_history_mode(bot, ch) == "file"

    def test_bot_default_is_file(self):
        bot = _make_bot()  # no history_mode override — defaults to "file"
        assert _get_history_mode(bot) == "file"

    def test_empty_string_channel_falls_through(self):
        """Empty string is falsy, should fall through to bot."""
        bot = _make_bot(history_mode="structured")
        ch = _make_channel(history_mode="")
        assert _get_history_mode(bot, ch) == "structured"

    def test_channel_structured(self):
        bot = _make_bot(history_mode="summary")
        ch = _make_channel(history_mode="structured")
        assert _get_history_mode(bot, ch) == "structured"

    def test_bot_file_no_channel(self):
        bot = _make_bot(history_mode="file")
        assert _get_history_mode(bot) == "file"
