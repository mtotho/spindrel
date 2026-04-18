"""Unit tests for the `evaluate` pipeline step type.

Covers the evaluator dispatch (app.services.eval_evaluator) and the
step_executor wiring (app.services.step_executor._run_evaluate_step).
Phase 1b: bot_invoke evaluator creates child Task rows + gathers captures
from task row / ToolCall / TraceEvent token_usage.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
# bot_invoke evaluator (Phase 1b — real evaluator)
# ---------------------------------------------------------------------------

class TestBotInvokeValidation:
    """Input-validation paths that don't need DB fixtures."""

    @pytest.mark.asyncio
    async def test_missing_bot_id_returns_per_case_error(self):
        cases = [{"input": "hi"}, {"input": "bye"}]
        out = await run_evaluator("bot_invoke", cases, {}, parallelism=1, per_case_timeout=5)
        assert len(out) == 2
        for entry in out:
            assert entry["captured"] is None
            assert "bot_id" in entry["error"]

    @pytest.mark.asyncio
    async def test_unsupported_override_field(self):
        cases = [{"input": "hi"}]
        spec = {"bot_id": "any", "override": {"field": "model", "value": "gpt-5"}}
        out = await run_evaluator("bot_invoke", cases, spec, parallelism=1, per_case_timeout=5)
        assert out[0]["captured"] is None
        assert "unsupported override field" in out[0]["error"]


class TestBotInvokeCapture:
    """Capture-shape + override-plumbing tests. Task creation is patched so the
    evaluator exercises create → await → collect without running the real task
    worker."""

    @pytest.mark.asyncio
    async def test_captured_shape_on_success(self):
        # Fake a completed eval task.
        now = datetime.now(timezone.utc)
        t_id = uuid.uuid4()

        async def fake_create(**kwargs):
            return t_id

        async def fake_await(task_id, timeout):
            return ("complete", "variant said hi", None, now, now + timedelta(milliseconds=450))

        async def fake_tool_calls(corr_id):
            return [{"name": "web_search", "type": "local", "arguments": {"q": "x"},
                     "iteration": 1, "duration_ms": 12, "error": None}]

        async def fake_tokens(corr_id):
            return {"prompt": 120, "completion": 30, "total": 150}

        with patch("app.services.eval_evaluator._create_eval_task", side_effect=fake_create), \
             patch("app.services.eval_evaluator._await_eval_task", side_effect=fake_await), \
             patch("app.services.eval_evaluator._collect_tool_calls", side_effect=fake_tool_calls), \
             patch("app.services.eval_evaluator._sum_token_usage", side_effect=fake_tokens):
            cases = [{"input": "say hi"}]
            spec = {"bot_id": "sprout", "override": {"field": "system_prompt", "value": "Be polite."}}
            out = await run_evaluator("bot_invoke", cases, spec, parallelism=1, per_case_timeout=10)

        assert len(out) == 1
        cap = out[0]["captured"]
        assert out[0]["error"] is None
        assert cap["response_text"] == "variant said hi"
        assert cap["token_count"] == {"prompt": 120, "completion": 30, "total": 150}
        assert cap["latency_ms"] == 450  # from completed_at − created_at
        assert cap["task_id"] == str(t_id)
        assert cap["tool_calls"][0]["name"] == "web_search"

    @pytest.mark.asyncio
    async def test_failed_task_still_returns_captured_with_error(self):
        """When the child task fails, the evaluator surfaces captured context
        plus the error string — so rejection reasons can still reach the
        proposer via history.jsonl."""
        now = datetime.now(timezone.utc)
        t_id = uuid.uuid4()

        async def fake_create(**kwargs):
            return t_id

        async def fake_await(task_id, timeout):
            return ("failed", None, "LLM timeout", now, None)

        async def fake_tool_calls(corr_id):
            return []

        async def fake_tokens(corr_id):
            return {"prompt": 0, "completion": 0, "total": 0}

        with patch("app.services.eval_evaluator._create_eval_task", side_effect=fake_create), \
             patch("app.services.eval_evaluator._await_eval_task", side_effect=fake_await), \
             patch("app.services.eval_evaluator._collect_tool_calls", side_effect=fake_tool_calls), \
             patch("app.services.eval_evaluator._sum_token_usage", side_effect=fake_tokens):
            spec = {"bot_id": "x", "override": {"field": "system_prompt", "value": "v"}}
            out = await run_evaluator("bot_invoke", [{"input": "q"}], spec, parallelism=1, per_case_timeout=5)

        assert out[0]["error"] == "LLM timeout"
        assert out[0]["captured"]["response_text"] == ""

    @pytest.mark.asyncio
    async def test_parallelism_semaphore_caps_concurrency(self):
        """Fan-out respects the parallelism cap."""
        t_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fake_create(**kwargs):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1
            return t_id

        async def fake_await(task_id, timeout):
            return ("complete", "x", None, now, now + timedelta(milliseconds=1))

        async def fake_noop(*_a, **_k):
            return {"prompt": 0, "completion": 0, "total": 0}

        with patch("app.services.eval_evaluator._create_eval_task", side_effect=fake_create), \
             patch("app.services.eval_evaluator._await_eval_task", side_effect=fake_await), \
             patch("app.services.eval_evaluator._collect_tool_calls", return_value=[]), \
             patch("app.services.eval_evaluator._sum_token_usage", side_effect=fake_noop):
            spec = {"bot_id": "b", "override": {"field": "system_prompt", "value": "v"}}
            cases = [{"input": str(i)} for i in range(8)]
            out = await run_evaluator("bot_invoke", cases, spec, parallelism=2, per_case_timeout=5)

        assert len(out) == 8
        assert max_in_flight <= 2


