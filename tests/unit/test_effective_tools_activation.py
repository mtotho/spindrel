"""Tests for resolve_effective_tools with activated integration carapace injection.

Verifies that when a channel has activated integrations whose activation
manifests include carapaces, those carapaces are injected into the effective
tools result — and that disabled lists and inactive integrations are respected.
"""
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.bots import BotConfig, SkillConfig
from app.agent.channel_overrides import resolve_effective_tools


def _bot(**kwargs) -> BotConfig:
    defaults = dict(
        id="test-bot",
        name="Test Bot",
        model="gpt-4",
        system_prompt="",
        local_tools=["file"],
        mcp_servers=[],
        client_tools=[],
        pinned_tools=[],
        skills=[],
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
        integrations=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _integration(integration_type: str, activated: bool) -> SimpleNamespace:
    return SimpleNamespace(integration_type=integration_type, activated=activated)


MOCK_MANIFESTS = {
    "mission_control": {
        "carapaces": ["mission-control"],
    },
    "frigate": {
        "carapaces": ["frigate-monitor", "frigate-alerts"],
    },
}


class TestActivationCarapacesInjected:
    """Activated integration adds its carapaces to effective tools."""

    @patch("app.agent.channel_overrides.get_activation_manifests", return_value=MOCK_MANIFESTS, create=True)
    def test_activation_carapaces_injected(self, _mock_manifests):
        bot = _bot(carapaces=["qa"])
        ch = _channel(
            integrations=[_integration("mission_control", activated=True)],
        )

        # Need to patch at the point of import inside the function
        with patch("integrations.get_activation_manifests", return_value=MOCK_MANIFESTS):
            eff = resolve_effective_tools(bot, ch)

        assert "qa" in eff.carapaces, "Bot's own carapace should be preserved"
        assert "mission-control" in eff.carapaces, (
            "Activated integration's carapace should be injected"
        )

    @patch("integrations.get_activation_manifests", return_value=MOCK_MANIFESTS)
    def test_multiple_activated_integrations(self, _mock_manifests):
        bot = _bot(carapaces=[])
        ch = _channel(
            integrations=[
                _integration("mission_control", activated=True),
                _integration("frigate", activated=True),
            ],
        )

        eff = resolve_effective_tools(bot, ch)

        assert "mission-control" in eff.carapaces
        assert "frigate-monitor" in eff.carapaces
        assert "frigate-alerts" in eff.carapaces

    @patch("integrations.get_activation_manifests", return_value=MOCK_MANIFESTS)
    def test_activation_carapaces_deduplicated_with_bot(self, _mock_manifests):
        """If the bot already has a carapace that the activation would inject,
        it should not appear twice."""
        bot = _bot(carapaces=["mission-control"])
        ch = _channel(
            integrations=[_integration("mission_control", activated=True)],
        )

        eff = resolve_effective_tools(bot, ch)

        assert eff.carapaces.count("mission-control") == 1


class TestActivationCarapacesNotInjectedWhenInactive:
    """Non-activated integration does not inject its carapaces."""

    @patch("integrations.get_activation_manifests", return_value=MOCK_MANIFESTS)
    def test_activation_carapaces_not_injected_when_inactive(self, _mock_manifests):
        bot = _bot(carapaces=["qa"])
        ch = _channel(
            integrations=[_integration("mission_control", activated=False)],
        )

        eff = resolve_effective_tools(bot, ch)

        assert "qa" in eff.carapaces, "Bot's own carapace should be preserved"
        assert "mission-control" not in eff.carapaces, (
            "Inactive integration's carapace should NOT be injected"
        )

    @patch("integrations.get_activation_manifests", return_value=MOCK_MANIFESTS)
    def test_mixed_activated_and_inactive(self, _mock_manifests):
        """Only activated integrations contribute carapaces."""
        bot = _bot(carapaces=[])
        ch = _channel(
            integrations=[
                _integration("mission_control", activated=True),
                _integration("frigate", activated=False),
            ],
        )

        eff = resolve_effective_tools(bot, ch)

        assert "mission-control" in eff.carapaces
        assert "frigate-monitor" not in eff.carapaces
        assert "frigate-alerts" not in eff.carapaces

    @patch("integrations.get_activation_manifests", return_value=MOCK_MANIFESTS)
    def test_no_integrations_at_all(self, _mock_manifests):
        """Channel with no integrations list should not crash."""
        bot = _bot(carapaces=["qa"])
        ch = _channel(integrations=[])

        eff = resolve_effective_tools(bot, ch)

        assert eff.carapaces == ["qa"]


class TestActivationCarapacesRespectsDisabled:
    """Activated carapaces can be disabled via carapaces_disabled."""

    @patch("integrations.get_activation_manifests", return_value=MOCK_MANIFESTS)
    def test_activation_carapaces_respects_disabled(self, _mock_manifests):
        bot = _bot(carapaces=["qa"])
        ch = _channel(
            integrations=[_integration("mission_control", activated=True)],
            carapaces_disabled=["mission-control"],
        )

        eff = resolve_effective_tools(bot, ch)

        assert "qa" in eff.carapaces, "Non-disabled carapace should remain"
        assert "mission-control" not in eff.carapaces, (
            "Activated carapace should be removed when in disabled list"
        )

    @patch("integrations.get_activation_manifests", return_value=MOCK_MANIFESTS)
    def test_disable_some_activation_carapaces(self, _mock_manifests):
        """Disabling one carapace from a multi-carapace activation keeps the others."""
        bot = _bot(carapaces=[])
        ch = _channel(
            integrations=[_integration("frigate", activated=True)],
            carapaces_disabled=["frigate-alerts"],
        )

        eff = resolve_effective_tools(bot, ch)

        assert "frigate-monitor" in eff.carapaces, (
            "Non-disabled activation carapace should be present"
        )
        assert "frigate-alerts" not in eff.carapaces, (
            "Disabled activation carapace should be removed"
        )

    @patch("integrations.get_activation_manifests", return_value=MOCK_MANIFESTS)
    def test_disable_bot_and_activation_carapaces(self, _mock_manifests):
        """Disabled list removes both bot carapaces and activation-injected ones."""
        bot = _bot(carapaces=["qa", "code-review"])
        ch = _channel(
            integrations=[_integration("mission_control", activated=True)],
            carapaces_disabled=["qa", "mission-control"],
        )

        eff = resolve_effective_tools(bot, ch)

        assert "qa" not in eff.carapaces
        assert "mission-control" not in eff.carapaces
        assert "code-review" in eff.carapaces
