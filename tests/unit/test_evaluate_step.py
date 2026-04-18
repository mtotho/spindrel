"""Unit tests for the `evaluate` pipeline step type.

Covers the evaluator dispatch (app.services.eval_evaluator) and the
step_executor wiring (app.services.step_executor._run_evaluate_step).
The bot_invoke evaluator is a Phase 1b stub; tests assert the stub
behavior so it's easy to swap in real implementation later.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from app.services.eval_evaluator import (
    _render_case_template,
    list_evaluators,
    run_evaluator,
)


# ---------------------------------------------------------------------------
# _render_case_template — narrow {{case.<field>}} substitution
# ---------------------------------------------------------------------------

class TestRenderCaseTemplate:
    def test_simple_substitution(self):
        out = _render_case_template("echo {{case.input}}", {"input": "hi"})
        assert out == "echo hi"

    def test_dotted_path(self):
        out = _render_case_template("x={{case.meta.tag}}", {"meta": {"tag": "v1"}})
        assert out == "x=v1"

    def test_missing_key_left_unsubstituted(self):
        out = _render_case_template("x={{case.absent}}", {})
        assert out == "x={{case.absent}}"

    def test_dict_serialized_as_json(self):
        out = _render_case_template("p={{case.obj}}", {"obj": {"a": 1}})
        assert out == 'p={"a": 1}'

    def test_shell_escape_quotes_value(self):
        out = _render_case_template("echo {{case.x}}", {"x": "hi 'there"}, shell_escape=True)
        # single-quote wrapping with embedded escaping
        assert out == r"echo 'hi '\''there'"


# ---------------------------------------------------------------------------
# Evaluator dispatch — registry
# ---------------------------------------------------------------------------

class TestEvaluatorRegistry:
    def test_lists_known_evaluators(self):
        names = list_evaluators()
        assert "exec" in names
        assert "bot_invoke" in names

    @pytest.mark.asyncio
    async def test_unknown_evaluator_raises(self):
        with pytest.raises(ValueError, match="unknown evaluator"):
            await run_evaluator("nope", [], {}, parallelism=1, per_case_timeout=5)


# ---------------------------------------------------------------------------
# exec evaluator — real subprocess (small, fast, no flake)
# ---------------------------------------------------------------------------

class TestExecEvaluator:
    @pytest.mark.asyncio
    async def test_runs_command_per_case(self):
        cases = [{"input": "hello"}, {"input": "world"}]
        spec = {"command": "printf {{case.input}}"}
        out = await run_evaluator("exec", cases, spec, parallelism=2, per_case_timeout=5)
        assert len(out) == 2
        outputs = sorted(o["captured"]["stdout"] for o in out)
        assert outputs == ["hello", "world"]
        assert all(o["captured"]["exit_code"] == 0 for o in out)
        assert all(o["error"] is None for o in out)

    @pytest.mark.asyncio
    async def test_captures_nonzero_exit(self):
        cases = [{"x": 1}]
        spec = {"command": "exit 7"}
        out = await run_evaluator("exec", cases, spec, parallelism=1, per_case_timeout=5)
        assert out[0]["captured"]["exit_code"] == 7
        assert out[0]["error"] is None  # exec doesn't fail the eval — exit code is the signal

    @pytest.mark.asyncio
    async def test_missing_command_in_spec(self):
        out = await run_evaluator("exec", [{"x": 1}], {}, parallelism=1, per_case_timeout=5)
        assert out[0]["captured"] is None
        assert "missing 'command'" in out[0]["error"]

    @pytest.mark.asyncio
    async def test_timeout_kills_runaway(self):
        cases = [{"x": 1}]
        spec = {"command": "sleep 10"}
        out = await run_evaluator("exec", cases, spec, parallelism=1, per_case_timeout=0.5)
        assert "timed out" in out[0]["error"]
        assert out[0]["captured"]["timed_out"] is True

    @pytest.mark.asyncio
    async def test_parallelism_runs_concurrently(self):
        # 4 cases each sleeping 0.5s — with parallelism=4, total wall time
        # should be much closer to 0.5s than 2.0s.
        cases = [{"i": i} for i in range(4)]
        spec = {"command": "sleep 0.5"}
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        out = await run_evaluator("exec", cases, spec, parallelism=4, per_case_timeout=5)
        elapsed = loop.time() - t0
        assert all(o["captured"]["exit_code"] == 0 for o in out)
        # generous: parallel run should be under 1.5s; serial would be ≥2s.
        assert elapsed < 1.5, f"expected parallel exec, got {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# bot_invoke evaluator (Phase 1b stub)
# ---------------------------------------------------------------------------

class TestBotInvokeStub:
    @pytest.mark.asyncio
    async def test_returns_informative_error_per_case(self):
        cases = [{"input": "hi"}, {"input": "bye"}]
        out = await run_evaluator("bot_invoke", cases, {}, parallelism=1, per_case_timeout=5)
        assert len(out) == 2
        for entry in out:
            assert entry["captured"] is None
            assert "Phase 1b" in entry["error"]


# ---------------------------------------------------------------------------
# step_executor._run_evaluate_step — pipeline-level wiring
# ---------------------------------------------------------------------------

class TestEvaluateStepWiring:
    @pytest.mark.asyncio
    async def test_resolves_cases_from_prior_step_and_runs(self):
        from app.services.step_executor import _run_evaluate_step

        # Build a minimal "task" object — only the attrs the function uses.
        task = MagicMock()
        task.execution_config = {"params": {}}

        # Prior step produced a JSON list-of-dicts for cases.
        prior_cases = [{"input": "alpha"}, {"input": "beta"}]
        steps = [
            {"id": "load_cases", "type": "tool"},
            {"id": "run_eval", "type": "evaluate", "evaluator": "exec",
             "command": "printf {{case.input}}", "cases": "{{steps.load_cases.result}}",
             "parallelism": 2, "per_case_timeout": 5},
        ]
        step_states = [
            {"id": "load_cases", "status": "done", "result": json.dumps(prior_cases)},
            {"id": "run_eval", "status": "running"},
        ]

        status, result, error = await _run_evaluate_step(task, steps[1], 1, steps, step_states)
        assert error is None, f"unexpected error: {error}"
        assert status == "done"
        parsed = json.loads(result)
        assert len(parsed) == 2
        outputs = sorted(p["captured"]["stdout"] for p in parsed)
        assert outputs == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_missing_evaluator_fails(self):
        from app.services.step_executor import _run_evaluate_step
        task = MagicMock()
        task.execution_config = {"params": {}}
        steps = [{"id": "x", "type": "evaluate"}]
        step_states = [{"id": "x", "status": "running"}]
        status, result, error = await _run_evaluate_step(task, steps[0], 0, steps, step_states)
        assert status == "failed"
        assert "evaluator" in error

    @pytest.mark.asyncio
    async def test_cases_resolves_to_non_list_fails(self):
        from app.services.step_executor import _run_evaluate_step
        task = MagicMock()
        task.execution_config = {"params": {}}
        steps = [
            {"id": "load", "type": "tool"},
            {"id": "ev", "type": "evaluate", "evaluator": "exec",
             "command": "true", "cases": "{{steps.load.result}}"},
        ]
        step_states = [
            {"id": "load", "status": "done", "result": "not a list"},
            {"id": "ev", "status": "running"},
        ]
        status, _, error = await _run_evaluate_step(task, steps[1], 1, steps, step_states)
        assert status == "failed"
        assert "must resolve to a list" in error or "resolved to None" in error
