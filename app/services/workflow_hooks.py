"""Workflow lifecycle hooks — listens for task completions to advance workflow runs."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def _on_task_complete(ctx, task=None, status=None, **kw):
    """Fire when any task completes — check if it belongs to a workflow run."""
    if task is None:
        return

    cb = task.callback_config or {}
    run_id = cb.get("workflow_run_id")
    if not run_id:
        return

    step_idx = cb.get("workflow_step_index")
    if step_idx is None:
        return

    logger.info("Workflow hook: task %s completed (status=%s) for run %s step %d",
                task.id, status, run_id, step_idx)

    from app.services.workflow_executor import on_step_task_completed
    await on_step_task_completed(run_id, step_idx, status, task)


def register_workflow_hooks():
    """Register workflow hooks into the lifecycle hook system."""
    from app.agent.hooks import register_hook
    register_hook("after_task_complete", _on_task_complete)
    logger.info("Registered workflow task completion hook")
