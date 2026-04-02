"""Tests for tool retrieval cache in app/agent/tools.py."""

import time
from unittest.mock import patch

import pytest

from app.agent.tools import (
    _cache_key,
    _tool_cache,
    _TOOL_CACHE_TTL,
    invalidate_tool_cache,
)


class TestCacheKey:
    def test_deterministic(self):
        k1 = _cache_key("hello", ["a", "b"], ["s1"], 10, 0.35)
        k2 = _cache_key("hello", ["a", "b"], ["s1"], 10, 0.35)
        assert k1 == k2

    def test_different_query(self):
        k1 = _cache_key("hello", ["a"], ["s1"], 10, 0.35)
        k2 = _cache_key("world", ["a"], ["s1"], 10, 0.35)
        assert k1 != k2

    def test_different_tools(self):
        k1 = _cache_key("hello", ["a"], ["s1"], 10, 0.35)
        k2 = _cache_key("hello", ["a", "b"], ["s1"], 10, 0.35)
        assert k1 != k2

    def test_different_servers(self):
        k1 = _cache_key("hello", ["a"], ["s1"], 10, 0.35)
        k2 = _cache_key("hello", ["a"], ["s2"], 10, 0.35)
        assert k1 != k2

    def test_order_independent(self):
        """Tool/server names are sorted, so order shouldn't matter."""
        k1 = _cache_key("hello", ["b", "a"], ["s2", "s1"], 10, 0.35)
        k2 = _cache_key("hello", ["a", "b"], ["s1", "s2"], 10, 0.35)
        assert k1 == k2

    def test_different_threshold(self):
        k1 = _cache_key("hello", ["a"], ["s1"], 10, 0.35)
        k2 = _cache_key("hello", ["a"], ["s1"], 10, 0.50)
        assert k1 != k2


class TestInvalidateToolCache:
    def test_clears_cache(self):
        _tool_cache["test_key"] = (time.monotonic(), [], 0.0, [])
        assert len(_tool_cache) > 0
        invalidate_tool_cache()
        assert len(_tool_cache) == 0

    def test_no_error_when_empty(self):
        invalidate_tool_cache()
        invalidate_tool_cache()  # double-clear is fine


class TestRetrieveToolsCache:
    """Test that retrieve_tools uses the cache correctly."""

    @pytest.fixture(autouse=True)
    def clean_cache(self):
        invalidate_tool_cache()
        yield
        invalidate_tool_cache()

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_embed(self):
        """A cached result should be returned without calling the embedding API."""
        from app.agent.tools import retrieve_tools

        # Pre-populate cache with a known result
        ck = _cache_key("test query", ["tool_a"], ["server_a"], 10, 0.35)
        expected_tools = [{"function": {"name": "test_tool"}}]
        _tool_cache[ck] = (time.monotonic(), expected_tools, 0.9, [{"name": "test_tool", "sim": 0.9}])

        with patch("app.agent.tools._embed_query") as mock_embed:
            result_tools, sim, candidates = await retrieve_tools(
                "test query", ["tool_a"], ["server_a"], top_k=10, threshold=0.35
            )

        mock_embed.assert_not_called()
        assert result_tools == expected_tools
        assert sim == 0.9

    @pytest.mark.asyncio
    async def test_expired_cache_is_skipped(self):
        """An expired cache entry should not be used."""
        from app.agent.tools import retrieve_tools

        ck = _cache_key("test query", ["tool_a"], ["server_a"], 10, 0.35)
        # Set timestamp far in the past
        _tool_cache[ck] = (time.monotonic() - _TOOL_CACHE_TTL - 1, [{"x": 1}], 0.9, [])

        with patch("app.agent.tools._embed_query", side_effect=Exception("embed error")):
            # Should NOT use cache, will try to embed (and fail gracefully)
            result_tools, sim, candidates = await retrieve_tools(
                "test query", ["tool_a"], ["server_a"], top_k=10, threshold=0.35
            )

        # embed_query failed, so no tools returned
        assert result_tools == []
        assert sim == 0.0
