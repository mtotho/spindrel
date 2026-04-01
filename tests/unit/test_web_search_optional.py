"""Tests for WEB_SEARCH_MODE runtime dispatch."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.web_search import web_search, _check_ssrf, _BLOCKED_NETWORKS


class TestWebSearchModeDispatch:
    @pytest.mark.asyncio
    async def test_searxng_mode_calls_searxng(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [
            {"title": "Test", "url": "https://example.com", "content": "result"},
        ]}
        mock_resp.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with patch("app.config.settings.WEB_SEARCH_MODE", "searxng"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_cls.return_value.__aexit__.return_value = False

            result = await web_search("test query", num_results=1)

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
    async def test_searxng_connection_error(self):
        """SearXNG unreachable should return helpful error, not crash."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        with patch("app.config.settings.WEB_SEARCH_MODE", "searxng"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            mock_cls.return_value.__aexit__.return_value = False

            result = await web_search("test query")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "SearXNG" in parsed["error"]
        assert "COMPOSE_PROFILES" in parsed["error"]


class TestRegistration:
    def test_web_search_is_registered(self):
        from app.tools.registry import _tools
        assert "web_search" in _tools
        assert "fetch_url" in _tools

    def test_ssrf_helpers_importable(self):
        """_check_ssrf and _BLOCKED_NETWORKS must stay importable for test_security.py."""
        assert callable(_check_ssrf)
        assert len(_BLOCKED_NETWORKS) > 0
