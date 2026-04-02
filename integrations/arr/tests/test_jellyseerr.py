"""Tests for Jellyseerr tools."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# jellyseerr_requests
# ---------------------------------------------------------------------------


class TestJellyseerrRequests:
    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyseerr._get", new_callable=AsyncMock)
    async def test_success(self, mock_get):
        mock_get.return_value = {
            "pageInfo": {"results": 2},
            "results": [
                {
                    "id": 1,
                    "type": "movie",
                    "status": 1,  # pending
                    "requestedBy": {"displayName": "alice"},
                    "createdAt": "2026-03-30T10:00:00Z",
                    "media": {
                        "mediaType": "movie",
                        "externalServiceSlug": "inception-2010",
                        "tmdbId": 27205,
                    },
                },
                {
                    "id": 2,
                    "type": "tv",
                    "status": 2,  # approved
                    "requestedBy": {"displayName": "bob"},
                    "createdAt": "2026-03-29T08:00:00Z",
                    "media": {
                        "mediaType": "tv",
                        "tvdbId": 81189,
                    },
                },
            ],
        }
        from integrations.arr.tools.jellyseerr import jellyseerr_requests

        result = json.loads(await jellyseerr_requests())
        assert result["total"] == 2
        assert len(result["requests"]) == 2
        assert result["requests"][0]["status"] == "pending"
        assert result["requests"][0]["tmdb_id"] == 27205
        assert result["requests"][1]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setenv("JELLYSEERR_URL", "")
        from integrations.arr.tools.jellyseerr import jellyseerr_requests

        result = json.loads(await jellyseerr_requests())
        assert "error" in result
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyseerr._get", new_callable=AsyncMock)
    async def test_http_error(self, mock_get):
        mock_resp = httpx.Response(500, request=httpx.Request("GET", "http://test"))
        mock_get.side_effect = httpx.HTTPStatusError(
            "err", request=mock_resp.request, response=mock_resp
        )
        from integrations.arr.tools.jellyseerr import jellyseerr_requests

        result = json.loads(await jellyseerr_requests())
        assert "error" in result
        assert "500" in result["error"]


# ---------------------------------------------------------------------------
# jellyseerr_search
# ---------------------------------------------------------------------------


class TestJellyseerrSearch:
    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyseerr._get", new_callable=AsyncMock)
    async def test_success(self, mock_get):
        mock_get.return_value = {
            "results": [
                {
                    "id": 550,
                    "mediaType": "movie",
                    "title": "Fight Club",
                    "releaseDate": "1999-10-15",
                    "overview": "An insomniac office worker and a soap salesman form an underground fight club.",
                },
                {
                    "id": 1399,
                    "mediaType": "tv",
                    "name": "Game of Thrones",
                    "firstAirDate": "2011-04-17",
                    "overview": "Seven noble families fight for control.",
                    "mediaInfo": {"status": 5},  # available
                },
            ],
        }
        from integrations.arr.tools.jellyseerr import jellyseerr_search

        result = json.loads(await jellyseerr_search(query="fight"))
        assert result["count"] == 2
        assert result["results"][0]["title"] == "Fight Club"
        assert result["results"][0]["year"] == "1999"
        assert result["results"][1]["status"] == "available"

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setenv("JELLYSEERR_URL", "")
        from integrations.arr.tools.jellyseerr import jellyseerr_search

        result = json.loads(await jellyseerr_search(query="test"))
        assert "error" in result
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyseerr._get", new_callable=AsyncMock)
    async def test_connect_error(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        from integrations.arr.tools.jellyseerr import jellyseerr_search

        result = json.loads(await jellyseerr_search(query="test"))
        assert "error" in result
        assert "Cannot connect" in result["error"]


# ---------------------------------------------------------------------------
# jellyseerr_manage
# ---------------------------------------------------------------------------


class TestJellyseerrManage:
    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyseerr._post", new_callable=AsyncMock)
    async def test_approve_success(self, mock_post):
        mock_post.return_value = {}
        from integrations.arr.tools.jellyseerr import jellyseerr_manage

        result = json.loads(await jellyseerr_manage(action="approve", request_id=42))
        assert result["status"] == "ok"
        assert "42" in result["message"]
        assert "approved" in result["message"]
        mock_post.assert_called_once_with("/api/v1/request/42/approve")

    @pytest.mark.asyncio
    async def test_approve_without_request_id(self):
        from integrations.arr.tools.jellyseerr import jellyseerr_manage

        result = json.loads(await jellyseerr_manage(action="approve"))
        assert "error" in result
        assert "request_id required" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyseerr._post", new_callable=AsyncMock)
    async def test_decline(self, mock_post):
        mock_post.return_value = {}
        from integrations.arr.tools.jellyseerr import jellyseerr_manage

        result = json.loads(await jellyseerr_manage(action="decline", request_id=7))
        assert result["status"] == "ok"
        assert "declined" in result["message"]
        mock_post.assert_called_once_with("/api/v1/request/7/decline")

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyseerr._post", new_callable=AsyncMock)
    async def test_request_movie(self, mock_post):
        mock_post.return_value = {"id": 99}
        from integrations.arr.tools.jellyseerr import jellyseerr_manage

        result = json.loads(
            await jellyseerr_manage(action="request", media_id=550, media_type="movie")
        )
        assert result["status"] == "ok"
        assert result["request_id"] == 99
        mock_post.assert_called_once_with(
            "/api/v1/request", {"mediaId": 550, "mediaType": "movie"}
        )

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyseerr._post", new_callable=AsyncMock)
    async def test_request_tv_with_seasons(self, mock_post):
        mock_post.return_value = {"id": 100}
        from integrations.arr.tools.jellyseerr import jellyseerr_manage

        result = json.loads(
            await jellyseerr_manage(
                action="request", media_id=1399, media_type="tv", seasons=[1, 2]
            )
        )
        assert result["status"] == "ok"
        mock_post.assert_called_once_with(
            "/api/v1/request",
            {"mediaId": 1399, "mediaType": "tv", "seasons": [1, 2]},
        )

    @pytest.mark.asyncio
    async def test_request_missing_params(self):
        from integrations.arr.tools.jellyseerr import jellyseerr_manage

        result = json.loads(await jellyseerr_manage(action="request", media_id=550))
        assert "error" in result
        assert "media_id and media_type required" in result["error"]

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        from integrations.arr.tools.jellyseerr import jellyseerr_manage

        result = json.loads(await jellyseerr_manage(action="nuke"))
        assert "error" in result
        assert "Unknown action" in result["error"]

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setenv("JELLYSEERR_URL", "")
        from integrations.arr.tools.jellyseerr import jellyseerr_manage

        result = json.loads(await jellyseerr_manage(action="approve", request_id=1))
        assert "error" in result
        assert "not configured" in result["error"]
