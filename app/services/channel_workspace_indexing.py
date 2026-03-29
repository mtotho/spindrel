"""Channel workspace indexing — indexes channel workspace files into filesystem_chunks.

Uses bot_id = "channel:{channel_id}" as a sentinel for channel-scoped indexing.
Files are indexed relative to the shared workspace root.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)


def _get_channel_index_bot_id(channel_id: str) -> str:
    """Sentinel bot_id for channel workspace chunks."""
    return f"channel:{channel_id}"


async def index_channel_workspace(
    channel_id: str,
    bot: "BotConfig",
    *,
    force: bool = True,
    channel_segments: list[dict] | None = None,
) -> dict | None:
    """Index channel workspace files into filesystem_chunks.

    Uses bot_id = "channel:{channel_id}" as sentinel for channel-scoped indexing.
    Root = shared workspace root (or bot workspace root).
    Patterns = channels/{channel_id}/workspace/**/*.md

    When channel_segments is provided, constructs segment objects for index_directory
    so that additional directories (e.g. data/repo/) are indexed alongside the base
    .md pattern.
    """
    from app.agent.fs_indexer import index_directory
    from app.services.channel_workspace import _get_ws_root
    from app.services.workspace_indexing import resolve_indexing

    ws_root = _get_ws_root(bot)
    root = str(Path(ws_root).resolve())
    sentinel_bot_id = _get_channel_index_bot_id(channel_id)
    base_prefix = f"channels/{channel_id}/workspace"
    patterns = [f"{base_prefix}/**/*.md"]

    # Resolve embedding model from bot's workspace config
    _resolved = resolve_indexing(
        bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config,
    )
    embedding_model = _resolved["embedding_model"]

    # Build segments when channel has index_segments configured
    segments = None
    skip_stale = True
    if channel_segments:
        segments = [
            # Base segment: .md files in workspace root
            {
                "path_prefix": base_prefix,
                "patterns": ["**/*.md"],
                "embedding_model": embedding_model,
            },
        ]
        for seg in channel_segments:
            segments.append({
                "path_prefix": f"{base_prefix}/{seg['path_prefix'].strip('/')}",
                "patterns": seg.get("patterns") or ["**/*"],
                "embedding_model": seg.get("embedding_model") or embedding_model,
            })
        # With segments, enable stale cleanup so removed segments get cleaned up
        skip_stale = False

    try:
        stats = await index_directory(
            root,
            sentinel_bot_id,
            patterns,
            force=force,
            embedding_model=embedding_model,
            segments=segments,
            skip_stale_cleanup=skip_stale,
        )
        logger.info(
            "Channel workspace index for channel %s (model=%s, segments=%d): %s",
            channel_id, embedding_model, len(channel_segments or []), stats,
        )
        return stats
    except Exception:
        logger.exception("Failed to index channel workspace for channel %s", channel_id)
        return None
