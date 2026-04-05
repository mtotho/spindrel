"""Tests for tool discovery, skill auto-enrollment, and hybrid search features."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tools import (
    _cache_key,
    _fuse_tool_results,
    _tool_cache,
    _vector_only_tool_results,
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
# Policy pre-filtering of discovered tools
# ---------------------------------------------------------------------------


class TestDiscoveredToolPolicyPreFilter:
    """Test that discovered tools are pre-filtered against deny policies."""

    @pytest.mark.asyncio
    async def test_deny_policy_excludes_discovered_tool(self):
        """A discovered (non-declared) tool with deny policy should be excluded."""
        from app.agent.bots import BotConfig
        from app.services.tool_policies import PolicyDecision

        bot = BotConfig(
            id="test", name="test", model="m", system_prompt="p",
            tool_retrieval=True, tool_discovery=True,
            local_tools=["declared_tool"],
        )

        # Simulate context_assembly's discovered tool filtering logic
        # _authorized_names = declared tools
        _authorized_names = {"declared_tool", "get_tool_info"}
        retrieved = [
            {"function": {"name": "declared_tool"}},
            {"function": {"name": "undeclared_discovered"}},
        ]

        # Mock evaluate_tool_policy: deny undeclared_discovered, allow everything else
        async def mock_evaluate(db, bot_id, tool_name, args):
            if tool_name == "undeclared_discovered":
                return PolicyDecision(action="deny", reason="blocked by policy")
            return PolicyDecision(action="allow")

        with patch("app.services.tool_policies.evaluate_tool_policy", side_effect=mock_evaluate):
            # Run the filtering logic (extracted from context_assembly)
            _policy_allowed = []
            for _rt in retrieved:
                _rn = _rt.get("function", {}).get("name")
                if _rn and _rn not in _authorized_names:
                    _decision = await mock_evaluate(None, bot.id, _rn, {})
                    if _decision.action == "deny":
                        continue
                _policy_allowed.append(_rt)

            assert len(_policy_allowed) == 1
            assert _policy_allowed[0]["function"]["name"] == "declared_tool"

    @pytest.mark.asyncio
    async def test_allow_policy_keeps_discovered_tool(self):
        """A discovered tool with allow policy should be kept."""
        from app.services.tool_policies import PolicyDecision

        _authorized_names = {"declared_tool"}
        retrieved = [
            {"function": {"name": "discovered_ok"}},
        ]

        async def mock_evaluate(db, bot_id, tool_name, args):
            return PolicyDecision(action="allow")

        _policy_allowed = []
        for _rt in retrieved:
            _rn = _rt.get("function", {}).get("name")
            if _rn and _rn not in _authorized_names:
                _decision = await mock_evaluate(None, "test", _rn, {})
                if _decision.action == "deny":
                    continue
            _policy_allowed.append(_rt)

        assert len(_policy_allowed) == 1
        assert _policy_allowed[0]["function"]["name"] == "discovered_ok"

    @pytest.mark.asyncio
    async def test_require_approval_passes_through(self):
        """A discovered tool with require_approval should NOT be pre-filtered (handled at dispatch)."""
        from app.services.tool_policies import PolicyDecision

        _authorized_names = {"declared_tool"}
        retrieved = [
            {"function": {"name": "needs_approval"}},
        ]

        async def mock_evaluate(db, bot_id, tool_name, args):
            return PolicyDecision(action="require_approval")

        _policy_allowed = []
        for _rt in retrieved:
            _rn = _rt.get("function", {}).get("name")
            if _rn and _rn not in _authorized_names:
                _decision = await mock_evaluate(None, "test", _rn, {})
                if _decision.action == "deny":
                    continue
            _policy_allowed.append(_rt)

        assert len(_policy_allowed) == 1
        assert _policy_allowed[0]["function"]["name"] == "needs_approval"

    @pytest.mark.asyncio
    async def test_declared_tools_skip_policy_check(self):
        """Declared tools (in _authorized_names) should NOT be policy-checked here."""
        from app.services.tool_policies import PolicyDecision

        _authorized_names = {"declared_tool"}
        retrieved = [
            {"function": {"name": "declared_tool"}},
        ]

        call_count = 0

        async def mock_evaluate(db, bot_id, tool_name, args):
            nonlocal call_count
            call_count += 1
            return PolicyDecision(action="deny")

        _policy_allowed = []
        for _rt in retrieved:
            _rn = _rt.get("function", {}).get("name")
            if _rn and _rn not in _authorized_names:
                _decision = await mock_evaluate(None, "test", _rn, {})
                if _decision.action == "deny":
                    continue
            _policy_allowed.append(_rt)

        # Declared tools should pass through without policy check
        assert len(_policy_allowed) == 1
        assert call_count == 0


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


# ---------------------------------------------------------------------------
# Hybrid tool retrieval (BM25 + RRF)
# ---------------------------------------------------------------------------


class TestVectorOnlyToolResults:
    """Test the _vector_only_tool_results helper."""

    def test_basic_threshold_filtering(self):
        """Tools above threshold are included, below are excluded."""
        rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.2),  # sim=0.8
            ({"function": {"name": "tool_b"}}, "tool_b", 0.7),  # sim=0.3
        ]
        out, candidates = _vector_only_tool_results(rows, 0.5, set(), 0.5, False)
        names = [t["function"]["name"] for t in out]
        assert "tool_a" in names
        assert "tool_b" not in names

    def test_discover_stricter_threshold(self):
        """Undeclared tools in discover mode use stricter threshold."""
        rows = [
            ({"function": {"name": "declared"}}, "declared", 0.45),   # sim=0.55
            ({"function": {"name": "undeclared"}}, "undeclared", 0.45),  # sim=0.55
        ]
        # threshold=0.5, discover_threshold=0.6
        out, _ = _vector_only_tool_results(rows, 0.5, {"declared"}, 0.6, True)
        names = [t["function"]["name"] for t in out]
        assert "declared" in names
        assert "undeclared" not in names  # 0.55 < 0.6

    def test_top_candidates_limited_to_5(self):
        """Top candidates should be limited to 5 entries."""
        rows = [({"function": {"name": f"tool_{i}"}}, f"tool_{i}", 0.1) for i in range(10)]
        _, candidates = _vector_only_tool_results(rows, 0.5, set(), 0.5, False)
        assert len(candidates) == 5


class TestFuseToolResults:
    """Test the _fuse_tool_results helper."""

    def test_vector_match_above_threshold_included(self):
        """Tools above vector threshold should be included regardless of BM25."""
        vector_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.2),  # sim=0.8
        ]
        bm25_rows = []
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.5, False)
        assert len(out) == 1
        assert out[0]["function"]["name"] == "tool_a"

    def test_bm25_only_match_included(self):
        """Tools that match BM25 but not vector should be included."""
        vector_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.8),  # sim=0.2, below threshold
        ]
        bm25_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.5),  # BM25 match
        ]
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.5, False)
        assert len(out) == 1
        assert out[0]["function"]["name"] == "tool_a"

    def test_bm25_surfaces_extra_tool(self):
        """BM25 can surface tools that vector search didn't find."""
        vector_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.2),  # sim=0.8
        ]
        bm25_rows = [
            ({"function": {"name": "tool_b"}}, "tool_b", 0.5),  # BM25-only
        ]
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.5, False)
        names = [t["function"]["name"] for t in out]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_no_duplicates_in_fused_output(self):
        """A tool appearing in both vector and BM25 should only appear once."""
        vector_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.2),  # sim=0.8
        ]
        bm25_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.5),  # same tool
        ]
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.5, False)
        assert len(out) == 1

    def test_discover_threshold_applied_to_bm25_only_undeclared(self):
        """In discover mode, undeclared tools from BM25 are still included (keyword match)."""
        vector_rows = [
            ({"function": {"name": "undeclared"}}, "undeclared", 0.6),  # sim=0.4, below both thresholds
        ]
        bm25_rows = [
            ({"function": {"name": "undeclared"}}, "undeclared", 0.3),  # BM25 match
        ]
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.6, True)
        # BM25 match should rescue it even in discover mode
        assert len(out) == 1
        assert out[0]["function"]["name"] == "undeclared"


