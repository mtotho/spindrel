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
    from app.services.bot_indexing import iter_watch_targets

    global _stop_event, _watcher_tasks
    _stop_event = asyncio.Event()
    seen: set[tuple[str, str]] = set()
    for plan, ws_root in iter_watch_targets(list(bots)):
        abs_root = str(Path(ws_root).resolve())
        key = (abs_root, plan.bot_id)
        if key in seen:
            continue
        seen.add(key)
        name_prefix = "fs_watcher:memory" if plan.scope == "memory" else "fs_watcher"
        task = asyncio.create_task(
            _debounced_watch(
                ws_root, plan.bot_id, plan.patterns,
                embedding_model=plan.embedding_model if plan.scope != "memory" else None,
                segments=plan.segments,
            ),
            name=f"{name_prefix}:{plan.bot_id}:{abs_root}",
        )
        _watcher_tasks.append(task)
    for bot in bots:
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
                from app.services.bot_indexing import reindex_bot

                for bot in list_bots():
                    if bot.shared_workspace_id != workspace_id:
                        continue
                    try:
                        await reindex_bot(bot, force=True)
                    except Exception:
                        logger.exception("Shared workspace watcher: reindex failed for bot %s", bot.id)
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
            from app.services.bot_indexing import reindex_bot

            for bot in list_bots():
                try:
                    await reindex_bot(bot, force=False)
                except Exception:
                    logger.exception("Periodic reindex: failed for bot %s", bot.id)

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
