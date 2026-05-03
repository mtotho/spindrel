"""Helpers for carrying recent visible image context across chat turns."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Message


@dataclass(frozen=True)
class RecentInlineImageContext:
    payloads: list[dict]
    source_message_id: uuid.UUID
    source_message_created_at: datetime
    attachment_ids: list[str]
    mime_types: list[str]
    filenames: list[str]
    max_age_seconds: int | None
    max_images: int

    def trace_data(self, *, current_message_id: uuid.UUID | None = None) -> dict:
        now = datetime.now(timezone.utc)
        source_created_at = self.source_message_created_at
        if source_created_at.tzinfo is None:
            source_created_at = source_created_at.replace(tzinfo=timezone.utc)
        age_seconds = max(0, int((now - source_created_at).total_seconds()))
        return {
            "source": "recent_chat_image",
            "reason": "text_followup_without_current_attachment",
            "current_message_id": str(current_message_id) if current_message_id else None,
            "source_message_id": str(self.source_message_id),
            "attachment_ids": self.attachment_ids,
            "mime_types": self.mime_types,
            "filenames": self.filenames,
            "admitted_count": len(self.payloads),
            "age_seconds": age_seconds,
            "max_age_seconds": self.max_age_seconds,
            "max_images": self.max_images,
            "content_included": False,
        }


async def recent_inline_image_context(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    before_message_id: uuid.UUID | None = None,
    max_age_seconds: int | None = None,
    max_images: int = 3,
    scan_messages: int = 50,
) -> RecentInlineImageContext | None:
    """Return inline payloads and trace metadata for the latest visible image.

    Project-style chats can refer back to "that plant" hours later, so this is
    intentionally not time-limited by default. The bounded message scan prevents
    arbitrary old attachments from being silently rehydrated.
    """
    if max_images <= 0 or scan_messages <= 0:
        return None

    before_created_at: datetime | None = None
    if before_message_id is not None:
        before = await db.get(Message, before_message_id)
        if before is not None:
            before_created_at = before.created_at

    stmt = (
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.session_id == session_id)
        .where(Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(scan_messages)
    )
    if max_age_seconds is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        stmt = stmt.where(Message.created_at >= cutoff)
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
        attachment_ids: list[str] = []
        mime_types: list[str] = []
        filenames: list[str] = []
        for att in images[:max_images]:
            mime = att.mime_type or "image/jpeg"
            filename = att.filename or "attachment"
            attachment_id = str(att.id)
            payloads.append({
                "type": "image",
                "content": base64.b64encode(att.file_data or b"").decode("ascii"),
                "mime_type": mime,
                "name": filename,
                "attachment_id": attachment_id,
                "source": "recent_chat_image",
            })
            attachment_ids.append(attachment_id)
            mime_types.append(mime)
            filenames.append(filename)
        return RecentInlineImageContext(
            payloads=payloads,
            source_message_id=msg.id,
            source_message_created_at=msg.created_at,
            attachment_ids=attachment_ids,
            mime_types=mime_types,
            filenames=filenames,
            max_age_seconds=max_age_seconds,
            max_images=max_images,
        )

    return None


async def recent_inline_image_payloads(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    before_message_id: uuid.UUID | None = None,
    max_age_seconds: int | None = None,
    max_images: int = 3,
) -> list[dict]:
    """Return inline image payloads from the latest recent visible image message.

    Compatibility wrapper for callers that only need model payloads.
    """
    context = await recent_inline_image_context(
        db,
        session_id=session_id,
        before_message_id=before_message_id,
        max_age_seconds=max_age_seconds,
        max_images=max_images,
    )
    return context.payloads if context else []
