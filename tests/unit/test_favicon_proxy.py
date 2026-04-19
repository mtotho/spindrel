"""Tests for the favicon proxy endpoint.

The ``web_search`` HTML widget runs under a CSP that blocks cross-origin
images, so it fetches favicons through ``/api/v1/favicon?domain=...`` —
this test pins the domain-validation, caching, and scope requirements.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import api_v1_favicon


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-key"}


@pytest.fixture(autouse=True)
def _clear_cache():
    api_v1_favicon._CACHE.clear()
    yield
    api_v1_favicon._CACHE.clear()


@pytest.mark.asyncio
async def test_invalid_domain_rejected(auth_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/favicon?domain=not a domain", headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_missing_domain_422(auth_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/favicon", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fetches_and_caches(auth_headers):
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00fake"

    async def fake_fetch(domain):
        return fake_png, "image/png"

    with patch.object(api_v1_favicon, "_fetch_favicon", new=AsyncMock(side_effect=fake_fetch)) as mock:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.get("/api/v1/favicon?domain=example.com", headers=auth_headers)
            r2 = await client.get("/api/v1/favicon?domain=example.com", headers=auth_headers)
    assert r1.status_code == 200
    assert r1.content == fake_png
    assert r1.headers["content-type"].startswith("image/")
    assert r2.status_code == 200
    assert r2.content == fake_png
    assert mock.await_count == 1  # second call served from cache


@pytest.mark.asyncio
async def test_upstream_failure_404s(auth_headers):
    async def failing_fetch(domain):
        raise httpx.HTTPError("boom")

    with patch.object(api_v1_favicon, "_fetch_favicon", new=AsyncMock(side_effect=failing_fetch)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/favicon?domain=example.com", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cache_cap_enforced(auth_headers):
    fake_png = b"x"

    async def fake_fetch(domain):
        return fake_png, "image/png"

    original_cap = api_v1_favicon._CACHE_MAX
    api_v1_favicon._CACHE_MAX = 2
    try:
        with patch.object(api_v1_favicon, "_fetch_favicon", new=AsyncMock(side_effect=fake_fetch)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.get("/api/v1/favicon?domain=a.com", headers=auth_headers)
                await client.get("/api/v1/favicon?domain=b.com", headers=auth_headers)
                await client.get("/api/v1/favicon?domain=c.com", headers=auth_headers)
        assert "a.com" not in api_v1_favicon._CACHE
        assert "b.com" in api_v1_favicon._CACHE
        assert "c.com" in api_v1_favicon._CACHE
    finally:
        api_v1_favicon._CACHE_MAX = original_cap
