"""Optional async file watcher for filesystem indexes (requires watchfiles)."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path, PurePosixPath

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


async def _debounced_watch(root: str, bot_id: str, patterns: list[str]) -> None:
    try:
        import watchfiles
    except ImportError:
        logger.warning("watchfiles not installed; skipping watcher for %s", root)
        return

    global _stop_event
    assert _stop_event is not None

    root_path = Path(root).resolve()
    logger.info("Filesystem watcher started: %s (bot=%s)", root, bot_id)
    pending: set[Path] = set()
    last_change_time = 0.0

    try:
        async for changes in watchfiles.awatch(str(root_path), stop_event=_stop_event):
            for _, path_str in changes:
                p = Path(path_str)
                try:
                    rel = p.relative_to(root_path)
                    if _matches_patterns(rel, patterns):
                        pending.add(p)
                except ValueError:
                    pass
            last_change_time = time.monotonic()

            # Debounce: wait until activity settles
            await asyncio.sleep(_DEBOUNCE_SECONDS)
            if pending and time.monotonic() - last_change_time >= _DEBOUNCE_SECONDS:
                batch = list(pending)
                pending.clear()
                logger.info("Watcher: re-indexing %d changed file(s) in %s", len(batch), root)
                from app.agent.fs_indexer import index_directory
                try:
                    await index_directory(root, bot_id, patterns, file_paths=batch, force=True)
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
        # Workspace-based watcher (new)
        ws = getattr(bot, "workspace", None)
        if ws and ws.enabled and ws.indexing.enabled and ws.indexing.watch:
            from app.services.workspace import workspace_service
            ws_root = workspace_service.get_workspace_root(bot.id, bot=bot)
            abs_root = str(Path(ws_root).resolve())
            key = (abs_root, bot.id)
            if key not in seen:
                seen.add(key)
                task = asyncio.create_task(
                    _debounced_watch(ws_root, bot.id, ws.indexing.patterns),
                    name=f"fs_watcher:{bot.id}:{abs_root}",
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


async def stop_watchers() -> None:
    global _stop_event
    if _stop_event:
        _stop_event.set()
    for t in _watcher_tasks:
        t.cancel()
    _watcher_tasks.clear()
