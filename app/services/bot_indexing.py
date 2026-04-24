"""Unified per-bot indexing interface.

Consolidates workspace / memory / channel indexing decisions behind one
typed `resolve_for()` reader plus one `reindex_bot()` writer. Call sites
previously reached into `workspace_indexing.resolve_indexing()` +
`get_all_roots()` directly, duplicating the three-tier cascade and the
memory/segment gating logic at every location.

This module is the single ownership boundary. `memory_indexing` and
`channel_workspace_indexing` are absorbed in later commits; for now
`reindex_bot()` composes them behind one stable entry point.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator, Literal

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)

Scope = Literal["workspace", "memory", "channel"]


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
    if scope in ("memory", "channel"):
        raise NotImplementedError(
            f"bot_indexing.resolve_for(scope={scope!r}) arrives in a later commit"
        )
    raise ValueError(f"unknown scope: {scope!r}")


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
        segments=resolved["segments"] or None,
        scope="workspace",
        shared_workspace=bool(bot.shared_workspace_id),
        skip_stale_cleanup=False,
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
    force: bool = True,
) -> dict | None:
    """Index channel workspace files into filesystem_chunks.

    Absorbed from the old ``channel_workspace_indexing.index_channel_workspace``.
    Uses ``bot_id = "channel:{channel_id}"`` as sentinel so channel chunks
    don't collide with the bot's own workspace chunks. Root = shared
    workspace root (or bot's own workspace root).

    Only needs the resolved ``embedding_model`` from the cascade; the root
    and patterns are channel-derived, so this bypasses ``BotIndexPlan``
    and reads the cascade directly.
    """
    from pathlib import Path

    from app.agent.fs_indexer import index_directory
    from app.services.channel_workspace import _get_ws_root
    from app.services.workspace_indexing import resolve_indexing

    resolved = resolve_indexing(
        bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config,
    )
    embedding_model = resolved["embedding_model"]

    ws_root = _get_ws_root(bot)
    root = str(Path(ws_root).resolve())
    sentinel_bot_id = f"channel:{channel_id}"
    base_prefix = f"channels/{channel_id}"
    patterns = [f"{base_prefix}/**/*.md"]

    segments = None
    skip_stale = True
    if channel_segments:
        segments = [{
            "path_prefix": base_prefix,
            "patterns": ["**/*.md"],
            "embedding_model": embedding_model,
        }]
        for seg in channel_segments:
            segments.append({
                "path_prefix": f"{base_prefix}/{seg['path_prefix'].strip('/')}",
                "patterns": seg.get("patterns") or ["**/*"],
                "embedding_model": seg.get("embedding_model") or embedding_model,
            })
        skip_stale = False

    try:
        stats = await index_directory(
            root, sentinel_bot_id, patterns, force=force,
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
            from app.services.memory_indexing import get_memory_patterns

            mem_plan = BotIndexPlan(
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
            )
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
