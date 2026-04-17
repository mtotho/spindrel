"""Step executor — runs inline task pipelines.

A pipeline is an ordered list of steps stored in task.steps, each of type
exec (shell), tool (local tool call), or agent (LLM conversation turn).
Exec and tool steps run inline; agent steps spawn a child task and resume
via callback when it completes.

The condition evaluator, prompt renderer, and context builder are shared
with the workflow executor — they were extracted here as the canonical
location for these pure functions.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.db.engine import async_session
from app.db.models import Task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Condition evaluator — pure function, no side effects
# ---------------------------------------------------------------------------

def evaluate_condition(condition: dict | None, context: dict) -> bool:
    """Evaluate a step condition against the current run context.

    Context shape:
        {
            "steps": {"step_id": {"status": "done", "result": "..."}},
            "params": {"name": "value"},
        }

    Condition shapes:
        None / empty -> always True
        {"step": "id", "status": "done"}
        {"step": "id", "status": "done", "output_contains": "text"}
        {"step": "id", "output_not_contains": "text"}
        {"param": "name", "equals": value}
        {"all": [cond, ...]}  -- AND
        {"any": [cond, ...]}  -- OR
        {"not": cond}         -- negation
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
# Prompt rendering — {{param}} and {{steps.id.result}} substitution
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}")


def _parse_result_json(result: str | None) -> dict | None:
    """Try to parse a step result as JSON. Returns dict or None."""
    if not result:
        return None
    try:
        parsed = json.loads(result)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def render_prompt(
    template: str,
    params: dict,
    step_states: list[dict],
    steps: list[dict],
    shell_escape: bool = False,
) -> str:
    """Render a step prompt template with parameter and step result substitution.

    Supports:
        {{param_name}}                    -> param value
        {{steps.step_id.result}}          -> prior step's result text
        {{steps.step_id.status}}          -> prior step's status
        {{steps.step_id.result.json_key}} -> JSON field from result

    When shell_escape=True, substituted values are wrapped in single quotes
    so they're safe for shell interpolation.
    """
    step_lookup: dict[str, dict] = {}
    for i, step_def in enumerate(steps):
        sid = step_def.get("id", f"step_{i}")
        if i < len(step_states):
            step_lookup[sid] = step_states[i]
            # Index by 1-based position to match UI numbering
            step_lookup[str(i + 1)] = step_states[i]

    def _quote(val: str) -> str:
        if not shell_escape:
            return val
        # Shell single-quote: replace ' with '\'' then wrap in ''
        return "'" + val.replace("'", "'\\''") + "'"

    def _replace(match: re.Match) -> str:
        key = match.group(1).strip()

        # Steps reference: steps.step_id.field[.json_key]
        if key.startswith("steps."):
            parts = key.split(".")
            if len(parts) >= 3:
                step_id = parts[1]
                field = parts[2]
                state = step_lookup.get(step_id, {})
                val = state.get(field)
                # Drill into JSON result: steps.1.result.some_key
                if val is not None and len(parts) > 3:
                    parsed = _parse_result_json(str(val))
                    if parsed is not None:
                        json_key = ".".join(parts[3:])
                        # Support simple dotted access
                        obj: any = parsed
                        for k in parts[3:]:
                            if isinstance(obj, dict) and k in obj:
                                obj = obj[k]
                            else:
                                return match.group(0)  # unresolved
                        val = json.dumps(obj) if isinstance(obj, (dict, list)) else str(obj)
                    else:
                        return match.group(0)  # not valid JSON
                return _quote(str(val)) if val is not None else match.group(0)
            return match.group(0)

        # Param reference
        if key in params:
            return _quote(str(params[key]))

        # Leave unresolved templates as-is
        return match.group(0)

    return _TEMPLATE_RE.sub(_replace, template)


def build_condition_context(steps: list[dict], step_states: list[dict], params: dict | None = None) -> dict:
    """Build the context dict for condition evaluation from current step states."""
    steps_ctx = {}
    for i, step_def in enumerate(steps):
        sid = step_def.get("id", f"step_{i}")
        if i < len(step_states):
            steps_ctx[sid] = step_states[i]
    return {"steps": steps_ctx, "params": params or {}}


# ---------------------------------------------------------------------------
# Auto-inject prior results into step context
# ---------------------------------------------------------------------------

