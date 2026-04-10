"""Workflow executor — state machine for advancing workflow runs.

Handles:
- Condition evaluation (pure dict-based, no eval())
- Prompt rendering ({{param}} and {{steps.id.result}} substitution)
- Workflow triggering (param/secret validation, run creation)
- Step advancement (condition check, approval gates, task creation)
- Task completion callbacks (result capture, failure handling, re-advance)
- Step-level dispatch types: agent (default), exec (shell command), tool (inline local tool call)
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update as sa_update
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.db.engine import async_session
from app.db.models import Task, Workflow, WorkflowRun

logger = logging.getLogger(__name__)


def _set_step_states(run: WorkflowRun, step_states: list[dict]) -> None:
    """Assign step_states and force SQLAlchemy to include it in the UPDATE.

    Plain JSONB columns without MutableList don't track in-place mutations.
    flag_modified ensures the column is always written.
    """
    run.step_states = step_states
    flag_modified(run, "step_states")


# ---------------------------------------------------------------------------
# In-process advancement lock — prevents concurrent advance_workflow() calls
# for the same run_id within a single process.
# ---------------------------------------------------------------------------
_advance_locks: dict[uuid.UUID, asyncio.Lock] = {}


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


async def _post_workflow_chat_message(
    run: WorkflowRun,
    workflow_name: str,
    event_type: str,
    content: str,
    *,
    step_id: str | None = None,
    step_index: int | None = None,
    total_steps: int | None = None,
    completed_steps: int | None = None,
) -> None:
    """Post a workflow lifecycle message to the channel's active session.

    Messages appear in the channel chat with ``trigger: "workflow"`` metadata,
    rendered as collapsed cards by the UI (similar to heartbeat messages).
    No-op when the run has no ``channel_id``.

    For ``step_done`` and ``step_failed`` events, updates the most recent
    progress message in-place instead of creating a new one.  This prevents
    the chat from accumulating N frozen-snapshot messages and keeps the
    progress counter current.
    """
    if not run.channel_id:
        return
    try:
        from app.agent.bots import get_bot
        from app.db.models import Channel, Message, Session
        from sqlalchemy import update as sa_upd

        bot_name = run.bot_id
        try:
            bot = get_bot(run.bot_id)
            bot_name = bot.display_name or bot.name or run.bot_id
        except Exception:
            pass

        async with async_session() as db:
            channel = await db.get(Channel, run.channel_id)
            if not channel or not channel.active_session_id:
                return

            metadata = {
                "trigger": "workflow",
                "workflow_event": event_type,
                "workflow_id": run.workflow_id,
                "workflow_name": workflow_name,
                "workflow_run_id": str(run.id),
                "sender_type": "bot",
                "sender_display_name": bot_name,
                "dispatched": False,
            }
            if step_id is not None:
                metadata["step_id"] = step_id
            if step_index is not None:
                metadata["step_index"] = step_index
            if total_steps is not None:
                metadata["total_steps"] = total_steps
            if completed_steps is not None:
                metadata["completed_steps"] = completed_steps

            now = datetime.now(timezone.utc)

            # For step progress events, update the existing progress message
            # in-place rather than creating a new one per step.
            if event_type in ("step_done", "step_failed"):
                existing = (
                    await db.execute(
                        select(Message)
                        .where(
                            Message.session_id == channel.active_session_id,
                            Message.metadata_["workflow_run_id"].astext == str(run.id),
                            Message.metadata_["workflow_event"].astext.in_(
                                ["step_done", "step_failed"]
                            ),
                        )
                        .order_by(Message.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.content = content
                    existing.metadata_ = metadata
                    flag_modified(existing, "metadata_")
                    await db.execute(
                        sa_upd(Session)
                        .where(Session.id == channel.active_session_id)
                        .values(last_active=now)
                    )
                    await db.commit()
                    await db.refresh(existing)
                    # In-place edit — emit message_updated so clients patch
                    # the matching id in their local cache.
                    from app.services.channel_events import publish_message_updated
                    publish_message_updated(channel.id, existing)
                    return

            record = Message(
                session_id=channel.active_session_id,
                role="assistant",
                content=content,
                metadata_=metadata,
                created_at=now,
            )
            db.add(record)
            await db.execute(
                sa_upd(Session)
                .where(Session.id == channel.active_session_id)
                .values(last_active=now)
            )
            await db.commit()
            await db.refresh(record)
            from app.services.channel_events import publish_message
            publish_message(channel.id, record)
    except Exception:
        logger.debug(
            "Failed to post workflow chat message (event=%s, run=%s)",
            event_type, run.id, exc_info=True,
        )


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
# Definition snapshot helper
# ---------------------------------------------------------------------------

def _get_run_definition(
    run: WorkflowRun, workflow: Workflow,
) -> tuple[list[dict], dict, list[str]]:
    """Return (steps, defaults, secrets) from snapshot if available, else live workflow.

    Provides backward compatibility — old runs without snapshots fall back to the live workflow.
    """
    snap = getattr(run, "workflow_snapshot", None)
    if isinstance(snap, dict):
        return snap.get("steps", []), snap.get("defaults", {}), snap.get("secrets", [])
    return workflow.steps, workflow.defaults or {}, workflow.secrets or []


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

    # Capture workflow definition snapshot at trigger time
    workflow_snapshot = {
        "steps": workflow.steps,
        "defaults": workflow.defaults or {},
        "secrets": workflow.secrets or [],
    }

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
        workflow_snapshot=workflow_snapshot,
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

    # Post "started" message to channel chat
    await _post_workflow_chat_message(
        run, workflow.name, "started",
        f"Workflow **{workflow.name}** started ({len(workflow.steps)} steps)",
        total_steps=len(workflow.steps),
        completed_steps=0,
    )

    # Start advancement — wrap in try/except to prevent orphaned "running" runs
    try:
        await advance_workflow(run.id)
    except Exception:
        logger.exception("advance_workflow failed during trigger for run %s", run.id)
        async with async_session() as db:
            failed_run = await db.get(WorkflowRun, run.id)
            if failed_run and failed_run.status == "running":
                failed_run.status = "failed"
                failed_run.error = "Initial advancement failed — see server logs"
                failed_run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                await _post_workflow_chat_message(
                    failed_run, workflow.name, "failed",
                    f"Workflow **{workflow.name}** failed to start",
                    total_steps=len(workflow.steps),
                    completed_steps=0,
                )

    # Re-read from DB so callers get step_states updated by advance_workflow
    # (which runs in its own session).
    async with async_session() as db:
        fresh = await db.get(WorkflowRun, run.id)
        if fresh:
            return fresh
    return run


# ---------------------------------------------------------------------------
# Step advancement — the state machine (Phase 5A)
# ---------------------------------------------------------------------------

async def advance_workflow(run_id: uuid.UUID) -> None:
    """Advance a workflow run to the next actionable step (with per-run lock)."""
    lock = _advance_locks.setdefault(run_id, asyncio.Lock())
    async with lock:
        await _advance_workflow_inner(run_id)
    # Clean up lock only if we still own the dict entry AND no one is waiting.
    # Use pop-and-check to avoid the race where another coroutine grabs the
    # lock between our release and this check.
    removed = _advance_locks.pop(run_id, None)
    if removed is not None and removed.locked():
        # Someone acquired the lock between our release and pop — put it back
        _advance_locks.setdefault(run_id, removed)


async def _advance_workflow_inner(run_id: uuid.UUID) -> None:
    """Inner advancement logic.

    Uses a single session with row-level locking to prevent race conditions.
    Loops through pending steps (no recursion):
    - Evaluates conditions (skip if false)
    - Pauses at approval gates
    - Creates tasks for runnable steps
    - Marks run complete when all steps are terminal
    """
    logger.info("advance_workflow called for run %s", run_id)

    # Deferred event dispatch — collected inside the loop, fired after session closes
    pending_events: list[tuple[WorkflowRun, str, str, str]] = []
    fire_completion = False

    while True:
        action_taken = False

        async with async_session() as db:
            run = await db.get(WorkflowRun, run_id, with_for_update=True)
            if not run:
                logger.warning("advance_workflow: run %s not found", run_id)
                return
            if run.status not in ("running", "awaiting_approval"):
                logger.info("advance_workflow: run %s status=%s, skipping", run_id, run.status)
                return

            workflow = await db.get(Workflow, run.workflow_id)
            if not workflow:
                run.status = "failed"
                run.error = f"Workflow '{run.workflow_id}' not found"
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                return

            steps, defaults, _secrets = _get_run_definition(run, workflow)
            step_states = copy.deepcopy(run.step_states)  # deep copy to avoid shared-dict mutation
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
                    _set_step_states(run, step_states)
                    await db.commit()
                    logger.info("Workflow run %s awaiting approval at step %d (%s)",
                                run_id, i, step_def.get("id", "?"))
                    return

                # Execution cap — prevent runaway workflows (only for task-creating steps)
                step_type = step_def.get("type", "agent")
                if step_type != "tool":
                    executed = sum(
                        1 for s in step_states
                        if s["status"] in ("running", "done", "failed")
                    )
                    cap = settings.WORKFLOW_MAX_TASK_EXECUTIONS
                    if executed >= cap:
                        run.status = "failed"
                        run.error = f"Execution cap reached ({cap} tasks)"
                        run.completed_at = datetime.now(timezone.utc)
                        _set_step_states(run, step_states)
                        await db.commit()
                        logger.error(
                            "Workflow run %s hit execution cap (%d)", run_id, cap,
                        )
                        return

                # Handle tool step type — inline execution, no Task created
                if step_type == "tool":
                    tool_name = step_def.get("tool_name")
                    if not tool_name:
                        now = datetime.now(timezone.utc)
                        state["status"] = "failed"
                        state["error"] = "Step type 'tool' requires 'tool_name'"
                        state["started_at"] = now.isoformat()
                        state["completed_at"] = now.isoformat()
                        _set_step_states(run, step_states)
                        run.status = "failed"
                        run.error = f"Step '{step_def.get('id', i)}' missing tool_name"
                        run.completed_at = now
                        await db.commit()
                        return

                    # Render template vars in tool_args
                    raw_args = step_def.get("tool_args", {})
                    rendered_args = {
                        k: render_prompt(str(v), run.params, step_states, steps)
                        for k, v in raw_args.items()
                    }

                    from app.tools.registry import call_local_tool
                    now = datetime.now(timezone.utc)
                    try:
                        result = await call_local_tool(tool_name, json.dumps(rendered_args))
                        max_chars = step_def.get("result_max_chars", defaults.get("result_max_chars", 2000))
                        state["status"] = "done"
                        state["result"] = result[:max_chars]
                    except Exception as e:
                        state["status"] = "failed"
                        state["error"] = str(e)

                    state["started_at"] = now.isoformat()
                    state["completed_at"] = now.isoformat()
                    _set_step_states(run, step_states)
                    context = _build_condition_context(steps, step_states, run.params)
                    action_taken = True

                    # Apply on_failure for tool steps
                    if state["status"] == "failed":
                        on_failure = step_def.get("on_failure", "abort")
                        if on_failure == "abort":
                            run.status = "failed"
                            run.error = f"Tool step '{step_def.get('id', i)}' failed: {state['error']}"
                            run.completed_at = now
                            await db.commit()
                            return
                        # continue falls through to next step
                    await db.commit()
                    continue  # Loop to next step

                # Create task for this step (agent or exec)
                # CRITICAL: task INSERT + step state UPDATE must be atomic.
                # If committed separately, the task worker can pick up and
                # complete the task before the step is marked "running",
                # causing duplicate task creation.
                # The with_for_update row lock above prevents concurrent
                # advancement from creating duplicates — the step status check
                # (status != "pending") is the guard.
                now = datetime.now(timezone.utc)
                try:
                    task = _build_step_task(run, workflow, step_def, i, steps, defaults)
                except Exception as e:
                    logger.exception("Failed to build step task for run %s step %d", run_id, i)
                    state["status"] = "failed"
                    state["error"] = f"Task creation failed: {e}"
                    state["completed_at"] = now.isoformat()
                    _set_step_states(run, step_states)
                    run.status = "failed"
                    run.error = f"Step '{step_def.get('id', i)}' task creation failed: {e}"
                    run.completed_at = now
                    await db.commit()
                    return

                state["status"] = "running"
                state["started_at"] = now.isoformat()
                state["task_id"] = str(task.id)
                run.current_step_index = i
                _set_step_states(run, step_states)
                db.add(task)  # Add to same session as run state update
                await db.commit()  # Atomic: task + step state committed together
                logger.info(
                    "advance_workflow: run %s step %d (%s) → task %s created, step marked 'running'",
                    run_id, i, step_def.get("id", "?"), task.id,
                )
                return  # Wait for task completion callback

            # No more pending steps — check terminal state
            all_terminal = all(
                s["status"] in ("done", "skipped", "failed") for s in step_states
            )
            _set_step_states(run, step_states)

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
            summary = f"{done_ct} done, {fail_ct} failed, {skip_ct} skipped"
            await _dispatch_workflow_event(
                run, workflow.name, event, summary,
            )
            await _post_workflow_chat_message(
                run, workflow.name, event,
                f"Workflow **{workflow.name}** {event} — {summary}",
                total_steps=len(step_states),
                completed_steps=done_ct + fail_ct + skip_ct,
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

def _build_step_task(
    run: WorkflowRun,
    workflow: Workflow,
    step_def: dict,
    step_index: int,
    steps: list[dict] | None = None,
    defaults: dict | None = None,
) -> Task:
    """Build a Task object for the given workflow step WITHOUT committing.

    The caller is responsible for adding the task to their session and committing
    atomically with the step state update — this prevents the race where the task
    worker picks up and completes a task before the step is marked "running".

    ``steps`` and ``defaults`` come from ``_get_run_definition`` (snapshot-aware).
    When not provided (backward compat from approve_step), falls back to live workflow.
    """
    if steps is None:
        steps, defaults, _secrets = _get_run_definition(run, workflow)
    if defaults is None:
        defaults = workflow.defaults or {}

    step_type = step_def.get("type", "agent")

    # Render prompt (tool steps may not have one)
    raw_prompt = step_def.get("prompt", "")
    prompt = render_prompt(raw_prompt, run.params, run.step_states, steps) if raw_prompt else ""

    # Build execution_config from workflow defaults + step overrides
    ecfg: dict = {}

    # For exec steps, the prompt IS the command
    if step_type == "exec":
        ecfg["command"] = prompt
        if step_def.get("args"):
            ecfg["args"] = step_def["args"]
        if step_def.get("working_directory"):
            ecfg["working_directory"] = step_def["working_directory"]
    else:
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
    snap_secrets = (run.workflow_snapshot or {}).get("secrets", []) if run.workflow_snapshot else (workflow.secrets or [])
    step_secrets = step_def.get("secrets")
    if step_secrets:
        allowed = [s for s in step_secrets if s in snap_secrets]
    else:
        allowed = list(snap_secrets)
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

    # Determine task_type based on step type
    task_type = "exec" if step_type == "exec" else "workflow"

    task = Task(
        id=uuid.uuid4(),
        bot_id=run.bot_id,
        channel_id=run.channel_id,
        session_id=step_session_id,
        prompt=prompt,
        title=f"Workflow: {workflow.name} — {step_def.get('id', f'step_{step_index}')}",
        status="pending",
        task_type=task_type,
        dispatch_type="none",  # Workflow manages its own dispatch
        execution_config=ecfg,
        callback_config=callback_config,
        max_run_seconds=timeout,
        created_at=datetime.now(timezone.utc),
    )

    logger.info(
        "Built task %s (type=%s) for workflow run %s step %d (%s)",
        task.id, task_type, run.id, step_index, step_def.get("id", "?"),
    )
    return task


# ---------------------------------------------------------------------------
# Task completion callback (Phase 5C)
# ---------------------------------------------------------------------------

async def on_step_task_completed(
    run_id: str, step_index: int, status: str, task: Task
) -> None:
    """Called when a workflow step's task completes. Updates step state and advances."""
    logger.info(
        "on_step_task_completed: run=%s step=%d status=%s task=%s",
        run_id, step_index, status, task.id,
    )
    try:
        _run_id = uuid.UUID(run_id)
    except (ValueError, TypeError):
        logger.error("Invalid workflow_run_id: %s", run_id)
        return

    async with async_session() as db:
        # Row-level lock prevents lost updates when multiple task completions
        # race — without it, two concurrent completions can read the same
        # step_states snapshot and the second commit overwrites the first.
        run = await db.get(WorkflowRun, _run_id, with_for_update=True)
        if not run:
            logger.warning("WorkflowRun %s not found for task completion", run_id)
            return

        # Skip processing if run is no longer active (e.g. cancelled while task was in-flight)
        if run.status not in ("running", "awaiting_approval"):
            logger.debug("Skipping step completion for run %s (status=%s)", run_id, run.status)
            return

        workflow = await db.get(Workflow, run.workflow_id)
        if not workflow:
            logger.warning("Workflow %s not found for run %s", run.workflow_id, run_id)
            return

        step_states = copy.deepcopy(run.step_states)
        if step_index >= len(step_states):
            logger.error("Step index %d out of bounds for run %s", step_index, run_id)
            return

        state = step_states[step_index]

        # Idempotency guard: if step is already terminal, skip processing
        if state["status"] in ("done", "failed", "skipped"):
            logger.debug("Step %d of run %s already terminal (%s), skipping", step_index, run_id, state["status"])
            return

        # Map task status to step status
        # Use fresh_task from DB for result/error — the `task` object passed
        # into the hook was loaded before execution and has stale result=None.
        steps, defaults, _secrets = _get_run_definition(run, workflow)
        step_def = steps[step_index] if step_index < len(steps) else {}
        fresh_task = await db.get(Task, task.id)
        result_source = fresh_task if fresh_task else task
        if status == "complete":
            state["status"] = "done"
            max_chars = step_def.get("result_max_chars", defaults.get("result_max_chars", 2000))
            state["result"] = (result_source.result or "")[:max_chars]
        else:
            state["status"] = "failed"
            state["error"] = result_source.error or f"Task {status}"

        state["task_id"] = str(task.id)
        state["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Store correlation_id for token usage tracking.
        # fresh_task was already loaded above for result/error.
        if fresh_task and fresh_task.correlation_id:
            state["correlation_id"] = str(fresh_task.correlation_id)

        # Prepare step event dispatch (fired AFTER commit to avoid holding row lock during network I/O)
        step_id = step_def.get("id", f"step_{step_index}")
        done_ct = sum(1 for s in step_states if s["status"] in ("done", "failed", "skipped"))
        total_ct = len(step_states)
        step_event = "step_done" if state["status"] == "done" else "step_failed"
        preview = (state.get("result") or state.get("error") or "")[:100]
        _pending_step_event = (
            run, workflow.name, step_event,
            f"{step_id} ({done_ct}/{total_ct})" + (f" — {preview}" if preview else ""),
        )

        # Handle on_failure policy
        on_failure = step_def.get("on_failure", "abort")
        _committed = False

        if state["status"] == "failed":
            if on_failure == "abort":
                run.status = "failed"
                run.error = f"Step '{step_def.get('id', step_index)}' failed: {state['error']}"
                _set_step_states(run, step_states)
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info("Workflow run %s aborted at step %d", run_id, step_index)
                await _dispatch_workflow_event(*_pending_step_event)
                await _dispatch_workflow_event(
                    run, workflow.name, "failed",
                    f"aborted at {step_id}: {state.get('error', '')[:100]}",
                )
                await _post_workflow_chat_message(
                    run, workflow.name, "step_failed",
                    state.get("error") or f"Step {step_id} failed",
                    step_id=step_id, step_index=step_index,
                    total_steps=total_ct, completed_steps=done_ct,
                )
                await _post_workflow_chat_message(
                    run, workflow.name, "failed",
                    f"Workflow **{workflow.name}** failed — aborted at {step_id}",
                    total_steps=total_ct, completed_steps=done_ct,
                )
                await _fire_after_workflow_complete(run, workflow)
                return
            elif on_failure.startswith("retry:"):
                try:
                    max_retries = int(on_failure.split(":")[1])
                except (ValueError, IndexError):
                    max_retries = 1
                retry_count = state.get("retry_count", 0)

                # Check execution cap before allowing retry
                executed = sum(
                    1 for s in step_states
                    if s["status"] in ("running", "done", "failed")
                )
                cap = settings.WORKFLOW_MAX_TASK_EXECUTIONS
                if executed >= cap:
                    run.status = "failed"
                    run.error = f"Execution cap reached ({cap} tasks) during retry"
                    run.completed_at = datetime.now(timezone.utc)
                    _set_step_states(run, step_states)
                    await db.commit()
                    logger.error(
                        "Workflow run %s hit execution cap (%d) during retry",
                        run_id, cap,
                    )
                    await _dispatch_workflow_event(*_pending_step_event)
                    return

                if retry_count < max_retries:
                    state["status"] = "pending"
                    state["error"] = None
                    state["retry_count"] = retry_count + 1
                    _set_step_states(run, step_states)
                    await db.commit()
                    _committed = True
                    logger.info("Retrying step %d (attempt %d/%d) for run %s",
                                step_index, retry_count + 1, max_retries, run_id)
            # on_failure == "continue" or retry exhausted: fall through to advance

        if not _committed:
            _set_step_states(run, step_states)
            await db.commit()
            logger.info(
                "on_step_task_completed: run %s step %d committed as '%s'",
                run_id, step_index, state["status"],
            )

    # Dispatch step event outside the DB lock
    await _dispatch_workflow_event(*_pending_step_event)

    # Post step chat message to the channel (full result, not the 100-char dispatch preview)
    _full_result = state.get("result") or state.get("error") or ""
    _step_chat_content = _full_result if _full_result else f"Step {step_id} {step_event.replace('step_', '')}"
    await _post_workflow_chat_message(
        run, workflow.name, step_event,
        _step_chat_content,
        step_id=step_id,
        step_index=step_index,
        total_steps=total_ct,
        completed_steps=done_ct,
    )

    # Advance to next step.
    # If this fails, the step state is already committed — the recovery
    # sweep will re-fire advancement.  Log prominently so we can debug.
    try:
        await advance_workflow(_run_id)
    except Exception:
        logger.exception(
            "advance_workflow failed after step %d completion for run %s "
            "(step state IS committed; recovery sweep will retry)",
            step_index, run_id,
        )


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

        step_states = copy.deepcopy(run.step_states)
        if step_index >= len(step_states):
            raise ValueError(f"Step index {step_index} out of bounds")
        if step_states[step_index]["status"] != "pending":
            raise ValueError(f"Step {step_index} is not pending")

        from app.services.workflows import get_workflow
        workflow = get_workflow(run.workflow_id)
        if not workflow:
            raise ValueError(f"Workflow '{run.workflow_id}' not found")

        steps, defaults, _secrets = _get_run_definition(run, workflow)
        step_def = steps[step_index]

        task = _build_step_task(run, workflow, step_def, step_index, steps, defaults)

        # Atomic: task INSERT + step state + run status committed together
        run.status = "running"
        step_states[step_index]["status"] = "running"
        step_states[step_index]["started_at"] = datetime.now(timezone.utc).isoformat()
        step_states[step_index]["task_id"] = str(task.id)
        _set_step_states(run, step_states)
        db.add(task)
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

        step_states = copy.deepcopy(run.step_states)
        if step_index >= len(step_states):
            raise ValueError(f"Step index {step_index} out of bounds")

        step_states[step_index]["status"] = "skipped"
        step_states[step_index]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _set_step_states(run, step_states)
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

        step_states = copy.deepcopy(run.step_states)
        if step_index >= len(step_states):
            raise ValueError(f"Step index {step_index} out of bounds")
        if step_states[step_index]["status"] != "failed":
            raise ValueError(f"Step {step_index} is not failed")

        step_states[step_index]["status"] = "pending"
        step_states[step_index]["error"] = None
        _set_step_states(run, step_states)
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
    """Cancel a running workflow and its pending tasks."""
    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run:
            raise ValueError("WorkflowRun not found")
        if run.status in ("complete", "cancelled"):
            raise ValueError(f"Run is already {run.status}")

        run.status = "cancelled"
        run.completed_at = datetime.now(timezone.utc)

        # Cancel any pending tasks belonging to this workflow run
        now = datetime.now(timezone.utc)
        await db.execute(
            sa_update(Task)
            .where(Task.status.in_(["pending"]))
            .where(Task.task_type.in_(["workflow", "exec"]))
            .where(Task.callback_config["workflow_run_id"].as_string() == str(run_id))
            .values(status="cancelled", completed_at=now)
        )

        await db.commit()
        await db.refresh(run)
    return run
