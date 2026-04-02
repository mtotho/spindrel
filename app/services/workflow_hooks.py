"""Workflow lifecycle hooks — listens for task completions to advance workflow runs.

NOTE: Workflow step advancement is now called DIRECTLY from _fire_task_complete()
in app/agent/tasks.py, bypassing fire_hook's error-swallowing behavior.
This module only registers hook infrastructure — the actual callback is a no-op
to prevent double-firing.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def _on_task_complete(ctx, task=None, status=None, **kw):
    """No-op — workflow advancement is handled directly in _fire_task_complete."""
    return


def register_workflow_hooks():
    """Register workflow hooks into the lifecycle hook system."""
    from app.agent.hooks import register_hook
    register_hook("after_task_complete", _on_task_complete)
    logger.info("Registered workflow task completion hook")