def _build_prior_results_preamble(steps: list[dict], step_states: list[dict], current_index: int) -> str:
    """Build a preamble section summarizing prior step results for auto-injection."""
    lines = []
    for i in range(current_index):
        if i >= len(step_states):
            break
        state = step_states[i]
        if state.get("status") not in ("done", "failed"):
            continue
        step_def = steps[i]
        label = step_def.get("label") or step_def.get("id", f"step_{i}")
        step_type = step_def.get("type", "agent")
        result = state.get("result", "")
        max_chars = 2000
        if len(result) > max_chars:
            result = result[:max_chars] + "... [truncated]"
        status = state["status"]
        lines.append(f"- {label} ({step_type}, {status}):\n{result}")
    if not lines:
        return ""
    return "Previous step results:\n" + "\n\n".join(lines)


def _build_prior_results_env(steps: list[dict], step_states: list[dict], current_index: int) -> dict[str, str]:
    """Build env vars for prior step results (for exec steps).

    For each prior step, exports:
        STEP_{n}_RESULT  — full result text
        STEP_{n}_STATUS  — done|failed
        STEP_{id}_RESULT — same, keyed by step id

    If the result is valid JSON with top-level keys, also exports each key:
        STEP_{n}_{key}   — value of that JSON field
    """
    env = {}
    for i in range(current_index):
        if i >= len(step_states):
            break
        state = step_states[i]
        if state.get("status") not in ("done", "failed"):
            continue
        result = state.get("result", "") or ""
        # By 1-based index (matches UI numbering)
        n = i + 1
        env[f"STEP_{n}_RESULT"] = result[:4000]
        env[f"STEP_{n}_STATUS"] = state.get("status", "")
        # By id
        step_def = steps[i]
        sid = step_def.get("id", f"step_{i}")
        safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", sid).upper()
        env[f"STEP_{safe_id}_RESULT"] = result[:4000]
        env[f"STEP_{safe_id}_STATUS"] = state.get("status", "")
        # Auto-extract top-level JSON keys
        parsed = _parse_result_json(result)
        if parsed:
            for key, val in parsed.items():
                safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", key)
                str_val = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
                env[f"STEP_{n}_{safe_key}"] = str_val[:4000]
    return env


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _init_step_states(steps: list[dict]) -> list[dict]:
    """Create initial step_states list from step definitions."""
    return [
        {
            "status": "pending",
            "result": None,
            "error": None,
            "started_at": None,
            "completed_at": None,
            "task_id": None,
        }
        for _ in steps
    ]


async def _persist_step_states(task_id: uuid.UUID, step_states: list[dict]) -> None:
    """Persist step_states to the database and live-update the channel envelope."""
    async with async_session() as db:
        t = await db.get(Task, task_id)
        if t:
            t.step_states = copy.deepcopy(step_states)
            flag_modified(t, "step_states")
            await db.commit()
            await db.refresh(t)
            _task_for_anchor = t
        else:
            _task_for_anchor = None

    # Publish MESSAGE_UPDATED so open channel UIs re-render the envelope.
    if _task_for_anchor is not None and _task_for_anchor.channel_id is not None:
        try:
            from app.services.task_run_anchor import update_anchor
            await update_anchor(_task_for_anchor)
        except Exception:
            logger.debug("update_anchor failed for task %s", task_id, exc_info=True)


