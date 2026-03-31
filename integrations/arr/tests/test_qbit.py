"""Tests for qBittorrent tools."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_qbit_client(torrents_data, transfer_data, post_response=None):
    """Build a mock _qbit_client context manager with predetermined responses."""

    @asynccontextmanager
    async def _mock_ctx():
        client = AsyncMock()

        torrents_resp = MagicMock()
        torrents_resp.json.return_value = torrents_data
        torrents_resp.raise_for_status = MagicMock()

        transfer_resp = MagicMock()
        transfer_resp.json.return_value = transfer_data
        transfer_resp.raise_for_status = MagicMock()

        client.get.side_effect = [torrents_resp, transfer_resp]

        if post_response is not None:
            pr = MagicMock()
            pr.json.return_value = post_response
            pr.raise_for_status = MagicMock()
            client.post.return_value = pr
        else:
            pr = MagicMock()
            pr.raise_for_status = MagicMock()
            client.post.return_value = pr

        yield client

    return _mock_ctx


def _make_post_only_client():
    """Build a mock _qbit_client that only needs post (for qbit_manage)."""

    @asynccontextmanager
    async def _mock_ctx():
        client = AsyncMock()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        client.post.return_value = resp
        yield client

    return _mock_ctx


def _make_error_client(exc):
    """Build a mock _qbit_client that raises on first get."""

    @asynccontextmanager
    async def _mock_ctx():
        client = AsyncMock()
        client.get.side_effect = exc
        client.post.side_effect = exc
        yield client

    return _mock_ctx


SAMPLE_TORRENTS = [
    {
        "name": "Ubuntu 24.04",
        "hash": "abc123",
        "state": "downloading",
        "size": 1_048_576 * 100,  # 100 MB
        "dlspeed": 1024 * 500,  # 500 KB/s
        "upspeed": 1024 * 50,
        "progress": 0.45,
        "eta": 600,
        "category": "linux",
    },
]

SAMPLE_TRANSFER = {
    "dl_info_speed": 1024 * 800,
    "up_info_speed": 1024 * 100,
}


# ---------------------------------------------------------------------------
# qbit_torrents
# ---------------------------------------------------------------------------


class TestQbitTorrents:
    @pytest.mark.asyncio
    @patch(
        "integrations.arr.tools.qbit._qbit_client",
        _make_mock_qbit_client(SAMPLE_TORRENTS, SAMPLE_TRANSFER),
    )
    async def test_success(self):
        from integrations.arr.tools.qbit import qbit_torrents

        result = json.loads(await qbit_torrents())
        assert result["count"] == 1
        assert result["global_dl_speed_kb"] == 800.0
        assert result["global_up_speed_kb"] == 100.0
        t = result["torrents"][0]
        assert t["name"] == "Ubuntu 24.04"
        assert t["hash"] == "abc123"
        assert t["progress_pct"] == 45.0
        assert t["size_mb"] == 100.0
        assert t["dl_speed_kb"] == 500.0

    @pytest.mark.asyncio
    @patch(
        "integrations.arr.tools.qbit._qbit_client",
        _make_mock_qbit_client([], {"dl_info_speed": 0, "up_info_speed": 0}),
    )
    async def test_empty_list(self):
        from integrations.arr.tools.qbit import qbit_torrents

        result = json.loads(await qbit_torrents())
        assert result["count"] == 0
        assert result["torrents"] == []
        assert result["global_dl_speed_kb"] == 0.0

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setenv("QBIT_URL", "")
        from integrations.arr.tools.qbit import qbit_torrents

        result = json.loads(await qbit_torrents())
        assert "error" in result
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    @patch(
        "integrations.arr.tools.qbit._qbit_client",
        _make_error_client(httpx.ConnectError("Connection refused")),
    )
    async def test_connect_error(self):
        from integrations.arr.tools.qbit import qbit_torrents

        result = json.loads(await qbit_torrents())
        assert "error" in result
        assert "Cannot connect" in result["error"]

    @pytest.mark.asyncio
    async def test_http_error(self):
        mock_resp = httpx.Response(500, request=httpx.Request("GET", "http://test"))
        exc = httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp)

        @asynccontextmanager
        async def _err_ctx():
            client = AsyncMock()
            client.get.side_effect = exc
            yield client

        with patch("integrations.arr.tools.qbit._qbit_client", _err_ctx):
            from integrations.arr.tools.qbit import qbit_torrents

            result = json.loads(await qbit_torrents())
            assert "error" in result
            assert "500" in result["error"]


# ---------------------------------------------------------------------------
# qbit_manage
# ---------------------------------------------------------------------------


class TestQbitManage:
    @pytest.mark.asyncio
    @patch("integrations.arr.tools.qbit._qbit_client", _make_post_only_client())
    async def test_pause_success(self):
        from integrations.arr.tools.qbit import qbit_manage

        result = json.loads(await qbit_manage(hashes=["abc123"], action="pause"))
        assert result["status"] == "ok"
        assert result["action"] == "pause"
        assert result["hashes"] == ["abc123"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.qbit._qbit_client", _make_post_only_client())
    async def test_resume_success(self):
        from integrations.arr.tools.qbit import qbit_manage

        result = json.loads(await qbit_manage(hashes=["abc123"], action="resume"))
        assert result["status"] == "ok"
        assert result["action"] == "resume"

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.qbit._qbit_client", _make_post_only_client())
    async def test_delete_with_files(self):
        from integrations.arr.tools.qbit import qbit_manage

        result = json.loads(await qbit_manage(hashes=["abc", "def"], action="delete_with_files"))
        assert result["status"] == "ok"
        assert result["action"] == "delete_with_files"
        assert "2 torrent(s)" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_hashes_error(self):
        from integrations.arr.tools.qbit import qbit_manage

        result = json.loads(await qbit_manage(hashes=[], action="pause"))
        assert "error" in result
        assert "empty" in result["error"]

    @pytest.mark.asyncio
    @patch("integrations.arr.tools.qbit._qbit_client", _make_post_only_client())
    async def test_unknown_action_error(self):
        from integrations.arr.tools.qbit import qbit_manage

        result = json.loads(await qbit_manage(hashes=["abc"], action="explode"))
        assert "error" in result
        assert "Unknown action" in result["error"]

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.setenv("QBIT_URL", "")
        from integrations.arr.tools.qbit import qbit_manage

        result = json.loads(await qbit_manage(hashes=["abc"], action="pause"))
        assert "error" in result
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    @patch(
        "integrations.arr.tools.qbit._qbit_client",
        _make_error_client(httpx.ConnectError("Connection refused")),
    )
    async def test_connect_error(self):
        from integrations.arr.tools.qbit import qbit_manage

        result = json.loads(await qbit_manage(hashes=["abc"], action="pause"))
        assert "error" in result
        assert "Cannot connect" in result["error"]
