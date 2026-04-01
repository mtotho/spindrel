"""Secret values vault — user-managed encrypted env vars.

Values are encrypted at rest (Fernet), decrypted into an in-memory cache,
and injected into workspace containers as env vars.  They are also registered
with the secret_registry so they get redacted from tool results.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SecretValue
from app.services.encryption import encrypt, decrypt

logger = logging.getLogger(__name__)

# In-memory cache: {name: plaintext_value}
_cache: dict[str, str] = {}


async def load_from_db() -> None:
    """Load all secret values into in-memory cache (called at startup)."""
    from app.db.engine import async_session

    async with async_session() as db:
        rows = (await db.execute(select(SecretValue))).scalars().all()

    _cache.clear()
    for row in rows:
        try:
            _cache[row.name] = decrypt(row.value)
        except Exception:
            logger.warning("Failed to decrypt secret value '%s'", row.name)

    if rows:
        logger.info("Loaded %d secret value(s) from DB", len(rows))


async def list_secrets(db: AsyncSession) -> list[dict[str, Any]]:
    """Return all secrets (never returns plaintext value)."""
    rows = (await db.execute(
        select(SecretValue).order_by(SecretValue.name)
    )).scalars().all()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description or "",
            "has_value": bool(row.value),
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


async def create_secret(
    db: AsyncSession,
    name: str,
    value: str,
    description: str = "",
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create a new secret value. Encrypts and stores, rebuilds registry."""
    now = datetime.now(timezone.utc)
    row = SecretValue(
        id=uuid.uuid4(),
        name=name,
        value=encrypt(value),
        description=description,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Update in-memory cache
    _cache[name] = value

    # Rebuild secret registry
    await _rebuild_registry()

    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description or "",
        "has_value": True,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def update_secret(
    db: AsyncSession,
    secret_id: uuid.UUID,
    name: str | None = None,
    value: str | None = None,
    description: str | None = None,
) -> dict[str, Any] | None:
    """Update a secret value. Returns updated dict or None if not found."""
    row = await db.get(SecretValue, secret_id)
    if row is None:
        return None

    old_name = row.name
    now = datetime.now(timezone.utc)

    if name is not None:
        row.name = name
    if value is not None:
        row.value = encrypt(value)
    if description is not None:
        row.description = description
    row.updated_at = now

    await db.commit()
    await db.refresh(row)

    # Update cache
    if old_name != row.name:
        _cache.pop(old_name, None)
    if value is not None:
        _cache[row.name] = value
    elif old_name != row.name and old_name in _cache:
        _cache[row.name] = _cache.pop(old_name)

    await _rebuild_registry()

    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description or "",
        "has_value": bool(row.value),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def delete_secret(db: AsyncSession, secret_id: uuid.UUID) -> bool:
    """Delete a secret value. Returns True if found and deleted."""
    row = await db.get(SecretValue, secret_id)
    if row is None:
        return False

    _cache.pop(row.name, None)
    await db.delete(row)
    await db.commit()

    await _rebuild_registry()
    return True


def get_env_dict() -> dict[str, str]:
    """Return {name: plaintext_value} for injection into containers."""
    return dict(_cache)


async def _rebuild_registry() -> None:
    """Rebuild the secret registry after a change."""
    try:
        from app.services.secret_registry import rebuild
        await rebuild()
    except Exception:
        logger.debug("Failed to rebuild secret registry", exc_info=True)
