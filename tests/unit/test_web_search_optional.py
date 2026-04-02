"""Tests for WEB_SEARCH_MODE runtime dispatch."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.tools.local.web_search import web_search, _check_ssrf, _BLOCKED_NETWORKS


# ---------------------------------------------------------------------------
# Helpers for SearXNG mocking
# ---------------------------------------------------------------------------

def _mock_searxng_client(*, side_effect=None, response_data=None, status_code=200):
    """Return a patched httpx.AsyncClient context for SearXNG tests."""
    mock_client = AsyncMock()
    if side_effect:
        mock_client.get.side_effect = side_effect
    else:
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_data or {"results": []}
        if status_code >= 400:
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                f"HTTP {status_code}", request=MagicMock(), response=MagicMock(status_code=status_code),
            )
        else:
            mock_resp.raise_for_status.return_value = None
        mock_client.get.return_value = mock_resp

    ctx = patch("httpx.AsyncClient")
    mock_cls = ctx.start()
    mock_cls.return_value.__aenter__.return_value = mock_client
    mock_cls.return_value.__aexit__.return_value = False
    return ctx


class TestWebSearchModeDispatch:
    @pytest.mark.asyncio
    async def test_searxng_mode_calls_searxng(self):
        data = {"results": [
            {"title": "Test", "url": "https://example.com", "content": "result"},
        ]}
        ctx = _mock_searxng_client(response_data=data)
        try:
            with patch("app.config.settings.WEB_SEARCH_MODE", "searxng"):
                result = await web_search("test query", num_results=1)
        finally:
            ctx.stop()

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["title"] == "Test"

    @pytest.mark.asyncio
    async def test_ddgs_mode_calls_ddgs(self):
        ddgs_results = [
            {"title": "DDG Result", "href": "https://ddg.example.com", "body": "found it"},
        ]
        with patch("app.config.settings.WEB_SEARCH_MODE", "ddgs"), \
             patch("asyncio.to_thread", new_callable=AsyncMock, return_value=ddgs_results):
            result = await web_search("test query", num_results=1)

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["title"] == "DDG Result"
        assert parsed[0]["url"] == "https://ddg.example.com"

    @pytest.mark.asyncio
    async def test_none_mode_returns_error(self):
        with patch("app.config.settings.WEB_SEARCH_MODE", "none"):
            result = await web_search("test query")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "disabled" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_unknown_mode_returns_error(self):
        """Typo or invalid mode should behave like 'none'."""
        with patch("app.config.settings.WEB_SEARCH_MODE", "typo"):
            result = await web_search("test query")

        parsed = json.loads(result)
        assert "error" in parsed


class TestSearXNGErrors:
    @pytest.mark.asyncio
    async def test_connection_error(self):
        ctx = _mock_searxng_client(side_effect=httpx.ConnectError("Connection refused"))
        try:
            with patch("app.config.settings.WEB_SEARCH_MODE", "searxng"):
                result = await web_search("test query")
        finally:
            ctx.stop()

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Cannot connect" in parsed["error"]
        assert "COMPOSE_PROFILES" in parsed["error"]

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        ctx = _mock_searxng_client(side_effect=httpx.ReadTimeout("timed out"))
        try:
            with patch("app.config.settings.WEB_SEARCH_MODE", "searxng"):
                result = await web_search("slow query")
        finally:
            ctx.stop()

        parsed = json.loads(result)
        assert "error" in parsed
        assert "timed out" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_http_500_error(self):
        ctx = _mock_searxng_client(status_code=500)
        try:
            with patch("app.config.settings.WEB_SEARCH_MODE", "searxng"):
                result = await web_search("test query")
        finally:
            ctx.stop()

        parsed = json.loads(result)
        assert "error" in parsed
        assert "500" in parsed["error"]


class TestDDGSErrors:
    @pytest.mark.asyncio
    async def test_ddgs_empty_results(self):
        """ddgs returning None or empty list should return empty JSON array."""
        for empty in (None, []):
            with patch("app.config.settings.WEB_SEARCH_MODE", "ddgs"), \
                 patch("asyncio.to_thread", new_callable=AsyncMock, return_value=empty):
                result = await web_search("obscure query")

            parsed = json.loads(result)
            assert parsed == []

    @pytest.mark.asyncio
    async def test_ddgs_exception_returns_error(self):
        """ddgs network/rate-limit errors should return clean JSON error."""
        with patch("app.config.settings.WEB_SEARCH_MODE", "ddgs"), \
             patch("asyncio.to_thread", new_callable=AsyncMock, side_effect=Exception("Rate limit")):
            result = await web_search("test query")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Rate limit" in parsed["error"]


class TestRegistration:
    def test_web_search_is_registered(self):
        from app.tools.registry import _tools
        assert "web_search" in _tools
        assert "fetch_url" in _tools

    def test_fetch_url_independent_of_mode(self):
        """fetch_url registration doesn't depend on WEB_SEARCH_MODE."""
        from app.tools.registry import _tools
        # fetch_url is registered via @register decorator unconditionally
        assert _tools["fetch_url"]["function"].__name__ == "fetch_url"

    def test_ssrf_helpers_importable(self):
        """_check_ssrf and _BLOCKED_NETWORKS must stay importable for test_security.py."""
        assert callable(_check_ssrf)
        assert len(_BLOCKED_NETWORKS) > 0
