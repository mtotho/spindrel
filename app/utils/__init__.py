"""Shared utility helpers."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def safe_create_task(coro, *, name: str = "") -> asyncio.Task:
    """Create an asyncio task with exception logging.

    Wraps ``asyncio.create_task`` so that unhandled exceptions in
    fire-and-forget background tasks are logged instead of silently lost.
    """
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_log_task_exception)
    return task


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(
            "Background task %s failed: %s",
            task.get_name(),
            exc,
            exc_info=exc,
        )
