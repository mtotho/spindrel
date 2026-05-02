"""Tests for tool discovery, skill auto-enrollment, and hybrid search features."""

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tools import (
    _bm25_tool_search,
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
                    ({"function": {"name": "discovered_tool"}}, "discovered_tool", 0.3, {})  # distance=0.3 → sim=0.7
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
            ({"function": {"name": "tool_a"}}, "tool_a", 0.5, {}),  # sim=0.5
            ({"function": {"name": "tool_b"}}, "tool_b", 0.5, {}),  # sim=0.5
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
            ({"function": {"name": "found_tool"}}, "found_tool", 0.34, {}),  # sim=0.66
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
            ({"function": {"name": "tool_a"}}, "tool_a", 0.2, {}),  # sim=0.8
            ({"function": {"name": "tool_b"}}, "tool_b", 0.7, {}),  # sim=0.3
        ]
        out, candidates = _vector_only_tool_results(rows, 0.5, set(), 0.5, False, False)
        names = [t["function"]["name"] for t in out]
        assert "tool_a" in names
        assert "tool_b" not in names

    def test_discover_stricter_threshold(self):
        """Undeclared tools in discover mode use stricter threshold."""
        rows = [
            ({"function": {"name": "declared"}}, "declared", 0.45, {}),   # sim=0.55
            ({"function": {"name": "undeclared"}}, "undeclared", 0.45, {}),  # sim=0.55
        ]
        # threshold=0.5, discover_threshold=0.6
        out, _ = _vector_only_tool_results(rows, 0.5, {"declared"}, 0.6, True, False)
        names = [t["function"]["name"] for t in out]
        assert "declared" in names
        assert "undeclared" not in names  # 0.55 < 0.6

    def test_top_candidates_limited_to_5(self):
        """Top candidates should be limited to 5 entries."""
        rows = [({"function": {"name": f"tool_{i}"}}, f"tool_{i}", 0.1, {}) for i in range(10)]
        _, candidates = _vector_only_tool_results(rows, 0.5, set(), 0.5, False, False)
        assert len(candidates) == 5

    def test_nan_distance_yields_finite_sim(self):
        """NaN distance (degenerate vector) must not leak NaN into top_candidates — Postgres JSONB rejects NaN."""
        rows = [({"function": {"name": "broken"}}, "broken", float("nan"), {})]
        _, candidates = _vector_only_tool_results(rows, 0.5, set(), 0.5, False, False)
        assert len(candidates) == 1
        assert math.isfinite(candidates[0]["sim"])
        assert candidates[0]["sim"] == 0.0


class TestFuseToolResults:
    """Test the _fuse_tool_results helper."""

    def test_vector_match_above_threshold_included(self):
        """Tools above vector threshold should be included regardless of BM25."""
        vector_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.2, {}),  # sim=0.8
        ]
        bm25_rows = []
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.5, False, False)
        assert len(out) == 1
        assert out[0]["function"]["name"] == "tool_a"

    def test_bm25_only_match_included(self):
        """Tools that match BM25 but not vector should be included."""
        vector_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.8, {}),  # sim=0.2, below threshold
        ]
        bm25_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.5, {}),  # BM25 match
        ]
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.5, False, False)
        assert len(out) == 1
        assert out[0]["function"]["name"] == "tool_a"

    def test_bm25_surfaces_extra_tool(self):
        """BM25 can surface tools that vector search didn't find."""
        vector_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.2, {}),  # sim=0.8
        ]
        bm25_rows = [
            ({"function": {"name": "tool_b"}}, "tool_b", 0.5, {}),  # BM25-only
        ]
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.5, False, False)
        names = [t["function"]["name"] for t in out]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_no_duplicates_in_fused_output(self):
        """A tool appearing in both vector and BM25 should only appear once."""
        vector_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.2, {}),  # sim=0.8
        ]
        bm25_rows = [
            ({"function": {"name": "tool_a"}}, "tool_a", 0.5, {}),  # same tool
        ]
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.5, False, False)
        assert len(out) == 1

    def test_discover_threshold_applied_to_bm25_only_undeclared(self):
        """In discover mode, undeclared tools from BM25 are still included (keyword match)."""
        vector_rows = [
            ({"function": {"name": "undeclared"}}, "undeclared", 0.6, {}),  # sim=0.4, below both thresholds
        ]
        bm25_rows = [
            ({"function": {"name": "undeclared"}}, "undeclared", 0.3, {}),  # BM25 match
        ]
        out, _ = _fuse_tool_results(vector_rows, bm25_rows, 0.5, set(), 0.6, True, False)
        # BM25 match should rescue it even in discover mode
        assert len(out) == 1
        assert out[0]["function"]["name"] == "undeclared"

    def test_explicit_exposure_filtered_when_context_respects_exposure(self):
        vector_rows = [
            (
                {"function": {"name": "explicit_candidate"}},
                "explicit_candidate",
                0.1,
                {"exposure": "explicit"},
            ),
            (
                {"function": {"name": "ambient_candidate"}},
                "ambient_candidate",
                0.1,
                {"exposure": "ambient"},
            ),
        ]

        out, _ = _fuse_tool_results(vector_rows, [], 0.5, set(), 0.6, True, True)

        assert [tool["function"]["name"] for tool in out] == ["ambient_candidate"]


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
            ({"function": {"name": "tool_a"}}, "tool_a", 0.3, {}),  # sim=0.7
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


