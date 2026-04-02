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
# Event dispatch — notify integrations (Slack, webhooks, etc.) of progress
# ---------------------------------------------------------------------------

async def _dispatch_workflow_event(
    run: WorkflowRun,
    workflow_name: str,
    event: str,
    detail: str = "",
) -> None:
    """Dispatch a workflow event to the run's integration channel.

    Events: started, step_done, step_failed, completed, failed
    Dispatch failures are swallowed — never block workflow execution.
    """
    if run.dispatch_type in ("none", None) or not run.dispatch_config:
        return
    try:
        from app.agent import dispatchers
        dispatcher = dispatchers.get(run.dispatch_type)
        run_short = str(run.id)[:8]
        text = f"[Workflow] {workflow_name} — {event}"
        if detail:
            text += f": {detail}"
        text += f" (run {run_short})"
        await dispatcher.post_message(
            run.dispatch_config, text, bot_id=run.bot_id,
        )
    except Exception:
        logger.debug("Workflow event dispatch failed (event=%s, run=%s)", event, run.id, exc_info=True)


async def _fire_after_workflow_complete(run: WorkflowRun, workflow: Workflow) -> None:
    """Fire the after_workflow_complete lifecycle hook."""
    try:
        from app.agent.hooks import HookContext, fire_hook
        ctx = HookContext(
            bot_id=run.bot_id,
            channel_id=run.channel_id,
            extra={
                "run_id": str(run.id),
                "workflow_id": run.workflow_id,
                "status": run.status,
            },
        )
        await fire_hook("after_workflow_complete", ctx, run=run, workflow=workflow)
    except Exception:
        logger.debug("after_workflow_complete hook failed for run %s", run.id, exc_info=True)


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

    logger.warning("Unrecognized condition keys: %s — evaluating as False", list(condition.keys()))
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
    session_mode: str | None = None,
) -> WorkflowRun:
    """Create and start a workflow run.

    Validates parameters and secrets, creates the WorkflowRun row,
    then kicks off advancement.
    """
    from app.services.workflows import get_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow '{workflow_id}' not found")

    # Enforce trigger restrictions
    triggers = workflow.triggers or {}
    if triggers and triggered_by in triggers:
        if not triggers[triggered_by]:
            raise ValueError(
                f"Workflow '{workflow_id}' does not allow '{triggered_by}' triggers"
            )

    # Resolve bot_id from workflow defaults if not provided
    effective_bot_id = bot_id or workflow.defaults.get("bot_id")
    if not effective_bot_id:
        raise ValueError("bot_id is required (not in params or workflow defaults)")

    # Validate params
    resolved_params = validate_params(workflow.params, params)

    # Validate secrets
    validate_secrets(workflow.secrets)

    # Resolve dispatch from channel if not provided
    # Channel model has `integration` (str|None) not `dispatch_type`
    if dispatch_type is None and channel_id:
        async with async_session() as db:
            from app.db.models import Channel
            ch = await db.get(Channel, channel_id)
            if ch:
                dispatch_type = ch.integration or "none"
                dispatch_config = dict(ch.dispatch_config or {}) if ch.dispatch_config else None

    # Initialize step states
    step_states = [
        {"status": "pending", "task_id": None, "result": None, "error": None,
         "started_at": None, "completed_at": None, "correlation_id": None}
        for _ in workflow.steps
    ]

    # Resolve effective session mode: explicit override > workflow default
    effective_mode = session_mode or getattr(workflow, "session_mode", "isolated")

    # Shared session mode: create a single session for the entire workflow run
    shared_session_id = None
    if effective_mode == "shared":
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
        session_mode=effective_mode,
        created_at=datetime.now(timezone.utc),
    )

    async with async_session() as db:
        db.add(run)
        await db.commit()
        await db.refresh(run)

    logger.info("Workflow run %s created for workflow '%s' (bot=%s)", run.id, workflow_id, effective_bot_id)

    # Dispatch "started" event to integration channel
    await _dispatch_workflow_event(
        run, workflow.name, "started",
        f"{len(workflow.steps)} steps",
    )

    # Start advancement
    await advance_workflow(run.id)
    return run


