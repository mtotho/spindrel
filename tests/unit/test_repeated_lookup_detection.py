"""Tests for repeated_lookup_detection — multi-tool detection."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.repeated_lookup_detection import (
    _CACHE_TTL,
    _TRACKED_TOOLS,
    _cache,
    find_repeated_lookups,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the module-level cache before each test."""
    _cache.clear()
    yield
    _cache.clear()


class TestTrackedTools:
    """Verify the tracked tool list covers the expected tools."""

    def test_includes_search_memory(self):
        assert "search_memory" in _TRACKED_TOOLS

    def test_includes_search_channel_workspace(self):
        assert "search_channel_workspace" in _TRACKED_TOOLS

    def test_includes_search_channel_archive(self):
        assert "search_channel_archive" in _TRACKED_TOOLS

    def test_excludes_web_search(self):
        assert "web_search" not in _TRACKED_TOOLS

    def test_excludes_get_memory_file(self):
        assert "get_memory_file" not in _TRACKED_TOOLS


class TestFindRepeatedLookups:
    """Integration-style tests for find_repeated_lookups with mocked DB."""

    @pytest.mark.asyncio
    async def test_returns_cached_result_within_ttl(self):
        """If a cached result exists and is fresh, return it without DB hit."""
        _cache["bot1"] = (time.monotonic(), ["cached query"])
        result = await find_repeated_lookups("bot1")
        assert result == ["cached query"]

    @pytest.mark.asyncio
    async def test_cache_expired_triggers_db_query(self):
        """Expired cache should trigger a fresh DB query."""
        _cache["bot1"] = (time.monotonic() - _CACHE_TTL - 1, ["old"])

        # Mock the DB layer — return one repeated query
        mock_row = MagicMock()
        mock_row.query_text = "how do i deploy"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        session_ctx = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=session_ctx):
            result = await find_repeated_lookups("bot1")

        assert result == ["how do i deploy"]
        # Verify cache was updated
        assert "bot1" in _cache
        assert _cache["bot1"][1] == ["how do i deploy"]

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        """DB errors should be swallowed, returning an empty list."""
        with patch("app.db.engine.async_session", side_effect=Exception("boom")):
            result = await find_repeated_lookups("bot_err")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_query_text_filtered(self):
        """Rows with empty query_text should be filtered out."""
        mock_row_good = MagicMock()
        mock_row_good.query_text = "valid query"
        mock_row_empty = MagicMock()
        mock_row_empty.query_text = ""

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row_good, mock_row_empty]
        mock_db.execute = AsyncMock(return_value=mock_result)

        session_ctx = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=session_ctx):
            result = await find_repeated_lookups("bot2")

        assert result == ["valid query"]
