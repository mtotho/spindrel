"""Unit tests for the feature validation service."""
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.bots import BotConfig
from app.services.feature_validation import (
    FeatureWarning,
    _check_static_features,
    validate_features,
)


def _make_bot(**kwargs) -> BotConfig:
    """Create a minimal BotConfig with defaults."""
    defaults = {
        "id": "test-bot",
        "name": "Test Bot",
        "model": "gpt-4o",
        "system_prompt": "You are helpful.",
        "local_tools": [],
        "client_tools": [],
        "mcp_servers": [],
        "pinned_tools": [],
        "carapaces": [],
        "memory_scheme": None,
        "history_mode": "file",
    }
    defaults.update(kwargs)
    return BotConfig(**defaults)

class TestStaticFeatures:
    def test_bot_with_all_tools_no_warnings(self):
        bot = _make_bot(
            memory_scheme="workspace-files",
            history_mode="file",
            local_tools=["file", "search_memory", "get_memory_file", "read_conversation_history"],
        )
        available = set(bot.local_tools)
        warnings = _check_static_features(bot, available)
        assert warnings == []

    def test_bot_missing_memory_scheme_tools(self):
        bot = _make_bot(
            memory_scheme="workspace-files",
            history_mode=None,
            local_tools=["file"],
        )
        available = set(bot.local_tools)
        warnings = _check_static_features(bot, available)
        assert len(warnings) == 1
        w = warnings[0]
        assert w.feature == "memory_scheme:workspace-files"
        assert "search_memory" in w.missing_tools
        assert "get_memory_file" in w.missing_tools

    def test_bot_missing_history_mode_tools(self):
        bot = _make_bot(
            history_mode="file",
            local_tools=[],
        )
        available = set(bot.local_tools)
        warnings = _check_static_features(bot, available)
        assert len(warnings) == 1
        assert warnings[0].feature == "history_mode:file"
        assert "read_conversation_history" in warnings[0].missing_tools

    def test_no_memory_scheme_no_warning(self):
        """Bot without workspace-files scheme should not warn about memory tools."""
        bot = _make_bot(memory_scheme=None, local_tools=[])
        warnings = _check_static_features(bot, set())
        # Only history_mode:file warning expected
        features = [w.feature for w in warnings]
        assert "memory_scheme:workspace-files" not in features

    def test_empty_bot_minimal_warnings(self):
        """An empty bot with default history_mode='file' should warn about history tools."""
        bot = _make_bot(local_tools=[], history_mode="file")
        warnings = _check_static_features(bot, set())
        assert len(warnings) == 1
        assert warnings[0].feature == "history_mode:file"

class TestToolDiscoverySuppressesWarnings:
    """Tool discovery makes all registered local tools available, suppressing false positives."""

    @pytest.mark.asyncio
    async def test_discovery_on_no_false_positives(self):
        """When tool_discovery=True, registered tools count as available."""
        bot = _make_bot(
            local_tools=[],  # declares nothing
            memory_scheme="workspace-files",
            history_mode="file",
        )
        bot.tool_discovery = True

        # Registry has all required tools
        fake_registry = {
            "file": {}, "search_memory": {}, "get_memory_file": {},
            "read_conversation_history": {},
        }

        with (
            patch("app.agent.bots.list_bots", return_value=[bot]),
            patch("app.tools.registry._tools", fake_registry),
        ):
            warnings = await validate_features()
            assert warnings == [], f"Expected no warnings but got: {[w.to_dict() for w in warnings]}"

    @pytest.mark.asyncio
    async def test_discovery_off_warns_for_missing(self):
        """When tool_discovery=False, only declared tools count."""
        bot = _make_bot(
            local_tools=[],
            memory_scheme="workspace-files",
            history_mode="file",
        )
        bot.tool_discovery = False

        fake_registry = {
            "file": {}, "search_memory": {}, "get_memory_file": {},
            "read_conversation_history": {},
        }

        with (
            patch("app.agent.bots.list_bots", return_value=[bot]),
            patch("app.tools.registry._tools", fake_registry),
        ):
            warnings = await validate_features()
            assert len(warnings) == 2  # memory + history


class TestFeatureWarningSerialization:
    def test_to_dict(self):
        w = FeatureWarning(
            bot_id="bot1",
            feature="activation:integration-x",
            description="test",
            missing_tools=["tool_a", "tool_b"],
        )
        d = w.to_dict()
        assert d["bot_id"] == "bot1"
        assert d["feature"] == "activation:integration-x"
        assert d["missing_tools"] == ["tool_a", "tool_b"]
