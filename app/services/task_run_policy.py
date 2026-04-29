"""Task-kind runtime policy.

Centralizes the small set of task-type decisions that affect context profile,
run origin, and skill auto-injection. This keeps bot-scoped maintenance jobs
from being hardcoded across the task worker.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskRunPolicy:
    context_profile: str | None = None
    origin: str = "task"
    skip_skill_inject: bool = False


_TASK_RUN_POLICIES: dict[str, TaskRunPolicy] = {
    "heartbeat": TaskRunPolicy(context_profile="heartbeat", origin="heartbeat"),
    "memory_hygiene": TaskRunPolicy(
        context_profile="task_none",
        origin="hygiene",
        skip_skill_inject=True,
    ),
    "skill_review": TaskRunPolicy(
        context_profile="task_none",
        origin="hygiene",
        skip_skill_inject=True,
    ),
    "delegation": TaskRunPolicy(context_profile="task_none", origin="subagent"),
}


def resolve_task_run_policy(task_type: str | None) -> TaskRunPolicy:
    """Return runtime policy for a Task row type."""
    return _TASK_RUN_POLICIES.get(task_type or "", TaskRunPolicy())
