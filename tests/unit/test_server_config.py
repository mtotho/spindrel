"""Tests for ``app/services/server_config.py``.

Two mutating public symbols that were uncovered in the 2026-04-17 audit:

- ``update_global_fallback_models`` — upserts the singleton row and
  refreshes the in-memory cache.
- ``update_model_tiers`` — same shape for the ``model_tiers`` JSONB column.

Both use ``pg_insert(...).on_conflict_do_update(...)``. SQLite supports
the same ``ON CONFLICT(col) DO UPDATE`` syntax, so the SA dialect
compiles cleanly against in-memory SQLite.

The pre-existing ``load_server_config`` mock tests are kept (they cover a
non-DB-touching path through the env-seed fallback). Module-level caches
are saved/restored in an autouse fixture for isolation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Reuse the SQLite type-compilation patches from test_outbox.
from tests.unit.test_outbox import _patch_pg_types_for_sqlite  # noqa: F401

from app.db.models import Base, ServerConfig
from app.services import server_config


@pytest_asyncio.fixture
async def engine_and_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    from sqlalchemy import text as sa_text
    from sqlalchemy.schema import DefaultClause
    originals: dict[tuple[str, str], object] = {}
    replacements = {"now()": "CURRENT_TIMESTAMP", "gen_random_uuid()": None}
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            txt = str(sd.arg) if hasattr(sd, "arg") else str(sd)
            new_default: str | None = None
            replaced = False
            for pg_expr, sqlite_expr in replacements.items():
                if pg_expr in txt:
                    replaced = True
                    new_default = sqlite_expr
                    break
            if not replaced and "::jsonb" in txt:
                replaced = True
                new_default = txt.replace("::jsonb", "")
            if not replaced and "::json" in txt:
                replaced = True
                new_default = txt.replace("::json", "")
            if replaced:
                originals[(table.name, col.name)] = sd
                col.server_default = (
                    DefaultClause(sa_text(new_default)) if new_default else None
                )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    for (tname, cname), default in originals.items():
        Base.metadata.tables[tname].c[cname].server_default = default
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine_and_factory) -> AsyncSession:
    _engine, factory = engine_and_factory
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def patched_async_session(engine_and_factory):
    _engine, factory = engine_and_factory
    with patch("app.db.engine.async_session", factory):
        yield factory


@pytest.fixture(autouse=True)
def _reset_caches():
    prev_models = list(server_config._global_fallback_models)
    prev_tiers = dict(server_config._model_tiers)
    server_config._global_fallback_models = []
    server_config._model_tiers = {}
    yield
    server_config._global_fallback_models = prev_models
    server_config._model_tiers = prev_tiers


# ---------------------------------------------------------------------------
# update_global_fallback_models
# ---------------------------------------------------------------------------


class TestUpdateGlobalFallbackModels:
    @pytest.mark.asyncio
    async def test_when_row_absent_then_inserts_singleton_and_refreshes_cache(
        self, db: AsyncSession, patched_async_session
    ):
        models = [
            {"model": "anthropic/claude-haiku-4-5", "provider_id": "anthropic-prod"},
            {"model": "openai/gpt-4o-mini", "provider_id": None},
        ]

        await server_config.update_global_fallback_models(models)

        row = (await db.execute(select(ServerConfig))).scalar_one()
        assert row.id == "default"
        assert row.global_fallback_models == models
        assert server_config.get_global_fallback_models() == models

    @pytest.mark.asyncio
    async def test_when_row_exists_then_overwrites_and_does_not_touch_other_columns(
        self, db: AsyncSession, patched_async_session
    ):
        # Pre-seed both columns so we can verify model_tiers stays untouched.
        seed_tiers = {"fast": {"model": "anthropic/claude-haiku-4-5", "provider_id": None}}
        await server_config.update_model_tiers(seed_tiers)
        new_models = [{"model": "ollama/llama3.1", "provider_id": "local"}]

        await server_config.update_global_fallback_models(new_models)

        rows = (await db.execute(select(ServerConfig))).scalars().all()
        assert len(rows) == 1  # still the singleton
        assert rows[0].global_fallback_models == new_models
        assert rows[0].model_tiers == seed_tiers
        assert server_config.get_global_fallback_models() == new_models
        assert server_config.get_model_tiers() == seed_tiers

    @pytest.mark.asyncio
    async def test_when_called_with_empty_list_then_clears_cache_and_persists_empty(
        self, db: AsyncSession, patched_async_session
    ):
        await server_config.update_global_fallback_models(
            [{"model": "anthropic/claude-haiku-4-5", "provider_id": None}]
        )

        await server_config.update_global_fallback_models([])

        row = (await db.execute(select(ServerConfig))).scalar_one()
        assert row.global_fallback_models == []
        assert server_config.get_global_fallback_models() == []


# ---------------------------------------------------------------------------
# update_model_tiers
# ---------------------------------------------------------------------------


class TestUpdateModelTiers:
    @pytest.mark.asyncio
    async def test_when_row_absent_then_inserts_singleton_and_refreshes_cache(
        self, db: AsyncSession, patched_async_session
    ):
        tiers = {
            "fast": {"model": "anthropic/claude-haiku-4-5", "provider_id": "anthropic-prod"},
            "frontier": {"model": "anthropic/claude-opus-4-7", "provider_id": "anthropic-prod"},
        }

        await server_config.update_model_tiers(tiers)

        row = (await db.execute(select(ServerConfig))).scalar_one()
        assert row.model_tiers == tiers
        assert server_config.get_model_tiers() == tiers

    @pytest.mark.asyncio
    async def test_when_row_exists_then_overwrites_and_does_not_touch_other_columns(
        self, db: AsyncSession, patched_async_session
    ):
        seed_models = [{"model": "anthropic/claude-haiku-4-5", "provider_id": None}]
        await server_config.update_global_fallback_models(seed_models)
        new_tiers = {"capable": {"model": "anthropic/claude-sonnet-4-6", "provider_id": None}}

        await server_config.update_model_tiers(new_tiers)

        rows = (await db.execute(select(ServerConfig))).scalars().all()
        assert len(rows) == 1
        assert rows[0].model_tiers == new_tiers
        assert rows[0].global_fallback_models == seed_models
        assert server_config.get_model_tiers() == new_tiers
        assert server_config.get_global_fallback_models() == seed_models

    @pytest.mark.asyncio
    async def test_when_called_with_empty_dict_then_clears_cache_and_persists_empty(
        self, db: AsyncSession, patched_async_session
    ):
        await server_config.update_model_tiers(
            {"fast": {"model": "anthropic/claude-haiku-4-5", "provider_id": None}}
        )

        await server_config.update_model_tiers({})

        row = (await db.execute(select(ServerConfig))).scalar_one()
        assert row.model_tiers == {}
        assert server_config.get_model_tiers() == {}


# ---------------------------------------------------------------------------
# Pure cache accessor + load_server_config (existing mock-based tests preserved)
# ---------------------------------------------------------------------------


class TestGetGlobalFallbackModels:
    def test_when_cache_set_then_returns_cached_value(self):
        server_config._global_fallback_models = [{"model": "test-model"}]
        assert server_config.get_global_fallback_models() == [{"model": "test-model"}]


class TestLoadServerConfig:
    """``load_server_config`` boot-time loader.

    These tests mock the session because the function is pure read +
    cache assignment — see Phase 4 of [[Track - Test Quality]] for the
    eventual real-DB rewrite.
    """

    @pytest.mark.asyncio
    async def test_when_db_row_has_models_then_cache_populated(self):
        mock_row = MagicMock()
        mock_row.global_fallback_models = [{"model": "db-model", "provider_id": None}]
        mock_row.model_tiers = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_session_ctx):
            await server_config.load_server_config()

        assert server_config._global_fallback_models == [
            {"model": "db-model", "provider_id": None}
        ]

    @pytest.mark.asyncio
    async def test_when_db_row_empty_then_seeds_from_env(self):
        mock_row = MagicMock()
        mock_row.global_fallback_models = []
        mock_row.model_tiers = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_settings = MagicMock()
        mock_settings.LLM_FALLBACK_MODEL = "env-fallback"
        mock_settings.LLM_FALLBACK_MODEL_PROVIDER_ID = ""

        with patch("app.db.engine.async_session", return_value=mock_session_ctx), \
             patch("app.config.settings", mock_settings):
            await server_config.load_server_config()

        assert server_config._global_fallback_models == [
            {"model": "env-fallback", "provider_id": None}
        ]

    @pytest.mark.asyncio
    async def test_when_no_row_and_no_env_then_cache_stays_empty(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_settings = MagicMock()
        mock_settings.LLM_FALLBACK_MODEL = ""

        with patch("app.db.engine.async_session", return_value=mock_session_ctx), \
             patch("app.config.settings", mock_settings):
            await server_config.load_server_config()

        assert server_config._global_fallback_models == []
