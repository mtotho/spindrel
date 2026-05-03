"""Task-kind runtime policy.

Centralizes the small set of task-type decisions that affect context profile,
run origin, and skill auto-injection. This keeps bot-scoped maintenance jobs
from being hardcoded across the task worker.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskRunPolicy:
    context_profile: str | None = None
    origin: str = "task"
    skip_skill_inject: bool = False
    run_control_policy: dict[str, Any] | None = None


_TASK_RUN_POLICIES: dict[str, TaskRunPolicy] = {
    "heartbeat": TaskRunPolicy(context_profile="heartbeat", origin="heartbeat"),
    "memory_hygiene": TaskRunPolicy(
        context_profile="memory_hygiene",
        origin="hygiene",
        skip_skill_inject=True,
        run_control_policy={
            "tool_surface": "strict",
            "soft_max_llm_calls": 8,
            "hard_max_llm_calls": 12,
            "soft_current_prompt_tokens": 24000,
        },
    ),
    "skill_review": TaskRunPolicy(
        context_profile="skill_review",
        origin="hygiene",
        skip_skill_inject=True,
        run_control_policy={
            "tool_surface": "strict",
            "soft_max_llm_calls": 5,
            "hard_max_llm_calls": 8,
            "soft_current_prompt_tokens": 24000,
        },
    ),
    "delegation": TaskRunPolicy(context_profile="task_none", origin="subagent"),
}


def resolve_task_run_policy(task_type: str | None) -> TaskRunPolicy:
    """Return runtime policy for a Task row type."""
    return _TASK_RUN_POLICIES.get(task_type or "", TaskRunPolicy())
