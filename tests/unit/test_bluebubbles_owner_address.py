"""Regression tests for BlueBubbles `_fetch_owner_address` cache behavior.

Bug captured: a single failed lookup (no aliases in API response, or HTTP
error) used to write `""` to the process-local cache, which then short-
circuited every subsequent webhook so `[unknown]` rendered for every
is_from_me message until process restart.

Contract under test: failures DO NOT cache; only successful resolutions do.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from integrations.bluebubbles import router as bb_router


@pytest.fixture(autouse=True)
def _reset_owner_cache():
    bb_router._owner_address.clear()
    yield
    bb_router._owner_address.clear()


def _fake_response(payload: dict) -> AsyncMock:
    resp = AsyncMock(spec=httpx.Response)
    resp.json = lambda: payload
    resp.raise_for_status = lambda: None
    return resp


class TestFetchOwnerAddress:
    @pytest.mark.asyncio
    async def test_when_alias_present_then_phone_cached(self):
        ok = _fake_response({"data": {"iMessageAliases": ["+15551234567", "user@example.com"]}})
        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=ok)
            result = await bb_router._fetch_owner_address("http://bb", "pw")
        assert result == "+15551234567"
        assert bb_router._owner_address.get("phone") == "+15551234567"

    @pytest.mark.asyncio
    async def test_when_no_phone_in_aliases_then_not_cached(self):
        empty = _fake_response({"data": {"iMessageAliases": ["user@example.com"]}})
        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=empty)
            result = await bb_router._fetch_owner_address("http://bb", "pw")
        assert result is None
        # Critical: empty result must NOT be cached. Otherwise subsequent
        # webhooks short-circuit and every is_from_me renders [unknown].
        assert "phone" not in bb_router._owner_address

    @pytest.mark.asyncio
    async def test_when_api_raises_then_not_cached(self):
        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("boom"),
            )
            result = await bb_router._fetch_owner_address("http://bb", "pw")
        assert result is None
        assert "phone" not in bb_router._owner_address

    @pytest.mark.asyncio
    async def test_when_initial_failure_then_retry_succeeds(self):
        """The whole point: a transient failure must not poison future calls."""
        empty = _fake_response({"data": {"iMessageAliases": []}})
        ok = _fake_response({"data": {"iMessageAliases": ["+15551234567"]}})

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=[empty, ok],
            )
            first = await bb_router._fetch_owner_address("http://bb", "pw")
            second = await bb_router._fetch_owner_address("http://bb", "pw")

        assert first is None
        assert second == "+15551234567"
        assert bb_router._owner_address.get("phone") == "+15551234567"

    @pytest.mark.asyncio
    async def test_when_phone_already_cached_then_short_circuits(self):
        bb_router._owner_address["phone"] = "+15559999999"
        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.get = AsyncMock()
            result = await bb_router._fetch_owner_address("http://bb", "pw")
        assert result == "+15559999999"
        client_cls.return_value.__aenter__.return_value.get.assert_not_called()
