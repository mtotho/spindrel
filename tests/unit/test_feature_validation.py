"""Unit tests for the feature validation service."""
import pytest

from app.agent.bots import BotConfig
from app.agent.carapaces import _registry as carapace_registry
from app.services.feature_validation import (
    FeatureWarning,
    _check_static_features,
    _check_carapace_requires,
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


def _make_carapace(id: str, *, requires=None, local_tools=None, includes=None):
    return {
        "id": id,
        "name": id,
        "description": None,
        "skills": [],
        "local_tools": local_tools or [],
        "mcp_tools": [],
        "pinned_tools": [],
        "system_prompt_fragment": None,
        "includes": includes or [],
        "delegates": [],
        "tags": [],
        "requires": requires or {},
        "source_path": None,
        "source_type": "manual",
        "content_hash": None,
    }


@pytest.fixture(autouse=True)
def clear_carapace_registry():
    carapace_registry.clear()
    yield
    carapace_registry.clear()


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


class TestCarapaceRequires:
    def test_carapace_with_satisfied_requires(self):
        carapace_registry["mc"] = _make_carapace(
            "mc",
            requires={"tools": ["create_task_card", "move_task_card"]},
            local_tools=["create_task_card", "move_task_card"],
        )
        bot = _make_bot(carapaces=["mc"])
        available = {"create_task_card", "move_task_card", "file"}
        warnings = _check_carapace_requires(bot, available)
        assert warnings == []

    def test_carapace_with_missing_required_tools(self):
        carapace_registry["mc"] = _make_carapace(
            "mc",
            requires={"tools": ["create_task_card", "move_task_card"]},
        )
        bot = _make_bot(carapaces=["mc"])
        available = {"file"}
        warnings = _check_carapace_requires(bot, available)
        assert len(warnings) == 1
        assert warnings[0].feature == "carapace:mc"
        assert "create_task_card" in warnings[0].missing_tools
        assert "move_task_card" in warnings[0].missing_tools

    def test_carapace_without_requires_no_warning(self):
        carapace_registry["simple"] = _make_carapace("simple")
        bot = _make_bot(carapaces=["simple"])
        warnings = _check_carapace_requires(bot, set())
        assert warnings == []

    def test_nested_carapace_requires(self):
        """Requires in included carapaces should also be checked."""
        carapace_registry["parent"] = _make_carapace(
            "parent", includes=["child"]
        )
        carapace_registry["child"] = _make_carapace(
            "child",
            requires={"tools": ["special_tool"]},
        )
        bot = _make_bot(carapaces=["parent"])
        available = {"file"}
        warnings = _check_carapace_requires(bot, available)
        assert len(warnings) == 1
        assert warnings[0].feature == "carapace:child"
        assert "special_tool" in warnings[0].missing_tools

    def test_no_carapaces_no_warnings(self):
        bot = _make_bot(carapaces=[])
        warnings = _check_carapace_requires(bot, set())
        assert warnings == []

    def test_missing_carapace_graceful(self):
        """Referencing a nonexistent carapace should not crash."""
        bot = _make_bot(carapaces=["nonexistent"])
        warnings = _check_carapace_requires(bot, set())
        assert warnings == []


class TestFeatureWarningSerialization:
    def test_to_dict(self):
        w = FeatureWarning(
            bot_id="bot1",
            feature="carapace:mc",
            description="test",
            missing_tools=["tool_a", "tool_b"],
        )
        d = w.to_dict()
        assert d["bot_id"] == "bot1"
        assert d["feature"] == "carapace:mc"
        assert d["missing_tools"] == ["tool_a", "tool_b"]
