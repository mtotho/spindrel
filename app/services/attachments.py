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


async def _get_bot_attachment_config(bot_id: str | None) -> dict:
    """Look up bot-level attachment overrides. Returns dict of non-None overrides."""
    if not bot_id:
        return {}
    try:
        from app.db.models import Bot as BotRow
        async with async_session() as db:
            row = await db.get(BotRow, bot_id)
        if not row:
            return {}
        overrides = {}
        if row.attachment_summarization_enabled is not None:
            overrides["enabled"] = row.attachment_summarization_enabled
        if row.attachment_summary_model is not None:
            overrides["model"] = row.attachment_summary_model
        if row.attachment_summary_model_provider_id is not None:
            overrides["model_provider_id"] = row.attachment_summary_model_provider_id
        if row.attachment_text_max_chars is not None:
            overrides["text_max_chars"] = row.attachment_text_max_chars
        if row.attachment_vision_concurrency is not None:
            overrides["vision_concurrency"] = row.attachment_vision_concurrency
        return overrides
    except Exception:
        logger.warning("Failed to load bot attachment config for %s", bot_id, exc_info=True)
        return {}


async def _get_channel_for_retention(channel_id: uuid.UUID | None):
    """Load channel row for retention config lookup."""
    if not channel_id:
        return None
    from app.db.models import Channel
    async with async_session() as db:
        return await db.get(Channel, channel_id)


