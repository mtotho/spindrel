"""Global server configuration — singleton row in server_config table.

Provides cached access to global_fallback_models and model_tiers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import ServerConfig

logger = logging.getLogger(__name__)

# Module-level caches
_global_fallback_models: list[dict] = []
_model_tiers: dict[str, dict] = {}

VALID_TIER_NAMES = {"free", "fast", "standard", "capable", "frontier"}


async def load_server_config() -> None:
    """Load server_config from DB into module cache. Call once at startup."""
    global _global_fallback_models, _model_tiers
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
            _global_fallback_models = [{"model": settings.LLM_FALLBACK_MODEL, "provider_id": settings.LLM_FALLBACK_MODEL_PROVIDER_ID or None}]
            logger.info("Seeded global fallback from LLM_FALLBACK_MODEL=%s", settings.LLM_FALLBACK_MODEL)
        else:
            _global_fallback_models = []

    if row and row.model_tiers:
        _model_tiers = dict(row.model_tiers)
        logger.info("Loaded %d model tier(s)", len(_model_tiers))
    else:
        _model_tiers = {}


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


# ---------------------------------------------------------------------------
# Model tiers
# ---------------------------------------------------------------------------

def get_model_tiers() -> dict[str, dict]:
    """Return the cached global model tiers mapping."""
    return _model_tiers


async def update_model_tiers(tiers: dict[str, dict]) -> None:
    """Update model tiers in DB and refresh cache."""
    global _model_tiers
    from app.db.engine import async_session
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = pg_insert(ServerConfig).values(
            id="default",
            model_tiers=tiers,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"model_tiers": tiers, "updated_at": now},
        )
        await db.execute(stmt)
        await db.commit()

    _model_tiers = dict(tiers)
    logger.info("Updated model tiers (%d entries)", len(tiers))


def resolve_model_tier(
    tier: str,
    channel_overrides: dict | None = None,
) -> tuple[str, str | None] | None:
    """Resolve tier name → (model, provider_id). Returns None if unconfigured.

    Resolution: channel override > global tier mapping.
    """
    # Channel override takes precedence
    if channel_overrides and tier in channel_overrides:
        entry = channel_overrides[tier]
        model = entry.get("model")
        if model:
            return model, entry.get("provider_id")

    # Global tier mapping
    if tier in _model_tiers:
        entry = _model_tiers[tier]
        model = entry.get("model")
        if model:
            return model, entry.get("provider_id")

    return None
