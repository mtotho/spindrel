"""DB-backed integration settings with in-memory cache.

Precedence: DB value > env var > default.
Env vars still work as deploy-time config; DB adds runtime editability from the admin UI.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IntegrationSetting

logger = logging.getLogger(__name__)

# In-memory cache: (integration_id, key) -> value
_cache: dict[tuple[str, str], str] = {}
# Track which keys are secret (for masking)
_secret_keys: dict[tuple[str, str], bool] = {}


# ---------------------------------------------------------------------------
# Startup loader
# ---------------------------------------------------------------------------

async def load_from_db() -> None:
    """Load all integration settings into the in-memory cache."""
    from app.db.engine import async_session

    async with async_session() as db:
        rows = (await db.execute(select(IntegrationSetting))).scalars().all()

    from app.services.encryption import decrypt

    _cache.clear()
    _secret_keys.clear()
    for row in rows:
        value = row.value
        if row.is_secret and value:
            value = decrypt(value)
        _cache[(row.integration_id, row.key)] = value
        _secret_keys[(row.integration_id, row.key)] = row.is_secret

    if rows:
        logger.info("Loaded %d integration setting(s) from DB", len(rows))


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_value(integration_id: str, key: str, default: str = "") -> str:
    """Get a setting value. DB cache > env var > default."""
    cached = _cache.get((integration_id, key))
    if cached is not None:
        return cached
    return os.environ.get(key, default)


def get_all_for_integration(integration_id: str, setup_vars: list[dict]) -> list[dict[str, Any]]:
    """Return settings list with current values, source, and masking for an integration.

    setup_vars: the env_vars list from setup.py SETUP dict.
    """
    results = []
    for var in setup_vars:
        key = var["key"]
        cache_key = (integration_id, key)
        is_secret = var.get("secret", False)

        # Determine value and source
        default_value = var.get("default", "")
        if cache_key in _cache:
            raw_value = _cache[cache_key]
            source = "db"
        elif os.environ.get(key):
            raw_value = os.environ[key]
            source = "env"
        else:
            raw_value = default_value
            source = "default"

        is_set = bool(raw_value)
        display_value = _mask_value(raw_value) if (is_secret and is_set) else raw_value

        results.append({
            "key": key,
            "description": var.get("description", ""),
            "required": var.get("required", False),
            "secret": is_secret,
            "value": display_value,
            "source": source,
            "is_set": is_set,
            "default": default_value or None,
        })
    return results


def _mask_value(value: str) -> str:
    """Mask a secret value for display."""
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

async def update_settings(
    integration_id: str,
    updates: dict[str, str],
    setup_vars: list[dict],
    db: AsyncSession,
) -> dict[str, str]:
    """Upsert settings to DB and update cache. Empty string = delete."""
    from app.services.encryption import encrypt

    # Build a lookup for secret flag from setup_vars
    secret_lookup = {v["key"]: v.get("secret", False) for v in setup_vars}
    applied: dict[str, str] = {}
    now = datetime.now(timezone.utc)

    for key, value in updates.items():
        if not value:
            # Empty string means delete — revert to env/default
            await _delete_one(integration_id, key, db, commit=False)
            applied[key] = ""
            continue

        is_secret = secret_lookup.get(key, False)
        db_value = encrypt(value) if is_secret else value
        stmt = pg_insert(IntegrationSetting).values(
            integration_id=integration_id,
            key=key,
            value=db_value,
            is_secret=is_secret,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=["integration_id", "key"],
            set_={"value": db_value, "is_secret": is_secret, "updated_at": now},
        )
        await db.execute(stmt)

        # Update cache with plaintext (decrypted) value
        _cache[(integration_id, key)] = value
        _secret_keys[(integration_id, key)] = is_secret
        applied[key] = value

    await db.commit()

    # Rebuild secret registry so updated integration secrets are tracked
    try:
        import asyncio
        from app.services.secret_registry import rebuild as _rebuild_secrets
        asyncio.create_task(_rebuild_secrets())
    except Exception:
        pass

    return applied


async def delete_setting(integration_id: str, key: str, db: AsyncSession) -> None:
    """Remove a single setting from DB and cache."""
    await _delete_one(integration_id, key, db, commit=True)


async def _delete_one(integration_id: str, key: str, db: AsyncSession, *, commit: bool) -> None:
    """Internal: delete one setting from DB + cache."""
    await db.execute(
        delete(IntegrationSetting).where(
            IntegrationSetting.integration_id == integration_id,
            IntegrationSetting.key == key,
        )
    )
    _cache.pop((integration_id, key), None)
    _secret_keys.pop((integration_id, key), None)
    if commit:
        await db.commit()
