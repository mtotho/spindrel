"""Unit tests for app.services.integration_settings."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.integration_settings import (
    _cache,
    _secret_keys,
    _mask_value,
    get_value,
    get_all_for_integration,
)


class TestRouterImports:
    """Verify the router module imports resolve correctly (catches bad import paths)."""

    def test_integrations_router_imports(self):
        from app.routers.api_v1_admin import integrations
        assert hasattr(integrations, "router")
        assert hasattr(integrations, "_get_setup_vars")


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the module-level cache before each test."""
    _cache.clear()
    _secret_keys.clear()
    yield
    _cache.clear()
    _secret_keys.clear()


class TestGetValue:
    def test_returns_cached_value(self):
        _cache[("frigate", "FRIGATE_URL")] = "http://cached:5000"
        assert get_value("frigate", "FRIGATE_URL") == "http://cached:5000"

    def test_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("FRIGATE_URL", "http://env:5000")
        assert get_value("frigate", "FRIGATE_URL") == "http://env:5000"

    def test_falls_back_to_default(self):
        assert get_value("frigate", "FRIGATE_URL", "http://default:5000") == "http://default:5000"

    def test_empty_default(self):
        assert get_value("frigate", "NONEXISTENT") == ""

    def test_db_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("FRIGATE_URL", "http://env:5000")
        _cache[("frigate", "FRIGATE_URL")] = "http://db:5000"
        assert get_value("frigate", "FRIGATE_URL") == "http://db:5000"


class TestMaskValue:
    def test_short_value(self):
        assert _mask_value("abc") == "****"
        assert _mask_value("12345678") == "****"

    def test_long_value(self):
        assert _mask_value("xoxb-1234567890-abcdef") == "xoxb****cdef"

    def test_empty_value(self):
        assert _mask_value("") == "****"


class TestGetAllForIntegration:
    def test_returns_all_vars_with_source(self, monkeypatch):
        setup_vars = [
            {"key": "FRIGATE_URL", "required": True, "description": "Frigate URL"},
            {"key": "FRIGATE_API_KEY", "required": False, "description": "API key", "secret": True},
        ]
        # URL from DB
        _cache[("frigate", "FRIGATE_URL")] = "http://db:5000"
        # API_KEY from env
        monkeypatch.setenv("FRIGATE_API_KEY", "my-secret-key-12345")

        result = get_all_for_integration("frigate", setup_vars)

        assert len(result) == 2

        url_setting = result[0]
        assert url_setting["key"] == "FRIGATE_URL"
        assert url_setting["source"] == "db"
        assert url_setting["value"] == "http://db:5000"
        assert url_setting["is_set"] is True
        assert url_setting["secret"] is False

        key_setting = result[1]
        assert key_setting["key"] == "FRIGATE_API_KEY"
        assert key_setting["source"] == "env"
        assert key_setting["is_set"] is True
        assert key_setting["secret"] is True
        # Secret should be masked
        assert "****" in key_setting["value"]
        assert key_setting["value"] != "my-secret-key-12345"

    def test_default_source_when_unset(self):
        setup_vars = [
            {"key": "MISSING_VAR", "required": False, "description": "Not set"},
        ]
        result = get_all_for_integration("frigate", setup_vars)
        assert result[0]["source"] == "default"
        assert result[0]["is_set"] is False
        assert result[0]["value"] == ""


class TestUpdateSettings:
    @pytest.mark.asyncio
    async def test_upsert_updates_cache(self):
        from app.services.integration_settings import update_settings

        # Mock DB session
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        setup_vars = [
            {"key": "FRIGATE_URL", "required": True, "description": "URL"},
            {"key": "FRIGATE_API_KEY", "required": False, "description": "Key", "secret": True},
        ]

        await update_settings("frigate", {"FRIGATE_URL": "http://new:5000"}, setup_vars, db)

        assert _cache[("frigate", "FRIGATE_URL")] == "http://new:5000"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_string_deletes(self):
        from app.services.integration_settings import update_settings

        _cache[("frigate", "FRIGATE_URL")] = "http://old:5000"

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        setup_vars = [{"key": "FRIGATE_URL", "required": True, "description": "URL"}]

        await update_settings("frigate", {"FRIGATE_URL": ""}, setup_vars, db)

        assert ("frigate", "FRIGATE_URL") not in _cache
        db.commit.assert_called_once()


class TestDeleteSetting:
    @pytest.mark.asyncio
    async def test_delete_removes_from_cache(self):
        from app.services.integration_settings import delete_setting

        _cache[("frigate", "FRIGATE_URL")] = "http://old:5000"
        _secret_keys[("frigate", "FRIGATE_URL")] = False

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        await delete_setting("frigate", "FRIGATE_URL", db)

        assert ("frigate", "FRIGATE_URL") not in _cache
        assert ("frigate", "FRIGATE_URL") not in _secret_keys
        db.commit.assert_called_once()
