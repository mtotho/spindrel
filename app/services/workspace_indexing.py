"""Three-tier indexing config resolution: bot-explicit → workspace default → global env."""
from __future__ import annotations

from app.config import settings

_DEFAULT_PATTERNS = ["**/*.py", "**/*.md", "**/*.yaml"]


def resolve_indexing(
    bot_indexing,
    bot_workspace_raw: dict,
    ws_indexing_config: dict | None,
) -> dict:
    """Resolve indexing config with three-tier cascade.

    Args:
        bot_indexing: WorkspaceIndexingConfig dataclass from bot config.
        bot_workspace_raw: Raw bot.workspace JSONB dict (to detect explicit keys).
        ws_indexing_config: SharedWorkspace.indexing_config JSONB (or None).

    Returns:
        Dict with resolved keys: patterns, similarity_threshold, top_k, watch, cooldown_seconds.
    """
    raw_idx = (bot_workspace_raw or {}).get("indexing", {})
    ws_cfg = ws_indexing_config or {}

    # patterns: bot explicit → workspace → global default
    if "patterns" in raw_idx:
        patterns = bot_indexing.patterns
    elif "patterns" in ws_cfg:
        patterns = ws_cfg["patterns"]
    else:
        patterns = list(_DEFAULT_PATTERNS)

    # similarity_threshold: bot (if not None) → workspace → global
    if bot_indexing.similarity_threshold is not None:
        similarity_threshold = bot_indexing.similarity_threshold
    elif ws_cfg.get("similarity_threshold") is not None:
        similarity_threshold = ws_cfg["similarity_threshold"]
    else:
        similarity_threshold = settings.FS_INDEX_SIMILARITY_THRESHOLD

    # top_k: bot (if not None) → workspace → global
    if bot_indexing.top_k is not None:
        top_k = bot_indexing.top_k
    elif ws_cfg.get("top_k") is not None:
        top_k = ws_cfg["top_k"]
    else:
        top_k = settings.FS_INDEX_TOP_K

    # watch: bot explicit → workspace → default True
    if "watch" in raw_idx:
        watch = bot_indexing.watch
    elif "watch" in ws_cfg:
        watch = ws_cfg["watch"]
    else:
        watch = True

    # cooldown_seconds: bot explicit → workspace → global
    if "cooldown_seconds" in raw_idx:
        cooldown_seconds = bot_indexing.cooldown_seconds
    elif "cooldown_seconds" in ws_cfg:
        cooldown_seconds = ws_cfg["cooldown_seconds"]
    else:
        cooldown_seconds = settings.FS_INDEX_COOLDOWN_SECONDS

    return {
        "patterns": patterns,
        "similarity_threshold": similarity_threshold,
        "top_k": top_k,
        "watch": watch,
        "cooldown_seconds": cooldown_seconds,
    }
