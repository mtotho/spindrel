"""Tests for carapace + channel override interaction.

Verifies that channel disabled lists are respected even when carapaces
try to re-introduce disabled tools/skills.
"""
from types import SimpleNamespace

from app.agent.bots import BotConfig, SkillConfig
from app.agent.channel_overrides import EffectiveTools, _apply_disabled, resolve_effective_tools


def _bot(**kwargs) -> BotConfig:
    defaults = dict(
        id="test-bot",
        name="Test Bot",
        model="gpt-4",
        system_prompt="",
        local_tools=["file", "exec_command"],
        mcp_servers=["github"],
        client_tools=[],
        pinned_tools=[],
        skills=[SkillConfig(id="testing", mode="pinned")],
        carapaces=["qa"],
    )
    defaults.update(kwargs)
    return BotConfig(**defaults)


def _channel(**kwargs) -> SimpleNamespace:
    defaults = dict(
        local_tools_disabled=None,
        mcp_servers_disabled=None,
        client_tools_disabled=None,
        carapaces_extra=None,
        carapaces_disabled=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestCarapaceChannelOverrides:
    def test_carapaces_extra_adds_to_effective(self):
        bot = _bot(carapaces=["qa"])
        ch = _channel(carapaces_extra=["code-review"])
        eff = resolve_effective_tools(bot, ch)
        assert "qa" in eff.carapaces
        assert "code-review" in eff.carapaces

    def test_carapaces_disabled_removes(self):
        bot = _bot(carapaces=["qa", "code-review"])
        ch = _channel(carapaces_disabled=["qa"])
        eff = resolve_effective_tools(bot, ch)
        assert "qa" not in eff.carapaces
        assert "code-review" in eff.carapaces

    def test_extra_then_disabled_removes_extra(self):
        """Disabled applied after extra — can disable a carapace that was just added."""
        bot = _bot(carapaces=[])
        ch = _channel(carapaces_extra=["qa"], carapaces_disabled=["qa"])
        eff = resolve_effective_tools(bot, ch)
        assert "qa" not in eff.carapaces

    def test_carapaces_extra_deduplicates(self):
        bot = _bot(carapaces=["qa"])
        ch = _channel(carapaces_extra=["qa", "code-review"])
        eff = resolve_effective_tools(bot, ch)
        assert eff.carapaces.count("qa") == 1

    def test_tool_disabled_preserved_through_override(self):
        """Channel tool disabled list is preserved in effective tools."""
        bot = _bot(local_tools=["file", "exec_command", "web_search"])
        ch = _channel(local_tools_disabled=["exec_command"])
        eff = resolve_effective_tools(bot, ch)
        assert "exec_command" not in eff.local_tools
        assert "file" in eff.local_tools

    def test_mutual_exclusion_extra_disabled(self):
        """A carapace in both extra and disabled should end up disabled."""
        bot = _bot(carapaces=["base"])
        ch = _channel(
            carapaces_extra=["qa", "code-review"],
            carapaces_disabled=["code-review"],
        )
        eff = resolve_effective_tools(bot, ch)
        assert "qa" in eff.carapaces
        assert "code-review" not in eff.carapaces
        assert "base" in eff.carapaces

    def test_no_channel_returns_bot_defaults(self):
        bot = _bot(carapaces=["qa", "code-review"])
        eff = resolve_effective_tools(bot, None)
        assert eff.carapaces == ["qa", "code-review"]
        assert eff.local_tools == bot.local_tools

    def test_pinned_tools_always_inherited(self):
        """Pinned tools are never restricted by channel — always inherited from bot."""
        bot = _bot(pinned_tools=["always_on"])
        ch = _channel()
        eff = resolve_effective_tools(bot, ch)
        assert eff.pinned_tools == ["always_on"]


class TestApplyDisabled:
    """Direct tests for _apply_disabled edge cases."""

    def test_none_disabled_returns_copy(self):
        result = _apply_disabled(["a", "b"], None)
        assert result == ["a", "b"]

    def test_empty_disabled_returns_copy(self):
        result = _apply_disabled(["a", "b"], [])
        assert result == ["a", "b"]

    def test_removes_matching_items(self):
        result = _apply_disabled(["a", "b", "c"], ["b"])
        assert result == ["a", "c"]

    def test_disabled_items_not_in_list_are_ignored(self):
        result = _apply_disabled(["a", "b"], ["x", "y"])
        assert result == ["a", "b"]

    def test_empty_bot_list(self):
        result = _apply_disabled([], ["a"])
        assert result == []

    def test_returns_new_list(self):
        original = ["a", "b"]
        result = _apply_disabled(original, None)
        assert result is not original