async def _run_exec_step(
    task: Task,
    step_def: dict,
    step_index: int,
    steps: list[dict],
    step_states: list[dict],
) -> tuple[str, str | None, str | None]:
    """Run a shell command step. Returns (status, result, error)."""
    import shlex as _shlex
    from app.agent.bots import get_bot
    from app.services.sandbox import sandbox_service

    try:
        raw_command = step_def.get("prompt", "").strip()
        command = render_prompt(raw_command, {}, step_states, steps, shell_escape=True)
        working_directory = step_def.get("working_directory")

        bot = get_bot(task.bot_id)

        # Build script directly — the command is already a shell string,
        # don't pass through shlex.join which would re-quote it.
        script_parts: list[str] = []
        if working_directory:
            script_parts.append(f"cd {_shlex.quote(working_directory)}")
        script_parts.append(command)
        script = " && ".join(script_parts)

        timeout = step_def.get("timeout", 120)

        # Build env vars with prior results
        env_vars = _build_prior_results_env(steps, step_states, step_index)

        # Prepend env var exports to the script (single-quoted to prevent
        # shell interpretation of backticks, $, etc. in result text)
        if env_vars:
            def _sq(v: str) -> str:
                return "'" + v.replace("'", "'\\''") + "'"
            exports = "\n".join(f'export {k}={_sq(v)}' for k, v in env_vars.items())
            script = exports + "\n" + script

        async def _do_exec():
            if bot.workspace.enabled or bot.shared_workspace_id:
                from app.services.workspace import workspace_service
                ws_result = await workspace_service.exec(
                    bot.id, script, bot.workspace, working_directory or "", bot=bot
                )
                from dataclasses import dataclass as _dc
                @_dc
                class _R:
                    stdout: str; stderr: str; exit_code: int; truncated: bool; duration_ms: int
                return _R(
                    stdout=ws_result.stdout, stderr=ws_result.stderr,
                    exit_code=ws_result.exit_code, truncated=ws_result.truncated,
                    duration_ms=ws_result.duration_ms,
                )
            elif bot.bot_sandbox.enabled:
                return await sandbox_service.exec_bot_local(bot.id, script, bot.bot_sandbox)
            else:
                raise RuntimeError("No sandbox available for exec step")

        result = await asyncio.wait_for(_do_exec(), timeout=timeout)

        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        if result.truncated:
            parts.append("[output truncated]")
        parts.append(f"[exit {result.exit_code}, {result.duration_ms}ms]")
        result_text = "\n".join(parts)

        max_chars = step_def.get("result_max_chars", 2000)
        if len(result_text) > max_chars:
            result_text = result_text[:max_chars] + "... [truncated]"

        if result.exit_code != 0:
            return ("failed", result_text, f"Non-zero exit code: {result.exit_code}")
        return ("done", result_text, None)

    except asyncio.TimeoutError:
        return ("failed", None, f"Timed out after {timeout}s")
    except Exception as e:
        return ("failed", None, str(e)[:2000])


async def _run_tool_step(
    step_def: dict,
    step_index: int,
    steps: list[dict],
    step_states: list[dict],
) -> tuple[str, str | None, str | None]:
    """Run a local tool call step. Returns (status, result, error)."""
    from app.tools.registry import call_local_tool

    tool_name = step_def.get("tool_name")
    if not tool_name:
        return ("failed", None, "Step type 'tool' requires 'tool_name'")

    raw_args = step_def.get("tool_args", {})
    rendered_args = {
        k: render_prompt(str(v), {}, step_states, steps)
        for k, v in raw_args.items()
    }

    try:
        result = await call_local_tool(tool_name, json.dumps(rendered_args))
        max_chars = step_def.get("result_max_chars", 2000)
        if len(result) > max_chars:
            result = result[:max_chars] + "... [truncated]"
        return ("done", result, None)
    except Exception as e:
        return ("failed", None, str(e)[:2000])


async def run_task_pipeline(task: Task) -> None:
    """Execute a pipeline task: run steps sequentially, persist progress.

    Exec and tool steps run inline. Agent steps spawn a child task and
    return — the pipeline resumes via on_pipeline_step_completed() when
    the child finishes.
    """
    steps = task.steps or []
    if not steps:
        logger.warning("Pipeline task %s has no steps", task.id)
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "failed"
                t.error = "Pipeline has no steps"
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
        return

    step_states = task.step_states or _init_step_states(steps)

    # Mark task as running
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
            return
        t.status = "running"
        t.run_at = now
        t.step_states = copy.deepcopy(step_states)
        flag_modified(t, "step_states")
        await db.commit()

    # Create (or look up) the in-channel envelope anchor so the UI can
    # render live step progress. UI-only — not dispatched to integrations.
    try:
        from app.services.task_run_anchor import ensure_anchor_message
        await ensure_anchor_message(task)
    except Exception:
        logger.warning("Pipeline %s: anchor creation failed", task.id, exc_info=True)

    try:
        await _advance_pipeline(task, steps, step_states)
    except Exception:
        logger.exception("Pipeline task %s failed with unhandled error", task.id)
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "failed"
                t.error = traceback.format_exc()[-4000:]
                t.completed_at = datetime.now(timezone.utc)
                # Also update step_states so the failing step shows its error
                if t.step_states:
                    for ss in t.step_states:
                        if ss.get("status") == "running":
                            ss["status"] = "failed"
                            ss["error"] = "Pipeline crashed"
                            ss["completed_at"] = datetime.now(timezone.utc).isoformat()
                    flag_modified(t, "step_states")
                await db.commit()


