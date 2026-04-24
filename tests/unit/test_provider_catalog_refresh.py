"""Unit tests for the background provider catalog refresh service.

Covers:
  - refresh_one_provider upserts ProviderModel rows with enriched metadata
  - last_refresh_ts is recorded on ProviderConfig.config on success
  - last_refresh_error is recorded on driver failure (and cleared on success)
  - disabled providers are skipped
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.db.models import ProviderConfig, ProviderModel


pytestmark = pytest.mark.asyncio


class _FakeDriver:
    def __init__(self, *, enriched=None, raise_exc=None):
        from app.services.provider_drivers.base import ProviderCapabilities
        self._enriched = enriched or []
        self._raise = raise_exc
        self.capabilities_impl = lambda: ProviderCapabilities(list_models=True)

    def capabilities(self):
        return self.capabilities_impl()

    async def list_models_enriched(self, config):
        if self._raise is not None:
            raise self._raise
        return self._enriched


async def _seed_provider(
    db_session, *, provider_id="test-prov", enabled=True, provider_type="openai-compatible"
):
    db_session.add(
        ProviderConfig(
            id=provider_id,
            provider_type=provider_type,
            display_name="Test",
            is_enabled=enabled,
            config={},
        )
    )
    await db_session.commit()


def _factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class TestRefreshOnePrivider:
    async def test_happy_path_creates_new_rows(self, engine, db_session):
        from app.services import provider_catalog_refresh, providers

        await _seed_provider(db_session)
        factory = _factory(engine)

        fake_driver = _FakeDriver(
            enriched=[
                {"id": "gpt-4o", "display": "GPT-4o", "max_tokens": 128000, "input_cost_per_1m": "$2.50"},
                {"id": "gpt-4o-mini", "display": "GPT-4o mini"},
            ]
        )

        with patch.object(provider_catalog_refresh, "async_session", factory), \
             patch.object(providers, "async_session", factory), \
             patch("app.services.provider_drivers.get_driver", return_value=fake_driver):
            await providers.load_providers()
            result = await provider_catalog_refresh.refresh_one_provider("test-prov")

        assert result["error"] is None
        assert result["created"] == 2
        assert result["total"] == 2

        async with factory() as session:
            rows = (
                await session.execute(
                    select(ProviderModel).where(
                        ProviderModel.provider_id == "test-prov"
                    )
                )
            ).scalars().all()
            mids = {r.model_id for r in rows}
            assert mids == {"gpt-4o", "gpt-4o-mini"}

    async def test_last_refresh_ts_recorded_on_success(self, engine, db_session):
        from app.services import provider_catalog_refresh, providers

        await _seed_provider(db_session)
        factory = _factory(engine)
        fake_driver = _FakeDriver(enriched=[{"id": "gpt-4o"}])

        with patch.object(provider_catalog_refresh, "async_session", factory), \
             patch.object(providers, "async_session", factory), \
             patch("app.services.provider_drivers.get_driver", return_value=fake_driver):
            await providers.load_providers()
            await provider_catalog_refresh.refresh_one_provider("test-prov")

        async with factory() as session:
            row = await session.get(ProviderConfig, "test-prov")
            assert row is not None
            assert "last_refresh_ts" in row.config
            assert row.config.get("last_refresh_error") is None

    async def test_error_recorded_when_driver_raises(self, engine, db_session):
        from app.services import provider_catalog_refresh, providers

        await _seed_provider(db_session)
        factory = _factory(engine)
        fake_driver = _FakeDriver(raise_exc=RuntimeError("network down"))

        with patch.object(provider_catalog_refresh, "async_session", factory), \
             patch.object(providers, "async_session", factory), \
             patch("app.services.provider_drivers.get_driver", return_value=fake_driver):
            await providers.load_providers()
            result = await provider_catalog_refresh.refresh_one_provider("test-prov")

        assert result["error"] is not None
        assert "network down" in result["error"]

        async with factory() as session:
            row = await session.get(ProviderConfig, "test-prov")
            assert row is not None
            assert row.config.get("last_refresh_error") is not None

    async def test_disabled_provider_skipped(self, engine, db_session):
        from app.services import provider_catalog_refresh, providers

        await _seed_provider(db_session, enabled=False)
        factory = _factory(engine)
        fake_driver = _FakeDriver(enriched=[{"id": "gpt-4o"}])

        with patch.object(provider_catalog_refresh, "async_session", factory), \
             patch.object(providers, "async_session", factory), \
             patch("app.services.provider_drivers.get_driver", return_value=fake_driver):
            await providers.load_providers()
            result = await provider_catalog_refresh.refresh_one_provider("test-prov")

        assert result["error"] == "provider disabled"
        # No rows should have been created
        async with factory() as session:
            rows = (
                await session.execute(
                    select(ProviderModel).where(
                        ProviderModel.provider_id == "test-prov"
                    )
                )
            ).scalars().all()
            assert rows == []

    async def test_error_cleared_on_subsequent_success(self, engine, db_session):
        from app.services import provider_catalog_refresh, providers

        await _seed_provider(db_session)
        factory = _factory(engine)

        # First run: fails.
        bad_driver = _FakeDriver(raise_exc=RuntimeError("first try"))
        with patch.object(provider_catalog_refresh, "async_session", factory), \
             patch.object(providers, "async_session", factory), \
             patch("app.services.provider_drivers.get_driver", return_value=bad_driver):
            await providers.load_providers()
            await provider_catalog_refresh.refresh_one_provider("test-prov")

        async with factory() as session:
            row = await session.get(ProviderConfig, "test-prov")
            assert row.config.get("last_refresh_error") is not None

        # Second run: succeeds — error field should be cleared.
        good_driver = _FakeDriver(enriched=[{"id": "gpt-4o"}])
        with patch.object(provider_catalog_refresh, "async_session", factory), \
             patch.object(providers, "async_session", factory), \
             patch("app.services.provider_drivers.get_driver", return_value=good_driver):
            await provider_catalog_refresh.refresh_one_provider("test-prov")

        async with factory() as session:
            row = await session.get(ProviderConfig, "test-prov")
            assert row.config.get("last_refresh_error") is None
