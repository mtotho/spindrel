"""Integration tests for auth profile endpoints: /auth/integrations, /auth/me/change-password."""
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.dependencies import get_db, verify_user
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_local_user(db, password_hash=None):
    from app.services.auth import hash_password
    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@test.com",
        display_name="Test User",
        auth_method="local",
        password_hash=password_hash or hash_password("oldpassword"),
        is_admin=False,
        integration_config={},
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# We need a client that injects the auth router and overrides verify_user
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def auth_client(db_session):
    """FastAPI test client with auth router included."""
    from fastapi import FastAPI
    from app.routers.auth import router as auth_router

    app = FastAPI()
    app.include_router(auth_router)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, app

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /auth/integrations
# ---------------------------------------------------------------------------

class TestAuthIntegrations:
    async def test_returns_list(self, auth_client):
        client, _ = auth_client
        resp = await client.get("/auth/integrations")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_includes_slack_when_available(self, auth_client):
        client, _ = auth_client
        # Mock discover_identity_fields to return slack
        mock_fields = [
            {
                "id": "slack",
                "name": "Slack",
                "fields": [{"key": "user_id", "label": "Slack User ID", "description": "test"}],
            }
        ]
        with patch("integrations.discover_identity_fields", return_value=mock_fields):
            resp = await client.get("/auth/integrations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "slack"
        assert data[0]["fields"][0]["key"] == "user_id"


# ---------------------------------------------------------------------------
# POST /auth/me/change-password
# ---------------------------------------------------------------------------

class TestChangePassword:
    async def test_change_password_success(self, auth_client, db_session):
        client, app = auth_client
        user = await _create_local_user(db_session)

        # Override verify_user to return our test user
        app.dependency_overrides[verify_user] = lambda: user

        resp = await client.post(
            "/auth/me/change-password",
            json={"current_password": "oldpassword", "new_password": "newpassword123"},
            headers={"Authorization": "Bearer fake-jwt"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify password was actually changed
        await db_session.refresh(user)
        from app.services.auth import verify_password
        assert verify_password("newpassword123", user.password_hash)

    async def test_change_password_wrong_current(self, auth_client, db_session):
        client, app = auth_client
        user = await _create_local_user(db_session)
        app.dependency_overrides[verify_user] = lambda: user

        resp = await client.post(
            "/auth/me/change-password",
            json={"current_password": "wrongpassword", "new_password": "newpassword123"},
            headers={"Authorization": "Bearer fake-jwt"},
        )
        assert resp.status_code == 401

    async def test_change_password_too_short(self, auth_client, db_session):
        client, app = auth_client
        user = await _create_local_user(db_session)
        app.dependency_overrides[verify_user] = lambda: user

        resp = await client.post(
            "/auth/me/change-password",
            json={"current_password": "oldpassword", "new_password": "short"},
            headers={"Authorization": "Bearer fake-jwt"},
        )
        assert resp.status_code == 400

    async def test_change_password_non_local_auth(self, auth_client, db_session):
        client, app = auth_client
        user = User(
            id=uuid.uuid4(),
            email="google@test.com",
            display_name="Google User",
            auth_method="google",
            password_hash=None,
            is_admin=False,
            integration_config={},
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        app.dependency_overrides[verify_user] = lambda: user

        resp = await client.post(
            "/auth/me/change-password",
            json={"current_password": "anything", "new_password": "newpassword123"},
            headers={"Authorization": "Bearer fake-jwt"},
        )
        assert resp.status_code == 400
        assert "local auth" in resp.json()["detail"]