async def _advance_pipeline(
    task: Task,
    steps: list[dict],
    step_states: list[dict],
    start_index: int = 0,
) -> None:
    """Advance the pipeline from start_index onward.

    Called both on initial run and when resuming after an agent step callback.
    """
    for i in range(start_index, len(steps)):
        step_def = steps[i]
        state = step_states[i]

        # Skip already-completed steps (resuming after callback)
        if state["status"] in ("done", "failed", "skipped"):
            continue

        step_type = step_def.get("type", "agent")
        now = datetime.now(timezone.utc)

        # Evaluate condition
        context = build_condition_context(steps, step_states)
        condition = step_def.get("when")
        if not evaluate_condition(condition, context):
            state["status"] = "skipped"
            state["started_at"] = now.isoformat()
            state["completed_at"] = now.isoformat()
            await _persist_step_states(task.id, step_states)
            logger.info("Pipeline %s step %d skipped (condition false)", task.id, i)
            continue

        state["status"] = "running"
        state["started_at"] = now.isoformat()
        await _persist_step_states(task.id, step_states)
        logger.info("Pipeline %s step %d/%d started (type=%s)", task.id, i + 1, len(steps), step_type)

        if step_type == "exec":
            status, result, error = await _run_exec_step(task, step_def, i, steps, step_states)
            state["status"] = status
            state["result"] = result
            state["error"] = error
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            await _persist_step_states(task.id, step_states)
            logger.info("Pipeline %s step %d exec → %s%s", task.id, i + 1, status, f" error={error}" if error else "")

            if status == "failed" and step_def.get("on_failure", "abort") == "abort":
                await _finalize_pipeline(task, steps, step_states, failed=True)
                return

        elif step_type == "tool":
            status, result, error = await _run_tool_step(step_def, i, steps, step_states)
            state["status"] = status
            state["result"] = result
            state["error"] = error
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            await _persist_step_states(task.id, step_states)
            logger.info("Pipeline %s step %d tool → %s%s", task.id, i + 1, status, f" error={error}" if error else "")

            if status == "failed" and step_def.get("on_failure", "abort") == "abort":
                await _finalize_pipeline(task, steps, step_states, failed=True)
                return

        elif step_type == "agent":
            # Agent steps spawn a child task and return — resumed via callback
            await _spawn_agent_step(task, step_def, i, steps, step_states)
            return  # Wait for callback

        else:
            state["status"] = "failed"
            state["error"] = f"Unknown step type: {step_type}"
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            await _persist_step_states(task.id, step_states)
            await _finalize_pipeline(task, steps, step_states, failed=True)
            return

    # All steps processed
    await _finalize_pipeline(task, steps, step_states)


async def _spawn_agent_step(
    parent_task: Task,
    step_def: dict,
    step_index: int,
    steps: list[dict],
    step_states: list[dict],
) -> None:
    """Create a child task for an agent (LLM) step."""
    raw_prompt = step_def.get("prompt", "")
    rendered_prompt = render_prompt(raw_prompt, {}, step_states, steps)

    # Auto-inject prior results into system preamble
    preamble_parts = []
    prior_results = _build_prior_results_preamble(steps, step_states, step_index)
    if prior_results:
        preamble_parts.append(prior_results)

    ecfg: dict = {}
    model = step_def.get("model")
    if model:
        ecfg["model_override"] = model
    if step_def.get("tools"):
        ecfg["tools"] = step_def["tools"]
    if step_def.get("carapaces"):
        ecfg["carapaces"] = step_def["carapaces"]
    if preamble_parts:
        ecfg["system_preamble"] = "\n\n".join(preamble_parts)

    child = Task(
        bot_id=parent_task.bot_id,
        channel_id=parent_task.channel_id,
        session_id=parent_task.session_id,
        prompt=rendered_prompt,
        status="pending",
        task_type="workflow",  # Uses workflow task type for session handling
        parent_task_id=parent_task.id,
        dispatch_type=parent_task.dispatch_type or "none",
        dispatch_config=dict(parent_task.dispatch_config or {}),
        execution_config=ecfg if ecfg else None,
        callback_config={
            "pipeline_task_id": str(parent_task.id),
            "pipeline_step_index": step_index,
        },
        max_run_seconds=step_def.get("timeout"),
        created_at=datetime.now(timezone.utc),
    )

    async with async_session() as db:
        db.add(child)
        await db.commit()
        await db.refresh(child)

    step_states[step_index]["task_id"] = str(child.id)
    await _persist_step_states(parent_task.id, step_states)

    logger.info(
        "Pipeline %s step %d: spawned agent task %s",
        parent_task.id, step_index, child.id,
    )


