"""Workflow executor — state machine for advancing workflow runs.

Handles:
- Condition evaluation (pure dict-based, no eval())
- Prompt rendering ({{param}} and {{steps.id.result}} substitution)
- Workflow triggering (param/secret validation, run creation)
- Step advancement (condition check, approval gates, task creation)
- Task completion callbacks (result capture, failure handling, re-advance)
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Task, Workflow, WorkflowRun

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Condition evaluator (Phase 4) — pure function, no side effects
# ---------------------------------------------------------------------------

def evaluate_condition(condition: dict | None, context: dict) -> bool:
    """Evaluate a step condition against the current run context.

    Context shape:
        {
            "steps": {"step_id": {"status": "done", "result": "..."}},
            "params": {"name": "value"},
        }

    Condition shapes:
        None / empty → always True
        {"step": "id", "status": "done"}
        {"step": "id", "status": "done", "output_contains": "text"}
        {"step": "id", "output_not_contains": "text"}
        {"param": "name", "equals": value}
        {"all": [cond, ...]}  — AND
        {"any": [cond, ...]}  — OR
        {"not": cond}         — negation
    """
    if condition is None:
        return True
    if not condition:
        return True

    # Compound conditions
    if "all" in condition:
        return all(evaluate_condition(c, context) for c in condition["all"])
    if "any" in condition:
        return any(evaluate_condition(c, context) for c in condition["any"])
    if "not" in condition:
        return not evaluate_condition(condition["not"], context)

    # Param check
    if "param" in condition:
        val = context.get("params", {}).get(condition["param"])
        if "equals" in condition:
            return val == condition["equals"]
        return val is not None

    # Step check
    if "step" in condition:
        state = context.get("steps", {}).get(condition["step"])
        if not state:
            return False
        if "status" in condition and state.get("status") != condition["status"]:
            return False
        if "output_contains" in condition:
            result_text = (state.get("result") or "").lower()
            if condition["output_contains"].lower() not in result_text:
                return False
        if "output_not_contains" in condition:
            result_text = (state.get("result") or "").lower()
            if condition["output_not_contains"].lower() in result_text:
                return False
        return True

    return False


# ---------------------------------------------------------------------------
# Prompt rendering (Phase 5B)
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}")


def render_prompt(template: str, params: dict, step_states: list[dict], steps: list[dict]) -> str:
    """Render a step prompt template with parameter and step result substitution.

    Supports:
        {{param_name}}          → param value
        {{steps.step_id.result}} → prior step's result text
        {{steps.step_id.status}} → prior step's status
    """
    # Build step lookup by id
    step_lookup: dict[str, dict] = {}
    for i, step_def in enumerate(steps):
        sid = step_def.get("id", f"step_{i}")
        if i < len(step_states):
            step_lookup[sid] = step_states[i]

    def _replace(match: re.Match) -> str:
        key = match.group(1).strip()

        # Steps reference: steps.step_id.field
        if key.startswith("steps."):
            parts = key.split(".", 2)
            if len(parts) == 3:
                _, step_id, field = parts
                state = step_lookup.get(step_id, {})
                val = state.get(field)
                return str(val) if val is not None else match.group(0)
            return match.group(0)

        # Param reference
        if key in params:
            return str(params[key])

        # Leave unresolved templates as-is
        return match.group(0)

    return _TEMPLATE_RE.sub(_replace, template)


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------

def validate_params(param_defs: dict, provided: dict) -> dict:
    """Validate and resolve parameters against workflow param definitions.

    Returns resolved params dict with defaults applied.
    Raises ValueError on validation failure.
    """
    resolved = {}
    for name, defn in param_defs.items():
        if name in provided:
            val = provided[name]
            # Type coercion/check
            expected_type = defn.get("type", "string")
            if expected_type == "string" and not isinstance(val, str):
                val = str(val)
            elif expected_type == "number" and not isinstance(val, (int, float)):
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    raise ValueError(f"Parameter '{name}' must be a number")
            elif expected_type == "boolean" and not isinstance(val, bool):
                if isinstance(val, str):
                    val = val.lower() in ("true", "1", "yes")
                else:
                    val = bool(val)
            resolved[name] = val
        elif defn.get("default") is not None:
            resolved[name] = defn["default"]
        elif defn.get("required", False):
            raise ValueError(f"Required parameter '{name}' is missing")
    return resolved


# ---------------------------------------------------------------------------
# Secret validation
# ---------------------------------------------------------------------------

def validate_secrets(declared_secrets: list[str]) -> None:
    """Validate that all declared secrets exist in the SecretValue store.

    Raises ValueError listing missing secrets.
    """
    if not declared_secrets:
        return
    from app.services.secret_values import get_env_dict
    available = set(get_env_dict().keys())
    missing = [s for s in declared_secrets if s not in available]
    if missing:
        raise ValueError(f"Missing secrets: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# Workflow triggering (Phase 5A)
# ---------------------------------------------------------------------------

async def trigger_workflow(
    workflow_id: str,
    params: dict,
    *,
    bot_id: str | None = None,
    channel_id: uuid.UUID | None = None,
    triggered_by: str = "api",
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
) -> WorkflowRun:
    """Create and start a workflow run.

    Validates parameters and secrets, creates the WorkflowRun row,
    then kicks off advancement.
    """
    from app.services.workflows import get_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow '{workflow_id}' not found")

    # Resolve bot_id from workflow defaults if not provided
    effective_bot_id = bot_id or workflow.defaults.get("bot_id")
    if not effective_bot_id:
        raise ValueError("bot_id is required (not in params or workflow defaults)")

    # Validate params
    resolved_params = validate_params(workflow.params, params)

    # Validate secrets
    validate_secrets(workflow.secrets)

    # Resolve dispatch from channel if not provided
    if dispatch_type is None and channel_id:
        async with async_session() as db:
            from app.db.models import Channel
            ch = await db.get(Channel, channel_id)
            if ch:
                dispatch_type = ch.dispatch_type or "none"
                dispatch_config = dict(ch.dispatch_config or {}) if ch.dispatch_config else None

    # Initialize step states
    step_states = [
        {"status": "pending", "task_id": None, "result": None, "error": None,
         "started_at": None, "completed_at": None, "correlation_id": None}
        for _ in workflow.steps
    ]

    # Shared session mode: create a single session for the entire workflow run
    shared_session_id = None
    if getattr(workflow, "session_mode", "isolated") == "shared":
        shared_session_id = uuid.uuid4()

    run = WorkflowRun(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
        bot_id=effective_bot_id,
        channel_id=channel_id,
        session_id=shared_session_id,
        params=resolved_params,
        status="running",
        current_step_index=0,
        step_states=step_states,
        dispatch_type=dispatch_type or "none",
        dispatch_config=dispatch_config,
        triggered_by=triggered_by,
        created_at=datetime.now(timezone.utc),
    )

    async with async_session() as db:
        db.add(run)
        await db.commit()
        await db.refresh(run)

    logger.info("Workflow run %s created for workflow '%s' (bot=%s)", run.id, workflow_id, effective_bot_id)

    # Start advancement
    await advance_workflow(run.id)
    return run


# ---------------------------------------------------------------------------
# Step advancement — the state machine (Phase 5A)
# ---------------------------------------------------------------------------

async def advance_workflow(run_id: uuid.UUID) -> None:
    """Advance a workflow run to the next actionable step.

    Loops through pending steps:
    - Evaluates conditions (skip if false)
    - Pauses at approval gates
    - Creates tasks for runnable steps
    - Marks run complete when all steps are terminal
    """
    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run or run.status not in ("running", "awaiting_approval"):
            return

        workflow = await db.get(Workflow, run.workflow_id)
        if not workflow:
            run.status = "failed"
            run.error = f"Workflow '{run.workflow_id}' not found"
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return

    steps = workflow.steps
    step_states = list(run.step_states)  # mutable copy

    # Build condition context
    context = _build_condition_context(steps, step_states, run.params)

    advanced = False
    for i, step_def in enumerate(steps):
        if i >= len(step_states):
            break

        state = step_states[i]
        if state["status"] != "pending":
            continue

        # Evaluate condition
        condition = step_def.get("when")
        if not evaluate_condition(condition, context):
            # Mark skipped
            state["status"] = "skipped"
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            # Update context for subsequent conditions
            context = _build_condition_context(steps, step_states, run.params)
            advanced = True
            continue

        # Approval gate
        if step_def.get("requires_approval"):
            async with async_session() as db:
                run = await db.get(WorkflowRun, run_id)
                if run:
                    run.status = "awaiting_approval"
                    run.current_step_index = i
                    run.step_states = step_states
                    await db.commit()
            logger.info("Workflow run %s awaiting approval at step %d (%s)", run_id, i, step_def.get("id", "?"))
            return

        # Create task for this step
        state["status"] = "running"
        state["started_at"] = datetime.now(timezone.utc).isoformat()
        advanced = True

        async with async_session() as db:
            run = await db.get(WorkflowRun, run_id)
            if run:
                run.current_step_index = i
                run.step_states = step_states
                await db.commit()

        await _create_step_task(run, workflow, step_def, i)
        return  # Wait for task completion callback

    # If we got here, no more steps to process — check if all are terminal
    all_terminal = all(s["status"] in ("done", "skipped", "failed") for s in step_states)
    if all_terminal or advanced:
        async with async_session() as db:
            run = await db.get(WorkflowRun, run_id)
            if run:
                run.step_states = step_states
                if all_terminal:
                    has_failure = any(s["status"] == "failed" for s in step_states)
                    run.status = "failed" if has_failure else "complete"
                    run.completed_at = datetime.now(timezone.utc)
                    logger.info("Workflow run %s completed with status '%s'", run_id, run.status)
                await db.commit()

        # Re-check if there are more steps after skips
        if not all_terminal:
            await advance_workflow(run_id)


def _build_condition_context(steps: list[dict], step_states: list[dict], params: dict) -> dict:
    """Build the context dict for condition evaluation from current step states."""
    steps_ctx = {}
    for i, step_def in enumerate(steps):
        sid = step_def.get("id", f"step_{i}")
        if i < len(step_states):
            steps_ctx[sid] = step_states[i]
    return {"steps": steps_ctx, "params": params}


# ---------------------------------------------------------------------------
# Step task creation
# ---------------------------------------------------------------------------

async def _create_step_task(
    run: WorkflowRun, workflow: Workflow, step_def: dict, step_index: int
) -> None:
    """Create a Task for the given workflow step and enqueue it."""
    # Render prompt
    prompt = render_prompt(
        step_def["prompt"],
        run.params,
        run.step_states,
        workflow.steps,
    )

    # Build execution_config from workflow defaults + step overrides
    defaults = workflow.defaults or {}
    ecfg: dict = {}

    # Model
    model = step_def.get("model") or defaults.get("model")
    if model:
        ecfg["model_override"] = model

    # System preamble
    preamble_lines = [
        f"[WORKFLOW STEP — {workflow.name}]",
        f"Workflow: {workflow.id} | Run: {run.id} | Step: {step_def.get('id', step_index)}",
        "Execute the instructions below. Return your result as a clear summary.",
        "---",
    ]
    ecfg["system_preamble"] = "\n".join(preamble_lines)

    # Tools
    tools = step_def.get("tools") or defaults.get("tools")
    if tools:
        ecfg["tools"] = tools

    # Carapaces
    carapaces = step_def.get("carapaces") or defaults.get("carapaces")
    if carapaces:
        ecfg["carapaces"] = carapaces

    # Scoped secrets — intersection of workflow.secrets and step.secrets
    workflow_secrets = workflow.secrets or []
    step_secrets = step_def.get("secrets")
    if step_secrets:
        allowed = [s for s in step_secrets if s in workflow_secrets]
    else:
        allowed = list(workflow_secrets)
    if allowed:
        ecfg["allowed_secrets"] = allowed

    # Timeout
    timeout = step_def.get("timeout") or defaults.get("timeout")

    # Callback config for workflow advancement
    callback_config = {
        "workflow_run_id": str(run.id),
        "workflow_step_index": step_index,
    }

    task = Task(
        id=uuid.uuid4(),
        bot_id=run.bot_id,
        channel_id=run.channel_id,
        session_id=run.session_id,
        prompt=prompt,
        title=f"Workflow: {workflow.name} — {step_def.get('id', f'step_{step_index}')}",
        status="pending",
        task_type="workflow",
        dispatch_type="none",  # Workflow manages its own dispatch
        execution_config=ecfg,
        callback_config=callback_config,
        max_run_seconds=timeout,
        created_at=datetime.now(timezone.utc),
    )

    async with async_session() as db:
        db.add(task)
        await db.commit()

    logger.info(
        "Created task %s for workflow run %s step %d (%s)",
        task.id, run.id, step_index, step_def.get("id", "?"),
    )


# ---------------------------------------------------------------------------
# Task completion callback (Phase 5C)
# ---------------------------------------------------------------------------

async def on_step_task_completed(
    run_id: str, step_index: int, status: str, task: Task
) -> None:
    """Called when a workflow step's task completes. Updates step state and advances."""
    try:
        _run_id = uuid.UUID(run_id)
    except (ValueError, TypeError):
        logger.error("Invalid workflow_run_id: %s", run_id)
        return

    async with async_session() as db:
        run = await db.get(WorkflowRun, _run_id)
        if not run:
            logger.warning("WorkflowRun %s not found for task completion", run_id)
            return

        workflow = await db.get(Workflow, run.workflow_id)
        if not workflow:
            logger.warning("Workflow %s not found for run %s", run.workflow_id, run_id)
            return

        step_states = list(run.step_states)
        if step_index >= len(step_states):
            logger.error("Step index %d out of bounds for run %s", step_index, run_id)
            return

        state = step_states[step_index]

        # Map task status to step status
        if status == "complete":
            state["status"] = "done"
            state["result"] = (task.result or "")[:2000]
        else:
            state["status"] = "failed"
            state["error"] = task.error or f"Task {status}"

        state["task_id"] = str(task.id)
        state["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Store correlation_id from the task for token usage tracking
        if task.execution_config and task.execution_config.get("_correlation_id"):
            state["correlation_id"] = task.execution_config["_correlation_id"]

        # Handle on_failure policy
        step_def = workflow.steps[step_index] if step_index < len(workflow.steps) else {}
        on_failure = step_def.get("on_failure", "abort")

        if state["status"] == "failed":
            if on_failure == "abort":
                run.status = "failed"
                run.error = f"Step '{step_def.get('id', step_index)}' failed: {state['error']}"
                run.step_states = step_states
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info("Workflow run %s aborted at step %d", run_id, step_index)
                return
            elif on_failure.startswith("retry:"):
                try:
                    max_retries = int(on_failure.split(":")[1])
                except (ValueError, IndexError):
                    max_retries = 1
                retry_count = state.get("retry_count", 0)
                if retry_count < max_retries:
                    state["status"] = "pending"
                    state["error"] = None
                    state["retry_count"] = retry_count + 1
                    run.step_states = step_states
                    await db.commit()
                    logger.info("Retrying step %d (attempt %d/%d) for run %s",
                                step_index, retry_count + 1, max_retries, run_id)
                    await advance_workflow(_run_id)
                    return
            # on_failure == "continue" falls through to advance

        run.step_states = step_states
        await db.commit()

    # Advance to next step
    await advance_workflow(_run_id)


# ---------------------------------------------------------------------------
# Approval / skip / retry helpers (for API endpoints)
# ---------------------------------------------------------------------------

async def approve_step(run_id: uuid.UUID, step_index: int) -> WorkflowRun:
    """Approve a gated step and resume workflow advancement."""
    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run:
            raise ValueError("WorkflowRun not found")
        if run.status != "awaiting_approval":
            raise ValueError(f"Run is not awaiting approval (status: {run.status})")

        step_states = list(run.step_states)
        if step_index >= len(step_states):
            raise ValueError(f"Step index {step_index} out of bounds")
        if step_states[step_index]["status"] != "pending":
            raise ValueError(f"Step {step_index} is not pending")

        # Clear the approval gate — mark as running and create task
        run.status = "running"
        await db.commit()

    from app.services.workflows import get_workflow
    workflow = get_workflow(run.workflow_id)
    if not workflow:
        raise ValueError(f"Workflow '{run.workflow_id}' not found")

    step_def = workflow.steps[step_index]

    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        step_states = list(run.step_states)
        step_states[step_index]["status"] = "running"
        step_states[step_index]["started_at"] = datetime.now(timezone.utc).isoformat()
        run.step_states = step_states
        await db.commit()

    await _create_step_task(run, workflow, step_def, step_index)
    return run


async def skip_step(run_id: uuid.UUID, step_index: int) -> WorkflowRun:
    """Skip a gated step and advance the workflow."""
    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run:
            raise ValueError("WorkflowRun not found")
        if run.status != "awaiting_approval":
            raise ValueError(f"Run is not awaiting approval (status: {run.status})")

        step_states = list(run.step_states)
        if step_index >= len(step_states):
            raise ValueError(f"Step index {step_index} out of bounds")

        step_states[step_index]["status"] = "skipped"
        step_states[step_index]["completed_at"] = datetime.now(timezone.utc).isoformat()
        run.step_states = step_states
        run.status = "running"
        await db.commit()

    await advance_workflow(run_id)

    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
    return run


async def retry_step(run_id: uuid.UUID, step_index: int) -> WorkflowRun:
    """Retry a failed step."""
    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run:
            raise ValueError("WorkflowRun not found")

        step_states = list(run.step_states)
        if step_index >= len(step_states):
            raise ValueError(f"Step index {step_index} out of bounds")
        if step_states[step_index]["status"] != "failed":
            raise ValueError(f"Step {step_index} is not failed")

        step_states[step_index]["status"] = "pending"
        step_states[step_index]["error"] = None
        run.step_states = step_states
        if run.status in ("failed",):
            run.status = "running"
            run.error = None
            run.completed_at = None
        await db.commit()

    await advance_workflow(run_id)

    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
    return run


async def cancel_workflow(run_id: uuid.UUID) -> WorkflowRun:
    """Cancel a running workflow."""
    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run:
            raise ValueError("WorkflowRun not found")
        if run.status in ("complete", "cancelled"):
            raise ValueError(f"Run is already {run.status}")

        run.status = "cancelled"
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(run)
    return run
