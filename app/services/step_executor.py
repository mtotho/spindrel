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

from app.agent.context import current_bot_id
from app.config import settings
from app.db.engine import async_session
from app.db.models import Task
from app.services.sub_sessions import emit_step_output_message

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
        if "output_contains" in condition or "output_not_contains" in condition:
            raw = state.get("result")
            if raw is None:
                result_text = ""
            elif isinstance(raw, (dict, list)):
                result_text = json.dumps(raw).lower()
            else:
                result_text = str(raw).lower()
            if "output_contains" in condition:
                if condition["output_contains"].lower() not in result_text:
                    return False
            if "output_not_contains" in condition:
                if condition["output_not_contains"].lower() in result_text:
                    return False
        return True

    logger.warning("Unrecognized condition keys: %s — evaluating as False", list(condition.keys()))
    return False


# ---------------------------------------------------------------------------
# Prompt rendering — {{param}} and {{steps.id.result}} substitution
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}")


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _parse_result_json(result: str | None) -> dict | None:
    """Try to parse a step result as JSON. Returns dict or None.

    LLM agent steps commonly produce prose + a fenced JSON block even when
    the prompt says "Return ONLY JSON". To keep ``{{steps.X.result.key}}``
    lookups and ``fail_if: {result_empty_keys: [...]}`` working across those
    outputs, we fall back to extracting the largest ```json``` / ``` block
    whose contents parse as a JSON object. Arrays and scalars are ignored
    (the caller expects a dict).
    """
    if not result:
        return None
    try:
        parsed = json.loads(result)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: scan for fenced JSON blocks and return the largest valid dict.
    best: dict | None = None
    for match in _FENCED_JSON_RE.finditer(result):
        candidate = match.group(1)
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict) and (best is None or len(candidate) > len(json.dumps(best))):
            best = obj
    return best


