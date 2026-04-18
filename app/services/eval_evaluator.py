"""Evaluator dispatch for the `evaluate` pipeline step type.

The `evaluate` step takes a `cases` list and an evaluator name, runs the
evaluator over every case (in parallel up to `parallelism`), and returns a
list of `{case, captured, error}` dicts that downstream `score_eval_results`
calls consume.

v1 evaluators:
  - exec        : run a shell command per case (template-substitutes case fields)
  - bot_invoke  : invoke a bot in isolation per case, capturing
                  {response_text, tool_calls, token_count, latency_ms}.
                  The override is delivered via a task-scoped ContextVar
                  (``current_system_prompt_override``) so the bot row is
                  never mutated.

The dispatch lives outside step_executor.py to keep that file focused on
pipeline-control logic. The step_executor calls into `run_evaluator`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-case template substitution — narrower than render_prompt; only swaps
# {{case.<field>}} into command/arg strings using the current case dict.
# ---------------------------------------------------------------------------

_CASE_TEMPLATE_RE = re.compile(r"\{\{\s*case\.([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")


def _render_case_template(template: str, case: dict, shell_escape: bool = False) -> str:
    """Substitute {{case.<field>}} placeholders. Supports dotted paths."""

    def _quote(v: str) -> str:
        if not shell_escape:
            return v
        return "'" + v.replace("'", "'\\''") + "'"

    def _replace(m: re.Match) -> str:
        path = m.group(1).split(".")
        obj: Any = case
        for k in path:
            if isinstance(obj, dict) and k in obj:
                obj = obj[k]
            else:
                return m.group(0)
        if isinstance(obj, (dict, list)):
            return _quote(json.dumps(obj))
        return _quote(str(obj))

    return _CASE_TEMPLATE_RE.sub(_replace, template)


# ---------------------------------------------------------------------------
# exec evaluator
# ---------------------------------------------------------------------------

async def _eval_exec_one(
    case: dict,
    spec: dict,
    timeout: float,
) -> dict:
    """Run a shell command for one case. Captures stdout, stderr, exit_code,
    duration_ms. Returns {case, captured, error}."""
    cmd_template = spec.get("command")
    if not cmd_template:
        return {"case": case, "captured": None, "error": "missing 'command' in evaluator spec"}
    command = _render_case_template(cmd_template, case, shell_escape=True)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "case": case,
                "captured": {"exit_code": -1, "stdout": "", "stderr": "", "timed_out": True},
                "error": f"exec timed out after {timeout}s",
            }
        captured = {
            "exit_code": proc.returncode,
            "stdout": stdout_b.decode("utf-8", errors="replace")[:8000],
            "stderr": stderr_b.decode("utf-8", errors="replace")[:8000],
        }
        return {"case": case, "captured": captured, "error": None}
    except Exception as e:
        logger.exception("exec evaluator failed for case")
        return {"case": case, "captured": None, "error": str(e)[:500]}


async def _run_exec_evaluator(
    cases: list[dict],
    spec: dict,
    parallelism: int,
    per_case_timeout: float,
    parent_task_id: uuid.UUID | None = None,
) -> list[dict]:
    sem = asyncio.Semaphore(max(1, parallelism))

    async def _worker(case: dict) -> dict:
        async with sem:
            return await _eval_exec_one(case, spec, per_case_timeout)

    return await asyncio.gather(*[_worker(c) for c in cases])


# ---------------------------------------------------------------------------
# bot_invoke evaluator
#
# Each case spawns an ephemeral Task row with:
#   - task_type="eval"                       → skips active-session resolution
#   - channel_id=None                        → no bus / outbox emissions
#   - session_id=None                        → fresh Session per case
#   - callback_config.pipeline_task_id=...   → _is_pipeline_child → True
#   - execution_config.system_prompt_override → ContextVar injected in run_task
# The evaluator then polls the Task row until status ∈ {complete, failed},
# then assembles {response_text, tool_calls, token_count, latency_ms} from
# the task row + ToolCall rows + TraceEvent(token_usage) rows.
# ---------------------------------------------------------------------------

_BOT_INVOKE_POLL_INTERVAL_S = 1.0


async def _create_eval_task(
    case: dict,
    bot_id: str,
    system_prompt_override: str | None,
    parent_task_id: uuid.UUID | None,
    correlation_id: uuid.UUID,
) -> "uuid.UUID":
    """Create a pending eval Task row. Returns its id."""
    from app.db.engine import async_session
    from app.db.models import Task

    exec_cfg: dict = {}
    if system_prompt_override is not None:
        exec_cfg["system_prompt_override"] = system_prompt_override
    cb_cfg: dict = {}
    if parent_task_id is not None:
        cb_cfg["pipeline_task_id"] = str(parent_task_id)

    async with async_session() as db:
        t = Task(
            bot_id=bot_id,
            channel_id=None,
            session_id=None,
            client_id="eval",
            prompt=case.get("input", "") if isinstance(case, dict) else str(case),
            status="pending",
            task_type="eval",
            dispatch_type="none",
            dispatch_config={},
            execution_config=exec_cfg or None,
            callback_config=cb_cfg or None,
            correlation_id=correlation_id,
            parent_task_id=parent_task_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)
        return t.id


async def _await_eval_task(task_id: uuid.UUID, timeout: float) -> tuple[str, str | None, str | None, datetime | None, datetime | None]:
    """Poll the Task row until it leaves 'pending'/'running' or timeout.

    Returns (status, result, error, created_at, completed_at).
    """
    from app.db.engine import async_session
    from app.db.models import Task

    deadline = time.monotonic() + timeout
    while True:
        async with async_session() as db:
            t = await db.get(Task, task_id)
        if t is None:
            return ("failed", None, f"task {task_id} disappeared", None, None)
        if t.status in ("complete", "failed"):
            return (t.status, t.result, t.error, t.created_at, t.completed_at)
        if time.monotonic() >= deadline:
            return ("failed", t.result, f"eval task timed out after {timeout}s (status={t.status})", t.created_at, None)
        await asyncio.sleep(_BOT_INVOKE_POLL_INTERVAL_S)


async def _collect_tool_calls(correlation_id: uuid.UUID) -> list[dict]:
    """Pull ToolCall rows for this eval invocation, ordered by created_at."""
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import ToolCall

    async with async_session() as db:
        rows = (await db.execute(
            select(ToolCall).where(ToolCall.correlation_id == correlation_id).order_by(ToolCall.created_at)
        )).scalars().all()
    return [
        {
            "name": r.tool_name,
            "type": r.tool_type,
            "arguments": r.arguments or {},
            "iteration": r.iteration,
            "duration_ms": r.duration_ms,
            "error": r.error,
        }
        for r in rows
    ]


async def _sum_token_usage(correlation_id: uuid.UUID) -> dict:
    """Sum token_usage TraceEvent rows for this eval invocation."""
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import TraceEvent

    async with async_session() as db:
        rows = (await db.execute(
            select(TraceEvent).where(
                TraceEvent.correlation_id == correlation_id,
                TraceEvent.event_type == "token_usage",
            )
        )).scalars().all()
    prompt = completion = total = 0
    for r in rows:
        data = r.data or {}
        prompt += int(data.get("prompt_tokens") or 0)
        completion += int(data.get("completion_tokens") or 0)
        total += int(data.get("total_tokens") or 0)
    return {"prompt": prompt, "completion": completion, "total": total}


async def _eval_bot_invoke_one(
    case: dict,
    spec: dict,
    parent_task_id: uuid.UUID | None,
    timeout: float,
) -> dict:
    bot_id = spec.get("bot_id")
    if not bot_id:
        return {"case": case, "captured": None, "error": "bot_invoke requires 'bot_id' in evaluator spec"}

    # Resolve override.value — only system_prompt is supported in v1.
    override = spec.get("override") or {}
    override_field = override.get("field") or "system_prompt"
    override_value = override.get("value")
    if override_field != "system_prompt":
        return {
            "case": case,
            "captured": None,
            "error": f"bot_invoke: unsupported override field '{override_field}' (v1 supports only 'system_prompt')",
        }

    correlation_id = uuid.uuid4()
    t0 = time.monotonic()
    try:
        task_id = await _create_eval_task(
            case=case,
            bot_id=bot_id,
            system_prompt_override=override_value,
            parent_task_id=parent_task_id,
            correlation_id=correlation_id,
        )
    except Exception as e:
        logger.exception("bot_invoke: failed to create eval task")
        return {"case": case, "captured": None, "error": f"create task failed: {e!s}"[:500]}

    status, result, error, created_at, completed_at = await _await_eval_task(task_id, timeout)
    if created_at and completed_at:
        latency_ms = int((completed_at - created_at).total_seconds() * 1000)
    else:
        latency_ms = int((time.monotonic() - t0) * 1000)

    try:
        tool_calls = await _collect_tool_calls(correlation_id)
    except Exception:
        logger.exception("bot_invoke: tool_call collection failed for %s", correlation_id)
        tool_calls = []
    try:
        tokens = await _sum_token_usage(correlation_id)
    except Exception:
        logger.exception("bot_invoke: token_usage collection failed for %s", correlation_id)
        tokens = {"prompt": 0, "completion": 0, "total": 0}

    captured = {
        "response_text": result or "",
        "tool_calls": tool_calls,
        "token_count": tokens,
        "latency_ms": latency_ms,
        "task_id": str(task_id),
    }
    if status == "failed":
        return {"case": case, "captured": captured, "error": error or "eval task failed"}
    return {"case": case, "captured": captured, "error": None}


async def _run_bot_invoke_evaluator(
    cases: list[dict],
    spec: dict,
    parallelism: int,
    per_case_timeout: float,
    parent_task_id: uuid.UUID | None = None,
) -> list[dict]:
    sem = asyncio.Semaphore(max(1, parallelism))

    async def _worker(case: dict) -> dict:
        async with sem:
            return await _eval_bot_invoke_one(case, spec, parent_task_id, per_case_timeout)

    return await asyncio.gather(*[_worker(c) for c in cases])


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------

_EVALUATORS = {
    "exec": _run_exec_evaluator,
    "bot_invoke": _run_bot_invoke_evaluator,
}


def list_evaluators() -> list[str]:
    return sorted(_EVALUATORS)


async def run_evaluator(
    evaluator: str,
    cases: list[dict],
    spec: dict,
    parallelism: int = 1,
    per_case_timeout: float = 60.0,
    parent_task_id: uuid.UUID | None = None,
) -> list[dict]:
    """Dispatch by evaluator name. Returns list of {case, captured, error}.

    Args:
      evaluator: 'exec' | 'bot_invoke'
      cases: list of case dicts (each at minimum has the user-defined fields
          referenced by the evaluator's command/prompt template).
      spec: evaluator-specific config (exec: {command: ...};
          bot_invoke: {bot_id: ..., override: {field, value}}).
      parallelism: max concurrent in-flight cases.
      per_case_timeout: seconds per case before kill / abort.
      parent_task_id: parent pipeline task id — threaded to bot_invoke so child
          eval tasks inherit ``_is_pipeline_child`` UI suppression.
    """
    fn = _EVALUATORS.get(evaluator)
    if fn is None:
        raise ValueError(f"unknown evaluator '{evaluator}'. Available: {list_evaluators()}")
    return await fn(cases, spec, parallelism, per_case_timeout, parent_task_id=parent_task_id)
