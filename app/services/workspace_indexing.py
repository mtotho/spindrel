"""Three-tier indexing config resolution: bot-explicit → workspace default → global env."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from app.agent.bots import IndexSegment

_DEFAULT_PATTERNS = ["**/*.py", "**/*.md", "**/*.yaml"]


def _resolve_segments(segments: list[IndexSegment], base: dict) -> list[dict]:
    """Resolve each segment by inheriting unset fields from the base resolved config.

    Returns a list of dicts with fully-resolved values per segment.
    """
    result = []
    for seg in segments:
        result.append({
            "path_prefix": seg.path_prefix,
            "embedding_model": seg.embedding_model if seg.embedding_model is not None else base["embedding_model"],
            "patterns": seg.patterns if seg.patterns is not None else base["patterns"],
            "similarity_threshold": seg.similarity_threshold if seg.similarity_threshold is not None else base["similarity_threshold"],
            "top_k": seg.top_k if seg.top_k is not None else base["top_k"],
            "watch": seg.watch if seg.watch is not None else base["watch"],
            "channel_id": seg.channel_id,
        })
    return result


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

    # embedding_model: bot (if not None) → workspace → global
    if bot_indexing.embedding_model is not None:
        embedding_model = bot_indexing.embedding_model
    elif ws_cfg.get("embedding_model") is not None:
        embedding_model = ws_cfg["embedding_model"]
    else:
        embedding_model = settings.EMBEDDING_MODEL

    # segments: bot-level only (not cascaded from workspace)
    segments = _resolve_segments(bot_indexing.segments, {
        "embedding_model": embedding_model,
        "patterns": patterns,
        "similarity_threshold": similarity_threshold,
        "top_k": top_k,
        "watch": watch,
    })

    return {
        "patterns": patterns,
        "similarity_threshold": similarity_threshold,
        "top_k": top_k,
        "watch": watch,
        "cooldown_seconds": cooldown_seconds,
        "include_bots": bot_indexing.include_bots or [],
        "embedding_model": embedding_model,
        "segments": segments,
    }


def get_all_roots(bot, workspace_service=None) -> list[str]:
    """Return all workspace roots for a bot.

    For shared workspace bots, returns the shared workspace root so that
    segments referencing common/, hub/, etc. (outside bots/{id}/) are reachable.
    File paths are then stored relative to the workspace root.

    For standalone bots, returns the bot's own workspace directory.

    Args:
        bot: BotConfig instance.
        workspace_service: Optional workspace service (imported lazily if None).

    Returns:
        List of host-side root paths to index/search.
    """
    if bot.shared_workspace_id:
        from app.services.shared_workspace import shared_workspace_service
        return [shared_workspace_service.get_host_root(bot.shared_workspace_id)]

    if workspace_service is None:
        from app.services.workspace import workspace_service
    own_root = workspace_service.get_workspace_root(bot.id, bot=bot)
    return [own_root]
