"""MC-owned async SQLite engine and session factory.

The database lives at {WORKSPACE_ROOT}/mission_control/mc.db.
Tables are created via metadata.create_all on first access (no Alembic).
"""
from __future__ import annotations

import asyncio
import logging
import os

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from integrations.mission_control.db.models import MCBase

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_init_lock = asyncio.Lock()


def _get_db_path() -> str:
    from integrations.mission_control.config import settings
    return settings.MISSION_CONTROL_DB_PATH


async def get_mc_engine():
    """Lazy-init the MC SQLite engine. Creates tables on first call."""
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    async with _init_lock:
        if _engine is not None:
            return _engine
        db_path = _get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        async with engine.begin() as conn:
            await conn.run_sync(MCBase.metadata.create_all)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
        _engine = engine
        logger.info("MC SQLite engine initialized at %s", db_path)
    return _engine


async def mc_session() -> AsyncSession:
    """Get an async session for MC's SQLite DB."""
    await get_mc_engine()  # ensure init
    assert _session_factory is not None
    return _session_factory()


async def close_mc_engine() -> None:
    """Dispose of the engine (for testing cleanup)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
