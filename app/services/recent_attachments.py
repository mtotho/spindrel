"""Helpers for carrying recent visible image context across chat turns."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Message


async def recent_inline_image_payloads(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    before_message_id: uuid.UUID | None = None,
    max_age_seconds: int = 600,
    max_images: int = 3,
) -> list[dict]:
    """Return inline image payloads from the latest recent visible image message.

    This is intentionally narrow: it preserves natural chat continuity for
    immediate text followups after an image without turning arbitrary old
    attachments into hidden context.
    """
    if max_images <= 0:
        return []

    before_created_at: datetime | None = None
    if before_message_id is not None:
        before = await db.get(Message, before_message_id)
        if before is not None:
            before_created_at = before.created_at

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    stmt = (
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.session_id == session_id)
        .where(Message.role == "user")
        .where(Message.created_at >= cutoff)
        .order_by(Message.created_at.desc())
        .limit(12)
    )
    if before_created_at is not None:
        stmt = stmt.where(Message.created_at < before_created_at)
    elif before_message_id is not None:
        stmt = stmt.where(Message.id != before_message_id)

    rows = list((await db.execute(stmt)).scalars().all())
    for msg in rows:
        meta = msg.metadata_ or {}
        if meta.get("hidden") or meta.get("context_visibility") == "background":
            continue
        images = [
            att for att in (msg.attachments or [])
            if att.type == "image" and att.file_data
        ]
        if not images:
            continue
        payloads: list[dict] = []
        for att in images[:max_images]:
            payloads.append({
                "type": "image",
                "content": base64.b64encode(att.file_data or b"").decode("ascii"),
                "mime_type": att.mime_type or "image/jpeg",
                "name": att.filename,
                "attachment_id": str(att.id),
                "source": "recent_chat_image",
            })
        return payloads

    return []
