"""Integration tests for API key CRUD, auth, and discovery."""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import AUTH_HEADERS, _TEST_REGISTRY, _get_test_bot

# Re-use the db fixtures from conftest
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app():
    """Build a minimal FastAPI test app."""
    from fastapi import FastAPI
    from app.routers.api_v1 import router as api_v1_router
    from app.routers.chat import router as chat_router
    return FastAPI().include_router(api_v1_router) or FastAPI()


@pytest_asyncio.fixture
async def api_client(db_session):
    """Client with standard admin auth override."""
    from fastapi import FastAPI
    from app.routers.api_v1 import router as api_v1_router
    from app.routers.chat import router as chat_router
    from app.dependencies import ApiKeyAuth, get_db, verify_auth, verify_admin_auth, verify_auth_or_user

    app = FastAPI()
    app.include_router(api_v1_router)
    app.include_router(chat_router)

    _admin_auth = ApiKeyAuth(
        key_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        scopes=["admin"],
        name="test",
    )

    async def _override_get_db():
        yield db_session

    async def _override_verify_auth():
        return "test-key"

    async def _override_admin():
        return _admin_auth

    async def _override_auth_or_user():
        return _admin_auth

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth] = _override_verify_auth
    app.dependency_overrides[verify_admin_auth] = _override_admin
    app.dependency_overrides[verify_auth_or_user] = _override_auth_or_user

    # Populate endpoint catalog for discover tests
    from app.services.endpoint_catalog import build_endpoint_catalog
    catalog = build_endpoint_catalog(app)

    with (
        patch("app.agent.bots._registry", _TEST_REGISTRY),
        patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
        patch("app.agent.persona.get_persona", return_value=None),
        patch("app.routers.api_v1_discover.ENDPOINT_CATALOG", catalog),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# CRUD Tests
# ---------------------------------------------------------------------------

class TestApiKeyCRUD:
    async def test_create_and_list(self, api_client: AsyncClient):
        # Create
        resp = await api_client.post(
            "/api/v1/admin/api-keys",
            json={"name": "Test Key", "scopes": ["chat", "channels:read"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "full_key" in data
        assert data["full_key"].startswith("ask_")
        assert data["key"]["name"] == "Test Key"
        assert set(data["key"]["scopes"]) == {"chat", "channels:read"}
        assert data["key"]["is_active"] is True

        key_id = data["key"]["id"]

        # List
        resp = await api_client.get("/api/v1/admin/api-keys", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        keys = resp.json()
        assert any(k["id"] == key_id for k in keys)
        # Full key should NOT appear in list
        for k in keys:
            assert "full_key" not in k

    async def test_get_detail(self, api_client: AsyncClient):
        resp = await api_client.post(
            "/api/v1/admin/api-keys",
            json={"name": "Detail Key", "scopes": ["admin"]},
            headers=AUTH_HEADERS,
        )
        key_id = resp.json()["key"]["id"]

        resp = await api_client.get(
            f"/api/v1/admin/api-keys/{key_id}", headers=AUTH_HEADERS
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Detail Key"

    async def test_update(self, api_client: AsyncClient):
        resp = await api_client.post(
            "/api/v1/admin/api-keys",
            json={"name": "Update Me", "scopes": ["chat"]},
            headers=AUTH_HEADERS,
        )
        key_id = resp.json()["key"]["id"]

        resp = await api_client.put(
            f"/api/v1/admin/api-keys/{key_id}",
            json={"name": "Updated", "scopes": ["chat", "channels:write"], "is_active": False},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"
        assert resp.json()["is_active"] is False
        assert "channels:write" in resp.json()["scopes"]

    async def test_delete(self, api_client: AsyncClient):
        resp = await api_client.post(
            "/api/v1/admin/api-keys",
            json={"name": "Delete Me", "scopes": []},
            headers=AUTH_HEADERS,
        )
        key_id = resp.json()["key"]["id"]

        resp = await api_client.delete(
            f"/api/v1/admin/api-keys/{key_id}", headers=AUTH_HEADERS
        )
        assert resp.status_code == 200

        resp = await api_client.get(
            f"/api/v1/admin/api-keys/{key_id}", headers=AUTH_HEADERS
        )
        assert resp.status_code == 404

    async def test_scopes_endpoint(self, api_client: AsyncClient):
        resp = await api_client.get(
            "/api/v1/admin/api-keys/scopes", headers=AUTH_HEADERS
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "groups" in data
        assert "all_scopes" in data
        assert "admin" in data["all_scopes"]
        assert "Chat" in data["groups"]

    async def test_invalid_scopes_rejected(self, api_client: AsyncClient):
        resp = await api_client.post(
            "/api/v1/admin/api-keys",
            json={"name": "Bad", "scopes": ["invalid:scope"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    async def test_not_found(self, api_client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await api_client.get(
            f"/api/v1/admin/api-keys/{fake_id}", headers=AUTH_HEADERS
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth Integration Tests
# ---------------------------------------------------------------------------

class TestApiKeyAuth:
    async def test_scoped_key_auth_success(self, api_client: AsyncClient, db_session: AsyncSession):
        """Scoped key with chat scope should access chat endpoints."""
        from app.services.api_keys import create_api_key

        row, full_key = await create_api_key(db_session, "auth-test", ["chat", "channels:read"])

        # The discover endpoint uses verify_auth_or_user which should accept ask_ keys.
        # We test via the raw dependency resolution.
        from app.services.api_keys import validate_api_key, has_scope
        validated = await validate_api_key(db_session, full_key)
        assert validated is not None
        assert validated.name == "auth-test"
        assert has_scope(validated.scopes, "chat") is True
        assert has_scope(validated.scopes, "channels:read") is True
        assert has_scope(validated.scopes, "channels:write") is False

    async def test_expired_key_rejected(self, api_client: AsyncClient, db_session: AsyncSession):
        """Expired key should be rejected."""
        from app.services.api_keys import create_api_key

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        row, full_key = await create_api_key(
            db_session, "expired-key", ["chat"], expires_at=past
        )

        from app.services.api_keys import validate_api_key
        result = await validate_api_key(db_session, full_key)
        assert result is None

    async def test_inactive_key_rejected(self, api_client: AsyncClient, db_session: AsyncSession):
        """Inactive key should be rejected."""
        from app.services.api_keys import create_api_key

        row, full_key = await create_api_key(db_session, "inactive-key", ["chat"])
        row.is_active = False
        await db_session.commit()

        from app.services.api_keys import validate_api_key
        result = await validate_api_key(db_session, full_key)
        assert result is None


# ---------------------------------------------------------------------------
# Discovery Endpoint Tests
# ---------------------------------------------------------------------------

class TestDiscovery:
    async def test_discover_full_access(self, api_client: AsyncClient):
        """Static API key sees all endpoints."""
        resp = await api_client.get("/api/v1/discover", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "endpoints" in data
        assert len(data["endpoints"]) > 0
        # Should include chat and channels endpoints
        paths = [ep["path"] for ep in data["endpoints"]]
        assert "/chat" in paths
        assert "/api/v1/channels" in paths
