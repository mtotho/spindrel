"""In-memory reverse index of pinned file paths → channel IDs.

Loaded at startup, invalidated on pin/unpin. Used by file_ops to
cheaply check if a write should emit a PINNED_FILE_UPDATED event.
"""
from __future__ import annotations

import logging
import mimetypes
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB

from app.db.engine import async_session

logger = logging.getLogger(__name__)

# path → set of channel_ids that have this path pinned
_pinned_paths: dict[str, set[uuid.UUID]] = defaultdict(set)
_loaded: bool = False


async def load_pinned_paths() -> None:
    """Load all pinned paths from DB into in-memory cache. Called at startup."""
    global _loaded
    _pinned_paths.clear()

    from app.db.models import Channel

    async with async_session() as db:
        # Only fetch channels that have non-empty pinned_panels
        stmt = select(Channel.id, Channel.config).where(
            Channel.config["pinned_panels"].astext != "null",
            Channel.config["pinned_panels"].astext != "[]",
        )
        rows = (await db.execute(stmt)).all()

    count = 0
    for channel_id, config in rows:
        panels = (config or {}).get("pinned_panels", [])
        for panel in panels:
            path = panel.get("path")
            if path:
                _pinned_paths[path].add(channel_id)
                count += 1

    _loaded = True
    if count:
        logger.info("Loaded %d pinned-path mapping(s) across %d channel(s)", count, len(rows))


def is_path_pinned(path: str) -> set[uuid.UUID]:
    """Return set of channel_ids that have this path pinned. O(1)."""
    return _pinned_paths.get(path, set())


async def invalidate_channel(channel_id: uuid.UUID) -> None:
    """Re-query a single channel's pinned paths and rebuild its entries."""
    # Remove all existing entries for this channel
    for path_set in _pinned_paths.values():
        path_set.discard(channel_id)

    # Clean up empty sets
    empty_keys = [k for k, v in _pinned_paths.items() if not v]
    for k in empty_keys:
        del _pinned_paths[k]

    # Re-query this channel
    from app.db.models import Channel

    async with async_session() as db:
        ch = (await db.execute(
            select(Channel.config).where(Channel.id == channel_id)
        )).scalar_one_or_none()

    if ch:
        panels = (ch or {}).get("pinned_panels", [])
        for panel in panels:
            path = panel.get("path")
            if path:
                _pinned_paths[path].add(channel_id)


def _mimetype_for_path(path: str) -> str:
    """Infer content_type from file extension."""
    mt, _ = mimetypes.guess_type(path)
    if mt:
        return mt
    if path.endswith((".md", ".mdx")):
        return "text/markdown"
    return "text/plain"


async def notify_pinned_file_changed(path: str) -> None:
    """If *path* is pinned in any channel, publish PINNED_FILE_UPDATED events."""
    channel_ids = is_path_pinned(path)
    if not channel_ids:
        return

    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.payloads import PinnedFileUpdatedPayload
    from app.services.channel_events import publish_typed

    content_type = _mimetype_for_path(path)

    for cid in channel_ids:
        publish_typed(
            cid,
            ChannelEvent(
                channel_id=cid,
                kind=ChannelEventKind.PINNED_FILE_UPDATED,
                payload=PinnedFileUpdatedPayload(
                    channel_id=cid,
                    path=path,
                    content_type=content_type,
                ),
            ),
        )
