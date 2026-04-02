"""Workflow lifecycle hooks — listens for task completions to advance workflow runs."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def _on_task_complete(ctx, task=None, status=None, **kw):
    """Fire when any task completes — check if it belongs to a workflow run.

    NOTE: Workflow step advancement is now called DIRECTLY from
    _fire_task_complete() to bypass fire_hook's error swallowing.
    This hook callback is kept as a no-op guard to prevent double-firing
    if both paths somehow trigger.
    """
    # Workflow tasks are handled directly in _fire_task_complete (tasks.py)
    # to avoid the fire_hook error-swallowing problem.  Skip here.
    return


def register_workflow_hooks():
    """Register workflow hooks into the lifecycle hook system."""
    from app.agent.hooks import register_hook
    register_hook("after_task_complete", _on_task_complete)
    logger.info("Registered workflow task completion hook")
