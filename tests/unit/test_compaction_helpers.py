"""Unit tests for pure helpers in app.services.compaction."""
from unittest.mock import MagicMock

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.services.compaction import (
    _get_compaction_interval,
    _get_compaction_keep_turns,
    _get_compaction_model,
    _is_compaction_enabled,
    _stringify_message_content,
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
