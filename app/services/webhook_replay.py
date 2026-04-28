from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InboundWebhookReplay


async def record_inbound_webhook_delivery(
    db: AsyncSession,
    *,
    surface: str,
    dedupe_key: str,
    ttl_seconds: int = 7 * 24 * 60 * 60,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Return True for first sighting, False for replayed delivery keys."""
    clean_surface = surface.strip()
    clean_key = dedupe_key.strip()
    if not clean_surface or not clean_key:
        raise ValueError("surface and dedupe_key are required")

    now = datetime.now(timezone.utc)
    await db.execute(delete(InboundWebhookReplay).where(InboundWebhookReplay.expires_at <= now))
    db.add(
        InboundWebhookReplay(
            surface=clean_surface,
            dedupe_key=clean_key,
            expires_at=now + timedelta(seconds=max(60, int(ttl_seconds))),
            metadata_=metadata or {},
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return False
    return True
