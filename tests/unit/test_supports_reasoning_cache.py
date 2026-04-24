"""Unit tests for the reasoning-capable model cache.

Covers the `load_providers()` SELECT that populates `_reasoning_capable_models`
and the two public accessors (`supports_reasoning`, `supports_reasoning_set`).
Uses the real SQLite-in-memory fixture from `tests/conftest.py` — no mocks.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.db.models import ProviderConfig, ProviderModel


pytestmark = pytest.mark.asyncio


async def _insert_models(db_session, pairs: list[tuple[str, bool]]):
    db_session.add(
        ProviderConfig(
            id="test-provider",
            provider_type="openai-compatible",
            display_name="Test",
            is_enabled=True,
        )
    )
    for model_id, flag in pairs:
        db_session.add(
            ProviderModel(
                provider_id="test-provider",
                model_id=model_id,
                supports_reasoning=flag,
            )
        )
    await db_session.commit()


class TestReasoningCapableCache:
    async def test_load_providers_populates_cache_from_db(self, engine, db_session):
        """Smoking gun: cache is driven by the DB column, not a hardcoded list."""
        from app.services import providers

        await _insert_models(
            db_session,
            [
                ("claude-opus-4-7", True),
                ("gpt-4o", False),
                ("gpt-5-mini", True),
            ],
        )

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.services.providers.async_session", factory):
            await providers.load_providers()

        assert providers.supports_reasoning("claude-opus-4-7") is True
        assert providers.supports_reasoning("gpt-5-mini") is True
        assert providers.supports_reasoning("gpt-4o") is False
        # Unknown models default to False — no family-based guessing
        assert providers.supports_reasoning("unknown-model-xyz") is False

    async def test_supports_reasoning_set_returns_sorted_list(self, engine, db_session):
        from app.services import providers

        await _insert_models(
            db_session,
            [
                ("zeta-model", True),
                ("alpha-model", True),
                ("middle-model", True),
                ("non-reasoning", False),
            ],
        )

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.services.providers.async_session", factory):
            await providers.load_providers()

        result = providers.supports_reasoning_set()
        assert result == ["alpha-model", "middle-model", "zeta-model"]
        assert "non-reasoning" not in result

    async def test_cache_cleared_on_reload(self, engine, db_session):
        """Removing a row from the DB + reloading clears it from the cache."""
        from app.services import providers

        await _insert_models(
            db_session,
            [("claude-opus-4-7", True)],
        )

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.services.providers.async_session", factory):
            await providers.load_providers()
            assert providers.supports_reasoning("claude-opus-4-7") is True

            # Flip the row to False and reload
            from sqlalchemy import update as sa_update
            await db_session.execute(
                sa_update(ProviderModel)
                .where(ProviderModel.model_id == "claude-opus-4-7")
                .values(supports_reasoning=False)
            )
            await db_session.commit()
            await providers.load_providers()

            assert providers.supports_reasoning("claude-opus-4-7") is False

    async def test_empty_db_yields_empty_cache(self, engine, db_session):
        from app.services import providers

        # No ProviderConfig / ProviderModel rows
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        with patch("app.services.providers.async_session", factory):
            await providers.load_providers()

        assert providers.supports_reasoning("claude-opus-4-7") is False
        assert providers.supports_reasoning_set() == []
