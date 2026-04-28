"""Memory-indexing compatibility shim — absorbed into app.services.bot_indexing.

Kept as a thin delegator for external callers and test-patch points;
`get_memory_patterns()` is kept for compatibility, but the source of truth
now lives in `bot_indexing`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

def get_memory_patterns() -> list[str]:
    """Return the glob patterns used to index memory files."""
    from app.services.bot_indexing import get_memory_patterns as _get_memory_patterns
    return _get_memory_patterns()


async def index_memory_for_bot(bot: "BotConfig", *, force: bool = True) -> dict | None:
    """Delegate to ``bot_indexing.reindex_bot`` (memory scope only)."""
    from app.services.bot_indexing import reindex_bot
    return await reindex_bot(
        bot, include_memory=True, include_workspace=False, force=force,
    )
