"""Error handling: 401/404 for bad auth and unknown resources."""

from typing import AsyncGenerator

import pytest
import pytest_asyncio

import httpx

from tests.e2e.harness.config import E2EConfig


@pytest.mark.e2e
class TestErrorHandling:
    @pytest_asyncio.fixture
    async def unauthenticated_client(
        self, e2e_config: E2EConfig,
    ) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Client with no auth header."""
        async with httpx.AsyncClient(
            base_url=e2e_config.base_url,
            timeout=httpx.Timeout(e2e_config.request_timeout),
        ) as c:
            yield c

    @pytest_asyncio.fixture
    async def bad_auth_client(
        self, e2e_config: E2EConfig,
    ) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Client with wrong API key."""
        async with httpx.AsyncClient(
            base_url=e2e_config.base_url,
            headers={"Authorization": "Bearer wrong-key-12345"},
            timeout=httpx.Timeout(e2e_config.request_timeout),
        ) as c:
            yield c

    async def test_no_auth_returns_401(
        self,
        e2e_env,  # noqa: ARG002
        unauthenticated_client: httpx.AsyncClient,
    ) -> None:
        """Request without auth header returns 401 or 403."""
        resp = await unauthenticated_client.get("/health")
        assert resp.status_code in (401, 403), (
            f"Expected 401/403 without auth, got {resp.status_code}"
        )

    async def test_wrong_api_key_returns_401(
        self,
        e2e_env,  # noqa: ARG002
        bad_auth_client: httpx.AsyncClient,
    ) -> None:
        """Request with wrong API key returns 401 or 403."""
        resp = await bad_auth_client.get("/health")
        assert resp.status_code in (401, 403), (
            f"Expected 401/403 with wrong key, got {resp.status_code}"
        )

    async def test_unknown_bot_returns_error(
        self,
        e2e_env,  # noqa: ARG002
        e2e_config: E2EConfig,
    ) -> None:
        """Chat with non-existent bot returns 404 or 400."""
        async with httpx.AsyncClient(
            base_url=e2e_config.base_url,
            headers={"Authorization": f"Bearer {e2e_config.api_key}"},
            timeout=httpx.Timeout(e2e_config.request_timeout),
        ) as c:
            resp = await c.post(
                "/chat",
                json={"message": "hello", "bot_id": "nonexistent-bot-xyz"},
            )
            assert resp.status_code in (400, 404, 422), (
                f"Expected error for unknown bot, got {resp.status_code}"
            )

    async def test_invalid_json_returns_422(
        self,
        e2e_env,  # noqa: ARG002
        e2e_config: E2EConfig,
    ) -> None:
        """Malformed request body returns 422."""
        async with httpx.AsyncClient(
            base_url=e2e_config.base_url,
            headers={
                "Authorization": f"Bearer {e2e_config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(e2e_config.request_timeout),
        ) as c:
            resp = await c.post("/chat", content=b"not json at all")
            assert resp.status_code == 422
