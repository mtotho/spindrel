"""Global server configuration — singleton row in server_config table.

Provides cached access to global_fallback_models (and future global settings).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import ServerConfig

logger = logging.getLogger(__name__)

# Module-level cache
_global_fallback_models: list[dict] = []


async def load_server_config() -> None:
    """Load server_config from DB into module cache. Call once at startup."""
    global _global_fallback_models
    from app.db.engine import async_session

    async with async_session() as db:
        row = (await db.execute(select(ServerConfig).where(ServerConfig.id == "default"))).scalar_one_or_none()

    if row and row.global_fallback_models:
        _global_fallback_models = list(row.global_fallback_models)
        logger.info("Loaded %d global fallback model(s)", len(_global_fallback_models))
    else:
        # Seed from legacy .env setting if DB is empty
        from app.config import settings
        if settings.LLM_FALLBACK_MODEL:
            _global_fallback_models = [{"model": settings.LLM_FALLBACK_MODEL, "provider_id": None}]
            logger.info("Seeded global fallback from LLM_FALLBACK_MODEL=%s", settings.LLM_FALLBACK_MODEL)
        else:
            _global_fallback_models = []


def get_global_fallback_models() -> list[dict]:
    """Return the cached global fallback models list."""
    return _global_fallback_models


async def update_global_fallback_models(models: list[dict]) -> None:
    """Update global fallback models in DB and refresh cache."""
    global _global_fallback_models
    from app.db.engine import async_session
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = pg_insert(ServerConfig).values(
            id="default",
            global_fallback_models=models,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"global_fallback_models": models, "updated_at": now},
        )
        await db.execute(stmt)
        await db.commit()

    _global_fallback_models = list(models)
    logger.info("Updated global fallback models (%d entries)", len(models))
