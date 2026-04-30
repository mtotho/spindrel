"""Unified per-bot indexing interface.

Consolidates workspace / memory / channel indexing decisions behind one
typed `resolve_for()` reader plus one `reindex_bot()` writer. Call sites
previously reached into `workspace_indexing.resolve_indexing()` +
`get_all_roots()` directly, duplicating the three-tier cascade and the
memory/segment gating logic at every location.

This module is the single ownership boundary. `memory_indexing` and
`channel_workspace_indexing` remain as compatibility adapters; indexing policy
lives here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator, Literal

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)

Scope = Literal["workspace", "memory", "channel"]
MEMORY_PATTERNS = ["memory/**/*.md"]
_CHANNEL_INDEX_IN_FLIGHT: set[tuple[str, str]] = set()


@dataclass(frozen=True)
class BotIndexPlan:
    """Resolved indexing plan for one (bot, scope) pair.

    `bot_id` is the sentinel id to store on chunks — for channel scope
    this becomes ``"channel:{channel_id}"``, not the bot's own id.
    """

    bot_id: str
    roots: tuple[str, ...]
    patterns: list[str]
    embedding_model: str
    similarity_threshold: float
    top_k: int
    watch: bool
    cooldown_seconds: int
    segments: list[dict] | None
    scope: Scope
    shared_workspace: bool
    skip_stale_cleanup: bool
    include_bots: list[str] | None = None
    segments_source: str | None = None


def resolve_for(
    bot: "BotConfig",
    *,
    scope: Scope = "workspace",
    channel_id: str | None = None,
    channel_segments: list[dict] | None = None,
) -> BotIndexPlan | None:
    """Return the indexing plan for ``bot`` under ``scope``, or None.

    Pure reader — no I/O, no DB writes. Returns ``None`` when the scope
    does not apply to this bot (e.g. workspace disabled).
    """
    if scope == "workspace":
        return _resolve_workspace(bot)
    if scope == "memory":
        return _resolve_memory(bot)
    if scope == "channel":
        return _resolve_channel(
            bot,
            channel_id=channel_id,
            channel_segments=channel_segments,
        )
    raise ValueError(f"unknown scope: {scope!r}")


def get_memory_patterns() -> list[str]:
    """Return workspace-root-relative memory watcher patterns."""
    return list(MEMORY_PATTERNS)


def channel_index_bot_id(channel_id: str) -> str:
    """Return the sentinel bot_id used for channel-scoped filesystem chunks."""
    return f"channel:{channel_id}"


def plan_to_resolved_config(
    plan: BotIndexPlan,
    *,
    enabled: bool | None = None,
) -> dict:
    """Convert a plan back to the legacy resolved-indexing response shape."""
    resolved = {
        "patterns": list(plan.patterns),
        "similarity_threshold": plan.similarity_threshold,
        "top_k": plan.top_k,
        "watch": plan.watch,
        "cooldown_seconds": plan.cooldown_seconds,
        "embedding_model": plan.embedding_model,
        "segments": plan.segments or [],
        "include_bots": plan.include_bots or [],
        "segments_source": plan.segments_source or "default",
    }
    if enabled is not None:
        resolved["enabled"] = enabled
    return resolved


def _resolve_workspace(bot: "BotConfig") -> BotIndexPlan | None:
    if not bot.workspace.enabled:
        return None
    from app.services.workspace_indexing import get_all_roots, resolve_indexing

    resolved = resolve_indexing(
        bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config
    )
    roots = tuple(get_all_roots(bot))
    return BotIndexPlan(
        bot_id=bot.id,
        roots=roots,
        patterns=resolved["patterns"],
        embedding_model=resolved["embedding_model"],
        similarity_threshold=resolved["similarity_threshold"],
        top_k=resolved["top_k"],
        watch=resolved["watch"],
        cooldown_seconds=resolved["cooldown_seconds"],
        segments=resolved.get("segments") or None,
        scope="workspace",
        shared_workspace=bool(bot.shared_workspace_id),
        skip_stale_cleanup=False,
        include_bots=resolved.get("include_bots") or [],
        segments_source=resolved.get("segments_source") or "default",
    )


def _resolve_memory(bot: "BotConfig") -> BotIndexPlan | None:
    if getattr(bot, "memory_scheme", None) != "workspace-files":
        return None
    plan = _resolve_workspace(bot)
    if plan is None:
        return None
    return BotIndexPlan(
        bot_id=plan.bot_id,
        roots=plan.roots,
        patterns=get_memory_patterns(),
        embedding_model=plan.embedding_model,
        similarity_threshold=plan.similarity_threshold,
        top_k=plan.top_k,
        watch=True,
        cooldown_seconds=plan.cooldown_seconds,
        segments=None,
        scope="memory",
        shared_workspace=plan.shared_workspace,
        skip_stale_cleanup=True,
        include_bots=plan.include_bots,
        segments_source=plan.segments_source,
    )


def _resolve_channel(
    bot: "BotConfig",
    *,
    channel_id: str | None,
    channel_segments: list[dict] | None = None,
    base_prefix: str | None = None,
    base_root: str | None = None,
) -> BotIndexPlan | None:
    if not channel_id:
        raise ValueError("channel_id is required for channel indexing")

    plan = _resolve_workspace(bot)
    if plan is None:
        return None

    from pathlib import Path

    from app.services.channel_workspace import _get_ws_root

    ch_id = str(channel_id)
    root = str(Path(base_root or _get_ws_root(bot)).resolve())
    base_prefix = (base_prefix or f"channels/{ch_id}").strip("/")
    patterns = [f"{base_prefix}/**/*.md"]

    segments = None
    skip_stale = True
    if channel_segments:
        segments = [
            {
                "path_prefix": base_prefix,
                "patterns": ["**/*.md"],
                "embedding_model": plan.embedding_model,
            }
        ]
        for seg in channel_segments:
            path_prefix = str(seg["path_prefix"]).strip("/")
            segments.append(
                {
                    "path_prefix": f"{base_prefix}/{path_prefix}",
                    "patterns": seg.get("patterns") or ["**/*"],
                    "embedding_model": seg.get("embedding_model") or plan.embedding_model,
                }
            )
        skip_stale = False

    return BotIndexPlan(
        bot_id=channel_index_bot_id(ch_id),
        roots=(root,),
        patterns=patterns,
        embedding_model=plan.embedding_model,
        similarity_threshold=plan.similarity_threshold,
        top_k=plan.top_k,
        watch=plan.watch,
        cooldown_seconds=plan.cooldown_seconds,
        segments=segments,
        scope="channel",
        shared_workspace=plan.shared_workspace,
        skip_stale_cleanup=skip_stale,
        include_bots=plan.include_bots,
        segments_source=plan.segments_source,
    )


async def reindex_bot(
    bot: "BotConfig",
    *,
    include_workspace: bool = True,
    include_memory: bool = True,
    force: bool = True,
    cleanup_orphans: bool = False,
) -> dict | None:
    """Run per-bot indexing — memory + workspace in one call.

    When ``cleanup_orphans=True`` (startup path), stale filesystem_chunks
    whose ``root`` is outside the bot's current roots are removed before
    indexing, and the shared-workspace-no-segments branch additionally
    deletes non-memory chunks under each current root — matching the
    previous ``main.py:204-222`` behavior, gated behind this flag so it
    only runs at startup, not on every watcher tick.
    """
    plan = _resolve_workspace(bot)
    do_memory = (
        include_memory
        and bot.memory_scheme == "workspace-files"
        and bot.workspace.enabled
    )
    if plan is None and not do_memory:
        return None

    from app.agent.fs_indexer import cleanup_stale_roots, index_directory

    merged: dict = {"indexed": 0, "skipped": 0, "removed": 0, "errors": 0, "cooldown": False}
    touched = False

    if cleanup_orphans and plan is not None:
        try:
            removed = await cleanup_stale_roots(bot.id, list(plan.roots))
            if removed:
                merged["stale_roots_cleaned"] = removed
                touched = True
                logger.info("Cleaned up %d stale chunks for bot %s", removed, bot.id)
        except Exception:
            logger.exception("Failed to clean up stale roots for bot %s", bot.id)

    if do_memory:
        try:
            mem_stats = await _reindex_memory(bot, plan=plan, force=force)
            if mem_stats:
                _merge_stats(merged, mem_stats)
                touched = True
                logger.info("Memory index for bot %s: %s", bot.id, mem_stats)
        except Exception:
            logger.exception("Failed to index memory for bot %s", bot.id)

    if include_workspace and plan is not None and bot.workspace.indexing.enabled:
        if not plan.segments:
            if cleanup_orphans and plan.shared_workspace:
                await _cleanup_non_memory_chunks(bot, plan)
        else:
            for root in plan.roots:
                try:
                    stats = await index_directory(
                        root, bot.id, plan.patterns, force=force,
                        embedding_model=plan.embedding_model,
                        segments=plan.segments,
                    )
                    _merge_stats(merged, stats)
                    touched = True
                    logger.info("Indexed workspace root %s for bot %s: %s", root, bot.id, stats)
                except Exception:
                    logger.exception(
                        "Failed to index workspace root %s for bot %s", root, bot.id
                    )

    return merged if touched else None


def _merge_stats(into: dict, other: dict) -> None:
    for k in ("indexed", "skipped", "removed", "errors"):
        into[k] = into.get(k, 0) + other.get(k, 0)


async def _reindex_memory(
    bot: "BotConfig",
    *,
    plan: BotIndexPlan | None = None,
    force: bool = True,
) -> dict | None:
    """Index memory files for a workspace-files bot.

    Absorbed from the old ``memory_indexing.index_memory_for_bot`` helper.
    Uses the bot's resolved embedding model so memory chunks match what
    ``search_memory`` queries. Skips stale-cleanup at the indexer level
    because memory chunks are identified by the memory-prefix, not by
    root ownership.
    """
    if bot.memory_scheme != "workspace-files" or not bot.workspace.enabled:
        return None
    if plan is None:
        plan = _resolve_workspace(bot)
        if plan is None:
            return None

    from app.agent.fs_indexer import index_directory
    from app.services.memory_scheme import get_memory_index_patterns

    patterns = get_memory_index_patterns(bot)
    results: list[dict] = []
    for root in plan.roots:
        try:
            stats = await index_directory(
                root, bot.id, patterns, force=force,
                embedding_model=plan.embedding_model,
                skip_stale_cleanup=True,
            )
            results.append(stats)
            logger.info(
                "Memory index for bot %s root %s (model=%s): %s",
                bot.id, root, plan.embedding_model, stats,
            )
        except Exception:
            logger.exception("Failed to index memory for bot %s root %s", bot.id, root)

    if not results:
        return None
    merged = {"indexed": 0, "skipped": 0, "removed": 0, "errors": 0, "cooldown": False}
    for r in results:
        _merge_stats(merged, r)
    return merged


async def reindex_channel(
    channel_id: str,
    bot: "BotConfig",
    *,
    channel_segments: list[dict] | None = None,
    force: bool = False,
) -> dict | None:
    """Index channel workspace files into filesystem_chunks.

    Absorbed from the old ``channel_workspace_indexing.index_channel_workspace``.
    Uses ``bot_id = "channel:{channel_id}"`` as sentinel so channel chunks
    don't collide with the bot's own workspace chunks. Root = shared
    workspace root (or bot's own workspace root).

    The channel flavor uses a sentinel bot id and channel-derived patterns,
    but still inherits embedding/search defaults from the bot workspace
    cascade through ``resolve_for(scope="channel")``. Context assembly calls
    this opportunistically during agent turns, so the default must respect the
    filesystem-index cooldown; explicit maintenance/admin callers may pass
    ``force=True`` when they truly need a rebuild.
    """
    from app.agent.fs_indexer import index_directory

    base_prefix = None
    base_root = None
    try:
        from app.db.engine import async_session
        from app.db.models import Channel
        from app.services.projects import is_project_like_surface, resolve_channel_work_surface

        async with async_session() as db:
            channel = await db.get(Channel, channel_id)
            surface = await resolve_channel_work_surface(db, channel, bot) if channel is not None else None
        if is_project_like_surface(surface):
            base_prefix = surface.index_prefix
            base_root = surface.index_root_host_path
    except Exception:
        logger.debug("Could not resolve project index prefix for channel %s", channel_id, exc_info=True)
        if channel is not None and getattr(channel, "project_id", None):
            raise

    plan = _resolve_channel(
        bot,
        channel_id=channel_id,
        channel_segments=channel_segments,
        base_prefix=base_prefix,
        base_root=base_root,
    )
    if plan is None:
        return None

    in_flight_key = (plan.roots[0], plan.bot_id)
    if in_flight_key in _CHANNEL_INDEX_IN_FLIGHT:
        logger.info(
            "Skipping channel workspace index for channel %s (already in flight)",
            channel_id,
        )
        return {
            "indexed": 0,
            "skipped": 0,
            "removed": 0,
            "errors": 0,
            "cooldown": True,
            "in_flight": True,
        }

    _CHANNEL_INDEX_IN_FLIGHT.add(in_flight_key)
    try:
        stats = await index_directory(
            plan.roots[0], plan.bot_id, plan.patterns, force=force,
            embedding_model=plan.embedding_model,
            segments=plan.segments,
            skip_stale_cleanup=plan.skip_stale_cleanup,
        )
        logger.info(
            "Channel workspace index for channel %s (model=%s, segments=%d): %s",
            channel_id, plan.embedding_model, len(channel_segments or []), stats,
        )
        return stats
    except Exception:
        logger.exception("Failed to index channel workspace for channel %s", channel_id)
        return None
    finally:
        _CHANNEL_INDEX_IN_FLIGHT.discard(in_flight_key)


def iter_watch_targets(
    bots: list["BotConfig"],
) -> Iterator[tuple[BotIndexPlan, str]]:
    """Yield ``(plan, root)`` for every filesystem watcher this pass should mount.

    Handles both workspace-indexing bots (``plan.scope == "workspace"``) and
    memory-only bots with ``memory_scheme == "workspace-files"`` (yields a
    synthetic ``scope="memory"`` plan carrying the memory patterns). Shared-
    workspace bots are skipped — they are covered by
    ``start_shared_workspace_watchers()``.
    """
    for bot in bots:
        if getattr(bot, "shared_workspace_id", None):
            continue
        ws = getattr(bot, "workspace", None)
        if not (ws and ws.enabled):
            continue
        plan = _resolve_workspace(bot)
        if plan is None:
            continue
        if ws.indexing.enabled:
            if not plan.watch:
                continue
            for root in plan.roots:
                yield (plan, root)
        elif getattr(bot, "memory_scheme", None) == "workspace-files":
            mem_plan = _resolve_memory(bot)
            if mem_plan is None:
                continue
            for root in plan.roots:
                yield (mem_plan, root)


async def _cleanup_non_memory_chunks(bot: "BotConfig", plan: BotIndexPlan) -> None:
    """Remove non-memory filesystem_chunks for bot at plan.roots.

    Preserves ``memory/**`` chunks (prefix resolved from the bot's memory
    scheme). Mirrors the inline block previously at ``main.py:204-222``.
    """
    from pathlib import Path

    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import FilesystemChunk
    from app.services.memory_scheme import get_memory_index_prefix

    mem_prefix = get_memory_index_prefix(bot)
    for root in plan.roots:
        try:
            resolved_root = str(Path(root).resolve())
            async with async_session() as db:
                del_ = await db.execute(
                    delete(FilesystemChunk).where(
                        FilesystemChunk.bot_id == bot.id,
                        FilesystemChunk.root == resolved_root,
                        ~FilesystemChunk.file_path.like(mem_prefix.rstrip("/") + "/%"),
                    )
                )
                if del_.rowcount:
                    logger.info(
                        "Cleaned up %d non-memory chunks for bot %s (no segments)",
                        del_.rowcount, bot.id,
                    )
                await db.commit()
        except Exception:
            logger.exception("Failed to clean up non-memory chunks for bot %s", bot.id)
