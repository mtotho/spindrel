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


# ---------------------------------------------------------------------------
# GET /auth/me — scope hydration (Track - User Management Phase 2)
# ---------------------------------------------------------------------------

class TestAuthMeScopes:
    async def test_member_user_returns_member_scopes(self, auth_client, db_session):
        from app.services.auth import create_local_user
        client, app = auth_client

        user = await create_local_user(
            db_session, "member-me@test.com", "Member", "pw12345678"
        )
        app.dependency_overrides[verify_user] = lambda: user

        resp = await client.get("/auth/me", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_admin"] is False
        # member_user preset scopes are attached
        assert "chat" in data["scopes"]
        assert "channels:write" in data["scopes"]
        # admin scope absent
        assert "admin" not in data["scopes"]

    async def test_admin_user_returns_admin_scope(self, auth_client, db_session):
        from app.services.auth import create_local_user
        client, app = auth_client

        user = await create_local_user(
            db_session, "admin-me@test.com", "Admin", "pw12345678", is_admin=True
        )
        app.dependency_overrides[verify_user] = lambda: user

        resp = await client.get("/auth/me", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_admin"] is True
        assert data["scopes"] == ["admin"]

    async def test_user_without_api_key_non_admin_gets_empty_scopes(
        self, auth_client, db_session
    ):
        """A user whose provisioning silently failed lands here. UI hydrates
        empty scopes → renders no admin surface. Backend 403s on any scoped
        endpoint (see TestRequireScopesEnforcement). UI and backend agree."""
        client, app = auth_client
        orphan = User(
            id=uuid.uuid4(),
            email="orphan-me@test.com",
            display_name="Orphan",
            auth_method="local",
            password_hash="x",
            is_admin=False,
            integration_config={},
            api_key_id=None,
        )
        db_session.add(orphan)
        await db_session.commit()
        await db_session.refresh(orphan)

        app.dependency_overrides[verify_user] = lambda: orphan

        resp = await client.get("/auth/me", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        assert resp.json()["scopes"] == []

    async def test_admin_without_api_key_still_gets_admin_scope(
        self, auth_client, db_session
    ):
        """Admin recovery — if provisioning failed for the sole admin, they
        still see the admin surface via is_admin. Matches the require_scopes
        is_admin bypass."""
        client, app = auth_client
        orphan_admin = User(
            id=uuid.uuid4(),
            email="orphan-admin@test.com",
            display_name="Orphan Admin",
            auth_method="local",
            password_hash="x",
            is_admin=True,
            integration_config={},
            api_key_id=None,
        )
        db_session.add(orphan_admin)
        await db_session.commit()
        await db_session.refresh(orphan_admin)

        app.dependency_overrides[verify_user] = lambda: orphan_admin

        resp = await client.get("/auth/me", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        assert resp.json()["scopes"] == ["admin"]


# ---------------------------------------------------------------------------
# /auth/me/api-key — self-service API key (Track - User Management Phase 7)
# ---------------------------------------------------------------------------

class TestAuthMeApiKey:
    async def test_get_returns_null_when_no_key(self, auth_client, db_session):
        client, app = auth_client
        user = User(
            id=uuid.uuid4(),
            email=f"no-key-{uuid.uuid4().hex[:6]}@test.com",
            display_name="No Key",
            auth_method="local",
            password_hash="x",
            is_admin=False,
            integration_config={},
            api_key_id=None,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        app.dependency_overrides[verify_user] = lambda: user
        resp = await client.get("/auth/me/api-key", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        assert resp.json() is None

    async def test_get_returns_metadata_for_provisioned_user(
        self, auth_client, db_session
    ):
        from app.services.auth import create_local_user

        client, app = auth_client
        user = await create_local_user(
            db_session, f"kmeta-{uuid.uuid4().hex[:6]}@test.com", "Keyed", "pw12345678"
        )
        app.dependency_overrides[verify_user] = lambda: user

        resp = await client.get("/auth/me/api-key", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert data["id"]
        assert data["name"].startswith("user:")
        assert data["is_active"] is True
        # Never leaks plaintext
        assert "full_key" not in data
        assert "key_hash" not in data
        assert "key_value" not in data
        # Scopes reflect member preset
        assert "chat" in data["scopes"]
        assert "admin" not in data["scopes"]
        # key_prefix is 12 chars (SCOPE_PRESETS generate_key format)
        assert len(data["key_prefix"]) == 12

    async def test_rotate_mints_new_key_and_revokes_old(
        self, auth_client, db_session
    ):
        from app.services.auth import create_local_user
        from app.db.models import ApiKey as ApiKeyRow

        client, app = auth_client
        user = await create_local_user(
            db_session, f"rot-{uuid.uuid4().hex[:6]}@test.com", "Rotator", "pw12345678"
        )
        old_key_id = user.api_key_id
        assert old_key_id is not None

        app.dependency_overrides[verify_user] = lambda: user
        resp = await client.post(
            "/auth/me/api-key/rotate", headers={"Authorization": "Bearer fake"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["full_key"]  # plaintext returned ONCE
        assert data["full_key"].startswith(data["key"]["key_prefix"])
        new_key_id = data["key"]["id"]
        assert new_key_id != str(old_key_id)

        # user now points at the new key
        await db_session.refresh(user)
        assert str(user.api_key_id) == new_key_id

        # old key is deactivated (soft-revoke)
        old_row = await db_session.get(ApiKeyRow, old_key_id)
        assert old_row is not None
        assert old_row.is_active is False

        # new key is active and has the right scopes
        new_row = await db_session.get(ApiKeyRow, uuid.UUID(new_key_id))
        assert new_row is not None
        assert new_row.is_active is True
        assert "chat" in (new_row.scopes or [])

    async def test_rotate_admin_gets_admin_preset(self, auth_client, db_session):
        from app.services.auth import create_local_user

        client, app = auth_client
        user = await create_local_user(
            db_session,
            f"arot-{uuid.uuid4().hex[:6]}@test.com",
            "Admin Rot",
            "pw12345678",
            is_admin=True,
        )
        app.dependency_overrides[verify_user] = lambda: user

        resp = await client.post(
            "/auth/me/api-key/rotate", headers={"Authorization": "Bearer fake"}
        )
        assert resp.status_code == 200
        scopes = resp.json()["key"]["scopes"]
        assert "admin" in scopes

    async def test_rotate_mints_first_key_when_none_exists(
        self, auth_client, db_session
    ):
        client, app = auth_client
        orphan = User(
            id=uuid.uuid4(),
            email=f"orphan-rot-{uuid.uuid4().hex[:6]}@test.com",
            display_name="Orphan Rot",
            auth_method="local",
            password_hash="x",
            is_admin=False,
            integration_config={},
            api_key_id=None,
        )
        db_session.add(orphan)
        await db_session.commit()
        await db_session.refresh(orphan)
        assert orphan.api_key_id is None

        app.dependency_overrides[verify_user] = lambda: orphan
        resp = await client.post(
            "/auth/me/api-key/rotate", headers={"Authorization": "Bearer fake"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["full_key"]
        await db_session.refresh(orphan)
        assert orphan.api_key_id is not None


# ---------------------------------------------------------------------------
# /auth/me/bots — owned + granted (Track - User Management Phase 7)
# ---------------------------------------------------------------------------

class TestAuthMeBots:
    async def test_returns_owned_bots_with_owner_role(self, auth_client, db_session):
        from app.db.models import Bot as BotRow
        from app.services.auth import create_local_user

        client, app = auth_client
        user = await create_local_user(
            db_session, f"mybots-{uuid.uuid4().hex[:6]}@test.com", "Owner", "pw12345678"
        )
        bot = BotRow(
            id=f"bot-{uuid.uuid4().hex[:8]}",
            name="My Bot",
            model="test-model",
            system_prompt="",
            user_id=user.id,
        )
        db_session.add(bot)
        await db_session.commit()

        app.dependency_overrides[verify_user] = lambda: user
        resp = await client.get("/auth/me/bots", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == bot.id
        assert data[0]["role"] == "owner"

    async def test_returns_granted_bots_with_grant_role(self, auth_client, db_session):
        from app.db.models import Bot as BotRow, BotGrant
        from app.services.auth import create_local_user

        client, app = auth_client
        owner = await create_local_user(
            db_session, f"owner-{uuid.uuid4().hex[:6]}@test.com", "Owner", "pw12345678"
        )
        grantee = await create_local_user(
            db_session, f"grantee-{uuid.uuid4().hex[:6]}@test.com", "Grantee", "pw12345678"
        )
        bot = BotRow(
            id=f"bot-{uuid.uuid4().hex[:8]}",
            name="Shared Bot",
            model="test-model",
            system_prompt="",
            user_id=owner.id,
        )
        db_session.add(bot)
        await db_session.flush()
        db_session.add(BotGrant(bot_id=bot.id, user_id=grantee.id, role="view"))
        await db_session.commit()

        app.dependency_overrides[verify_user] = lambda: grantee
        resp = await client.get("/auth/me/bots", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == bot.id
        assert data[0]["role"] == "view"

    async def test_owner_role_wins_when_user_is_both_owner_and_grantee(
        self, auth_client, db_session
    ):
        from app.db.models import Bot as BotRow, BotGrant
        from app.services.auth import create_local_user

        client, app = auth_client
        user = await create_local_user(
            db_session, f"dual-{uuid.uuid4().hex[:6]}@test.com", "Dual", "pw12345678"
        )
        bot = BotRow(
            id=f"bot-{uuid.uuid4().hex[:8]}",
            name="Self-granted",
            model="test-model",
            system_prompt="",
            user_id=user.id,
        )
        db_session.add(bot)
        await db_session.flush()
        db_session.add(BotGrant(bot_id=bot.id, user_id=user.id, role="view"))
        await db_session.commit()

        app.dependency_overrides[verify_user] = lambda: user
        resp = await client.get("/auth/me/bots", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["role"] == "owner"

    async def test_returns_empty_for_user_with_no_bots(self, auth_client, db_session):
        from app.services.auth import create_local_user

        client, app = auth_client
        user = await create_local_user(
            db_session, f"nobots-{uuid.uuid4().hex[:6]}@test.com", "Empty", "pw12345678"
        )
        app.dependency_overrides[verify_user] = lambda: user
        resp = await client.get("/auth/me/bots", headers={"Authorization": "Bearer fake"})
        assert resp.status_code == 200
        assert resp.json() == []
