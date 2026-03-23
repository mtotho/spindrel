"""Attachment retention sweep — nulls file_data on expired attachments."""

import asyncio
import logging

from sqlalchemy import text, update

from app.config import settings
from app.db.engine import async_session
from app.db.models import Attachment, Channel

logger = logging.getLogger(__name__)


def get_effective_retention(channel: Channel | None) -> dict:
    """Resolve effective retention config: channel → global → None."""
    if channel:
        retention_days = channel.attachment_retention_days if channel.attachment_retention_days is not None else settings.ATTACHMENT_RETENTION_DAYS
        max_size_bytes = channel.attachment_max_size_bytes if channel.attachment_max_size_bytes is not None else settings.ATTACHMENT_MAX_SIZE_BYTES
        types_allowed = channel.attachment_types_allowed if channel.attachment_types_allowed is not None else settings.ATTACHMENT_TYPES_ALLOWED
    else:
        retention_days = settings.ATTACHMENT_RETENTION_DAYS
        max_size_bytes = settings.ATTACHMENT_MAX_SIZE_BYTES
        types_allowed = settings.ATTACHMENT_TYPES_ALLOWED
    return {
        "retention_days": retention_days,
        "max_size_bytes": max_size_bytes,
        "types_allowed": types_allowed,
    }


async def run_attachment_purge_sweep() -> int:
    """Null out file_data on expired attachments. Returns total purged count.

    Resolution: channel.attachment_retention_days → global ATTACHMENT_RETENTION_DAYS → None (keep forever).
    Retroactive: applies to all attachments, not just new ones.
    Orphaned attachments (no channel): use global default.
    """
    total_purged = 0

    async with async_session() as db:
        # 1. Purge attachments in channels with per-channel retention
        result = await db.execute(text("""
            UPDATE attachments a
            SET file_data = NULL
            FROM channels c
            WHERE a.channel_id = c.id
              AND a.file_data IS NOT NULL
              AND c.attachment_retention_days IS NOT NULL
              AND a.created_at < now() - (c.attachment_retention_days || ' days')::interval
        """))
        channel_purged = result.rowcount
        if channel_purged:
            logger.info("Purged file_data from %d attachments (per-channel retention)", channel_purged)
        total_purged += channel_purged

        # 2. Purge attachments in channels with NO per-channel retention, using global default
        global_days = settings.ATTACHMENT_RETENTION_DAYS
        if global_days is not None:
            result = await db.execute(text("""
                UPDATE attachments a
                SET file_data = NULL
                FROM channels c
                WHERE a.channel_id = c.id
                  AND a.file_data IS NOT NULL
                  AND c.attachment_retention_days IS NULL
                  AND a.created_at < now() - (:global_days || ' days')::interval
            """), {"global_days": str(global_days)})
            global_purged = result.rowcount
            if global_purged:
                logger.info("Purged file_data from %d attachments (global retention %d days)", global_purged, global_days)
            total_purged += global_purged

            # 3. Purge orphaned attachments (no channel) using global default
            result = await db.execute(text("""
                UPDATE attachments
                SET file_data = NULL
                WHERE channel_id IS NULL
                  AND file_data IS NOT NULL
                  AND created_at < now() - (:global_days || ' days')::interval
            """), {"global_days": str(global_days)})
            orphan_purged = result.rowcount
            if orphan_purged:
                logger.info("Purged file_data from %d orphaned attachments (global retention)", orphan_purged)
            total_purged += orphan_purged

        await db.commit()

    if total_purged:
        logger.info("Attachment retention sweep complete: %d total purged", total_purged)
    else:
        logger.debug("Attachment retention sweep complete: nothing to purge")

    return total_purged


async def attachment_retention_worker():
    """Background loop: runs purge sweep on a configurable interval."""
    interval = settings.ATTACHMENT_RETENTION_SWEEP_INTERVAL_S
    logger.info("Attachment retention worker started (interval=%ds)", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            await run_attachment_purge_sweep()
        except Exception:
            logger.exception("Attachment retention sweep failed")
