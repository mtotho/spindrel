"""Tests for Bazarr tools."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# bazarr_subtitles
# ---------------------------------------------------------------------------


class TestBazarrSubtitles:
    @pytest.mark.asyncio
    @patch("integrations.arr.tools.bazarr._get", new_callable=AsyncMock)
    async def test_wanted_episodes(self, mock_get):
        mock_get.return_value = {
            "total": 2,
            "data": [
                {
                    "seriesTitle": "Breaking Bad",
                    "missing_subtitles": [{"code2": "en", "name": "English"}],
                    "season": 1,
                    "episode": 3,
                    "sceneName": "breaking.bad.s01e03",
                },
                {
                    "seriesTitle": "The Office",
                    "missing_subtitles": [{"code2": "fr", "name": "French"}],
                    "season": 2,
                    "episode": 1,
                },
            ],
        }
        from integrations.arr.tools.bazarr import bazarr_subtitles

        result = json.loads(await bazarr_subtitles(action="wanted", media_type="episodes"))
        assert result["total"] == 2
        assert len(result["items"]) == 2
        assert result["items"][0]["title"] == "Breaking Bad"
        assert result["items"][0]["season"] == 1
        assert result["items"][0]["episode"] == 3
        assert result["items"][0]["scene_name"] == "breaking.bad.s01e03"
        mock_get.assert_called_once_with(
            "/api/episodes/wanted", params={"length": "20"}
        )

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.bazarr._get", new_callable=AsyncMock)
    async def test_wanted_movies(self, mock_get):
        mock_get.return_value = {
            "total": 1,
            "data": [
                {
                    "title": "Inception",
                    "missing_subtitles": [{"code2": "es", "name": "Spanish"}],
                },
            ],
        }
        from integrations.arr.tools.bazarr import bazarr_subtitles

        result = json.loads(await bazarr_subtitles(action="wanted", media_type="movies", limit=10))
        assert result["total"] == 1
        assert result["items"][0]["title"] == "Inception"
        mock_get.assert_called_once_with(
            "/api/movies/wanted", params={"length": "10"}
        )

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.bazarr._post", new_callable=AsyncMock)
    async def test_search_trigger(self, mock_post):
        mock_post.return_value = {}
        from integrations.arr.tools.bazarr import bazarr_subtitles

        result = json.loads(await bazarr_subtitles(action="search", media_type="episodes"))
        assert result["status"] == "ok"
        assert "search triggered" in result["message"]
        mock_post.assert_called_once_with("/api/episodes/wanted/search")

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.bazarr._get", new_callable=AsyncMock)
    async def test_status(self, mock_get):
        mock_get.return_value = {
            "data": {
                "bazarr_version": "1.4.0",
                "sonarr_version": "4.0.0",
                "radarr_version": "5.0.0",
            },
        }
        from integrations.arr.tools.bazarr import bazarr_subtitles

        result = json.loads(await bazarr_subtitles(action="status"))
        assert "status" in result

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setenv("BAZARR_URL", "")
        from integrations.arr.tools.bazarr import bazarr_subtitles

        result = json.loads(await bazarr_subtitles())
        assert "error" in result
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.bazarr._get", new_callable=AsyncMock)
    async def test_http_error(self, mock_get):
        mock_resp = httpx.Response(500, request=httpx.Request("GET", "http://test"))
        mock_get.side_effect = httpx.HTTPStatusError(
            "err", request=mock_resp.request, response=mock_resp
        )
        from integrations.arr.tools.bazarr import bazarr_subtitles

        result = json.loads(await bazarr_subtitles())
        assert "error" in result
        assert "500" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.bazarr._get", new_callable=AsyncMock)
    async def test_connect_error(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        from integrations.arr.tools.bazarr import bazarr_subtitles

        result = json.loads(await bazarr_subtitles())
        assert "error" in result
        assert "Cannot connect" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.bazarr._get", new_callable=AsyncMock)
    async def test_empty_results(self, mock_get):
        mock_get.return_value = {"total": 0, "data": []}
        from integrations.arr.tools.bazarr import bazarr_subtitles

        result = json.loads(await bazarr_subtitles())
        assert result["total"] == 0
        assert result["items"] == []
