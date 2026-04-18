"""Tests for app.services.secret_values — encrypted env var vault."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models import SecretValue
from app.services import secret_values


@pytest.fixture
def secret_cache_reset():
    """Snapshot + clear the module-level _cache before + after each test (B.28)."""
    snapshot = dict(secret_values._cache)
    secret_values._cache.clear()
    yield
    secret_values._cache.clear()
    secret_values._cache.update(snapshot)


@pytest.fixture
def rebuild_registry_mock():
    """Patch _rebuild_registry — otherwise it recurses into secret_registry which
    opens its own async_session and rebuilds global regex state (E.1)."""
    with patch(
        "app.services.secret_values._rebuild_registry",
        new_callable=AsyncMock,
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# get_env_dict — returns cached plaintext values
# ---------------------------------------------------------------------------

class TestGetEnvDict:
    def test_when_cache_empty_then_returns_empty_dict(self, secret_cache_reset):
        assert secret_values.get_env_dict() == {}

    def test_when_cache_populated_then_returns_cached_pairs(self, secret_cache_reset):
        secret_values._cache["MY_KEY"] = "my-value"
        secret_values._cache["OTHER_KEY"] = "other-value"

        result = secret_values.get_env_dict()

        assert result == {"MY_KEY": "my-value", "OTHER_KEY": "other-value"}

    def test_when_caller_mutates_result_then_cache_unaffected(self, secret_cache_reset):
        secret_values._cache["MY_KEY"] = "my-value"

        result = secret_values.get_env_dict()
        result["MY_KEY"] = "tampered"

        assert secret_values._cache["MY_KEY"] == "my-value"


# ---------------------------------------------------------------------------
# load_from_db — real DB + real encrypt/decrypt round trip
# ---------------------------------------------------------------------------

class TestLoadFromDb:
    @pytest.mark.asyncio
    async def test_when_rows_present_then_cache_populated_with_plaintext(
        self, db_session, patched_async_sessions, secret_cache_reset
    ):
        # encrypt() is a no-op when ENCRYPTION_KEY is empty — stored value is
        # plaintext, decrypt() passes it through unchanged.
        db_session.add(SecretValue(name="DEPLOY_KEY", value="deploy-secret-abc"))
        db_session.add(SecretValue(name="SLACK_TOKEN", value="xoxb-slack-123"))
        await db_session.commit()

        await secret_values.load_from_db()

        assert secret_values._cache == {
            "DEPLOY_KEY": "deploy-secret-abc",
            "SLACK_TOKEN": "xoxb-slack-123",
        }

    @pytest.mark.asyncio
    async def test_when_no_rows_then_cache_empty(
        self, db_session, patched_async_sessions, secret_cache_reset
    ):
        secret_values._cache["STALE"] = "stale-value"

        await secret_values.load_from_db()

        assert secret_values._cache == {}


# ---------------------------------------------------------------------------
# list_secrets — public API, redacts values
# ---------------------------------------------------------------------------

class TestListSecrets:
    @pytest.mark.asyncio
    async def test_when_rows_present_then_returns_metadata_without_value(
        self, db_session, secret_cache_reset
    ):
        db_session.add(SecretValue(name="ALPHA_KEY", value="alpha-val", description="alpha"))
        db_session.add(SecretValue(name="BETA_KEY", value="beta-val", description="beta"))
        await db_session.commit()

        result = await secret_values.list_secrets(db_session)

        names = [r["name"] for r in result]
        assert names == ["ALPHA_KEY", "BETA_KEY"]
        assert all(r["has_value"] for r in result)
        assert "value" not in result[0]


# ---------------------------------------------------------------------------
# create_secret — real DB
# ---------------------------------------------------------------------------

class TestCreateSecret:
    @pytest.mark.asyncio
    async def test_when_called_then_row_persisted_and_cache_populated(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        result = await secret_values.create_secret(
            db_session,
            name="GITHUB_TOKEN",
            value="ghp_real_token_value",
            description="Test GitHub token",
            created_by="admin@example.com",
        )

        row = (
            await db_session.execute(select(SecretValue).where(SecretValue.name == "GITHUB_TOKEN"))
        ).scalar_one()
        assert result["name"] == "GITHUB_TOKEN"
        assert result["has_value"] is True
        assert result["created_by"] == "admin@example.com"
        assert secret_values._cache["GITHUB_TOKEN"] == "ghp_real_token_value"
        assert row.description == "Test GitHub token"

    @pytest.mark.asyncio
    async def test_when_value_encrypted_in_db_then_cache_stores_plaintext(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        with patch("app.services.secret_values.encrypt", return_value="enc:ciphertext"):
            await secret_values.create_secret(db_session, name="ENCRYPTED_KEY", value="plain-value")

        row = (
            await db_session.execute(select(SecretValue).where(SecretValue.name == "ENCRYPTED_KEY"))
        ).scalar_one()
        assert row.value == "enc:ciphertext"
        assert secret_values._cache["ENCRYPTED_KEY"] == "plain-value"

    @pytest.mark.asyncio
    async def test_when_sibling_secret_exists_then_create_does_not_touch_it(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        await secret_values.create_secret(db_session, name="OG_KEY", value="og-val")

        await secret_values.create_secret(db_session, name="NEW_KEY", value="new-val")

        og_row = (
            await db_session.execute(select(SecretValue).where(SecretValue.name == "OG_KEY"))
        ).scalar_one()
        assert og_row.value == "og-val"
        assert secret_values._cache == {"OG_KEY": "og-val", "NEW_KEY": "new-val"}

    @pytest.mark.asyncio
    async def test_when_created_then_rebuild_registry_awaited(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        await secret_values.create_secret(db_session, name="TRIGGER_KEY", value="trigger-val")

        rebuild_registry_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# update_secret — rename, value change, rename+value, not found
# ---------------------------------------------------------------------------

class TestUpdateSecret:
    @pytest.mark.asyncio
    async def test_when_renamed_then_cache_key_migrates_preserving_value(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        created = await secret_values.create_secret(
            db_session, name="OLD_KEY", value="the-value"
        )

        result = await secret_values.update_secret(
            db_session, uuid.UUID(created["id"]), name="NEW_KEY"
        )

        assert result is not None
        assert result["name"] == "NEW_KEY"
        assert "OLD_KEY" not in secret_values._cache
        assert secret_values._cache["NEW_KEY"] == "the-value"

    @pytest.mark.asyncio
    async def test_when_value_changed_then_cache_and_db_updated(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        created = await secret_values.create_secret(
            db_session, name="API_SECRET", value="old-val"
        )

        result = await secret_values.update_secret(
            db_session, uuid.UUID(created["id"]), value="new-val"
        )

        assert result is not None
        assert secret_values._cache["API_SECRET"] == "new-val"

    @pytest.mark.asyncio
    async def test_when_rename_and_value_changed_then_new_name_has_new_value(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        created = await secret_values.create_secret(
            db_session, name="OLD_KEY", value="old-val"
        )

        await secret_values.update_secret(
            db_session, uuid.UUID(created["id"]), name="NEW_KEY", value="new-val"
        )

        assert "OLD_KEY" not in secret_values._cache
        assert secret_values._cache["NEW_KEY"] == "new-val"

    @pytest.mark.asyncio
    async def test_when_id_not_found_then_returns_none_and_db_untouched(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        result = await secret_values.update_secret(
            db_session, uuid.uuid4(), name="GHOST", value="ghost-val"
        )

        assert result is None
        assert secret_values._cache == {}
        rebuild_registry_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# delete_secret — real DB
# ---------------------------------------------------------------------------

class TestDeleteSecret:
    @pytest.mark.asyncio
    async def test_when_row_exists_then_deleted_and_cache_cleared_and_returns_true(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        created = await secret_values.create_secret(
            db_session, name="DELETE_ME", value="doomed-val"
        )

        result = await secret_values.delete_secret(db_session, uuid.UUID(created["id"]))

        assert result is True
        assert "DELETE_ME" not in secret_values._cache
        row = (
            await db_session.execute(select(SecretValue).where(SecretValue.name == "DELETE_ME"))
        ).scalar_one_or_none()
        assert row is None

    @pytest.mark.asyncio
    async def test_when_sibling_exists_then_delete_leaves_it_untouched(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        target = await secret_values.create_secret(db_session, name="TARGET", value="target-val")
        await secret_values.create_secret(db_session, name="SIBLING", value="sibling-val")

        await secret_values.delete_secret(db_session, uuid.UUID(target["id"]))

        sibling = (
            await db_session.execute(select(SecretValue).where(SecretValue.name == "SIBLING"))
        ).scalar_one()
        assert sibling.value == "sibling-val"
        assert secret_values._cache == {"SIBLING": "sibling-val"}

    @pytest.mark.asyncio
    async def test_when_id_not_found_then_returns_false_and_cache_untouched(
        self, db_session, secret_cache_reset, rebuild_registry_mock
    ):
        secret_values._cache["KEEP_ME"] = "keep-val"

        result = await secret_values.delete_secret(db_session, uuid.uuid4())

        assert result is False
        assert secret_values._cache == {"KEEP_ME": "keep-val"}
        rebuild_registry_mock.assert_not_awaited()