class TestBotInvokeTaskCreation:
    """Round-trip through the real _create_eval_task using SQLite-in-memory so
    we verify the Task row is shaped correctly (pipeline_task_id for UI
    suppression, task_type='eval', system_prompt_override in execution_config).
    """

    @pytest.mark.asyncio
    async def test_creates_eval_task_with_expected_shape(self, patched_async_sessions):
        from app.db.models import Task
        from app.services.eval_evaluator import _create_eval_task
        from sqlalchemy import select

        parent_id = uuid.uuid4()
        corr_id = uuid.uuid4()
        task_id = await _create_eval_task(
            case={"input": "hello world"},
            bot_id="sprout",
            system_prompt_override="You are a test variant.",
            parent_task_id=parent_id,
            correlation_id=corr_id,
        )

        factory = patched_async_sessions
        async with factory() as db:
            t = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()

        assert t.task_type == "eval"
        assert t.status == "pending"
        assert t.channel_id is None
        assert t.session_id is None
        assert t.client_id == "eval"
        assert t.prompt == "hello world"
        assert t.callback_config == {"pipeline_task_id": str(parent_id)}
        assert t.execution_config == {"system_prompt_override": "You are a test variant."}
        assert t.correlation_id == corr_id
        assert t.parent_task_id == parent_id


class TestSystemPromptOverrideContextVar:
    """The override must flow through _effective_system_prompt when set."""

    def test_contextvar_replaces_effective_prompt(self, bot_registry):
        from app.agent.context import current_system_prompt_override
        from app.services.sessions import _effective_system_prompt

        bot = bot_registry.register("sprout", system_prompt="Normal prompt.")
        token = current_system_prompt_override.set("VARIANT PROMPT")
        try:
            out = _effective_system_prompt(bot)
            assert out == "VARIANT PROMPT"
        finally:
            current_system_prompt_override.reset(token)

    def test_without_override_returns_normal_prompt(self, bot_registry):
        from app.agent.context import current_system_prompt_override
        from app.services.sessions import _effective_system_prompt

        bot = bot_registry.register("sprout", system_prompt="Normal prompt.")
        # Ensure no override is set from a prior test
        assert current_system_prompt_override.get() is None
        out = _effective_system_prompt(bot)
        # Normal path includes bot.system_prompt somewhere in the assembled text.
        assert "Normal prompt." in out
        # Override text must not leak from another test
        assert "VARIANT PROMPT" not in out


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
