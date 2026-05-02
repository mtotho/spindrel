"""Widget JWT revocation list — `(api_key_id, jti)` keyed.

Hot path is :func:`is_revoked`, called on every widget-authenticated
request. A small in-process LRU cache keeps the common-case
"no revocation" lookup off the DB. Revoked entries are cached too —
the cache is positive *and* negative — so a leaked-token kill keeps
working even when the bot is hammering an endpoint.
"""
from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WidgetTokenRevocation


_CACHE_TTL_SECONDS = 30
_CACHE_MAX_ENTRIES = 1024
# value is (is_revoked: bool, expires_at_unix: float)
_cache: OrderedDict[tuple[uuid.UUID, str], tuple[bool, float]] = OrderedDict()


def _cache_get(key: tuple[uuid.UUID, str]) -> bool | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    is_revoked, expires_at_unix = entry
    if time.time() >= expires_at_unix:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return is_revoked


def _cache_set(key: tuple[uuid.UUID, str], value: bool) -> None:
    _cache[key] = (value, time.time() + _CACHE_TTL_SECONDS)
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)


def _cache_clear() -> None:
    """Test hook — clear the in-process cache."""
    _cache.clear()


async def revoke(
    db: "AsyncSession",
    *,
    api_key_id: uuid.UUID,
    jti: str,
    expires_at: datetime,
) -> None:
    """Insert a revocation row. Idempotent on (api_key_id, jti)."""
    existing = await db.get(WidgetTokenRevocation, (api_key_id, jti))
    if existing is None:
        db.add(
            WidgetTokenRevocation(
                api_key_id=api_key_id,
                jti=jti,
                expires_at=expires_at,
            )
        )
        await db.flush()
    # Update positive cache so the verifier sees it on the very next call.
    _cache_set((api_key_id, jti), True)


async def is_revoked(
    db: "AsyncSession",
    *,
    api_key_id: uuid.UUID,
    jti: str,
) -> bool:
    """Hot-path check. Returns True if the (api_key_id, jti) pair has
    a non-expired revocation row. Negative results are cached too so
    chatty widget requests don't all hit the DB."""
    key = (api_key_id, jti)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    stmt = select(WidgetTokenRevocation.expires_at).where(
        WidgetTokenRevocation.api_key_id == api_key_id,
        WidgetTokenRevocation.jti == jti,
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        _cache_set(key, False)
        return False

    # If the underlying token is past its exp, the revocation is moot —
    # the JWT verifier would already reject the bearer. Drop the row
    # opportunistically so the cache and table stay tidy.
    if row.expires_at < datetime.now(timezone.utc):
        await db.execute(
            delete(WidgetTokenRevocation).where(
                WidgetTokenRevocation.api_key_id == api_key_id,
                WidgetTokenRevocation.jti == jti,
            )
        )
        _cache_set(key, False)
        return False

    _cache_set(key, True)
    return True


async def purge_expired(db: "AsyncSession") -> int:
    """Drop revocation rows whose underlying token is past expiry.
    Called from the existing data-retention sweep.
    """
    result = await db.execute(
        delete(WidgetTokenRevocation).where(
            WidgetTokenRevocation.expires_at < datetime.now(timezone.utc)
        )
    )
    deleted = result.rowcount or 0
    if deleted:
        _cache_clear()
    return deleted