def render_prompt(
    template: str,
    params: dict,
    step_states: list[dict],
    steps: list[dict],
    shell_escape: bool = False,
) -> str:
    """Render a step prompt template with parameter and step result substitution.

    Supports:
        {{param_name}}                    -> param value (flat)
        {{params.key}} / {{params.a.b}}   -> nested param drilling
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

        # Params reference: params.key or params.a.b.c (dotted)
        if key.startswith("params."):
            parts = key.split(".")
            obj: any = params
            for k in parts[1:]:
                if isinstance(obj, dict) and k in obj:
                    obj = obj[k]
                else:
                    return match.group(0)  # unresolved
            if isinstance(obj, (dict, list)):
                return _quote(json.dumps(obj))
            return _quote(str(obj))

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
            val = params[key]
            if isinstance(val, (dict, list)):
                return _quote(json.dumps(val))
            return _quote(str(val))

        # Dotted flat-param drill (e.g. {{item.id}} when params has "item"):
        # first segment names a param, remaining segments drill into it.
        if "." in key:
            parts = key.split(".")
            head = parts[0]
            if head in params:
                obj: any = params[head]
                for k in parts[1:]:
                    if isinstance(obj, dict) and k in obj:
                        obj = obj[k]
                    else:
                        return match.group(0)
                if isinstance(obj, (dict, list)):
                    return _quote(json.dumps(obj))
                return _quote(str(obj))

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


def task_params(task: Task) -> dict:
    """Pull ``execution_config['params']`` off a task, defaulting to ``{}``."""
    cfg = task.execution_config or {}
    return dict(cfg.get("params") or {})


def _resolve_value_ref(
    expr: str,
    params: dict,
    step_states: list[dict],
    steps: list[dict],
) -> object:
    """Resolve a value reference to its raw Python value (list/dict/scalar).

    Unlike :func:`render_prompt` which returns a string, this function
    returns the raw underlying value — used by ``foreach`` to iterate.

    Supported forms:
      * ``"{{steps.<id>.result[.json_key...]}}"`` / bare ``steps.<id>.result``
      * ``"{{params.<key>[.nested...]}}"`` / bare ``params.<key>``
      * ``"{{<flat_param>}}"`` / bare ``<flat_param>``

    Unresolved references return ``None``.
    """
    if not isinstance(expr, str):
        return expr
    key = expr.strip()
    if key.startswith("{{") and key.endswith("}}"):
        key = key[2:-2].strip()

    # Params reference: params.a.b.c
    if key.startswith("params."):
        parts = key.split(".")
        obj: object = params
        for k in parts[1:]:
            if isinstance(obj, dict) and k in obj:
                obj = obj[k]
            else:
                return None
        return obj

    # Steps reference: steps.<id>.<field>[.<json_key>...]
    if key.startswith("steps."):
        parts = key.split(".")
        if len(parts) < 3:
            return None
        step_id = parts[1]
        field = parts[2]

        step_lookup: dict[str, dict] = {}
        for i, step_def in enumerate(steps):
            sid = step_def.get("id", f"step_{i}")
            if i < len(step_states):
                step_lookup[sid] = step_states[i]
                step_lookup[str(i + 1)] = step_states[i]

        state = step_lookup.get(step_id)
        if not state:
            return None
        val = state.get(field)
        # Drill into JSON result
        if len(parts) > 3:
            if not isinstance(val, (dict, list)):
                parsed = _parse_result_json(str(val)) if val is not None else None
                if parsed is None:
                    return None
                val = parsed
            for k in parts[3:]:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    return None
        return val

    # Flat param
    return params.get(key)


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
        result = state.get("result")
        if result is None:
            result = ""
        elif not isinstance(result, str):
            # user_prompt steps store dict responses; foreach stores a
            # small summary dict too. Serialize so downstream str ops work.
            result = json.dumps(result)
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
        raw_result = state.get("result")
        if raw_result is None:
            result = ""
        elif isinstance(raw_result, str):
            result = raw_result
        else:
            result = json.dumps(raw_result)
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
        command = render_prompt(raw_command, task_params(task), step_states, steps, shell_escape=True)
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


def _render_widget_envelope(
    task: Task,
    step_def: dict,
    steps: list[dict],
    step_states: list[dict],
    item_ctx: dict | None = None,
) -> dict:
    """Render the ``widget_template`` / ``widget_args`` for a user_prompt step.

    Substitution: ``{{params.*}}``, ``{{steps.*}}``, and — when called from
    inside a ``foreach`` iteration — ``{{item.*}}`` / ``{{item_index}}``.
    """
    template = step_def.get("widget_template") or {}
    widget_args = step_def.get("widget_args") or {}

    params = dict(task_params(task))
    if item_ctx:
        params.update(item_ctx)

    def _walk(v):
        if isinstance(v, str):
            return render_prompt(v, params, step_states, steps)
        if isinstance(v, list):
            return [_walk(x) for x in v]
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        return v

    rendered_args = _walk(widget_args)
    rendered_template = _walk(template)

    return {
        "template": rendered_template,
        "args": rendered_args,
        "title": step_def.get("title") or step_def.get("label"),
    }


def _resolve_response_schema(
    raw_schema: dict,
    task: Task,
    step_states: list[dict],
    steps: list[dict],
    item_ctx: dict | None = None,
) -> dict:
    """Resolve template refs inside a response schema.

    For ``multi_item`` schemas, ``items_ref`` is evaluated against the
    current step states and materialized as ``items`` (list of dicts each
    with an ``id``). If ``items`` is already present, it's kept as-is.
    """
    schema = dict(raw_schema)
    if schema.get("type") != "multi_item":
        return schema
    if schema.get("items"):
        return schema
    ref = schema.get("items_ref")
    if not ref:
        return schema
    params = dict(task_params(task))
    if item_ctx:
        params.update(item_ctx)
    resolved = _resolve_value_ref(ref, params, step_states, steps)
    if isinstance(resolved, list):
        schema["items"] = [x for x in resolved if isinstance(x, dict) and x.get("id")]
    return schema


def _validate_resolve_response(response_schema: dict, response: object) -> str | None:
    """Return an error string if ``response`` does not match ``response_schema``.

    Schema shapes (v1):
      * ``{"type": "binary"}`` → ``{"decision": "approve" | "reject"}``
      * ``{"type": "multi_item", "items": [{"id": ...}, ...]}``
        → ``{item_id: "approve" | "reject", ...}`` — every key must be a
        known item id, every value must be ``"approve"`` or ``"reject"``.
    """
    kind = (response_schema or {}).get("type")
    if not isinstance(response, dict):
        return "Response must be a JSON object"

    if kind == "binary":
        decision = response.get("decision")
        if decision not in ("approve", "reject"):
            return "Binary response requires 'decision' of 'approve' or 'reject'"
        return None

    if kind == "multi_item":
        items = response_schema.get("items") or []
        known_ids = {str(it.get("id")) for it in items if it.get("id") is not None}
        for k, v in response.items():
            if k not in known_ids:
                return f"Unknown item id: {k!r}"
            if v not in ("approve", "reject"):
                return f"Invalid decision for item {k!r}: {v!r}"
        return None

    # Unknown/absent schema — permissive: accept any dict.
    return None


async def _run_foreach_step(
    task: Task,
    step_def: dict,
    step_index: int,
    steps: list[dict],
    step_states: list[dict],
) -> str:
    """Run a ``foreach`` step: iterate a list, run ``do`` sub-steps per item.

    Returns a terminal state: ``'done'``, ``'failed'``, or
    ``'awaiting_user_input'`` (if a sub-step paused — NOT supported in v1:
    currently treated as failed with a clear error). Intermediate state
    is written to ``step_states[step_index]`` as:

    ```
    {
      status, started_at, completed_at,
      iterations: [[<sub_state>, ...], ...],   # parallel to items
      items: [<item>, ...],                    # resolved list
      result: <aggregated result string>,
    }
    ```

    Sub-step types supported in v1: ``exec``, ``tool``. Nested
    ``user_prompt`` / ``foreach`` / ``agent`` are deferred.
    """
    over_expr = step_def.get("over")
    do_sub_steps = step_def.get("do") or []
    on_failure = step_def.get("on_failure", "abort")

    params = task_params(task)
    items = _resolve_value_ref(over_expr, params, step_states, steps)

    state = step_states[step_index]
    if items is None:
        state["status"] = "failed"
        state["error"] = f"foreach 'over' expression did not resolve: {over_expr!r}"
        return "failed"
    if not isinstance(items, list):
        state["status"] = "failed"
        state["error"] = (
            f"foreach 'over' must resolve to a list, got "
            f"{type(items).__name__}"
        )
        return "failed"

    state["items"] = items
    state["iterations"] = [
        [
            {
                "status": "pending",
                "result": None,
                "error": None,
            }
            for _ in do_sub_steps
        ]
        for _ in items
    ]
    await _persist_step_states(task.id, step_states)

    any_failed = False
    for iter_idx, item in enumerate(items):
        iter_params = dict(params)
        iter_params["item"] = item
        iter_params["item_index"] = iter_idx
        iter_params["item_count"] = len(items)

        iter_failed = False
        for sub_idx, sub_def in enumerate(do_sub_steps):
            sub_state = state["iterations"][iter_idx][sub_idx]
            sub_type = sub_def.get("type", "tool")

            # Render the entire sub-step (including the `when:` clause) with
            # iter-local params first so per-iteration template substitution
            # like `{{item.id}}` works inside the gate. Without this, the
            # when-clause sees the literal `{{item.id}}` string and gates
            # uniformly across iterations.
            rendered = _render_sub_step_def(sub_def, iter_params, step_states, steps)

            # when-gate on the sub-step (evaluated with item bound + rendered)
            sub_ctx = build_condition_context(steps, step_states, iter_params)
            if not evaluate_condition(rendered.get("when"), sub_ctx):
                sub_state["status"] = "skipped"
                await _persist_step_states(task.id, step_states)
                continue

            sub_state["status"] = "running"
            await _persist_step_states(task.id, step_states)

            if sub_type == "tool":
                rendered_args = {
                    k: render_prompt(str(v), iter_params, step_states, steps)
                    for k, v in (rendered.get("tool_args") or {}).items()
                }
                status, result, error = await _call_tool_with_args(
                    rendered.get("tool_name"), rendered_args, rendered, task.bot_id
                )
            else:
                # v1: only `tool` sub-steps are supported inside foreach.
                # exec/agent/user_prompt/foreach nesting is an explicit
                # follow-up (see plan's "parked" list).
                status = "failed"
                result = None
                error = f"Unsupported sub-step type in foreach: {sub_type!r}"

            sub_state["status"] = status
            sub_state["result"] = result
            sub_state["error"] = error
            await _persist_step_states(task.id, step_states)

            if status == "failed":
                iter_failed = True
                any_failed = True
                if sub_def.get("on_failure", "abort") == "abort":
                    # stop this iteration's sub-steps
                    break

        if iter_failed and on_failure == "abort":
            # mark remaining iterations as skipped
            for j in range(iter_idx + 1, len(items)):
                for sub_state in state["iterations"][j]:
                    sub_state["status"] = "skipped"
            await _persist_step_states(task.id, step_states)
            state["status"] = "failed"
            state["error"] = f"foreach aborted at iteration {iter_idx}"
            return "failed"

    # Empty foreach: nothing iterated → 'skipped' (not 'done') so the UI shows
    # the step as a no-op rather than a successful completion the user has to
    # mentally explain. Pairs with the user_prompt auto-skip path which also
    # marks 'skipped' when the multi_item items list resolves to empty.
    if not items:
        state["status"] = "skipped"
    elif any_failed and on_failure == "abort":
        state["status"] = "failed"
    else:
        state["status"] = "done"
    if any_failed and on_failure == "continue":
        state["error"] = "one or more foreach iterations failed"
    state["result"] = json.dumps({
        "iterations": len(items),
        "failures": sum(
            1
            for iteration in state["iterations"]
            for ss in iteration
            if ss.get("status") == "failed"
        ),
    })
    return state["status"]


def _render_sub_step_def(
    sub_def: dict,
    iter_params: dict,
    step_states: list[dict],
    steps: list[dict],
) -> dict:
    """Render string fields on a sub-step definition with iter-local params."""
    def _walk(v):
        if isinstance(v, str):
            return render_prompt(v, iter_params, step_states, steps)
        if isinstance(v, list):
            return [_walk(x) for x in v]
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        return v
    return _walk(sub_def)


async def _call_tool_with_args(
    tool_name: str | None,
    rendered_args: dict,
    sub_def: dict,
    bot_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Invoke a local tool by name with pre-rendered args.

    ``bot_id`` seeds ``current_bot_id`` for the call so tools that depend on
    the ContextVar (call_api, list_api_endpoints) can resolve the task's
    identity. Without it those tools return "No bot context available."
    """
    if not tool_name:
        return ("failed", None, "foreach sub-step of type 'tool' requires 'tool_name'")
    from app.tools.registry import call_local_tool
    bot_id_token = current_bot_id.set(bot_id)
    try:
        result = await call_local_tool(tool_name, json.dumps(rendered_args))
        max_chars = sub_def.get("result_max_chars", 2000)
        if result and len(result) > max_chars:
            result = result[:max_chars] + "... [truncated]"
        # Mirror _run_tool_step's error-payload detection so foreach sub-steps
        # that returned `{"error": ...}` surface as failed instead of green.
        err = _detect_error_payload(result) if result else None
        if err is not None:
            return ("failed", result, err)
        return ("done", result, None)
    except Exception as e:
        return ("failed", None, str(e)[:2000])
    finally:
        current_bot_id.reset(bot_id_token)


