"""Smoke test: server is up and healthy."""

import pytest

from tests.e2e.harness.client import E2EClient


@pytest.mark.e2e
class TestHealth:
    async def test_health_returns_ok(self, client: E2EClient) -> None:
        """GET /health returns 200 with healthy=True."""
        body = await client.health()
        assert body["healthy"] is True
        assert body["database"] is True

    async def test_health_has_bot_count(self, client: E2EClient) -> None:
        """Health endpoint reports at least one bot loaded."""
        body = await client.health()
        assert body["bot_count"] >= 1

    async def test_health_has_uptime(self, client: E2EClient) -> None:
        """Health endpoint reports uptime in seconds."""
        body = await client.health()
        assert isinstance(body["uptime_seconds"], int)
        assert body["uptime_seconds"] >= 0
