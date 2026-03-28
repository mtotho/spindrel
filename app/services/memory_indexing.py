"""Memory-specific indexing helpers.

Ensures memory files (memory/**/*.md) are indexed regardless of whether
workspace.indexing.enabled is set.  This decouples search_memory from the
general workspace indexing toggle.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)

MEMORY_PATTERNS = ["memory/**/*.md"]


def get_memory_patterns() -> list[str]:
    """Return the glob patterns used to index memory files."""
    return list(MEMORY_PATTERNS)


async def index_memory_for_bot(bot: "BotConfig", *, force: bool = True) -> dict | None:
    """Index memory files for a bot with memory_scheme='workspace-files'.

    Calls index_directory with memory-only patterns, bypassing any check on
    workspace.indexing.enabled.  Returns None if the bot doesn't use
    workspace-files memory scheme or doesn't have workspace enabled.
    """
    if bot.memory_scheme != "workspace-files" or not bot.workspace.enabled:
        return None

    from app.agent.fs_indexer import index_directory
    from app.services.workspace import workspace_service
    from app.services.workspace_indexing import get_all_roots, resolve_indexing
    from app.services.memory_scheme import get_memory_index_patterns

    # Use the resolved embedding model so memory chunks match what search_memory queries
    _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
    embedding_model = _resolved["embedding_model"]

    # Use index-aware patterns (bots/{id}/memory/**/*.md for shared workspace bots)
    patterns = get_memory_index_patterns(bot)
    results: list[dict] = []
    for root in get_all_roots(bot, workspace_service):
        try:
            stats = await index_directory(
                root, bot.id, patterns, force=force,
                embedding_model=embedding_model,
            )
            results.append(stats)
            logger.info("Memory index for bot %s root %s (model=%s): %s", bot.id, root, embedding_model, stats)
        except Exception:
            logger.exception("Failed to index memory for bot %s root %s", bot.id, root)

    if not results:
        return None
    # Merge stats from all roots
    merged = {"indexed": 0, "skipped": 0, "removed": 0, "errors": 0, "cooldown": False}
    for r in results:
        for k in ("indexed", "skipped", "removed", "errors"):
            merged[k] += r.get(k, 0)
    return merged
