"""Mission Control lifecycle hooks.

Registers listeners for generic lifecycle events. Currently:
- after_task_complete: advance plan execution when a linked step task finishes.
"""
from __future__ import annotations

import logging

from app.agent.hooks import HookContext, register_hook

logger = logging.getLogger(__name__)


async def _on_task_complete(ctx: HookContext, task=None, status=None, **kwargs):
    """When a task completes, check if it's linked to a plan step and advance."""
    if not task:
        return
    callback_config = getattr(task, "callback_config", None) or {}
    step_id = callback_config.get("mc_plan_step_id")
    if not step_id:
        return

    logger.info(
        "MC hook: task %s completed (status=%s), advancing plan step %s",
        getattr(task, "id", "?"), status, step_id,
    )

    try:
        from integrations.mission_control.plan_executor import on_step_task_completed
        await on_step_task_completed(step_id, status, task)
    except Exception:
        logger.exception("MC hook: failed to advance plan after task completion")


register_hook("after_task_complete", _on_task_complete)