async def _run_user_prompt_step(
    task: Task,
    step_def: dict,
    step_index: int,
    steps: list[dict],
    step_states: list[dict],
    item_ctx: dict | None = None,
) -> None:
    """Pause the pipeline and emit an inline widget for user resolution.

    Sets ``step_states[step_index]`` to ``awaiting_user_input`` with the
    rendered widget envelope and response schema attached. The main loop
    must treat this as a terminal pause and return; the pipeline resumes
    via :func:`app.routers.api_v1_admin.tasks.admin_resolve_step`.
    """
    envelope = _render_widget_envelope(task, step_def, steps, step_states, item_ctx)

    # Render the response schema too, so multi_item schemas that declare
    # ``items_ref: "{{steps.foo.result.items}}"`` get materialized into a
    # concrete ``items`` list at pause time. Otherwise _validate_resolve_response
    # sees an empty items list and rejects every submission.
    raw_schema = step_def.get("response_schema") or {"type": "binary"}
    response_schema = _resolve_response_schema(
        raw_schema, task, step_states, steps, item_ctx
    )

    # Auto-skip when multi_item resolves to zero items — there's nothing for
    # a human to approve, so don't clutter the Findings panel with a phantom
    # review. Downstream foreach steps that iterate the approved subset will
    # also iterate zero items and complete immediately. Binary schemas still
    # pause (always exactly one decision to make).
    #
    # Write a human-readable result so the UI can explain the instant-done
    # — without it the step row reads as "review: done 34ms" which looks
    # like the user somehow missed a review window. The result is still
    # JSON-serialized to match the string-typed contract every other step
    # path uses (the admin editor's StepCard calls `.slice()` on it).
    if (
        response_schema.get("type") == "multi_item"
        and not response_schema.get("items")
    ):
        state = step_states[step_index]
        # Mark as 'skipped' (not 'done') so the UI naturally renders the row
        # with strikethrough + dim styling. Downstream foreach steps that
        # iterate the same empty proposals list will also resolve to skipped,
        # so the entire tail of the pipeline reads as "no work to do" instead
        # of as a string of green checkmarks the user has to interpret.
        state["status"] = "skipped"
        state["widget_envelope"] = envelope
        state["response_schema"] = response_schema
        state["result"] = (
            "Auto-skipped: the prior step returned no items to review — "
            "nothing for a human to approve or reject."
        )
        state["error"] = None
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        await _persist_step_states(task.id, step_states)
        return

    state = step_states[step_index]
    state["status"] = "awaiting_user_input"
    state["widget_envelope"] = envelope
    state["response_schema"] = response_schema
    state["result"] = None
    state["error"] = None
    await _persist_step_states(task.id, step_states)


