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
        "include_bots": bot_indexing.include_bots or [],
    }


def get_all_roots(bot, workspace_service=None) -> list[str]:
    """Return all workspace roots for a bot: own root + include_bots roots.

    Args:
        bot: BotConfig instance.
        workspace_service: Optional workspace service (imported lazily if None).

    Returns:
        List of host-side root paths to index/search.
    """
    if workspace_service is None:
        from app.services.workspace import workspace_service
    own_root = workspace_service.get_workspace_root(bot.id, bot=bot)
    roots = [own_root]
    if bot.workspace.indexing.include_bots and bot.shared_workspace_id:
        from app.services.shared_workspace import shared_workspace_service
        import os
        sw_root = shared_workspace_service.get_host_root(bot.shared_workspace_id)
        for other_bot_id in bot.workspace.indexing.include_bots:
            other_root = os.path.join(sw_root, "bots", other_bot_id)
            if other_root not in roots:
                roots.append(other_root)
    return roots