async def on_pipeline_step_completed(
    pipeline_task_id: str,
    step_index: int,
    status: str,
    child_task: Task,
) -> None:
    """Called when a child agent task completes. Resumes the pipeline."""
    async with async_session() as db:
        parent = await db.get(Task, uuid.UUID(pipeline_task_id))
        if parent is None:
            logger.error("Pipeline task %s not found for step callback", pipeline_task_id)
            return

        steps = parent.steps or []
        step_states = copy.deepcopy(parent.step_states or [])

    if step_index >= len(step_states):
        logger.error("Step index %d out of range for pipeline %s", step_index, pipeline_task_id)
        return

    now = datetime.now(timezone.utc)
    state = step_states[step_index]
    state["status"] = "done" if status == "complete" else "failed"
    state["result"] = child_task.result
    state["error"] = child_task.error
    state["completed_at"] = now.isoformat()

    # Truncate result
    step_def = steps[step_index] if step_index < len(steps) else {}
    max_chars = step_def.get("result_max_chars", 2000)
    if state["result"] and len(state["result"]) > max_chars:
        state["result"] = state["result"][:max_chars] + "... [truncated]"

    await _persist_step_states(uuid.UUID(pipeline_task_id), step_states)

    # Check on_failure
    if state["status"] == "failed" and step_def.get("on_failure", "abort") == "abort":
        await _finalize_pipeline(parent, steps, step_states, failed=True)
        return

    # Continue to next step
    await _advance_pipeline(parent, steps, step_states, start_index=step_index + 1)


async def _finalize_pipeline(
    task: Task,
    steps: list[dict],
    step_states: list[dict],
    failed: bool | None = None,
) -> None:
    """Mark the pipeline task as complete/failed and aggregate results."""
    if failed is None:
        failed = any(s.get("status") == "failed" for s in step_states)

    # Aggregate results from all completed steps
    result_parts = []
    for i, state in enumerate(step_states):
        if state.get("status") in ("done", "failed"):
            step_def = steps[i] if i < len(steps) else {}
            label = step_def.get("label") or step_def.get("id", f"step_{i}")
            result_parts.append(f"[{label}: {state['status']}] {state.get('result', '') or state.get('error', '')}")

    aggregated = "\n\n".join(result_parts) if result_parts else "No results"

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t:
            t.status = "failed" if failed else "complete"
            t.result = aggregated[:10000]
            t.completed_at = now
            t.step_states = copy.deepcopy(step_states)
            flag_modified(t, "step_states")
            if failed:
                errors = [s.get("error") for s in step_states if s.get("status") == "failed" and s.get("error")]
                t.error = "; ".join(errors)[:4000] if errors else "Pipeline step failed"
            await db.commit()

    status = "failed" if failed else "complete"
    logger.info("Pipeline %s finalized → %s", task.id, status)

    # Refresh the envelope anchor with final state + optionally post a
    # dispatcher-visible summary message to the channel.
    if task.channel_id is not None:
        try:
            async with async_session() as _db:
                _t_final = await _db.get(Task, task.id)
            if _t_final is not None:
                from app.services.task_run_anchor import (
                    create_summary_message,
                    update_anchor,
                )
                await update_anchor(_t_final)
                ecfg = _t_final.execution_config or {}
                if ecfg.get("post_final_to_channel"):
                    await create_summary_message(_t_final)
        except Exception:
            logger.warning(
                "Pipeline %s: finalize anchor/summary publish failed",
                task.id, exc_info=True,
            )

    from app.agent.tasks import _fire_task_complete
    await _fire_task_complete(task, status)
