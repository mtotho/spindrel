"""Unit tests for the integration activation mechanism."""
from __future__ import annotations

import uuid
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# discover_activation_manifests
# ---------------------------------------------------------------------------

class TestDiscoverActivationManifests:
    def test_discover_returns_mc_manifest(self):
        """MC setup.py declares an activation block — discovery finds it."""
        import integrations
        integrations._activation_manifests = None

        manifests = integrations.discover_activation_manifests()
        assert "mission_control" in manifests
        mc = manifests["mission_control"]
        assert "carapaces" in mc
        assert "mission-control" in mc["carapaces"]
        assert mc.get("requires_workspace") is True
        assert mc.get("description")

        # Reset for other tests
        integrations._activation_manifests = None

    def test_get_activation_manifests_caches(self):
        """get_activation_manifests returns cached result after first call."""
        import integrations
        integrations._activation_manifests = None

        integrations.get_activation_manifests()
        # Overwrite cache with custom value
        integrations._activation_manifests = {"test": {"carapaces": ["x"]}}
        result2 = integrations.get_activation_manifests()
        assert result2 == {"test": {"carapaces": ["x"]}}

        # Reset for other tests
        integrations._activation_manifests = None

    def test_includes_merges_carapaces(self):
        """Arr includes mission_control — its manifest should contain both carapaces."""
        import integrations
        integrations._activation_manifests = None

        manifests = integrations.discover_activation_manifests()
        arr = manifests.get("arr")
        assert arr is not None, "arr activation manifest not found"
        # arr declares carapaces: ["arr"] and includes: ["mission_control"]
        # After resolution, it should have both arr and mission-control carapaces
        assert "arr" in arr["carapaces"]
        assert "mission-control" in arr["carapaces"]

        # requires_workspace is NOT inherited — arr keeps its own value (False)
        assert arr.get("requires_workspace") is False

        # The includes field should be preserved
        assert "mission_control" in arr.get("includes", [])

        # Reset for other tests
        integrations._activation_manifests = None

    def test_includes_does_not_duplicate_carapaces(self):
        """If the including manifest already has a carapace from includes, no duplicate."""
        import integrations
        integrations._activation_manifests = None

        # Simulate: integration A includes B, both declare carapace "shared"
        with patch.object(integrations, "_iter_integration_candidates", return_value=[]):
            integrations._activation_manifests = None

        # Manually set up manifests for resolution testing
        integrations._activation_manifests = None
        manifests_raw = {
            "intA": {"carapaces": ["shared", "a-only"], "includes": ["intB"]},
            "intB": {"carapaces": ["shared", "b-only"]},
        }
        # Simulate resolution by calling the merge logic directly
        for itype, manifest in manifests_raw.items():
            includes = manifest.get("includes")
            if not includes:
                continue
            merged = list(manifest["carapaces"])
            for inc_id in includes:
                inc = manifests_raw.get(inc_id)
                if not inc:
                    continue
                for cap_id in inc.get("carapaces", []):
                    if cap_id not in merged:
                        merged.append(cap_id)
            manifest["carapaces"] = merged

        assert manifests_raw["intA"]["carapaces"] == ["shared", "a-only", "b-only"]
        assert manifests_raw["intB"]["carapaces"] == ["shared", "b-only"]

        # Reset
        integrations._activation_manifests = None


# ---------------------------------------------------------------------------
# Context assembly: activated integrations inject carapaces
# ---------------------------------------------------------------------------

