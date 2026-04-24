"""Integration tests for api_v1_admin/models.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.provider_drivers import ProviderCapabilities
from tests.factories import build_provider_config, build_provider_model
from tests.integration.conftest import AUTH_HEADERS
from tests.integration.test_provider_admin import _make_driver_stub

pytestmark = pytest.mark.asyncio


class TestAdminModels:
    async def test_when_provider_api_lists_models_then_db_only_manual_rows_are_also_exposed(
        self, client, db_session,
    ):
        provider = build_provider_config(
            id="chatgpt-subscription",
            provider_type="openai-subscription",
            display_name="ChatGPT Account",
        )
        manual = build_provider_model(
            "chatgpt-subscription",
            model_id="gpt-5.5",
            display_name="GPT-5.5",
            max_tokens=272000,
        )
        db_session.add_all([provider, manual])
        await db_session.commit()

        driver = _make_driver_stub(
            capabilities=ProviderCapabilities(list_models=True, chat_completions=True),
            models=["gpt-5.4", "gpt-5.4-mini"],
        )

        with patch("app.services.providers.get_driver", return_value=driver):
            await __import__("app.services.providers", fromlist=["load_providers"]).load_providers()
            resp = await client.get("/api/v1/admin/models", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        groups = resp.json()
        sub_group = next(g for g in groups if g["provider_id"] == "chatgpt-subscription")
        model_ids = [m["id"] for m in sub_group["models"]]
        assert "gpt-5.4" in model_ids
        assert "gpt-5.5" in model_ids
