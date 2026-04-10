"""Optional async file watcher for filesystem indexes (requires watchfiles)."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path, PurePosixPath

from sqlalchemy import delete

logger = logging.getLogger(__name__)

_stop_event: asyncio.Event | None = None
_watcher_tasks: list[asyncio.Task] = []

_DEBOUNCE_SECONDS = 2.0


def _matches_patterns(rel: Path, patterns: list[str]) -> bool:
    s = str(PurePosixPath(rel))
    for pat in patterns:
        if PurePosixPath(s).match(pat):
            return True
    return False


async def _remove_deleted_chunks(
    root_path: Path, bot_id: str, removed: set[Path],
) -> int:
    """Delete DB chunks for files that were removed from disk."""
    if not removed:
        return 0
    rel_paths = []
    for p in removed:
        try:
            rel_paths.append(str(PurePosixPath(p.relative_to(root_path))))
        except ValueError:
            continue
    if not rel_paths:
        return 0
    from app.db.engine import async_session
    from app.db.models import FilesystemChunk
    async with async_session() as db:
        result = await db.execute(
            delete(FilesystemChunk).where(
                FilesystemChunk.bot_id == bot_id,
                FilesystemChunk.root == str(root_path),
                FilesystemChunk.file_path.in_(rel_paths),
            )
        )
        await db.commit()
        count = result.rowcount
    if count:
        logger.info("Watcher: removed %d chunk(s) for %d deleted file(s) in %s", count, len(rel_paths), root_path)
    return count


async def _debounced_watch(
    root: str, bot_id: str, patterns: list[str],
    embedding_model: str | None = None, segments: list[dict] | None = None,
) -> None:
    try:
        import watchfiles
        from watchfiles import Change
    except ImportError:
        logger.warning("watchfiles not installed; skipping watcher for %s", root)
        return

    global _stop_event
    assert _stop_event is not None

    root_path = Path(root).resolve()
    logger.info("Filesystem watcher started: %s (bot=%s)", root, bot_id)
    pending: set[Path] = set()
    removed: set[Path] = set()
    last_change_time = 0.0

    try:
        async for changes in watchfiles.awatch(str(root_path), stop_event=_stop_event):
            for change_type, path_str in changes:
                p = Path(path_str)
                try:
                    rel = p.relative_to(root_path)
                    if _matches_patterns(rel, patterns):
                        if change_type == Change.deleted:
                            removed.add(p)
                            pending.discard(p)
                        else:
                            pending.add(p)
                            removed.discard(p)
                except ValueError:
                    pass
            last_change_time = time.monotonic()

            # Debounce: wait until activity settles
            await asyncio.sleep(_DEBOUNCE_SECONDS)
            if (pending or removed) and time.monotonic() - last_change_time >= _DEBOUNCE_SECONDS:
                # Handle deletions
                if removed:
                    del_batch = set(removed)
                    removed.clear()
                    try:
                        await _remove_deleted_chunks(root_path, bot_id, del_batch)
                    except Exception:
                        logger.exception("Watcher: failed to remove chunks for deleted files in %s", root)

                # Handle added/modified files
                if pending:
                    batch = list(pending)
                    pending.clear()
                    logger.info("Watcher: re-indexing %d changed file(s) in %s", len(batch), root)
                    from app.agent.fs_indexer import index_directory
                    try:
                        await index_directory(
                            root, bot_id, patterns, file_paths=batch, force=True,
                            embedding_model=embedding_model, segments=segments,
                        )
                    except Exception:
                        logger.exception("Watcher: index_directory failed for %s", root)
    except asyncio.CancelledError:
        pass
    logger.info("Filesystem watcher stopped: %s", root)


async def start_watchers(bots: list) -> None:
    """Launch watcher tasks for workspace and legacy filesystem_indexes configs."""
    global _stop_event, _watcher_tasks
    _stop_event = asyncio.Event()
    seen: set[tuple[str, str]] = set()
    for bot in bots:
        # Workspace-based watcher — skip shared workspace bots (covered by shared ws watcher)
        ws = getattr(bot, "workspace", None)
        if ws and ws.enabled and ws.indexing.enabled and not getattr(bot, "shared_workspace_id", None):
            from app.services.workspace_indexing import resolve_indexing, get_all_roots
            _resolved = resolve_indexing(ws.indexing, getattr(bot, "_workspace_raw", {}), getattr(bot, "_ws_indexing_config", None))
            if not _resolved["watch"]:
                continue
            for ws_root in get_all_roots(bot):
                abs_root = str(Path(ws_root).resolve())
                key = (abs_root, bot.id)
                if key not in seen:
                    seen.add(key)
                    task = asyncio.create_task(
                        _debounced_watch(
                            ws_root, bot.id, _resolved["patterns"],
                            embedding_model=_resolved.get("embedding_model"),
                            segments=_resolved.get("segments"),
                        ),
                        name=f"fs_watcher:{bot.id}:{abs_root}",
                    )
                    _watcher_tasks.append(task)
        # Memory-only watcher for bots with workspace-files memory but no general indexing
        elif (
            ws and ws.enabled
            and not ws.indexing.enabled
            and getattr(bot, "memory_scheme", None) == "workspace-files"
            and not getattr(bot, "shared_workspace_id", None)
        ):
            from app.services.memory_indexing import get_memory_patterns
            from app.services.workspace_indexing import get_all_roots
            for ws_root in get_all_roots(bot):
                abs_root = str(Path(ws_root).resolve())
                key = (abs_root, bot.id)
                if key not in seen:
                    seen.add(key)
                    task = asyncio.create_task(
                        _debounced_watch(ws_root, bot.id, get_memory_patterns()),
                        name=f"fs_watcher:memory:{bot.id}:{abs_root}",
                    )
                    _watcher_tasks.append(task)
        # Legacy filesystem_indexes
        for cfg in getattr(bot, "filesystem_indexes", []):
            if not cfg.watch:
                continue
            abs_root = str(Path(cfg.root).resolve())
            key = (abs_root, bot.id)
            if key in seen:
                continue
            seen.add(key)
            task = asyncio.create_task(
                _debounced_watch(cfg.root, bot.id, cfg.patterns),
                name=f"fs_watcher:{bot.id}:{abs_root}",
            )
            _watcher_tasks.append(task)
    if _watcher_tasks:
        logger.info("Started %d filesystem watcher task(s)", len(_watcher_tasks))


async def _watch_shared_workspace(
    workspace_id: str, host_root: str,
) -> None:
    """Watch an entire shared workspace directory for file changes.

    On changes, re-indexes filesystem chunks for each bot in the workspace.
    """
    try:
        import watchfiles
    except ImportError:
        logger.warning("watchfiles not installed; skipping shared workspace watcher for %s", workspace_id)
        return

    global _stop_event
    assert _stop_event is not None

    root_path = Path(host_root).resolve()
    if not root_path.exists():
        return
    logger.info("Shared workspace watcher started: %s (workspace=%s)", host_root, workspace_id)
    last_change_time = 0.0
    has_pending = False

    try:
        async for changes in watchfiles.awatch(str(root_path), stop_event=_stop_event):
            for _, path_str in changes:
                if Path(path_str).is_file() or not Path(path_str).exists():
                    has_pending = True
            if not has_pending:
                continue
            last_change_time = time.monotonic()

            await asyncio.sleep(_DEBOUNCE_SECONDS)
            if has_pending and time.monotonic() - last_change_time >= _DEBOUNCE_SECONDS:
                has_pending = False
                logger.info("Shared workspace watcher: changes detected in %s, re-indexing", workspace_id)

                # Re-index filesystem for each bot in the workspace
                from app.agent.bots import list_bots
                from app.agent.fs_indexer import index_directory
                from app.services.workspace_indexing import resolve_indexing, get_all_roots

                for bot in list_bots():
                    if bot.shared_workspace_id != workspace_id:
                        continue
                    if bot.workspace.indexing.enabled:
                        try:
                            _resolved = resolve_indexing(
                                bot.workspace.indexing,
                                getattr(bot, "_workspace_raw", {}),
                                getattr(bot, "_ws_indexing_config", None),
                            )
                            _segments = _resolved.get("segments")
                            # Shared workspace bots without segments: skip file
                            # indexing — only memory gets indexed.  Without this
                            # guard, segments=[] is falsy and index_directory()
                            # falls through to blanket-glob the entire workspace.
                            if not _segments:
                                if getattr(bot, "memory_scheme", None) == "workspace-files":
                                    from app.services.memory_indexing import index_memory_for_bot
                                    await index_memory_for_bot(bot, force=True)
                                continue
                            for root in get_all_roots(bot):
                                await index_directory(
                                    root, bot.id, _resolved["patterns"], force=True,
                                    embedding_model=_resolved["embedding_model"],
                                    segments=_segments,
                                )
                        except Exception:
                            logger.exception("Shared workspace watcher: index failed for bot %s", bot.id)
                    elif getattr(bot, "memory_scheme", None) == "workspace-files":
                        # Memory-only re-index for bots without general indexing
                        try:
                            from app.services.memory_indexing import index_memory_for_bot
                            await index_memory_for_bot(bot, force=True)
                        except Exception:
                            logger.exception("Shared workspace watcher: memory index failed for bot %s", bot.id)
    except asyncio.CancelledError:
        pass
    logger.info("Shared workspace watcher stopped: %s", host_root)


async def start_shared_workspace_watchers(
    workspaces: list[tuple[str, str]],
) -> None:
    """Start watchers for shared workspace directories.

    Args:
        workspaces: list of (workspace_id, host_root) tuples
    """
    global _stop_event, _watcher_tasks
    if _stop_event is None:
        _stop_event = asyncio.Event()
    for workspace_id, host_root in workspaces:
        task = asyncio.create_task(
            _watch_shared_workspace(workspace_id, host_root),
            name=f"shared_ws_watcher:{workspace_id}",
        )
        _watcher_tasks.append(task)
    if workspaces:
        logger.info("Started %d shared workspace watcher(s)", len(workspaces))


async def periodic_reindex_worker() -> None:
    """Safety-net worker: periodically re-verifies all filesystem indexes.

    Runs a non-forced index pass that checks content hashes and touches
    indexed_at timestamps.  Catches cases where the file watcher crashed
    silently or files changed outside watched directories.
    """
    from app.config import settings
    interval = settings.FS_INDEX_PERIODIC_MINUTES
    if interval <= 0:
        logger.info("Periodic reindex disabled (FS_INDEX_PERIODIC_MINUTES=0)")
        return

    # Wait one full interval before the first run (startup already indexed everything)
    await asyncio.sleep(interval * 60)
    logger.info("Periodic reindex worker started (every %dm)", interval)

    while True:
        try:
            if settings.SYSTEM_PAUSED:
                await asyncio.sleep(60)
                continue

            from app.agent.bots import list_bots
            from app.agent.fs_indexer import index_directory
            from app.services.workspace_indexing import resolve_indexing, get_all_roots
            from app.services.workspace import workspace_service
            from app.services.memory_indexing import index_memory_for_bot

            for bot in list_bots():
                # Memory files
                if bot.memory_scheme == "workspace-files" and bot.workspace.enabled:
                    try:
                        await index_memory_for_bot(bot)
                    except Exception:
                        logger.exception("Periodic reindex: memory failed for bot %s", bot.id)

                # Workspace indexing
                if bot.workspace.enabled and bot.workspace.indexing.enabled:
                    _resolved = resolve_indexing(
                        bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config
                    )
                    _segments = _resolved.get("segments")
                    if bot.shared_workspace_id and not _segments:
                        continue
                    for root in get_all_roots(bot, workspace_service):
                        try:
                            await index_directory(
                                root, bot.id, _resolved["patterns"],
                                embedding_model=_resolved["embedding_model"],
                                segments=_segments,
                            )
                        except Exception:
                            logger.exception("Periodic reindex: failed for bot %s root %s", bot.id, root)

            logger.info("Periodic reindex pass complete")
        except Exception:
            logger.exception("Periodic reindex worker error")
        await asyncio.sleep(interval * 60)


async def stop_watchers() -> None:
    global _stop_event
    if _stop_event:
        _stop_event.set()
    for t in _watcher_tasks:
        t.cancel()
    _watcher_tasks.clear()