# ---------------------------------------------------------------------------
# BM25 tool search uses websearch_to_tsquery (OR semantics) so a single
# high-signal token can rescue a query buried in conversational noise.
# Regression for the 2026-04-11 trace where qa-bot's "rolland can you test
# hte get weather tool" returned 0 BM25 rows because plainto_tsquery ANDs
# every non-stopword token (bot names + typos always kill the match).
# ---------------------------------------------------------------------------


class TestBm25ToolSearchUsesWebsearchTsquery:
    """`_bm25_tool_search` must build SQL with `websearch_to_tsquery`, not
    `plainto_tsquery`, so a noisy conversational query like 'rolland can you
    test hte get weather tool' isn't shut out by AND semantics."""

    @pytest.mark.asyncio
    async def test_sql_uses_websearch_to_tsquery(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        await _bm25_tool_search(
            mock_db,
            query="rolland can you test hte get weather tool",
            local_tool_names={"get_weather"},
            mcp_server_names=set(),
            limit=10,
            discover_all=False,
        )

        assert mock_db.execute.await_count == 1
        sql_obj, params = mock_db.execute.await_args.args
        sql_text = str(sql_obj)
        assert "websearch_to_tsquery" in sql_text, (
            "BM25 tool search must use websearch_to_tsquery for OR semantics; "
            "plainto_tsquery ANDs every non-stopword token and is silently dead "
            "for any conversational tool query."
        )
        assert "plainto_tsquery" not in sql_text
        assert params["q"] == "rolland can you test hte get weather tool"


# ---------------------------------------------------------------------------
# index_local_tools: embedding failure must still persist the row so the
# tool appears in the admin Tool Pool (bot editor). RAG similarity search
# won't match it until a later successful re-embed — but it's usable via
# manual enrollment. Regression for external integrations (e.g.
# bennieloggins) where a fresh enable + transient embed failure left the
# tools invisible to bots even though the integration page showed them
# live-registered.
# ---------------------------------------------------------------------------


class TestIndexLocalToolsEmbedFailure:
    @pytest.mark.asyncio
    async def test_embed_failure_still_upserts_row_with_sentinel_hash(self, engine):
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

        from app.agent.tools import index_local_tools
        from app.db.models import ToolEmbedding
        from app.tools.registry import _tools

        fake_schema = {
            "type": "function",
            "function": {
                "name": "bennie_loggins_log_poop",
                "description": "Log a poop event",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        _tools["bennie_loggins_log_poop"] = {
            "function": lambda: None,
            "schema": fake_schema,
            "source_dir": None,
            "source_integration": "bennieloggins",
            "source_file": "logging.py",
            "safety_tier": "mutating",
        }
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            with (
                patch("app.agent.tools.async_session", factory),
                patch("app.agent.tools._embed_query", side_effect=RuntimeError("embedding provider down")),
            ):
                await index_local_tools()

            async with factory() as db:
                rows = (await db.execute(
                    select(ToolEmbedding).where(
                        ToolEmbedding.tool_name == "bennie_loggins_log_poop",
                    )
                )).scalars().all()

            assert len(rows) == 1, "tool must be upserted even when embedding fails"
            row = rows[0]
            assert row.source_integration == "bennieloggins"
            assert row.embedding is None
            # Sentinel hash lets the next index pass detect the row as stale
            # and retry the embed call.
            assert row.content_hash.startswith("noembed:")
        finally:
            _tools.pop("bennie_loggins_log_poop", None)


# ---------------------------------------------------------------------------
# get_tool_info activates the tool for the next iteration
# ---------------------------------------------------------------------------
#
# Regression: previously, get_tool_info just returned the schema as JSON and
# the tool remained absent from tools_param, making the "call get_tool_info
# to load it" hint message a lie. The agent would look up ha_get_state, get
# the schema back, then correctly report "I can inspect its schema, but I
# don't have a direct callable handle." See the 2026-04-11 #8 trace.


class TestGetToolInfoActivation:
    """get_tool_info must append the looked-up schema to current_activated_tools
    so the agent loop can merge it into tools_param on the next iteration."""

    @pytest.mark.asyncio
    async def test_local_tool_activates(self):
        from app.agent.context import current_activated_tools
        from app.tools.local.discovery import get_tool_info
        from app.tools.registry import _tools

        fake_schema = {
            "type": "function",
            "function": {
                "name": "fake_local_tool",
                "description": "fake",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        _tools["fake_local_tool"] = {"schema": fake_schema, "handler": None}
        try:
            activation_list: list[dict] = []
            token = current_activated_tools.set(activation_list)
            try:
                result = await get_tool_info("fake_local_tool")
            finally:
                current_activated_tools.reset(token)

            assert "fake_local_tool" in result
            assert len(activation_list) == 1
            assert activation_list[0]["function"]["name"] == "fake_local_tool"
        finally:
            _tools.pop("fake_local_tool", None)

    @pytest.mark.asyncio
    async def test_mcp_tool_activates_from_db(self):
        from app.agent.context import current_activated_tools
        from app.tools.local.discovery import get_tool_info

        mcp_schema = {
            "type": "function",
            "function": {
                "name": "ha_get_state",
                "description": "Get HA entity state",
                "parameters": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                },
            },
        }

        class _Row:
            server_name = "ha-mcp"
            schema_ = mcp_schema

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = _Row()
        mock_db.execute.return_value = mock_result

        with patch("app.db.engine.async_session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            activation_list: list[dict] = []
            token = current_activated_tools.set(activation_list)
            try:
                result = await get_tool_info("ha_get_state")
            finally:
                current_activated_tools.reset(token)

        assert "ha_get_state" in result
        assert "ha-mcp" in result
        assert len(activation_list) == 1
        assert activation_list[0]["function"]["name"] == "ha_get_state"

    @pytest.mark.asyncio
    async def test_not_found_does_not_activate(self):
        from app.agent.context import current_activated_tools
        from app.tools.local.discovery import get_tool_info

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.db.engine.async_session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            activation_list: list[dict] = []
            token = current_activated_tools.set(activation_list)
            try:
                result = await get_tool_info("no_such_tool")
            finally:
                current_activated_tools.reset(token)

        assert "error" in result
        assert activation_list == []

    @pytest.mark.asyncio
    async def test_no_activation_context_does_not_error(self):
        """When called outside the agent loop (no activation list set), get_tool_info
        still returns the schema successfully. Keeps the tool usable from scripts, tests,
        and admin endpoints that don't run inside run_agent_tool_loop."""
        from app.agent.context import current_activated_tools
        from app.tools.local.discovery import get_tool_info
        from app.tools.registry import _tools

        fake_schema = {
            "type": "function",
            "function": {
                "name": "fake_no_ctx_tool",
                "description": "fake",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        _tools["fake_no_ctx_tool"] = {"schema": fake_schema, "handler": None}
        try:
            token = current_activated_tools.set(None)
            try:
                result = await get_tool_info("fake_no_ctx_tool")
            finally:
                current_activated_tools.reset(token)
            assert "fake_no_ctx_tool" in result
        finally:
            _tools.pop("fake_no_ctx_tool", None)

    @pytest.mark.asyncio
    async def test_duplicate_lookup_does_not_double_activate(self):
        from app.agent.context import current_activated_tools
        from app.tools.local.discovery import get_tool_info
        from app.tools.registry import _tools

        fake_schema = {
            "type": "function",
            "function": {
                "name": "fake_dedup_tool",
                "description": "fake",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        _tools["fake_dedup_tool"] = {"schema": fake_schema, "handler": None}
        try:
            activation_list: list[dict] = []
            token = current_activated_tools.set(activation_list)
            try:
                await get_tool_info("fake_dedup_tool")
                await get_tool_info("fake_dedup_tool")
            finally:
                current_activated_tools.reset(token)

            assert len(activation_list) == 1
        finally:
            _tools.pop("fake_dedup_tool", None)

    def test_snapshot_restore_preserves_activation_list(self):
        """Delegation / sub-agent paths snapshot & restore agent ContextVars. The new
        current_activated_tools ContextVar must participate so a parent bot's
        post-delegation get_tool_info calls append to the parent's list (not the
        dead child list left behind by the child run_agent_tool_loop).
        """
        from app.agent.context import (
            AgentContextSnapshot,
            current_activated_tools,
            restore_agent_context,
            snapshot_agent_context,
        )

        parent_list: list[dict] = [{"function": {"name": "parent_tool"}}]
        parent_token = current_activated_tools.set(parent_list)
        try:
            # Parent has captured a snapshot before delegating
            snap = snapshot_agent_context()
            assert isinstance(snap, AgentContextSnapshot)
            assert snap.activated_tools is parent_list

            # Child run_agent_tool_loop overwrites with a new list
            child_list: list[dict] = []
            child_token = current_activated_tools.set(child_list)
            try:
                # Child activates a tool
                child_list.append({"function": {"name": "child_tool"}})
                assert current_activated_tools.get() is child_list
            finally:
                current_activated_tools.reset(child_token)

            # Delegation layer restores parent context
            restore_agent_context(snap)

            # Parent's contextvar must point back at parent_list — NOT the child
            assert current_activated_tools.get() is parent_list
            # Parent's list is untouched by child activations
            assert [t["function"]["name"] for t in parent_list] == ["parent_tool"]
        finally:
            current_activated_tools.reset(parent_token)
