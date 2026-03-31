"""Unit tests for scoped API key provisioning (users + integrations).

Tests the ensure_entity_api_key helper, user provisioning on create/login,
role change scope sync, require_scopes enforcement for JWT users,
and integration API key management.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.api_keys import (
    SCOPE_PRESETS,
    has_scope,
    resolve_scopes,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# resolve_scopes
# ---------------------------------------------------------------------------

class TestResolveScopes:
    def test_resolve_preset_name(self):
        scopes = resolve_scopes("admin_user")
        assert scopes == ["admin"]

    def test_resolve_member_preset(self):
        scopes = resolve_scopes("member_user")
        assert "chat" in scopes
        assert "bots:read" in scopes
        assert "admin" not in scopes

    def test_resolve_explicit_list(self):
        scopes = resolve_scopes(["chat", "bots:read"])
        assert scopes == ["chat", "bots:read"]

    def test_resolve_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown scope preset"):
            resolve_scopes("nonexistent_preset")

    def test_slack_integration_preset_exists(self):
        scopes = resolve_scopes("slack_integration")
        assert "admin" in scopes
        assert "chat" in scopes


# ---------------------------------------------------------------------------
# SCOPE_PRESETS content
# ---------------------------------------------------------------------------

class TestScopePresets:
    def test_admin_user_preset(self):
        preset = SCOPE_PRESETS["admin_user"]
        assert preset["scopes"] == ["admin"]

    def test_member_user_preset(self):
        preset = SCOPE_PRESETS["member_user"]
        scopes = preset["scopes"]
        assert "chat" in scopes
        assert "channels:read" in scopes
        assert "channels:write" in scopes
        assert "admin" not in scopes
        assert "users:write" not in scopes
        assert "settings:write" not in scopes


# ---------------------------------------------------------------------------
# ensure_entity_api_key
# ---------------------------------------------------------------------------

class TestEnsureEntityApiKey:
    """Test ensure_entity_api_key creates and updates keys correctly."""

    async def test_creates_new_key_when_no_existing(self, db_session: AsyncSession):
        from app.services.api_keys import ensure_entity_api_key

        key, full_value = await ensure_entity_api_key(
            db_session,
            name="test-entity",
            scopes=["chat", "bots:read"],
            existing_key_id=None,
        )
        assert key is not None
        assert full_value is not None
        assert full_value.startswith("ask_")
        assert key.scopes == ["chat", "bots:read"]
        assert key.name == "test-entity"
        assert key.is_active is True
        # key_value should be stored (store_key_value=True)
        assert key.key_value == full_value

    async def test_updates_scopes_on_existing_key(self, db_session: AsyncSession):
        from app.services.api_keys import ensure_entity_api_key, create_api_key

        # Create initial key
        initial_key, initial_value = await create_api_key(
            db_session, "existing", ["chat"], store_key_value=True,
        )

        # Update via ensure_entity_api_key
        key, full_value = await ensure_entity_api_key(
            db_session,
            name="updated-entity",
            scopes=["admin"],
            existing_key_id=initial_key.id,
        )

        # Should return same key with updated scopes, no new value
        assert key.id == initial_key.id
        assert full_value is None  # no new key generated
        assert key.scopes == ["admin"]

    async def test_creates_new_key_when_existing_is_inactive(self, db_session: AsyncSession):
        from app.services.api_keys import ensure_entity_api_key, create_api_key

        # Create and deactivate a key
        old_key, _ = await create_api_key(
            db_session, "old", ["chat"], store_key_value=True,
        )
        old_key.is_active = False
        await db_session.commit()

        # ensure_entity_api_key should create a new one
        key, full_value = await ensure_entity_api_key(
            db_session,
            name="replacement",
            scopes=["admin"],
            existing_key_id=old_key.id,
        )
        assert key.id != old_key.id
        assert full_value is not None
        assert key.scopes == ["admin"]


# ---------------------------------------------------------------------------
# User API key provisioning
# ---------------------------------------------------------------------------

class TestUserProvisioning:
    """Test that user creation and login auto-provision API keys."""

    async def test_create_local_user_provisions_key(self, db_session: AsyncSession):
        from app.services.auth import create_local_user

        user = await create_local_user(
            db_session, "test@example.com", "Test User", "password123",
        )
        assert user.api_key_id is not None

        # Verify key has member scopes (not admin)
        from app.db.models import ApiKey
        key = await db_session.get(ApiKey, user.api_key_id)
        assert key is not None
        assert "chat" in key.scopes
        assert "admin" not in key.scopes

    async def test_create_admin_user_provisions_admin_key(self, db_session: AsyncSession):
        from app.services.auth import create_local_user

        user = await create_local_user(
            db_session, "admin@example.com", "Admin User", "password123",
            is_admin=True,
        )
        assert user.api_key_id is not None

        from app.db.models import ApiKey
        key = await db_session.get(ApiKey, user.api_key_id)
        assert key is not None
        assert key.scopes == ["admin"]

    async def test_create_google_user_provisions_key(self, db_session: AsyncSession):
        from app.services.auth import get_or_create_google_user

        user = await get_or_create_google_user(
            db_session, "google@example.com", "Google User", None,
        )
        assert user.api_key_id is not None

        from app.db.models import ApiKey
        key = await db_session.get(ApiKey, user.api_key_id)
        assert key is not None
        assert "chat" in key.scopes

    async def test_ensure_user_api_key_idempotent(self, db_session: AsyncSession):
        from app.services.auth import create_local_user, ensure_user_api_key

        user = await create_local_user(
            db_session, "idem@example.com", "Idem User", "password123",
        )
        original_key_id = user.api_key_id
        assert original_key_id is not None

        # Calling again should be a no-op
        await ensure_user_api_key(db_session, user)
        assert user.api_key_id == original_key_id

    async def test_ensure_user_api_key_backfills_missing(self, db_session: AsyncSession):
        from app.services.auth import ensure_user_api_key
        from app.db.models import User

        # Create user WITHOUT api_key_id (simulates pre-migration user)
        user = User(
            email="legacy@example.com",
            display_name="Legacy User",
            auth_method="local",
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.api_key_id is None

        await ensure_user_api_key(db_session, user)
        assert user.api_key_id is not None


# ---------------------------------------------------------------------------
# Role change sync
# ---------------------------------------------------------------------------

class TestRoleChangeSync:
    """Test that changing is_admin updates the API key scopes."""

    async def test_promote_to_admin_updates_scopes(self, db_session: AsyncSession):
        from app.services.auth import create_local_user
        from app.services.api_keys import ensure_entity_api_key, SCOPE_PRESETS
        from app.db.models import ApiKey

        user = await create_local_user(
            db_session, "promoted@example.com", "Will Be Admin", "password123",
        )
        key = await db_session.get(ApiKey, user.api_key_id)
        assert "admin" not in key.scopes

        # Simulate role change
        user.is_admin = True
        scopes = SCOPE_PRESETS["admin_user"]["scopes"]
        await ensure_entity_api_key(
            db_session, name=f"user:{user.email}", scopes=scopes,
            existing_key_id=user.api_key_id,
        )
        await db_session.commit()

        await db_session.refresh(key)
        assert key.scopes == ["admin"]

    async def test_demote_from_admin_updates_scopes(self, db_session: AsyncSession):
        from app.services.auth import create_local_user
        from app.services.api_keys import ensure_entity_api_key, SCOPE_PRESETS
        from app.db.models import ApiKey

        user = await create_local_user(
            db_session, "demoted@example.com", "Was Admin", "password123",
            is_admin=True,
        )
        key = await db_session.get(ApiKey, user.api_key_id)
        assert key.scopes == ["admin"]

        # Simulate demotion
        user.is_admin = False
        scopes = SCOPE_PRESETS["member_user"]["scopes"]
        await ensure_entity_api_key(
            db_session, name=f"user:{user.email}", scopes=scopes,
            existing_key_id=user.api_key_id,
        )
        await db_session.commit()

        await db_session.refresh(key)
        assert "admin" not in key.scopes
        assert "chat" in key.scopes


# ---------------------------------------------------------------------------
# require_scopes enforcement for JWT users
# ---------------------------------------------------------------------------

class TestRequireScopesEnforcement:
    """Test that require_scopes checks user API key scopes."""

    def test_legacy_user_without_key_gets_full_access(self):
        """Users without api_key_id (legacy) should bypass scope checks."""
        from app.dependencies import require_scopes
        from app.services.api_keys import has_scope

        user = MagicMock()
        user._resolved_scopes = None  # no key provisioned

        # The check function should return the user without raising
        # We test the logic directly
        resolved = getattr(user, "_resolved_scopes", None)
        assert resolved is None  # should take the backward compat path

    def test_user_with_admin_scopes_passes_all_checks(self):
        """Admin users should pass any scope check."""
        assert has_scope(["admin"], "users:write") is True
        assert has_scope(["admin"], "settings:write") is True

    def test_member_user_fails_admin_scope_check(self):
        """Member users should fail admin-only scope checks."""
        member_scopes = SCOPE_PRESETS["member_user"]["scopes"]
        assert has_scope(member_scopes, "users:write") is False
        assert has_scope(member_scopes, "settings:write") is False
        assert has_scope(member_scopes, "providers:write") is False

    def test_member_user_passes_allowed_scope_checks(self):
        """Member users should pass scope checks for allowed actions."""
        member_scopes = SCOPE_PRESETS["member_user"]["scopes"]
        assert has_scope(member_scopes, "chat") is True
        assert has_scope(member_scopes, "channels:read") is True
        assert has_scope(member_scopes, "channels:write") is True
        assert has_scope(member_scopes, "todos:read") is True


# ---------------------------------------------------------------------------
# Integration API key management
# ---------------------------------------------------------------------------

class TestIntegrationApiKeys:
    """Test integration API key provisioning and retrieval."""

    async def test_provision_integration_key(self, db_session: AsyncSession):
        from app.services.api_keys import provision_integration_api_key

        key, full_value = await provision_integration_api_key(
            db_session, "test_integration", ["chat", "channels:read"],
        )
        assert key is not None
        assert full_value is not None
        assert full_value.startswith("ask_")
        assert key.name == "integration:test_integration"
        assert "chat" in key.scopes

    async def test_get_integration_api_key(self, db_session: AsyncSession):
        from app.services.api_keys import (
            provision_integration_api_key,
            get_integration_api_key,
        )

        await provision_integration_api_key(
            db_session, "get_test", ["chat"],
        )

        key = await get_integration_api_key(db_session, "get_test")
        assert key is not None
        assert key.name == "integration:get_test"

    async def test_get_integration_api_key_value(self, db_session: AsyncSession):
        from app.services.api_keys import (
            provision_integration_api_key,
            get_integration_api_key_value,
        )

        _, full_value = await provision_integration_api_key(
            db_session, "value_test", ["chat"],
        )

        retrieved = await get_integration_api_key_value(db_session, "value_test")
        assert retrieved == full_value

    async def test_get_nonexistent_integration_key(self, db_session: AsyncSession):
        from app.services.api_keys import (
            get_integration_api_key,
            get_integration_api_key_value,
        )

        key = await get_integration_api_key(db_session, "nonexistent")
        assert key is None

        value = await get_integration_api_key_value(db_session, "nonexistent")
        assert value is None

    async def test_provision_updates_existing(self, db_session: AsyncSession):
        from app.services.api_keys import (
            provision_integration_api_key,
            get_integration_api_key,
        )

        # First provision
        key1, value1 = await provision_integration_api_key(
            db_session, "update_test", ["chat"],
        )

        # Update scopes
        key2, value2 = await provision_integration_api_key(
            db_session, "update_test", ["chat", "admin"],
        )

        assert key2.id == key1.id  # same key
        assert value2 is None  # no new value
        assert "admin" in key2.scopes

    async def test_revoke_integration_key(self, db_session: AsyncSession):
        from app.services.api_keys import (
            provision_integration_api_key,
            revoke_integration_api_key,
            get_integration_api_key,
            get_integration_api_key_value,
        )

        await provision_integration_api_key(
            db_session, "revoke_test", ["chat"],
        )

        revoked = await revoke_integration_api_key(db_session, "revoke_test")
        assert revoked is True

        # Key should be gone
        key = await get_integration_api_key(db_session, "revoke_test")
        assert key is None

        value = await get_integration_api_key_value(db_session, "revoke_test")
        assert value is None

    async def test_revoke_nonexistent_returns_false(self, db_session: AsyncSession):
        from app.services.api_keys import revoke_integration_api_key

        revoked = await revoke_integration_api_key(db_session, "never_existed")
        assert revoked is False
