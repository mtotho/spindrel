"""Evaluator dispatch for the `evaluate` pipeline step type.

The `evaluate` step takes a `cases` list and an evaluator name, runs the
evaluator over every case (in parallel up to `parallelism`), and returns a
list of `{case, captured, error}` dicts that downstream `score_eval_results`
calls consume.

v1 evaluators:
  - exec        : run a shell command per case (template-substitutes case fields)
  - bot_invoke  : (deferred to Phase 1b) invoke a bot in isolation per case

The dispatch lives outside step_executor.py to keep that file focused on
pipeline-control logic. The step_executor calls into `run_evaluate_step`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
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
) -> list[dict]:
    sem = asyncio.Semaphore(max(1, parallelism))

    async def _worker(case: dict) -> dict:
        async with sem:
            return await _eval_exec_one(case, spec, per_case_timeout)

    return await asyncio.gather(*[_worker(c) for c in cases])


# ---------------------------------------------------------------------------
# bot_invoke evaluator (Phase 1b — stub returns informative error)
# ---------------------------------------------------------------------------

async def _run_bot_invoke_evaluator(
    cases: list[dict],
    spec: dict,
    parallelism: int,
    per_case_timeout: float,
) -> list[dict]:
    return [
        {
            "case": c,
            "captured": None,
            "error": "bot_invoke evaluator not yet implemented (Phase 1b)",
        }
        for c in cases
    ]


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
) -> list[dict]:
    """Dispatch by evaluator name. Returns list of {case, captured, error}.

    Args:
      evaluator: 'exec' | 'bot_invoke'
      cases: list of case dicts (each at minimum has the user-defined fields
          referenced by the evaluator's command/prompt template).
      spec: evaluator-specific config (e.g., for exec: {command: "..."}).
      parallelism: max concurrent in-flight cases.
      per_case_timeout: seconds per case before kill / abort.
    """
    fn = _EVALUATORS.get(evaluator)
    if fn is None:
        raise ValueError(f"unknown evaluator '{evaluator}'. Available: {list_evaluators()}")
    return await fn(cases, spec, parallelism, per_case_timeout)
