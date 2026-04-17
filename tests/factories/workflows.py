"""Factories for Workflow and WorkflowRun.

``build_workflow_run`` defaults ``step_states`` to a one-step ``running`` list
so tests that exercise the workflow executor have a realistic starting state.
Remember: ANY mutation of ``step_states`` must be followed by
``flag_modified(run, "step_states")`` — see CLAUDE.md DB Gotchas.
"""
from __future__ import annotations

import uuid

from app.db.models import Workflow, WorkflowRun


def build_workflow(**overrides) -> Workflow:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=f"workflow-{suffix}",
        name=f"Test Workflow {suffix}",
        params={},
        secrets=[],
        defaults={},
        steps=[{"type": "tool", "tool": "noop"}],
        triggers={},
        tags=[],
    )
    return Workflow(**{**defaults, **overrides})


def build_workflow_run(**overrides) -> WorkflowRun:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=uuid.uuid4(),
        workflow_id=f"workflow-{suffix}",
        bot_id=f"bot-{suffix}",
        params={},
        status="running",
        current_step_index=0,
        step_states=[
            {"status": "running", "task_id": None, "result": None, "error": None}
        ],
        dispatch_type="none",
    )
    return WorkflowRun(**{**defaults, **overrides})
