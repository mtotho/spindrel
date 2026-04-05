"""Tests for tool discovery and skill auto-enrollment features."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tools import (
    _cache_key,
    _tool_cache,
    invalidate_tool_cache,
    retrieve_tools,
)


# ---------------------------------------------------------------------------
# retrieve_tools with discover_all
# ---------------------------------------------------------------------------


class TestRetrieveToolsDiscoverAll:
    """Test the discover_all parameter on retrieve_tools()."""

    @pytest.fixture(autouse=True)
    def clean_cache(self):
        invalidate_tool_cache()
        yield
        invalidate_tool_cache()

    def test_cache_key_includes_discover_flag(self):
        """discover_all should produce a different cache key."""
        base = _cache_key("hello", ["a"], ["s1"], 10, 0.35)
        # The discover flag is appended as "d"
        assert base + "d" != base

    @pytest.mark.asyncio
    async def test_discover_all_cache_separate_from_normal(self):
        """discover_all=True and discover_all=False should use different cache entries."""
        ck_normal = _cache_key("q", ["a"], ["s"], 10, 0.4)
        ck_discover = ck_normal + "d"

        _tool_cache[ck_normal] = (time.monotonic(), [{"function": {"name": "normal"}}], 0.8, [])
        _tool_cache[ck_discover] = (time.monotonic(), [{"function": {"name": "discovered"}}], 0.9, [])

        with patch("app.agent.tools._embed_query") as mock_embed:
            # Normal mode should return "normal"
            result, sim, _ = await retrieve_tools("q", ["a"], ["s"], top_k=10, threshold=0.4, discover_all=False)
            assert result[0]["function"]["name"] == "normal"

            # Discover mode should return "discovered"
            result, sim, _ = await retrieve_tools("q", ["a"], ["s"], top_k=10, threshold=0.4, discover_all=True)
            assert result[0]["function"]["name"] == "discovered"

        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_discover_all_empty_tools_still_queries(self):
        """When local_tool_names is empty but discover_all=True, should still search all local tools."""
        mock_embedding = [0.1] * 256  # dummy embedding

        with patch("app.agent.tools._embed_query", return_value=mock_embedding):
            with patch("app.agent.tools.async_session") as mock_session_ctx:
                mock_db = AsyncMock()
                mock_result = MagicMock()
                mock_result.all.return_value = [
                    ({"function": {"name": "discovered_tool"}}, "discovered_tool", 0.3)  # distance=0.3 → sim=0.7
                ]
                mock_db.execute.return_value = mock_result
                mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                result, sim, _ = await retrieve_tools(
                    "test query", [], [],  # empty declared tools
                    top_k=10, threshold=0.4, discover_all=True,
                )

                # Should have found the tool
                assert len(result) == 1
                assert result[0]["function"]["name"] == "discovered_tool"

    @pytest.mark.asyncio
    async def test_discover_all_false_empty_tools_returns_empty(self):
        """When local_tool_names is empty and discover_all=False, should return nothing."""
        result, sim, _ = await retrieve_tools(
            "test query", [], [],
            top_k=10, threshold=0.4, discover_all=False,
        )
        assert result == []
        assert sim == 0.0

    @pytest.mark.asyncio
    async def test_discover_threshold_stricter_for_undeclared(self):
        """Undeclared tools should use a stricter threshold (threshold + 0.1)."""
        mock_embedding = [0.1] * 256

        # Two tools: one declared (tool_a), one undeclared (tool_b)
        # Both at similarity 0.5 (distance 0.5)
        # With threshold 0.45, declared passes (0.5 >= 0.45), undeclared needs 0.55 and fails
        rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.5),  # sim=0.5
            ({"function": {"name": "tool_b"}}, "tool_b", 0.5),  # sim=0.5
        ]

        with patch("app.agent.tools._embed_query", return_value=mock_embedding):
            with patch("app.agent.tools.async_session") as mock_session_ctx:
                mock_db = AsyncMock()
                mock_result = MagicMock()
                mock_result.all.return_value = rows
                mock_db.execute.return_value = mock_result
                mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                result, sim, _ = await retrieve_tools(
                    "test query", ["tool_a"], [],
                    top_k=10, threshold=0.45, discover_all=True,
                )

                names = [t["function"]["name"] for t in result]
                # tool_a passes at 0.5 >= 0.45
                assert "tool_a" in names
                # tool_b fails: 0.5 < 0.55 (stricter threshold)
                assert "tool_b" not in names

    @pytest.mark.asyncio
    async def test_discover_threshold_capped_at_065(self):
        """Discover threshold should be capped at 0.65 even if base threshold is high."""
        mock_embedding = [0.1] * 256

        # With threshold 0.6, discover threshold would be 0.7 but capped to 0.65
        # Tool at sim=0.66 should pass
        rows = [
            ({"function": {"name": "found_tool"}}, "found_tool", 0.34),  # sim=0.66
        ]

        with patch("app.agent.tools._embed_query", return_value=mock_embedding):
            with patch("app.agent.tools.async_session") as mock_session_ctx:
                mock_db = AsyncMock()
                mock_result = MagicMock()
                mock_result.all.return_value = rows
                mock_db.execute.return_value = mock_result
                mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                result, sim, _ = await retrieve_tools(
                    "test query", [], [],
                    top_k=10, threshold=0.6, discover_all=True,
                )

                # 0.66 >= 0.65 (capped) → should be found
                assert len(result) == 1
                assert result[0]["function"]["name"] == "found_tool"


# ---------------------------------------------------------------------------
# BotConfig tool_discovery field
# ---------------------------------------------------------------------------


class TestBotConfigToolDiscovery:
    """Test that tool_discovery field is properly loaded."""

    def test_default_is_true(self):
        from app.agent.bots import BotConfig
        bot = BotConfig(id="t", name="t", model="m", system_prompt="p")
        assert bot.tool_discovery is True

    def test_can_be_set_false(self):
        from app.agent.bots import BotConfig
        bot = BotConfig(id="t", name="t", model="m", system_prompt="p", tool_discovery=False)
        assert bot.tool_discovery is False

    def test_yaml_loader_parses_field(self):
        from app.agent.bots import _yaml_data_to_row_dict
        data = {
            "id": "test",
            "name": "Test",
            "model": "test-model",
            "system_prompt": "Hello",
            "tool_discovery": False,
        }
        row_data = _yaml_data_to_row_dict(data)
        assert row_data["tool_discovery"] is False

    def test_yaml_loader_defaults_true(self):
        from app.agent.bots import _yaml_data_to_row_dict
        data = {
            "id": "test",
            "name": "Test",
            "model": "test-model",
            "system_prompt": "Hello",
        }
        row_data = _yaml_data_to_row_dict(data)
        assert row_data["tool_discovery"] is True


# ---------------------------------------------------------------------------
# Skill auto-enrollment
# ---------------------------------------------------------------------------


class TestCoreSkillAutoEnrollment:
    """Test that core skills are auto-enrolled for all bots."""

    @pytest.mark.asyncio
    async def test_get_core_skill_ids_uses_cache(self):
        """Second call within TTL should use cache, not DB."""
        import app.agent.context_assembly as ctx_mod

        ctx_mod._core_skill_cache = (time.monotonic(), ["cached_skill"])

        result = await ctx_mod._get_core_skill_ids()
        assert result == ["cached_skill"]

        # Clean up
        ctx_mod._core_skill_cache = None

    @pytest.mark.asyncio
    async def test_get_core_skill_ids_expired_cache(self):
        """Expired cache should not be used."""
        import app.agent.context_assembly as ctx_mod

        ctx_mod._core_skill_cache = (time.monotonic() - 120, ["stale_skill"])  # expired

        with patch("app.db.engine.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = ["fresh_skill"]
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await ctx_mod._get_core_skill_ids()
            assert result == ["fresh_skill"]

        ctx_mod._core_skill_cache = None

    def test_invalidate_clears_caches(self):
        """invalidate_skill_auto_enroll_cache should clear both caches."""
        import app.agent.context_assembly as ctx_mod

        ctx_mod._core_skill_cache = (time.monotonic(), ["x"])
        ctx_mod._integration_skill_cache["slack"] = (time.monotonic(), ["y"])

        ctx_mod.invalidate_skill_auto_enroll_cache()

        assert ctx_mod._core_skill_cache is None
        assert ctx_mod._integration_skill_cache == {}


class TestIntegrationSkillAutoEnrollment:
    """Test that integration skills are auto-enrolled when activated."""

    @pytest.mark.asyncio
    async def test_get_integration_skill_ids_caches_per_type(self):
        """Each integration type has its own cache entry."""
        import app.agent.context_assembly as ctx_mod

        now = time.monotonic()
        ctx_mod._integration_skill_cache["slack"] = (now, ["slack_skill"])
        ctx_mod._integration_skill_cache["github"] = (now, ["github_skill"])

        slack_result = await ctx_mod._get_integration_skill_ids("slack")
        github_result = await ctx_mod._get_integration_skill_ids("github")

        assert slack_result == ["slack_skill"]
        assert github_result == ["github_skill"]

        # Clean up
        ctx_mod._integration_skill_cache.clear()

    @pytest.mark.asyncio
    async def test_get_integration_skill_ids_expired_cache(self):
        """Expired cache should query DB again."""
        import app.agent.context_assembly as ctx_mod

        ctx_mod._integration_skill_cache["slack"] = (time.monotonic() - 120, ["stale"])

        with patch("app.db.engine.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = ["fresh_slack_skill"]
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await ctx_mod._get_integration_skill_ids("slack")
            assert result == ["fresh_slack_skill"]

        ctx_mod._integration_skill_cache.clear()
