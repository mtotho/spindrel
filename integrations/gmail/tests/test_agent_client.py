"""Tests for Gmail agent_client — channel resolution via admin API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from integrations.gmail.agent_client import resolve_channels_for_binding

_FAKE_REQUEST = httpx.Request("GET", "http://test:8000/api/v1/admin/channels")
_MOD = "integrations.gmail.agent_client"


def _api_response(channels: list[dict]) -> httpx.Response:
    """Build a mock response matching ChannelListOut shape."""
    body = {"channels": channels, "total": len(channels), "page": 1, "page_size": 25}
    return httpx.Response(200, json=body, request=_FAKE_REQUEST)


def _patches(resp):
    """Common patches for resolve_channels_for_binding tests."""
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=resp)
    return (
        patch(f"{_MOD}._http", mock_http),
        patch(f"{_MOD}._base_url", return_value="http://test:8000"),
        patch(f"{_MOD}._headers", return_value={"Authorization": "Bearer test"}),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_by_integration_binding():
    """Channels with gmail integration binding should be matched."""
    resp = _api_response([
        {
            "id": "ch-1", "name": "Gmail", "client_id": None,
            "integrations": [
                {"client_id": "gmail:user@gmail.com", "integration_type": "gmail"},
            ],
        },
        {
            "id": "ch-2", "name": "Other", "client_id": None,
            "integrations": [
                {"client_id": "slack:C123", "integration_type": "slack"},
            ],
        },
    ])
    p_http, p_url, p_hdrs = _patches(resp)
    with p_http, p_url, p_hdrs:
        result = await resolve_channels_for_binding("gmail:user@gmail.com")

    assert len(result) == 1
    assert result[0]["id"] == "ch-1"


@pytest.mark.asyncio
async def test_resolve_by_legacy_client_id():
    """Channels with legacy channel-level client_id should still match."""
    resp = _api_response([
        {
            "id": "ch-1", "name": "Gmail", "client_id": "gmail:user@gmail.com",
            "integrations": [],
        },
    ])
    p_http, p_url, p_hdrs = _patches(resp)
    with p_http, p_url, p_hdrs:
        result = await resolve_channels_for_binding("gmail:user@gmail.com")

    assert len(result) == 1
    assert result[0]["id"] == "ch-1"


@pytest.mark.asyncio
async def test_resolve_no_matches():
    """No channels matching the prefix → empty list."""
    resp = _api_response([
        {
            "id": "ch-1", "name": "Slack", "client_id": "slack:C123",
            "integrations": [],
        },
    ])
    p_http, p_url, p_hdrs = _patches(resp)
    with p_http, p_url, p_hdrs:
        result = await resolve_channels_for_binding("gmail:user@gmail.com")

    assert result == []


@pytest.mark.asyncio
async def test_resolve_handles_api_error():
    """API errors should return empty list, not crash."""
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    with (
        patch(f"{_MOD}._http", mock_http),
        patch(f"{_MOD}._base_url", return_value="http://test:8000"),
        patch(f"{_MOD}._headers", return_value={}),
    ):
        result = await resolve_channels_for_binding("gmail:")

    assert result == []


@pytest.mark.asyncio
async def test_resolve_multiple_channels():
    """Multiple channels with gmail bindings should all be returned."""
    resp = _api_response([
        {
            "id": "ch-1", "name": "Gmail Personal", "client_id": None,
            "integrations": [
                {"client_id": "gmail:user@gmail.com", "integration_type": "gmail"},
            ],
        },
        {
            "id": "ch-2", "name": "Gmail Work", "client_id": None,
            "integrations": [
                {"client_id": "gmail:user@gmail.com", "integration_type": "gmail"},
            ],
        },
    ])
    p_http, p_url, p_hdrs = _patches(resp)
    with p_http, p_url, p_hdrs:
        result = await resolve_channels_for_binding("gmail:user@gmail.com")

    assert len(result) == 2