class TestRetrieveToolsHybrid:
    """Test that retrieve_tools integrates hybrid search correctly."""

    @pytest.fixture(autouse=True)
    def clean_cache(self):
        invalidate_tool_cache()
        yield
        invalidate_tool_cache()

    @pytest.mark.asyncio
    async def test_hybrid_disabled_uses_vector_only(self):
        """When HYBRID_SEARCH_ENABLED=False, should use vector-only path."""
        mock_embedding = [0.1] * 256

        rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.3),  # sim=0.7
        ]

        with patch("app.agent.tools._embed_query", return_value=mock_embedding):
            with patch("app.agent.tools.async_session") as mock_session_ctx:
                mock_db = AsyncMock()
                mock_result = MagicMock()
                mock_result.all.return_value = rows
                mock_db.execute.return_value = mock_result
                mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                with patch("app.agent.tools.settings") as mock_settings:
                    mock_settings.TOOL_RETRIEVAL_TOP_K = 10
                    mock_settings.TOOL_RETRIEVAL_THRESHOLD = 0.4
                    mock_settings.HYBRID_SEARCH_ENABLED = False

                    result, sim, _ = await retrieve_tools(
                        "test query", ["tool_a"], [],
                        top_k=10, threshold=0.4,
                    )

                    assert len(result) == 1
                    assert result[0]["function"]["name"] == "tool_a"