# ---------------------------------------------------------------------------
# Step advancement — the state machine (Phase 5A)
# ---------------------------------------------------------------------------

async def advance_workflow(run_id: uuid.UUID) -> None:
    """Advance a workflow run to the next actionable step.

    Uses a single session with row-level locking to prevent race conditions.
    Loops through pending steps (no recursion):
    - Evaluates conditions (skip if false)
    - Pauses at approval gates
    - Creates tasks for runnable steps
    - Marks run complete when all steps are terminal
    """
    # Deferred event dispatch — collected inside the loop, fired after session closes
    pending_events: list[tuple[WorkflowRun, str, str, str]] = []
    fire_completion = False

    while True:
        action_taken = False

        async with async_session() as db:
            run = await db.get(WorkflowRun, run_id, with_for_update=True)
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
            context = _build_condition_context(steps, step_states, run.params)

            for i, step_def in enumerate(steps):
                if i >= len(step_states):
                    break

                state = step_states[i]
                if state["status"] != "pending":
                    continue

                # Evaluate condition
                condition = step_def.get("when")
                if not evaluate_condition(condition, context):
                    state["status"] = "skipped"
                    state["completed_at"] = datetime.now(timezone.utc).isoformat()
                    context = _build_condition_context(steps, step_states, run.params)
                    action_taken = True
                    continue

                # Approval gate
                if step_def.get("requires_approval"):
                    run.status = "awaiting_approval"
                    run.current_step_index = i
                    run.step_states = step_states
                    await db.commit()
                    logger.info("Workflow run %s awaiting approval at step %d (%s)",
                                run_id, i, step_def.get("id", "?"))
                    return

                # Create task for this step
                now = datetime.now(timezone.utc)
                try:
                    task_id = await _create_step_task(run, workflow, step_def, i)
                except Exception as e:
                    logger.exception("Failed to create step task for run %s step %d", run_id, i)
                    state["status"] = "failed"
                    state["error"] = f"Task creation failed: {e}"
                    state["completed_at"] = now.isoformat()
                    run.step_states = step_states
                    run.status = "failed"
                    run.error = f"Step '{step_def.get('id', i)}' task creation failed: {e}"
                    run.completed_at = now
                    await db.commit()
                    return

                state["status"] = "running"
                state["started_at"] = now.isoformat()
                state["task_id"] = str(task_id)
                run.current_step_index = i
                run.step_states = step_states
                await db.commit()
                return  # Wait for task completion callback

            # No more pending steps — check terminal state
            all_terminal = all(
                s["status"] in ("done", "skipped", "failed") for s in step_states
            )
            run.step_states = step_states

            if all_terminal:
                has_failure = any(s["status"] == "failed" for s in step_states)
                run.status = "failed" if has_failure else "complete"
                run.completed_at = datetime.now(timezone.utc)
                logger.info("Workflow run %s completed with status '%s'", run_id, run.status)
                fire_completion = True

            await db.commit()

        # End of session — dispatch events outside the transaction
        if fire_completion:
            done_ct = sum(1 for s in step_states if s["status"] == "done")
            fail_ct = sum(1 for s in step_states if s["status"] == "failed")
            skip_ct = sum(1 for s in step_states if s["status"] == "skipped")
            event = "failed" if run.status == "failed" else "completed"
            await _dispatch_workflow_event(
                run, workflow.name, event,
                f"{done_ct} done, {fail_ct} failed, {skip_ct} skipped",
            )
            await _fire_after_workflow_complete(run, workflow)
            return

        # If we only skipped steps this iteration, loop back to re-evaluate
        if not action_taken:
            return


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
) -> uuid.UUID:
    """Create a Task for the given workflow step and enqueue it. Returns the task ID."""
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
    ]

    # Prior result injection (skip for shared sessions where full context is already available)
    inject = step_def.get("inject_prior_results", defaults.get("inject_prior_results", False))
    if inject and run.session_mode == "shared":
        inject = False
    if inject and step_index > 0:
        max_chars = step_def.get("prior_result_max_chars", defaults.get("prior_result_max_chars", 500))
        prior_lines = []
        steps = workflow.steps
        for i, st in enumerate(run.step_states):
            if i >= step_index:
                break
            if st.get("status") in ("done", "failed"):
                sid = steps[i].get("id", f"step_{i}") if i < len(steps) else f"step_{i}"
                text = (st.get("result") or st.get("error") or "")[:max_chars]
                prior_lines.append(f"- {sid} ({st['status']}): {text}")
        if prior_lines:
            preamble_lines.append("")
            preamble_lines.append("Previous step results:")
            preamble_lines.extend(prior_lines)

    preamble_lines.append("---")
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

    # For isolated mode (session_id=None), generate a per-step session so the
    # task worker doesn't resolve it to the channel's active session — that
    # would pollute the chat feed with step prompts.
    step_session_id = run.session_id or uuid.uuid4()

    task = Task(
        id=uuid.uuid4(),
        bot_id=run.bot_id,
        channel_id=run.channel_id,
        session_id=step_session_id,
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
    return task.id


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

        # Idempotency guard: if step is already terminal, skip processing
        if state["status"] in ("done", "failed", "skipped"):
            logger.debug("Step %d of run %s already terminal (%s), skipping", step_index, run_id, state["status"])
            return

        # Map task status to step status
        defaults = workflow.defaults or {}
        step_def = workflow.steps[step_index] if step_index < len(workflow.steps) else {}
        if status == "complete":
            state["status"] = "done"
            max_chars = step_def.get("result_max_chars", defaults.get("result_max_chars", 2000))
            state["result"] = (task.result or "")[:max_chars]
        else:
            state["status"] = "failed"
            state["error"] = task.error or f"Task {status}"

        state["task_id"] = str(task.id)
        state["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Store correlation_id for token usage tracking.
        # Re-fetch from DB because the task object passed to the hook is from
        # before execution — correlation_id is set during task execution.
        fresh_task = await db.get(Task, task.id)
        if fresh_task and fresh_task.correlation_id:
            state["correlation_id"] = str(fresh_task.correlation_id)

        # Dispatch step event
        step_id = step_def.get("id", f"step_{step_index}")
        done_ct = sum(1 for s in step_states if s["status"] in ("done", "failed", "skipped"))
        total_ct = len(step_states)
        step_event = "step_done" if state["status"] == "done" else "step_failed"
        preview = (state.get("result") or state.get("error") or "")[:100]
        await _dispatch_workflow_event(
            run, workflow.name, step_event,
            f"{step_id} ({done_ct}/{total_ct})" + (f" — {preview}" if preview else ""),
        )

        # Handle on_failure policy
        on_failure = step_def.get("on_failure", "abort")

        if state["status"] == "failed":
            if on_failure == "abort":
                run.status = "failed"
                run.error = f"Step '{step_def.get('id', step_index)}' failed: {state['error']}"
                run.step_states = step_states
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info("Workflow run %s aborted at step %d", run_id, step_index)
                # Dispatch abort event
                await _dispatch_workflow_event(
                    run, workflow.name, "failed",
                    f"aborted at {step_id}: {state.get('error', '')[:100]}",
                )
                await _fire_after_workflow_complete(run, workflow)
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

    task_id = await _create_step_task(run, workflow, step_def, step_index)

    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        step_states = list(run.step_states)
        step_states[step_index]["status"] = "running"
        step_states[step_index]["started_at"] = datetime.now(timezone.utc).isoformat()
        step_states[step_index]["task_id"] = str(task_id)
        run.step_states = step_states
        await db.commit()
        await db.refresh(run)

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