async def _run_evaluate_step(
    task: Task,
    step_def: dict,
    step_index: int,
    steps: list[dict],
    step_states: list[dict],
) -> tuple[str, str | None, str | None]:
    """Run an `evaluate` step. Returns (status, result_json, error).

    YAML shape:
      type: evaluate
      evaluator: exec | bot_invoke
      cases: "{{steps.load_cases.result}}"   # list of dicts (resolved from prior step)
      command: "..."                          # exec only — supports {{case.<field>}}
      parallelism: 4                          # max in-flight cases
      per_case_timeout: 30                    # seconds

    The result is a JSON-encoded list of {case, captured, error} ready for
    ``score_eval_results``.
    """
    from app.services.eval_evaluator import run_evaluator

    evaluator = step_def.get("evaluator")
    if not evaluator:
        return ("failed", None, "evaluate step requires 'evaluator'")

    # Resolve cases ref → raw list. When the prior step stored a JSON string,
    # _resolve_value_ref returns that string verbatim — try to parse it as a
    # JSON list before bailing.
    cases_ref = step_def.get("cases")
    raw_cases = _resolve_value_ref(cases_ref, task_params(task), step_states, steps) if cases_ref else None
    if isinstance(raw_cases, str):
        try:
            parsed = json.loads(raw_cases)
            if isinstance(parsed, list):
                raw_cases = parsed
            elif isinstance(parsed, dict) and isinstance(parsed.get("cases"), list):
                raw_cases = parsed["cases"]
        except (ValueError, TypeError):
            pass
    if raw_cases is None:
        return ("failed", None, f"evaluate: cases ref '{cases_ref}' resolved to None")
    if not isinstance(raw_cases, list):
        return ("failed", None, f"evaluate: cases must resolve to a list, got {type(raw_cases).__name__}")
    cases = [c if isinstance(c, dict) else {"input": c} for c in raw_cases]

    # Resolve parallelism / per_case_timeout (may be templated as well)
    def _coerce_int(val, default: int) -> int:
        if val is None:
            return default
        if isinstance(val, str):
            rendered = render_prompt(val, task_params(task), step_states, steps)
            try:
                return int(rendered)
            except (ValueError, TypeError):
                return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    parallelism = _coerce_int(step_def.get("parallelism"), 1)
    per_case_timeout = float(_coerce_int(step_def.get("per_case_timeout"), 60))

    # Build evaluator-specific spec from the step_def, rendering {{...}} on
    # every string found inside (dicts, lists, nested). Without recursion
    # `override.value: "{{steps.propose.result.prompt}}"` would pass through
    # verbatim and the evaluator would treat the literal template as the
    # system prompt.
    params = task_params(task)

    def _render_deep(val):
        if isinstance(val, str):
            return render_prompt(val, params, step_states, steps)
        if isinstance(val, dict):
            return {k: _render_deep(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_render_deep(v) for v in val]
        return val

    spec_keys_passthrough = ("command", "prompt", "bot_id", "override")
    spec: dict = {}
    for key in spec_keys_passthrough:
        if key not in step_def:
            continue
        spec[key] = _render_deep(step_def[key])

    try:
        results = await run_evaluator(
            evaluator, cases, spec,
            parallelism=parallelism,
            per_case_timeout=per_case_timeout,
            parent_task_id=task.id,
        )
    except Exception as e:
        logger.exception("evaluate step %d crashed", step_index)
        return ("failed", None, str(e)[:2000])

    result_json = json.dumps(results, default=str)
    max_chars = step_def.get("result_max_chars", 50000)
    if len(result_json) > max_chars:
        result_json = result_json[:max_chars] + '... [truncated]"'
    return ("done", result_json, None)


async def _run_tool_step(
    task: Task,
    step_def: dict,
    step_index: int,
    steps: list[dict],
    step_states: list[dict],
) -> tuple[str, str | None, str | None]:
    """Run a local tool call step. Returns (status, result, error).

    Error-payload detection: if the tool returns a JSON object with a
    non-null ``error`` key, treat the step as failed and keep the raw
    result for UI display. This catches "tool succeeded but reported an
    internal error in its payload" cases that used to surface as green
    checkmarks (Phase 5).
    """
    from app.tools.registry import call_local_tool

    tool_name = step_def.get("tool_name")
    if not tool_name:
        return ("failed", None, "Step type 'tool' requires 'tool_name'")

    raw_args = step_def.get("tool_args", {})
    params = task_params(task)
    rendered_args = {
        k: render_prompt(str(v), params, step_states, steps)
        for k, v in raw_args.items()
    }

    # Tool steps need the task's bot identity in the ContextVar so tools that
    # read `current_bot_id.get()` (call_api, list_api_endpoints, etc.) can look
    # up the bot's API key and permissions. Pipeline runners don't pass through
    # `set_agent_context`, so without this the step fails with "No bot context
    # available." Reset the token after the call so we don't leak into peers.
    bot_id_token = current_bot_id.set(task.bot_id)
    try:
        result = await call_local_tool(tool_name, json.dumps(rendered_args))
        max_chars = step_def.get("result_max_chars", 2000)
        if len(result) > max_chars:
            result = result[:max_chars] + "... [truncated]"
        # Error-payload detection — keep raw result, surface error string.
        err = _detect_error_payload(result)
        if err is not None:
            return ("failed", result, err)
        return ("done", result, None)
    except Exception as e:
        return ("failed", None, str(e)[:2000])
    finally:
        current_bot_id.reset(bot_id_token)


def _detect_error_payload(result: str) -> str | None:
    """If ``result`` is JSON with a non-null ``error`` key, return its message.

    Accepts either a bare string, a number, or a mapping for ``error`` —
    ``{"error": null}`` / ``{"error": ""}`` are NOT treated as failures so
    tools that use ``error`` as an always-present "null means success" key
    keep working.
    """
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    if "error" not in parsed:
        return None
    val = parsed["error"]
    if val is None or val == "" or val is False:
        return None
    if isinstance(val, str):
        return val[:500]
    try:
        return json.dumps(val)[:500]
    except Exception:
        return str(val)[:500]


def _evaluate_fail_if(
    step_def: dict,
    step_index: int,
    steps: list[dict],
    step_states: list[dict],
    task: Task,
) -> tuple[bool, str | None]:
    """Evaluate ``fail_if`` for a step that just completed successfully.

    Returns ``(should_fail, reason)``. Supports:

    - ``fail_if: {result_empty_keys: ["proposals"]}`` — fails when any named
      key is missing or empty in the parsed-JSON result of this step.
    - Any shape ``evaluate_condition`` accepts. If ``step:`` is omitted,
      the current step id is implied, so you can write ``fail_if:
      {output_contains: "unable to"}`` at step scope.
    """
    fail_if = step_def.get("fail_if")
    if not fail_if or not isinstance(fail_if, dict):
        return (False, None)

    # Convenience shortcut: required non-empty keys in the parsed result.
    if "result_empty_keys" in fail_if:
        state = step_states[step_index]
        parsed = _parse_result_json(state.get("result")) or {}
        keys = fail_if.get("result_empty_keys") or []
        missing = [k for k in keys if not parsed.get(k)]
        if missing:
            return (True, f"fail_if: empty result keys: {missing}")
        return (False, None)

    cond = fail_if
    if "step" not in cond and "param" not in cond and "all" not in cond and "any" not in cond and "not" not in cond:
        step_id = step_def.get("id") or f"step_{step_index}"
        cond = {**cond, "step": step_id}

    context = build_condition_context(steps, step_states, task_params(task))
    if evaluate_condition(cond, context):
        return (True, f"fail_if matched: {json.dumps(fail_if)[:200]}")
    return (False, None)


def _apply_fail_if_to_state(
    state: dict,
    step_def: dict,
    step_index: int,
    steps: list[dict],
    step_states: list[dict],
    task: Task,
) -> bool:
    """If the step's fail_if triggers, mutate state to ``failed``. Returns True if flipped."""
    if state.get("status") != "done":
        return False
    should_fail, reason = _evaluate_fail_if(step_def, step_index, steps, step_states, task)
    if should_fail:
        state["status"] = "failed"
        # Preserve result, layer the error reason on top of any existing one.
        prior = state.get("error")
        state["error"] = f"{reason}" + (f" | {prior}" if prior else "")
        return True
    return False


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
        context = build_condition_context(steps, step_states, task_params(task))
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
            _apply_fail_if_to_state(state, step_def, i, steps, step_states, task)
            await _persist_step_states(task.id, step_states)
            await emit_step_output_message(task=task, step_def=step_def, step_index=i, state=state)
            logger.info("Pipeline %s step %d exec → %s%s", task.id, i + 1, state["status"], f" error={state['error']}" if state.get("error") else "")

            if state["status"] == "failed" and step_def.get("on_failure", "abort") == "abort":
                await _finalize_pipeline(task, steps, step_states, failed=True)
                return

        elif step_type == "tool":
            status, result, error = await _run_tool_step(task, step_def, i, steps, step_states)
            state["status"] = status
            state["result"] = result
            state["error"] = error
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            _apply_fail_if_to_state(state, step_def, i, steps, step_states, task)
            await _persist_step_states(task.id, step_states)
            await emit_step_output_message(task=task, step_def=step_def, step_index=i, state=state)
            logger.info("Pipeline %s step %d tool → %s%s", task.id, i + 1, state["status"], f" error={state['error']}" if state.get("error") else "")

            if state["status"] == "failed" and step_def.get("on_failure", "abort") == "abort":
                await _finalize_pipeline(task, steps, step_states, failed=True)
                return

        elif step_type == "agent":
            # Agent steps spawn a child task and return — resumed via callback
            await _spawn_agent_step(task, step_def, i, steps, step_states)
            return  # Wait for callback

        elif step_type == "user_prompt":
            await _run_user_prompt_step(task, step_def, i, steps, step_states)
            # Auto-skip path (multi_item with zero items) marks the step as
            # terminal in-place. Without this check the orchestrator returns
            # waiting for a /resolve callback that will never come, leaving
            # the pipeline stuck at "running" forever.
            if state["status"] in ("done", "skipped"):
                logger.info(
                    "Pipeline %s step %d user_prompt auto-skipped (%s) → continue",
                    task.id, i + 1, state["status"],
                )
                continue
            logger.info("Pipeline %s step %d user_prompt → awaiting_user_input", task.id, i + 1)
            return  # Wait for /resolve

        elif step_type == "foreach":
            status = await _run_foreach_step(task, step_def, i, steps, step_states)
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            await _persist_step_states(task.id, step_states)
            logger.info("Pipeline %s step %d foreach → %s", task.id, i + 1, status)
            if status == "failed" and step_def.get("on_failure", "abort") == "abort":
                await _finalize_pipeline(task, steps, step_states, failed=True)
                return

        elif step_type == "evaluate":
            status, result, error = await _run_evaluate_step(task, step_def, i, steps, step_states)
            state["status"] = status
            state["result"] = result
            state["error"] = error
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            _apply_fail_if_to_state(state, step_def, i, steps, step_states, task)
            await _persist_step_states(task.id, step_states)
            await emit_step_output_message(task=task, step_def=step_def, step_index=i, state=state)
            logger.info("Pipeline %s step %d evaluate → %s%s", task.id, i + 1, state["status"], f" error={state['error']}" if state.get("error") else "")
            if state["status"] == "failed" and step_def.get("on_failure", "abort") == "abort":
                await _finalize_pipeline(task, steps, step_states, failed=True)
                return

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
    rendered_prompt = render_prompt(raw_prompt, task_params(parent_task), step_states, steps)

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
    if step_def.get("skills"):
        ecfg["skills"] = step_def["skills"]
    if preamble_parts:
        ecfg["system_preamble"] = "\n\n".join(preamble_parts)

    # For sub_session-isolated runs, route the child task's Messages into
    # the parent's sub-session (run_session_id) and detach from the parent
    # channel — outbox/renderers skip the run and only the anchor card in
    # the parent channel stays visible. For inline runs, preserve today's
    # behavior (child inherits parent's channel + session).
    if parent_task.run_isolation == "sub_session":
        child_session_id = parent_task.run_session_id
        child_channel_id = None
    else:
        child_session_id = parent_task.session_id
        child_channel_id = parent_task.channel_id

    child = Task(
        bot_id=parent_task.bot_id,
        channel_id=child_channel_id,
        session_id=child_session_id,
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
    # The ``child_task`` arg comes from the generic hook dispatcher, which
    # passes the stale in-memory object — it never sees the ``t.result =
    # result_text`` commit inside ``run_task``. Refetch the child directly
    # so we write the real LLM response into the parent's step_states
    # (otherwise the envelope shows the agent step as "done" with no
    # expandable output).
    async with async_session() as db:
        parent = await db.get(Task, uuid.UUID(pipeline_task_id))
        if parent is None:
            logger.error("Pipeline task %s not found for step callback", pipeline_task_id)
            return

        steps = parent.steps or []
        step_states = copy.deepcopy(parent.step_states or [])

        fresh_child = await db.get(Task, child_task.id)
        fresh_result = fresh_child.result if fresh_child else child_task.result
        fresh_error = fresh_child.error if fresh_child else child_task.error

    if step_index >= len(step_states):
        logger.error("Step index %d out of range for pipeline %s", step_index, pipeline_task_id)
        return

    now = datetime.now(timezone.utc)
    state = step_states[step_index]
    state["status"] = "done" if status == "complete" else "failed"
    state["result"] = fresh_result
    state["error"] = fresh_error
    state["completed_at"] = now.isoformat()

    # Truncate result
    step_def = steps[step_index] if step_index < len(steps) else {}
    max_chars = step_def.get("result_max_chars", 2000)
    if state["result"] and len(state["result"]) > max_chars:
        state["result"] = state["result"][:max_chars] + "... [truncated]"

    # Apply fail_if (e.g. empty proposals from an agent analysis).
    _apply_fail_if_to_state(state, step_def, step_index, steps, step_states, parent)

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
