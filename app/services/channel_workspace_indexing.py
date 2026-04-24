"""Channel-workspace indexing compatibility shim — absorbed into bot_indexing.

`_get_channel_index_bot_id` is still used by channel search tools as a
lookup sentinel; `index_channel_workspace` delegates to the new writer.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.bots import BotConfig


def _get_channel_index_bot_id(channel_id: str) -> str:
    """Sentinel bot_id used when storing channel-scoped filesystem chunks."""
    return f"channel:{channel_id}"


async def index_channel_workspace(
    channel_id: str,
    bot: "BotConfig",
    *,
    force: bool = True,
    channel_segments: list[dict] | None = None,
) -> dict | None:
    """Delegate to ``bot_indexing.reindex_channel``."""
    from app.services.bot_indexing import reindex_channel
    return await reindex_channel(
        channel_id, bot,
        channel_segments=channel_segments,
        force=force,
    )
