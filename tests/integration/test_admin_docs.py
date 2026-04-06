"""Tests for the /api/v1/admin/docs endpoint."""
import os
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.dependencies import ApiKeyAuth, verify_auth_or_user  # noqa: E402


def _build_app():
    from fastapi import FastAPI
    from app.routers.api_v1_admin.docs import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin")
    return app


@pytest_asyncio.fixture
async def client():
    app = _build_app()

    async def _mock_auth():
        return ApiKeyAuth(
            key_id=UUID("00000000-0000-0000-0000-000000000000"),
            scopes=["admin"],
            name="test",
        )

    app.dependency_overrides[verify_auth_or_user] = _mock_auth
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_docs_page_success(client):
    """GET /api/v1/admin/docs?path=integrations/index returns markdown content."""
    resp = await client.get("/api/v1/admin/docs", params={"path": "integrations/index"})
    assert resp.status_code == 200
    data = resp.json()
    assert "content" in data
    assert data["path"] == "integrations/index"
    assert len(data["content"]) > 0
    # Should contain markdown heading
    assert "#" in data["content"]


@pytest.mark.asyncio
async def test_get_docs_page_not_found(client):
    """GET /api/v1/admin/docs with nonexistent path returns 404."""
    resp = await client.get("/api/v1/admin/docs", params={"path": "nonexistent/page"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_docs_page_traversal_rejected(client):
    """Path traversal attempts are rejected."""
    resp = await client.get("/api/v1/admin/docs", params={"path": "../pyproject"})
    assert resp.status_code == 400

    resp = await client.get("/api/v1/admin/docs", params={"path": "integrations/../../etc/passwd"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_docs_page_absolute_path_rejected(client):
    """Absolute paths are rejected."""
    resp = await client.get("/api/v1/admin/docs", params={"path": "/etc/passwd"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_docs_page_caching(client):
    """Second request uses mtime cache (returns same content)."""
    resp1 = await client.get("/api/v1/admin/docs", params={"path": "integrations/index"})
    resp2 = await client.get("/api/v1/admin/docs", params={"path": "integrations/index"})
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["content"] == resp2.json()["content"]