async def create_attachment(
    message_id: uuid.UUID | None,
    channel_id: uuid.UUID | None,
    filename: str,
    mime_type: str,
    size_bytes: int,
    posted_by: str | None,
    source_integration: str,
    file_data: bytes | None = None,
    url: str | None = None,
    attachment_type: str | None = None,
    bot_id: str | None = None,
) -> Attachment:
    """Persist an attachment and kick off async summarization."""
    resolved_type = attachment_type or _infer_type(mime_type)

    # Enforce size and type restrictions (channel → global)
    stored_file_data = file_data
    if stored_file_data is not None:
        from app.services.attachment_retention import get_effective_retention
        channel = await _get_channel_for_retention(channel_id)
        effective = get_effective_retention(channel)

        max_size = effective["max_size_bytes"]
        if max_size is not None and size_bytes > max_size:
            logger.info(
                "Attachment %s (%d bytes) exceeds max_size_bytes %d for channel %s — storing metadata only",
                filename, size_bytes, max_size, channel_id,
            )
            stored_file_data = None

        types_allowed = effective["types_allowed"]
        if stored_file_data is not None and types_allowed is not None and resolved_type not in types_allowed:
            logger.info(
                "Attachment type '%s' not in allowed types %s for channel %s — storing metadata only",
                resolved_type, types_allowed, channel_id,
            )
            stored_file_data = None

    attachment = Attachment(
        id=uuid.uuid4(),
        message_id=message_id,
        channel_id=channel_id,
        type=resolved_type,
        url=url,
        file_data=stored_file_data,
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

    # Resolve bot-level overrides
    bot_config = await _get_bot_attachment_config(bot_id)
    summarization_enabled = bot_config.get("enabled", settings.ATTACHMENT_SUMMARY_ENABLED)

    # Fire eager summarization
    if summarization_enabled and resolved_type in ("image", "text", "file"):
        from app.services.attachment_summarizer import summarize_attachment
        asyncio.create_task(summarize_attachment(attachment.id, bot_overrides=bot_config))

    logger.info(
        "Created attachment %s (%s, %s) for message %s",
        attachment.id, resolved_type, filename, message_id,
    )
    return attachment


async def find_orphan_duplicate(
    channel_id: uuid.UUID,
    size_bytes: int,
    mime_type: str,
) -> Attachment | None:
    """Find an existing orphan attachment in the channel with matching size and MIME.

    Used by send_file to avoid creating a duplicate when another tool (e.g.
    generate_image) already created an orphan attachment for the same content
    in the same turn.
    """
    async with async_session() as db:
        result = await db.execute(
            select(Attachment)
            .where(
                Attachment.channel_id == channel_id,
                Attachment.message_id.is_(None),
                Attachment.posted_by.isnot(None),
                Attachment.size_bytes == size_bytes,
                Attachment.mime_type == mime_type,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


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


async def delete_attachment(attachment_id: uuid.UUID) -> dict:
    """Delete an attachment from the DB and dispatch deletion to integrations.

    Uses the dispatcher protocol so each integration handles its own cleanup
    (e.g. Slack deletes the file via files.delete). No integration-specific
    code lives here.

    Returns a dict with status info (deleted, integration_deleted, error).
    """
    async with async_session() as db:
        att = await db.get(Attachment, attachment_id)
        if att is None:
            return {"error": f"Attachment {attachment_id} not found."}

        # Attempt integration-side deletion before removing from DB.
        # Check metadata for integration-specific keys (e.g. slack_file_id)
        # rather than relying on source_integration alone — mirrored channels
        # may have source_integration="web" but still have a Slack file.
        integration_deleted = False
        meta = att.metadata_ or {}

        if att.channel_id and meta:
            integration_type = _infer_integration_from_metadata(meta, att.source_integration)
            if integration_type:
                dispatch_config = await _resolve_dispatch_config(att.channel_id, integration_type)
                if dispatch_config:
                    try:
                        from app.domain.dispatch_target import parse_dispatch_target
                        from app.integrations import renderer_registry

                        renderer = renderer_registry.get(integration_type)
                        if renderer is not None:
                            target_dict = dict(dispatch_config)
                            target_dict.setdefault("type", integration_type)
                            try:
                                target = parse_dispatch_target(target_dict)
                            except ValueError:
                                target = None
                            if target is not None:
                                integration_deleted = await renderer.delete_attachment(meta, target)
                    except Exception:
                        logger.warning(
                            "Failed to delete attachment %s via %s renderer",
                            attachment_id, integration_type, exc_info=True,
                        )

        filename = att.filename
        await db.delete(att)
        await db.commit()

    logger.info("Deleted attachment %s (%s), integration_deleted=%s", attachment_id, filename, integration_deleted)
    return {
        "deleted": str(attachment_id),
        "filename": filename,
        "integration_deleted": integration_deleted,
    }


def _infer_integration_from_metadata(meta: dict, source_integration: str) -> str | None:
    """Determine which integration to dispatch deletion to based on metadata keys.

    Metadata keys are prefixed with the integration name (e.g. slack_file_id),
    so we can detect which integration uploaded the file even if
    source_integration is "web" (mirrored channels).
    """
    # Map metadata key prefixes to integration types
    if meta.get("slack_file_id"):
        return "slack"
    # Future: discord_file_id → "discord", telegram_file_id → "telegram", etc.

    # Fallback: use source_integration if it's not "web"
    if source_integration and source_integration != "web":
        return source_integration

    return None


async def _resolve_dispatch_config(channel_id: uuid.UUID, integration_type: str) -> dict | None:
    """Resolve dispatch_config for a channel's integration binding."""
    from app.db.models import Channel, ChannelIntegration

    async with async_session() as db:
        # Try channel-level dispatch_config first
        channel = await db.get(Channel, channel_id)
        if channel and channel.integration == integration_type and channel.dispatch_config:
            return channel.dispatch_config

        # Fall back to ChannelIntegration binding
        result = await db.execute(
            select(ChannelIntegration)
            .where(
                ChannelIntegration.channel_id == channel_id,
                ChannelIntegration.integration_type == integration_type,
            )
            .limit(1)
        )
        binding = result.scalar_one_or_none()
        if not binding:
            return None

        if binding.dispatch_config:
            return binding.dispatch_config

        # Legacy: resolve via integration hook
        if binding.client_id:
            try:
                from app.agent.hooks import get_integration_meta
                meta = get_integration_meta(integration_type)
                if meta and meta.resolve_dispatch_config:
                    return meta.resolve_dispatch_config(binding.client_id)
            except Exception:
                pass

    return None


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
