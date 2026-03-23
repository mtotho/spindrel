"""Attachment CRUD service — shared across all integrations."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import async_session
from app.db.models import Attachment

logger = logging.getLogger(__name__)

# Infer attachment type from MIME type
_IMAGE_PREFIXES = ("image/",)
_TEXT_MIMES = {
    "text/plain", "text/markdown", "text/csv", "text/html",
    "application/json", "application/xml", "text/x-python",
    "application/x-yaml",
}
_AUDIO_PREFIXES = ("audio/",)
_VIDEO_PREFIXES = ("video/",)


def _infer_type(mime_type: str) -> str:
    if any(mime_type.startswith(p) for p in _IMAGE_PREFIXES):
        return "image"
    if mime_type in _TEXT_MIMES or mime_type.startswith("text/"):
        return "text"
    if any(mime_type.startswith(p) for p in _AUDIO_PREFIXES):
        return "audio"
    if any(mime_type.startswith(p) for p in _VIDEO_PREFIXES):
        return "video"
    return "file"


async def create_attachment(
    message_id: uuid.UUID,
    channel_id: uuid.UUID | None,
    url: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    posted_by: str | None,
    source_integration: str,
    attachment_type: str | None = None,
) -> Attachment:
    """Persist an attachment and kick off async summarization."""
    resolved_type = attachment_type or _infer_type(mime_type)
    attachment = Attachment(
        id=uuid.uuid4(),
        message_id=message_id,
        channel_id=channel_id,
        type=resolved_type,
        url=url,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        posted_by=posted_by,
        source_integration=source_integration,
    )
    async with async_session() as db:
        db.add(attachment)
        await db.commit()
        await db.refresh(attachment)

    # Fire eager summarization
    if settings.ATTACHMENT_SUMMARY_ENABLED and resolved_type in ("image", "text", "file"):
        from app.services.attachment_summarizer import summarize_attachment
        asyncio.create_task(summarize_attachment(attachment.id))

    logger.info(
        "Created attachment %s (%s, %s) for message %s",
        attachment.id, resolved_type, filename, message_id,
    )
    return attachment


async def get_attachment_by_id(attachment_id: uuid.UUID) -> Attachment | None:
    async with async_session() as db:
        return await db.get(Attachment, attachment_id)


async def get_attachments_for_message(message_id: uuid.UUID) -> list[Attachment]:
    async with async_session() as db:
        result = await db.execute(
            select(Attachment)
            .where(Attachment.message_id == message_id)
            .order_by(Attachment.created_at)
        )
        return list(result.scalars().all())


async def get_attachments_for_channel(
    channel_id: uuid.UUID,
    attachment_type: str | None = None,
    limit: int = 50,
) -> list[Attachment]:
    async with async_session() as db:
        q = select(Attachment).where(Attachment.channel_id == channel_id)
        if attachment_type:
            q = q.where(Attachment.type == attachment_type)
        q = q.order_by(Attachment.created_at.desc()).limit(limit)
        result = await db.execute(q)
        return list(result.scalars().all())
