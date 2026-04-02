"""Tests for scoped API key authentication on admin endpoints.

Verifies that the admin router's verify_admin_auth dependency correctly
passes scoped keys through to endpoint-level require_scopes() checks,
rather than requiring the 'admin' scope for all admin routes.

This was a real bug: bots with granular scopes like 'logs:read' got
"Admin access denied" because verify_admin_auth required 'admin' scope
before the endpoint's require_scopes could run.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import _TEST_REGISTRY, _get_test_bot

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixture: test client with REAL auth (no verify_admin_auth override)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def real_auth_client(db_session):
    """Client that does NOT override verify_admin_auth.

    Only get_db is overridden so we use the test database.
    This lets us test the real authentication chain end-to-end.
    """
    from fastapi import FastAPI
    from app.routers.api_v1 import router as api_v1_router
    from app.dependencies import get_db

    app = FastAPI()
    app.include_router(api_v1_router)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with (
        patch("app.agent.bots._registry", _TEST_REGISTRY),
        patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
        patch("app.agent.persona.get_persona", return_value=None),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_scoped_key(db: AsyncSession, scopes: list[str], name: str = "test-key") -> str:
    """Create a scoped API key and return the full key string."""
    from app.services.api_keys import create_api_key
    _, full_key = await create_api_key(db, name, scopes)
    return full_key


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------------------
# Tests: scoped key access to admin endpoints (the original bug)
# ---------------------------------------------------------------------------

class TestScopedKeyAdminAccess:
    """Test that scoped API keys can access admin endpoints when they have
    the right granular scope — not just 'admin'."""

    async def test_logs_read_scope_accesses_server_logs(
        self, real_auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Key with logs:read should access /admin/server-logs.

        This is the exact bug scenario: a bot with logs:read got
        'Admin access denied' because verify_admin_auth required 'admin'.
        """
        key = await _create_scoped_key(db_session, ["logs:read"])

        with patch("app.services.log_buffer.get_handler", return_value=None):
            resp = await real_auth_client.get(
                "/api/v1/admin/server-logs", headers=_auth(key)
            )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    async def test_logs_read_scope_accesses_log_level(
        self, real_auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Key with logs:read should access /admin/log-level."""
        key = await _create_scoped_key(db_session, ["logs:read"])

        resp = await real_auth_client.get(
            "/api/v1/admin/log-level", headers=_auth(key)
        )
        assert resp.status_code == 200

    async def test_admin_scope_accesses_server_logs(
        self, real_auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Key with admin scope should still work (regression check)."""
        key = await _create_scoped_key(db_session, ["admin"])

        with patch("app.services.log_buffer.get_handler", return_value=None):
            resp = await real_auth_client.get(
                "/api/v1/admin/server-logs", headers=_auth(key)
            )
        assert resp.status_code == 200

    async def test_static_api_key_accesses_admin(
        self, real_auth_client: AsyncClient
    ):
        """Static API_KEY should access admin endpoints (backward compat)."""
        with patch("app.services.log_buffer.get_handler", return_value=None):
            resp = await real_auth_client.get(
                "/api/v1/admin/server-logs",
                headers={"Authorization": "Bearer test-key"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: scope enforcement (wrong scope should be rejected)
# ---------------------------------------------------------------------------

class TestScopeEnforcement:
    """Test that require_scopes correctly rejects keys without the right scope."""

    async def test_wrong_scope_rejected_at_endpoint(
        self, real_auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Key with chat scope should NOT access /admin/server-logs (needs logs:read)."""
        key = await _create_scoped_key(db_session, ["chat"])

        resp = await real_auth_client.get(
            "/api/v1/admin/server-logs", headers=_auth(key)
        )
        assert resp.status_code == 403
        assert "Missing required scope" in resp.json()["detail"]

    async def test_logs_read_cannot_set_log_level(
        self, real_auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Key with logs:read should NOT be able to PUT /admin/log-level (needs logs:write)."""
        key = await _create_scoped_key(db_session, ["logs:read"])

        resp = await real_auth_client.put(
            "/api/v1/admin/log-level",
            json={"level": "DEBUG"},
            headers=_auth(key),
        )
        assert resp.status_code == 403
        assert "Missing required scope" in resp.json()["detail"]

    async def test_logs_write_can_set_log_level(
        self, real_auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Key with logs:write should be able to PUT /admin/log-level."""
        key = await _create_scoped_key(db_session, ["logs:write"])

        resp = await real_auth_client.put(
            "/api/v1/admin/log-level",
            json={"level": "WARNING"},
            headers=_auth(key),
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: authentication failures
# ---------------------------------------------------------------------------

class TestAdminAuthRejection:
    """Test that invalid/missing/empty-scope keys are properly rejected."""

    async def test_no_auth_header_rejected(self, real_auth_client: AsyncClient):
        """Missing Authorization header should return 422 (FastAPI validation)."""
        resp = await real_auth_client.get("/api/v1/admin/server-logs")
        assert resp.status_code == 422

    async def test_invalid_key_rejected(self, real_auth_client: AsyncClient):
        """Random bearer token should be rejected."""
        resp = await real_auth_client.get(
            "/api/v1/admin/server-logs",
            headers={"Authorization": "Bearer invalid-random-token"},
        )
        assert resp.status_code == 403

    async def test_invalid_scoped_key_rejected(self, real_auth_client: AsyncClient):
        """Fake ask_ key should be rejected."""
        resp = await real_auth_client.get(
            "/api/v1/admin/server-logs",
            headers={"Authorization": "Bearer ask_fakefakefake"},
        )
        assert resp.status_code == 403

    async def test_empty_scopes_key_rejected(
        self, real_auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Key with empty scopes should be rejected at admin gate."""
        key = await _create_scoped_key(db_session, [], name="empty-scopes")

        resp = await real_auth_client.get(
            "/api/v1/admin/server-logs", headers=_auth(key)
        )
        assert resp.status_code == 403

    async def test_expired_key_rejected(
        self, real_auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Expired key should be rejected."""
        from app.services.api_keys import create_api_key

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        _, full_key = await create_api_key(
            db_session, "expired", ["logs:read"], expires_at=past
        )

        resp = await real_auth_client.get(
            "/api/v1/admin/server-logs", headers=_auth(full_key)
        )
        assert resp.status_code == 403

    async def test_inactive_key_rejected(
        self, real_auth_client: AsyncClient, db_session: AsyncSession
    ):
        """Deactivated key should be rejected."""
        from app.services.api_keys import create_api_key

        row, full_key = await create_api_key(db_session, "inactive", ["logs:read"])
        row.is_active = False
        await db_session.commit()

        resp = await real_auth_client.get(
            "/api/v1/admin/server-logs", headers=_auth(full_key)
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: ADMIN_API_KEY behavior
# ---------------------------------------------------------------------------

class TestAdminApiKeyConfig:
    """Test verify_admin_auth behavior when ADMIN_API_KEY is configured."""

    async def test_admin_api_key_passes_admin_gate(self, db_session: AsyncSession):
        """When ADMIN_API_KEY is set, it passes verify_admin_auth for admin-only
        endpoints (those without their own require_scopes).

        Note: endpoints with require_scopes use verify_auth_or_user which does NOT
        check ADMIN_API_KEY — so ADMIN_API_KEY + require_scopes endpoints = 401.
        This is a known limitation: ADMIN_API_KEY is for the admin gate only.
        For endpoints with require_scopes, use the regular API_KEY or scoped keys.
        """
        from fastapi import FastAPI, APIRouter, Depends
        from app.dependencies import get_db, verify_admin_auth

        # Create a minimal admin endpoint WITHOUT require_scopes to test the gate
        admin_router = APIRouter(
            prefix="/api/v1/admin",
            dependencies=[Depends(verify_admin_auth)],
        )

        @admin_router.get("/test-gate")
        async def test_gate():
            return {"ok": True}

        app = FastAPI()
        app.include_router(admin_router)

        async def _override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = _override_get_db

        with patch("app.config.settings.ADMIN_API_KEY", "secret-admin-key"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/v1/admin/test-gate",
                    headers={"Authorization": "Bearer secret-admin-key"},
                )
            assert resp.status_code == 200

        app.dependency_overrides.clear()

    async def test_regular_api_key_rejected_when_admin_key_set(self, db_session: AsyncSession):
        """When ADMIN_API_KEY is set, regular API_KEY should NOT work for admin routes."""
        from fastapi import FastAPI
        from app.routers.api_v1 import router as api_v1_router
        from app.dependencies import get_db

        app = FastAPI()
        app.include_router(api_v1_router)

        async def _override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = _override_get_db

        with (
            patch("app.config.settings.ADMIN_API_KEY", "secret-admin-key"),
            patch("app.agent.bots._registry", _TEST_REGISTRY),
            patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
            patch("app.agent.persona.get_persona", return_value=None),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/v1/admin/server-logs",
                    headers={"Authorization": "Bearer test-key"},
                )
            # Regular API_KEY should be rejected when ADMIN_API_KEY is set
            assert resp.status_code == 403

        app.dependency_overrides.clear()

    async def test_scoped_key_works_even_with_admin_key_set(self, db_session: AsyncSession):
        """Scoped key with right scope should work even when ADMIN_API_KEY is configured."""
        from fastapi import FastAPI
        from app.routers.api_v1 import router as api_v1_router
        from app.dependencies import get_db

        key = await _create_scoped_key(db_session, ["logs:read"])

        app = FastAPI()
        app.include_router(api_v1_router)

        async def _override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = _override_get_db

        with (
            patch("app.config.settings.ADMIN_API_KEY", "secret-admin-key"),
            patch("app.agent.bots._registry", _TEST_REGISTRY),
            patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
            patch("app.agent.persona.get_persona", return_value=None),
            patch("app.services.log_buffer.get_handler", return_value=None),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/v1/admin/server-logs", headers=_auth(key),
                )
            assert resp.status_code == 200

        app.dependency_overrides.clear()
