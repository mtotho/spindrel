"""Tests for FlareSolverr tool functions."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from integrations.arr.tools.flaresolverr import (
    flaresolverr_destroy_all_sessions,
    flaresolverr_health,
    flaresolverr_sessions,
    flaresolverr_test_fetch,
)

MODULE = "integrations.arr.tools.flaresolverr"


# ---------------------------------------------------------------------------
# flaresolverr_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_ok():
    fs_response = {
        "status": "ok",
        "message": "Sessions",
        "version": "3.3.21",
        "sessions": ["sess-a", "sess-b"],
    }
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=fs_response) as mock_post:
        result = json.loads(await flaresolverr_health())

    assert result["status"] == "ok"
    assert result["version"] == "3.3.21"
    assert result["session_count"] == 2
    assert result["active_sessions"] == ["sess-a", "sess-b"]
    assert result["base_url"] == "http://flaresolverr:8191"
    assert "response_ms" in result
    mock_post.assert_awaited_once_with({"cmd": "sessions.list"}, timeout=15.0)


@pytest.mark.asyncio
async def test_health_no_sessions():
    fs_response = {"status": "ok", "version": "3.3.21", "sessions": []}
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=fs_response):
        result = json.loads(await flaresolverr_health())

    assert result["status"] == "ok"
    assert result["session_count"] == 0
    assert result["active_sessions"] == []


@pytest.mark.asyncio
async def test_health_connect_error():
    with patch(
        f"{MODULE}._post_v1",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        result = json.loads(await flaresolverr_health())

    assert "error" in result
    assert "Cannot connect" in result["error"]
    assert "container may be down" in result["error"]


@pytest.mark.asyncio
async def test_health_timeout():
    with patch(
        f"{MODULE}._post_v1",
        new_callable=AsyncMock,
        side_effect=httpx.TimeoutException("timed out"),
    ):
        result = json.loads(await flaresolverr_health())

    assert "error" in result
    assert "timed out" in result["error"]


@pytest.mark.asyncio
async def test_health_http_error():
    mock_resp = httpx.Response(
        500,
        request=httpx.Request("POST", "http://flaresolverr:8191/v1"),
        text="Internal Server Error",
    )
    with patch(
        f"{MODULE}._post_v1",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
    ):
        result = json.loads(await flaresolverr_health())

    assert "error" in result
    assert "500" in result["error"]


@pytest.mark.asyncio
async def test_health_not_configured(monkeypatch):
    monkeypatch.setenv("FLARESOLVERR_URL", "")
    result = json.loads(await flaresolverr_health())
    assert result["error"] == "FLARESOLVERR_URL is not configured"


# ---------------------------------------------------------------------------
# flaresolverr_sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sessions_list():
    fs_response = {"status": "ok", "version": "3.3.21", "sessions": ["a", "b", "c"]}
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=fs_response):
        result = json.loads(await flaresolverr_sessions(action="list"))

    assert result["status"] == "ok"
    assert result["session_count"] == 3
    assert result["sessions"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_sessions_create_with_id():
    fs_response = {"status": "ok", "session": "my-id", "message": "Session created"}
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=fs_response) as mock_post:
        result = json.loads(await flaresolverr_sessions(action="create", session_id="my-id"))

    assert result["status"] == "ok"
    assert result["session_id"] == "my-id"
    mock_post.assert_awaited_once()
    payload = mock_post.call_args[0][0]
    assert payload == {"cmd": "sessions.create", "session": "my-id"}


@pytest.mark.asyncio
async def test_sessions_create_no_id():
    fs_response = {"status": "ok", "session": "auto-uuid", "message": "Session created"}
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=fs_response) as mock_post:
        result = json.loads(await flaresolverr_sessions(action="create"))

    assert result["session_id"] == "auto-uuid"
    payload = mock_post.call_args[0][0]
    assert "session" not in payload


@pytest.mark.asyncio
async def test_sessions_destroy():
    fs_response = {"status": "ok", "message": "The session has been removed."}
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=fs_response) as mock_post:
        result = json.loads(await flaresolverr_sessions(action="destroy", session_id="sess-x"))

    assert result["status"] == "ok"
    assert result["session_id"] == "sess-x"
    mock_post.assert_awaited_once_with(
        {"cmd": "sessions.destroy", "session": "sess-x"},
        timeout=15.0,
    )


@pytest.mark.asyncio
async def test_sessions_destroy_missing_id():
    result = json.loads(await flaresolverr_sessions(action="destroy"))
    assert result["error"] == "session_id is required for action='destroy'"


@pytest.mark.asyncio
async def test_sessions_unknown_action():
    result = json.loads(await flaresolverr_sessions(action="bogus"))
    assert "error" in result
    assert "Unknown action" in result["error"]


@pytest.mark.asyncio
async def test_sessions_not_configured(monkeypatch):
    monkeypatch.setenv("FLARESOLVERR_URL", "")
    result = json.loads(await flaresolverr_sessions(action="list"))
    assert result["error"] == "FLARESOLVERR_URL is not configured"


# ---------------------------------------------------------------------------
# flaresolverr_test_fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_fetch_challenge_solved():
    fs_response = {
        "status": "ok",
        "message": "Challenge solved",
        "version": "3.3.21",
        "solution": {
            "url": "https://www.1337x.to/",
            "status": 200,
            "userAgent": "Mozilla/5.0",
            "response": "<html>...</html>" * 20,
            "cookies": [
                {"name": "cf_clearance", "value": "abc"},
                {"name": "__cf_bm", "value": "def"},
            ],
            "turnstile_token": None,
        },
    }
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=fs_response):
        result = json.loads(await flaresolverr_test_fetch(url="https://www.1337x.to/"))

    assert result["fs_status"] == "ok"
    assert result["solution_status"] == 200
    assert result["cookie_count"] == 2
    assert result["cf_clearance"] is True
    assert result["fs_version"] == "3.3.21"
    assert result["user_agent"] == "Mozilla/5.0"
    assert "response_ms" in result


@pytest.mark.asyncio
async def test_test_fetch_challenge_failed():
    fs_response = {
        "status": "error",
        "message": "Error: Cloudflare challenge timeout",
        "version": "3.3.21",
    }
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=fs_response):
        result = json.loads(await flaresolverr_test_fetch(url="https://www.1337x.to/"))

    assert result["fs_status"] == "error"
    assert "Cloudflare challenge timeout" in result["fs_message"]
    # No solution field means no solution_status
    assert "solution_status" not in result


@pytest.mark.asyncio
async def test_test_fetch_passes_session_id():
    fs_response = {"status": "ok", "message": "", "version": "3.3.21", "solution": {}}
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=fs_response) as mock_post:
        await flaresolverr_test_fetch(url="https://example.com", session_id="my-sess", max_timeout_ms=30000)

    payload = mock_post.call_args[0][0]
    assert payload["cmd"] == "request.get"
    assert payload["url"] == "https://example.com"
    assert payload["session"] == "my-sess"
    assert payload["maxTimeout"] == 30000


@pytest.mark.asyncio
async def test_test_fetch_timeout():
    with patch(
        f"{MODULE}._post_v1",
        new_callable=AsyncMock,
        side_effect=httpx.TimeoutException("timed out"),
    ):
        result = json.loads(await flaresolverr_test_fetch(url="https://www.1337x.to/"))

    assert "error" in result
    assert "timed out" in result["error"]


@pytest.mark.asyncio
async def test_test_fetch_not_configured(monkeypatch):
    monkeypatch.setenv("FLARESOLVERR_URL", "")
    result = json.loads(await flaresolverr_test_fetch(url="https://example.com"))
    assert result["error"] == "FLARESOLVERR_URL is not configured"


# ---------------------------------------------------------------------------
# flaresolverr_destroy_all_sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_destroy_all_no_sessions():
    list_response = {"status": "ok", "version": "3.3.21", "sessions": []}
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock, return_value=list_response) as mock_post:
        result = json.loads(await flaresolverr_destroy_all_sessions())

    assert result["status"] == "ok"
    assert result["destroyed_count"] == 0
    assert result["destroyed"] == []
    assert result["failed"] == []
    # Only one call: sessions.list
    assert mock_post.await_count == 1


@pytest.mark.asyncio
async def test_destroy_all_multiple_sessions():
    list_response = {"status": "ok", "version": "3.3.21", "sessions": ["a", "b", "c"]}
    destroy_response = {"status": "ok", "message": "removed"}
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [list_response, destroy_response, destroy_response, destroy_response]
        result = json.loads(await flaresolverr_destroy_all_sessions())

    assert result["status"] == "ok"
    assert result["destroyed_count"] == 3
    assert sorted(result["destroyed"]) == ["a", "b", "c"]
    assert result["failed"] == []
    assert mock_post.await_count == 4


@pytest.mark.asyncio
async def test_destroy_all_partial_failure():
    list_response = {"status": "ok", "version": "3.3.21", "sessions": ["a", "b"]}
    destroy_ok = {"status": "ok", "message": "removed"}
    with patch(f"{MODULE}._post_v1", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [list_response, destroy_ok, RuntimeError("boom")]
        result = json.loads(await flaresolverr_destroy_all_sessions())

    assert result["status"] == "partial"
    assert result["destroyed_count"] == 1
    assert result["destroyed"] == ["a"]
    assert len(result["failed"]) == 1
    assert result["failed"][0]["session_id"] == "b"


@pytest.mark.asyncio
async def test_destroy_all_connect_error():
    with patch(
        f"{MODULE}._post_v1",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("refused"),
    ):
        result = json.loads(await flaresolverr_destroy_all_sessions())

    assert "error" in result
    assert "Cannot connect" in result["error"]


@pytest.mark.asyncio
async def test_destroy_all_not_configured(monkeypatch):
    monkeypatch.setenv("FLARESOLVERR_URL", "")
    result = json.loads(await flaresolverr_destroy_all_sessions())
    assert result["error"] == "FLARESOLVERR_URL is not configured"
