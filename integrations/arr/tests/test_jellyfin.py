"""Tests for Jellyfin tools."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# jellyfin_now_playing
# ---------------------------------------------------------------------------


class TestJellyfinNowPlaying:
    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._get", new_callable=AsyncMock)
    async def test_active_session(self, mock_get):
        mock_get.return_value = [
            {
                "UserName": "alice",
                "Client": "Jellyfin Web",
                "DeviceName": "Chrome",
                "NowPlayingItem": {
                    "Type": "Episode",
                    "Name": "Pilot",
                    "SeriesName": "Breaking Bad",
                    "ParentIndexNumber": 1,
                    "IndexNumber": 1,
                    "RunTimeTicks": 10_000_000_000,
                },
                "PlayState": {
                    "PositionTicks": 5_000_000_000,
                    "IsPaused": False,
                },
            },
        ]
        from integrations.arr.tools.jellyfin import jellyfin_now_playing

        result = json.loads(await jellyfin_now_playing())
        assert result["count"] == 1
        session = result["sessions"][0]
        assert session["user"] == "alice"
        assert session["series"] == "Breaking Bad"
        assert session["progress_pct"] == 50.0
        assert session["is_paused"] is False

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._get", new_callable=AsyncMock)
    async def test_no_sessions(self, mock_get):
        mock_get.return_value = [
            {"UserName": "alice", "Client": "Web"},  # No NowPlayingItem
        ]
        from integrations.arr.tools.jellyfin import jellyfin_now_playing

        result = json.loads(await jellyfin_now_playing())
        assert result["count"] == 0
        assert result["sessions"] == []

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setenv("JELLYFIN_URL", "")
        from integrations.arr.tools.jellyfin import jellyfin_now_playing

        result = json.loads(await jellyfin_now_playing())
        assert "error" in result
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._get", new_callable=AsyncMock)
    async def test_http_error(self, mock_get):
        mock_resp = httpx.Response(401, request=httpx.Request("GET", "http://test"))
        mock_get.side_effect = httpx.HTTPStatusError(
            "err", request=mock_resp.request, response=mock_resp
        )
        from integrations.arr.tools.jellyfin import jellyfin_now_playing

        result = json.loads(await jellyfin_now_playing())
        assert "error" in result
        assert "401" in result["error"]


# ---------------------------------------------------------------------------
# jellyfin_library
# ---------------------------------------------------------------------------


class TestJellyfinLibrary:
    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._get_admin_user_id", new_callable=AsyncMock)
    @patch("integrations.arr.tools.jellyfin._get", new_callable=AsyncMock)
    async def test_recent_success(self, mock_get, mock_admin_id):
        mock_admin_id.return_value = "admin-id-123"
        mock_get.return_value = [
            {
                "Id": "item-1",
                "Name": "Inception",
                "Type": "Movie",
                "ProductionYear": 2010,
            },
        ]
        from integrations.arr.tools.jellyfin import jellyfin_library

        result = json.loads(await jellyfin_library(action="recent"))
        assert result["count"] == 1
        assert result["items"][0]["name"] == "Inception"
        assert result["items"][0]["year"] == 2010

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._get_admin_user_id", new_callable=AsyncMock)
    @patch("integrations.arr.tools.jellyfin._get", new_callable=AsyncMock)
    async def test_search_success(self, mock_get, mock_admin_id):
        mock_admin_id.return_value = "admin-id-123"
        mock_get.return_value = {
            "Items": [
                {
                    "Id": "item-2",
                    "Name": "The Matrix",
                    "Type": "Movie",
                    "ProductionYear": 1999,
                    "Overview": "A computer hacker learns about the true nature of reality.",
                },
            ],
        }
        from integrations.arr.tools.jellyfin import jellyfin_library

        result = json.loads(await jellyfin_library(action="search", search="matrix"))
        assert result["count"] == 1
        assert result["items"][0]["name"] == "The Matrix"
        assert "overview" in result["items"][0]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._get_admin_user_id", new_callable=AsyncMock)
    async def test_search_without_term(self, mock_admin_id):
        mock_admin_id.return_value = "admin-id-123"
        from integrations.arr.tools.jellyfin import jellyfin_library

        result = json.loads(await jellyfin_library(action="search"))
        assert "error" in result
        assert "search term required" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._get_admin_user_id", new_callable=AsyncMock)
    @patch("integrations.arr.tools.jellyfin._get", new_callable=AsyncMock)
    async def test_stats_success(self, mock_get, mock_admin_id):
        mock_admin_id.return_value = "admin-id-123"
        mock_get.return_value = {
            "MovieCount": 150,
            "SeriesCount": 40,
            "EpisodeCount": 3200,
        }
        from integrations.arr.tools.jellyfin import jellyfin_library

        result = json.loads(await jellyfin_library(action="stats"))
        assert result["stats"]["MovieCount"] == 150

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setenv("JELLYFIN_URL", "")
        from integrations.arr.tools.jellyfin import jellyfin_library

        result = json.loads(await jellyfin_library())
        assert "error" in result
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._get_admin_user_id", new_callable=AsyncMock)
    @patch("integrations.arr.tools.jellyfin._get", new_callable=AsyncMock)
    async def test_connect_error(self, mock_get, mock_admin_id):
        mock_admin_id.return_value = "admin-id-123"
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        from integrations.arr.tools.jellyfin import jellyfin_library

        result = json.loads(await jellyfin_library())
        assert "error" in result
        assert "Cannot connect" in result["error"]


# ---------------------------------------------------------------------------
# jellyfin_users
# ---------------------------------------------------------------------------


class TestJellyfinUsers:
    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._get", new_callable=AsyncMock)
    async def test_list(self, mock_get):
        mock_get.return_value = [
            {
                "Id": "user-1",
                "Name": "admin",
                "Policy": {"IsAdministrator": True, "IsDisabled": False},
                "LastLoginDate": "2026-03-30T10:00:00Z",
                "LastActivityDate": "2026-03-30T12:00:00Z",
            },
            {
                "Id": "user-2",
                "Name": "viewer",
                "Policy": {"IsAdministrator": False, "IsDisabled": False},
                "LastLoginDate": None,
                "LastActivityDate": None,
            },
        ]
        from integrations.arr.tools.jellyfin import jellyfin_users

        result = json.loads(await jellyfin_users(action="list"))
        assert result["count"] == 2
        assert result["users"][0]["name"] == "admin"
        assert result["users"][0]["is_admin"] is True
        assert result["users"][1]["is_admin"] is False

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._post", new_callable=AsyncMock)
    async def test_create(self, mock_post):
        mock_post.return_value = {"Id": "new-user-id", "Name": "bob"}
        from integrations.arr.tools.jellyfin import jellyfin_users

        result = json.loads(await jellyfin_users(action="create", username="bob", password="secret"))
        assert result["status"] == "ok"
        assert result["user_id"] == "new-user-id"
        assert result["username"] == "bob"
        mock_post.assert_called_once_with(
            "/Users/New", {"Name": "bob", "Password": "secret"}
        )

    @pytest.mark.asyncio
    async def test_create_without_username(self):
        from integrations.arr.tools.jellyfin import jellyfin_users

        result = json.loads(await jellyfin_users(action="create"))
        assert "error" in result
        assert "username required" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.jellyfin._delete", new_callable=AsyncMock)
    async def test_delete(self, mock_delete):
        mock_delete.return_value = None
        from integrations.arr.tools.jellyfin import jellyfin_users

        result = json.loads(await jellyfin_users(action="delete", user_id="user-2"))
        assert result["status"] == "ok"
        assert "user-2" in result["message"]
        mock_delete.assert_called_once_with("/Users/user-2")

    @pytest.mark.asyncio
    async def test_delete_without_user_id(self):
        from integrations.arr.tools.jellyfin import jellyfin_users

        result = json.loads(await jellyfin_users(action="delete"))
        assert "error" in result
        assert "user_id required" in result["error"]

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setenv("JELLYFIN_URL", "")
        from integrations.arr.tools.jellyfin import jellyfin_users

        result = json.loads(await jellyfin_users())
        assert "error" in result
        assert "not configured" in result["error"]
