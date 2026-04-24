"""Integration test: `/admin/bots/{id}/editor-data` surfaces the
reasoning-capable model whitelist so the bot editor UI can gate the
Reasoning effort control.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.db.models import ProviderConfig, ProviderModel
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _seed(db_session, pairs: list[tuple[str, bool]]):
    db_session.add(
        ProviderConfig(
            id="editor-data-provider",
            provider_type="openai-compatible",
            display_name="Test",
            is_enabled=True,
        )
    )
    for model_id, flag in pairs:
        db_session.add(
            ProviderModel(
                provider_id="editor-data-provider",
                model_id=model_id,
                supports_reasoning=flag,
            )
        )
    await db_session.commit()


async def _reload_cache(engine):
    from app.services import providers
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch("app.services.providers.async_session", factory):
        await providers.load_providers()


class TestEditorDataReasoningCapable:
    async def test_editor_data_includes_reasoning_whitelist(
        self, client, db_session, engine,
    ):
        await _seed(
            db_session,
            [
                ("anthropic/claude-opus-4-7", True),
                ("openai/gpt-5-mini", True),
                ("openai/gpt-4o", False),
            ],
        )
        await _reload_cache(engine)

        resp = await client.get(
            "/api/v1/admin/bots/test-bot/editor-data",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        whitelist = data.get("reasoning_capable_models", [])
        assert "anthropic/claude-opus-4-7" in whitelist
        assert "openai/gpt-5-mini" in whitelist
        assert "openai/gpt-4o" not in whitelist

    async def test_editor_data_empty_whitelist_when_no_reasoning_models(
        self, client, db_session, engine,
    ):
        await _seed(db_session, [("openai/gpt-4o", False)])
        await _reload_cache(engine)

        resp = await client.get(
            "/api/v1/admin/bots/test-bot/editor-data",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("reasoning_capable_models") == []
