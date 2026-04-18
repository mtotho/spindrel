"""Integration tests for api_v1_admin settings routes.

Routes under test:
- PUT  /settings       — delegates to update_settings(); raises ValueError → 422
- DELETE /settings/{key} — delegates to reset_setting(); raises ValueError → 422
- PUT  /global-model-tiers — validates tier names, then calls update_model_tiers()
- PUT  /global-fallback-models — delegates to update_global_fallback_models()

Both PUT /settings and DELETE /settings/{key} use pg_insert internally (via
update_settings / reset_setting). Those functions are patched at the service
level so the pg_insert never runs against the SQLite test DB.

VALID_TIER_NAMES = {"free", "fast", "standard", "capable", "frontier"}.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio

_UPDATE_SETTINGS = "app.services.server_settings.update_settings"
_RESET_SETTING = "app.services.server_settings.reset_setting"
_UPDATE_TIERS = "app.services.server_config.update_model_tiers"
_UPDATE_FALLBACK = "app.services.server_config.update_global_fallback_models"


# ---------------------------------------------------------------------------
# PUT /settings
# ---------------------------------------------------------------------------

class TestUpdateSettings:
    async def test_when_valid_settings_then_ok_with_applied_list(self, client):
        with patch(_UPDATE_SETTINGS, AsyncMock(return_value=["LOG_LEVEL"])):
            resp = await client.put(
                "/api/v1/admin/settings",
                json={"settings": {"LOG_LEVEL": "DEBUG"}},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "LOG_LEVEL" in body["applied"]

    async def test_when_unknown_key_then_422(self, client):
        with patch(_UPDATE_SETTINGS, AsyncMock(side_effect=ValueError("Unknown key: BOGUS_SETTING"))):
            resp = await client.put(
                "/api/v1/admin/settings",
                json={"settings": {"BOGUS_SETTING": "x"}},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 422
        assert "Unknown key" in resp.json()["detail"]

    async def test_when_service_raises_unexpected_then_400(self, client):
        with patch(_UPDATE_SETTINGS, AsyncMock(side_effect=RuntimeError("DB exploded"))):
            resp = await client.put(
                "/api/v1/admin/settings",
                json={"settings": {"LOG_LEVEL": "DEBUG"}},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /settings/{key}
# ---------------------------------------------------------------------------

class TestResetSetting:
    async def test_when_valid_key_then_ok_with_default(self, client):
        with patch(_RESET_SETTING, AsyncMock(return_value="INFO")):
            resp = await client.delete(
                "/api/v1/admin/settings/LOG_LEVEL",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["default"] == "INFO"

    async def test_when_unknown_key_then_422(self, client):
        with patch(_RESET_SETTING, AsyncMock(side_effect=ValueError("Unknown key: GHOST"))):
            resp = await client.delete(
                "/api/v1/admin/settings/GHOST",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 422
        assert "Unknown key" in resp.json()["detail"]

    async def test_when_service_raises_unexpected_then_400(self, client):
        with patch(_RESET_SETTING, AsyncMock(side_effect=RuntimeError("uh oh"))):
            resp = await client.delete(
                "/api/v1/admin/settings/LOG_LEVEL",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PUT /global-model-tiers
# ---------------------------------------------------------------------------

class TestUpdateModelTiers:
    async def test_when_valid_tier_names_then_ok(self, client):
        payload = {"tiers": {"free": {"models": ["llama3"]}, "fast": {"models": ["gpt-4o-mini"]}}}

        with patch(_UPDATE_TIERS, AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/global-model-tiers",
                json=payload,
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "free" in body["tiers"]

    async def test_when_invalid_tier_name_then_422(self, client):
        payload = {"tiers": {"premium": {"models": ["gpt-5"]}, "free": {}}}

        with patch(_UPDATE_TIERS, AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/global-model-tiers",
                json=payload,
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 422
        assert "premium" in resp.json()["detail"]

    async def test_when_empty_tiers_then_ok_and_update_called(self, client):
        mock_update = AsyncMock()
        with patch(_UPDATE_TIERS, mock_update):
            resp = await client.put(
                "/api/v1/admin/global-model-tiers",
                json={"tiers": {}},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        mock_update.assert_called_once_with({})


# ---------------------------------------------------------------------------
# PUT /global-fallback-models
# ---------------------------------------------------------------------------

class TestUpdateFallbackModels:
    async def test_when_models_provided_then_ok_with_echo(self, client):
        models = [{"model": "gpt-4o", "provider_id": "openai"}]

        with patch(_UPDATE_FALLBACK, AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/global-fallback-models",
                json={"models": models},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["models"] == models

    async def test_when_empty_list_then_ok(self, client):
        with patch(_UPDATE_FALLBACK, AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/global-fallback-models",
                json={"models": []},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["models"] == []