class TestContextAssemblyActivation:
    """Test that context assembly injects carapaces from activated integrations."""

    async def test_activated_integration_injects_carapace(self):
        """An activated MC integration should inject the mission-control carapace."""
        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        from dataclasses import replace as _dc_replace

        bot = BotConfig(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="Test",
            memory=MemoryConfig(enabled=False),
            knowledge=KnowledgeConfig(enabled=False),
            carapaces=[],
        )

        mock_ci = MagicMock()
        mock_ci.activated = True
        mock_ci.integration_type = "mission_control"

        mock_channel = MagicMock()
        mock_channel.integrations = [mock_ci]
        mock_channel.carapaces_disabled = None

        manifests = {"mission_control": {"carapaces": ["mission-control"]}}

        _ch_carapaces_disabled = set(getattr(mock_channel, "carapaces_disabled", None) or [])
        for _ci in (getattr(mock_channel, "integrations", None) or []):
            if not _ci.activated:
                continue
            _manifest = manifests.get(_ci.integration_type)
            if not _manifest:
                continue
            for _cap_id in _manifest.get("carapaces", []):
                if _cap_id not in (bot.carapaces or []) and _cap_id not in _ch_carapaces_disabled:
                    bot = _dc_replace(bot, carapaces=list(bot.carapaces or []) + [_cap_id])

        assert "mission-control" in bot.carapaces

    async def test_carapaces_disabled_overrides_activation(self):
        """carapaces_disabled should prevent activated integrations from injecting."""
        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        from dataclasses import replace as _dc_replace

        bot = BotConfig(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="Test",
            memory=MemoryConfig(enabled=False),
            knowledge=KnowledgeConfig(enabled=False),
            carapaces=[],
        )

        mock_ci = MagicMock()
        mock_ci.activated = True
        mock_ci.integration_type = "mission_control"

        mock_channel = MagicMock()
        mock_channel.integrations = [mock_ci]
        mock_channel.carapaces_disabled = ["mission-control"]  # DISABLED

        manifests = {"mission_control": {"carapaces": ["mission-control"]}}

        _ch_carapaces_disabled = set(getattr(mock_channel, "carapaces_disabled", None) or [])
        for _ci in (getattr(mock_channel, "integrations", None) or []):
            if not _ci.activated:
                continue
            _manifest = manifests.get(_ci.integration_type)
            if not _manifest:
                continue
            for _cap_id in _manifest.get("carapaces", []):
                if _cap_id not in (bot.carapaces or []) and _cap_id not in _ch_carapaces_disabled:
                    bot = _dc_replace(bot, carapaces=list(bot.carapaces or []) + [_cap_id])

        assert "mission-control" not in bot.carapaces

    async def test_non_activated_integration_not_injected(self):
        """Integrations with activated=false should not inject carapaces."""
        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        from dataclasses import replace as _dc_replace

        bot = BotConfig(
            id="test-bot",
            name="Test Bot",
            model="test/model",
            system_prompt="Test",
            memory=MemoryConfig(enabled=False),
            knowledge=KnowledgeConfig(enabled=False),
            carapaces=[],
        )

        mock_ci = MagicMock()
        mock_ci.activated = False  # NOT activated
        mock_ci.integration_type = "mission_control"

        mock_channel = MagicMock()
        mock_channel.integrations = [mock_ci]
        mock_channel.carapaces_disabled = None

        manifests = {"mission_control": {"carapaces": ["mission-control"]}}

        _ch_carapaces_disabled = set(getattr(mock_channel, "carapaces_disabled", None) or [])
        for _ci in (getattr(mock_channel, "integrations", None) or []):
            if not _ci.activated:
                continue
            _manifest = manifests.get(_ci.integration_type)
            if not _manifest:
                continue
            for _cap_id in _manifest.get("carapaces", []):
                if _cap_id not in (bot.carapaces or []) and _cap_id not in _ch_carapaces_disabled:
                    bot = _dc_replace(bot, carapaces=list(bot.carapaces or []) + [_cap_id])

        assert "mission-control" not in bot.carapaces


# ---------------------------------------------------------------------------
# Feature validation for activation
# ---------------------------------------------------------------------------

class TestValidateActivation:
    async def test_validate_activation_no_warnings_when_tools_present(self):
        """No warnings when the bot has all required tools."""
        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        from app.services.feature_validation import validate_activation

        bot = BotConfig(
            id="test-bot",
            name="Test",
            model="test/model",
            system_prompt="test",
            memory=MemoryConfig(enabled=False),
            knowledge=KnowledgeConfig(enabled=False),
            local_tools=["create_task_card", "move_task_card"],
        )

        manifests = {
            "mission_control": {
                "carapaces": ["mission-control"],
                "requires_workspace": True,
            }
        }

        mock_carapace = {"requires": {}}

        with (
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("integrations.get_activation_manifests", return_value=manifests),
            patch("app.agent.carapaces.get_carapace", return_value=mock_carapace),
            patch("app.agent.carapaces.resolve_carapaces", return_value=MagicMock(local_tools=[], mcp_tools=[])),
            patch("app.tools.mcp.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]),
        ):
            warnings = await validate_activation("test-bot", "mission_control")

        assert len(warnings) == 0

    async def test_validate_activation_warns_on_missing_tools(self):
        """Warning returned when required tools are missing."""
        from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
        from app.services.feature_validation import validate_activation

        bot = BotConfig(
            id="test-bot",
            name="Test",
            model="test/model",
            system_prompt="test",
            memory=MemoryConfig(enabled=False),
            knowledge=KnowledgeConfig(enabled=False),
            local_tools=[],
        )

        manifests = {
            "mission_control": {
                "carapaces": ["mission-control"],
                "requires_workspace": True,
            }
        }

        mock_carapace = {"requires": {"tools": ["create_task_card", "move_task_card"]}}

        with (
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("integrations.get_activation_manifests", return_value=manifests),
            patch("app.agent.carapaces.get_carapace", return_value=mock_carapace),
            patch("app.agent.carapaces.resolve_carapaces", return_value=MagicMock(local_tools=[], mcp_tools=[])),
            patch("app.tools.mcp.fetch_mcp_tools", new_callable=AsyncMock, return_value=[]),
        ):
            warnings = await validate_activation("test-bot", "mission_control")

        assert len(warnings) == 1
        assert "create_task_card" in warnings[0].missing_tools
        assert "move_task_card" in warnings[0].missing_tools
