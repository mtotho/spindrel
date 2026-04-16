"""Unit tests for step_executor — shared condition/prompt/context functions
and pipeline execution logic."""
import copy
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.step_executor import (
    build_condition_context,
    evaluate_condition,
    render_prompt,
    _build_prior_results_preamble,
    _build_prior_results_env,
    _init_step_states,
)


# ---------------------------------------------------------------------------
# evaluate_condition
# ---------------------------------------------------------------------------

class TestEvaluateCondition:
    """Tests for the shared condition evaluator (used by both workflows and pipelines)."""

    def test_none_condition_is_true(self):
        assert evaluate_condition(None, {}) is True

    def test_empty_dict_is_true(self):
        assert evaluate_condition({}, {}) is True

    # -- Step conditions --

    def test_step_status_match(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "ok"}}, "params": {}}
        assert evaluate_condition({"step": "s1", "status": "done"}, ctx) is True

    def test_step_status_mismatch(self):
        ctx = {"steps": {"s1": {"status": "failed", "result": ""}}, "params": {}}
        assert evaluate_condition({"step": "s1", "status": "done"}, ctx) is False

    def test_step_missing(self):
        ctx = {"steps": {}, "params": {}}
        assert evaluate_condition({"step": "s1", "status": "done"}, ctx) is False

    def test_output_contains(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "All checks PASSED ok"}}, "params": {}}
        assert evaluate_condition({"step": "s1", "output_contains": "passed"}, ctx) is True

    def test_output_contains_case_insensitive(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "ERROR found"}}, "params": {}}
        assert evaluate_condition({"step": "s1", "output_contains": "error"}, ctx) is True

    def test_output_contains_missing(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "All good"}}, "params": {}}
        assert evaluate_condition({"step": "s1", "output_contains": "error"}, ctx) is False

    def test_output_not_contains(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "All good"}}, "params": {}}
        assert evaluate_condition({"step": "s1", "output_not_contains": "error"}, ctx) is True

    def test_output_not_contains_fails(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "ERROR found"}}, "params": {}}
        assert evaluate_condition({"step": "s1", "output_not_contains": "error"}, ctx) is False

    def test_output_contains_with_none_result(self):
        ctx = {"steps": {"s1": {"status": "done", "result": None}}, "params": {}}
        assert evaluate_condition({"step": "s1", "output_contains": "anything"}, ctx) is False

    def test_status_and_output_combined(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "SUCCESS"}}, "params": {}}
        assert evaluate_condition({"step": "s1", "status": "done", "output_contains": "success"}, ctx) is True
        assert evaluate_condition({"step": "s1", "status": "failed", "output_contains": "success"}, ctx) is False

    # -- Param conditions --

    def test_param_equals(self):
        ctx = {"steps": {}, "params": {"env": "production"}}
        assert evaluate_condition({"param": "env", "equals": "production"}, ctx) is True
        assert evaluate_condition({"param": "env", "equals": "staging"}, ctx) is False

    def test_param_exists(self):
        ctx = {"steps": {}, "params": {"env": "prod"}}
        assert evaluate_condition({"param": "env"}, ctx) is True
        assert evaluate_condition({"param": "missing"}, ctx) is False

    def test_param_exists_none_value(self):
        ctx = {"steps": {}, "params": {"key": None}}
        assert evaluate_condition({"param": "key"}, ctx) is False

    # -- Compound conditions --

    def test_all_compound(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "ok"}}, "params": {"env": "prod"}}
        cond = {"all": [
            {"step": "s1", "status": "done"},
            {"param": "env", "equals": "prod"},
        ]}
        assert evaluate_condition(cond, ctx) is True

    def test_all_compound_fails(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "ok"}}, "params": {"env": "staging"}}
        cond = {"all": [
            {"step": "s1", "status": "done"},
            {"param": "env", "equals": "prod"},
        ]}
        assert evaluate_condition(cond, ctx) is False

    def test_any_compound(self):
        ctx = {"steps": {"s1": {"status": "failed", "result": ""}}, "params": {"env": "prod"}}
        cond = {"any": [
            {"step": "s1", "status": "done"},
            {"param": "env", "equals": "prod"},
        ]}
        assert evaluate_condition(cond, ctx) is True

    def test_any_compound_all_false(self):
        ctx = {"steps": {"s1": {"status": "failed", "result": ""}}, "params": {"env": "staging"}}
        cond = {"any": [
            {"step": "s1", "status": "done"},
            {"param": "env", "equals": "prod"},
        ]}
        assert evaluate_condition(cond, ctx) is False

    def test_not_compound(self):
        ctx = {"steps": {"s1": {"status": "failed", "result": ""}}, "params": {}}
        assert evaluate_condition({"not": {"step": "s1", "status": "done"}}, ctx) is True
        assert evaluate_condition({"not": {"step": "s1", "status": "failed"}}, ctx) is False

    def test_nested_compound(self):
        ctx = {"steps": {"s1": {"status": "done", "result": "ok"}}, "params": {"env": "prod"}}
        cond = {"all": [
            {"not": {"step": "s1", "status": "failed"}},
            {"any": [
                {"param": "env", "equals": "prod"},
                {"param": "env", "equals": "staging"},
            ]},
        ]}
        assert evaluate_condition(cond, ctx) is True

    def test_unrecognized_keys_return_false(self):
        assert evaluate_condition({"unknown_key": "value"}, {"steps": {}, "params": {}}) is False


# ---------------------------------------------------------------------------
# render_prompt
# ---------------------------------------------------------------------------

class TestRenderPrompt:
    """Tests for template substitution in step prompts."""

    def test_param_substitution(self):
        result = render_prompt("Hello {{name}}", {"name": "World"}, [], [])
        assert result == "Hello World"

    def test_step_result_by_id(self):
        steps = [{"id": "check", "type": "exec"}]
        states = [{"status": "done", "result": "healthy"}]
        result = render_prompt("Status: {{steps.check.result}}", {}, states, steps)
        assert result == "Status: healthy"

    def test_step_status_by_id(self):
        steps = [{"id": "check", "type": "exec"}]
        states = [{"status": "failed", "result": "err"}]
        result = render_prompt("Was: {{steps.check.status}}", {}, states, steps)
        assert result == "Was: failed"

    def test_step_result_by_index(self):
        steps = [{"id": "s0", "type": "exec"}, {"id": "s1", "type": "exec"}]
        states = [
            {"status": "done", "result": "first"},
            {"status": "done", "result": "second"},
        ]
        result = render_prompt("{{steps.0.result}} then {{steps.1.result}}", {}, states, steps)
        assert result == "first then second"

    def test_unresolved_template_preserved(self):
        result = render_prompt("{{unknown_var}}", {}, [], [])
        assert result == "{{unknown_var}}"

    def test_unresolved_step_reference(self):
        result = render_prompt("{{steps.missing.result}}", {}, [], [])
        assert result == "{{steps.missing.result}}"

    def test_mixed_params_and_steps(self):
        steps = [{"id": "fetch", "type": "tool"}]
        states = [{"status": "done", "result": "42"}]
        result = render_prompt(
            "For {{env}}: got {{steps.fetch.result}}",
            {"env": "prod"},
            states,
            steps,
        )
        assert result == "For prod: got 42"

    def test_none_result_preserves_template(self):
        steps = [{"id": "s0", "type": "exec"}]
        states = [{"status": "pending", "result": None}]
        result = render_prompt("{{steps.s0.result}}", {}, states, steps)
        assert result == "{{steps.s0.result}}"

    def test_auto_generated_step_id(self):
        """Steps without explicit id get step_N ids."""
        steps = [{"type": "exec"}, {"type": "exec"}]
        states = [
            {"status": "done", "result": "a"},
            {"status": "done", "result": "b"},
        ]
        result = render_prompt("{{steps.step_0.result}}", {}, states, steps)
        assert result == "a"

    def test_incomplete_step_ref(self):
        """steps.id without a field is preserved."""
        result = render_prompt("{{steps.check}}", {}, [], [])
        assert result == "{{steps.check}}"


# ---------------------------------------------------------------------------
# build_condition_context
# ---------------------------------------------------------------------------

class TestBuildConditionContext:
    def test_basic(self):
        steps = [{"id": "s0", "type": "exec"}, {"id": "s1", "type": "tool"}]
        states = [
            {"status": "done", "result": "ok"},
            {"status": "pending", "result": None},
        ]
        ctx = build_condition_context(steps, states, {"env": "prod"})
        assert ctx == {
            "steps": {
                "s0": {"status": "done", "result": "ok"},
                "s1": {"status": "pending", "result": None},
            },
            "params": {"env": "prod"},
        }

    def test_auto_id_generation(self):
        steps = [{"type": "exec"}]
        states = [{"status": "done", "result": "x"}]
        ctx = build_condition_context(steps, states)
        assert "step_0" in ctx["steps"]

    def test_more_steps_than_states(self):
        """If step_states hasn't been initialized for all steps yet."""
        steps = [{"id": "a", "type": "exec"}, {"id": "b", "type": "exec"}]
        states = [{"status": "done", "result": "ok"}]  # only 1 state
        ctx = build_condition_context(steps, states)
        assert "a" in ctx["steps"]
        assert "b" not in ctx["steps"]

    def test_no_params(self):
        ctx = build_condition_context([], [])
        assert ctx == {"steps": {}, "params": {}}


# ---------------------------------------------------------------------------
# _build_prior_results_preamble
# ---------------------------------------------------------------------------

class TestBuildPriorResultsPreamble:
    def test_no_prior_steps(self):
        assert _build_prior_results_preamble([], [], 0) == ""

    def test_single_done_step(self):
        steps = [{"id": "s0", "type": "exec", "label": "Check disk"}]
        states = [{"status": "done", "result": "80% free"}]
        result = _build_prior_results_preamble(steps, states, 1)
        assert "Previous step results:" in result
        assert "Check disk" in result
        assert "80% free" in result

    def test_skips_pending(self):
        steps = [{"id": "s0", "type": "exec", "label": "A"}]
        states = [{"status": "pending", "result": None}]
        assert _build_prior_results_preamble(steps, states, 1) == ""

    def test_includes_failed(self):
        steps = [{"id": "s0", "type": "exec", "label": "Check"}]
        states = [{"status": "failed", "result": "timeout"}]
        result = _build_prior_results_preamble(steps, states, 1)
        assert "failed" in result

    def test_truncates_long_results(self):
        steps = [{"id": "s0", "type": "exec", "label": "A"}]
        states = [{"status": "done", "result": "x" * 5000}]
        result = _build_prior_results_preamble(steps, states, 1)
        assert "truncated" in result
        assert len(result) < 5000

    def test_only_includes_steps_before_current_index(self):
        steps = [
            {"id": "s0", "type": "exec", "label": "A"},
            {"id": "s1", "type": "exec", "label": "B"},
        ]
        states = [
            {"status": "done", "result": "first"},
            {"status": "done", "result": "second"},
        ]
        # current_index=1 should only include s0
        result = _build_prior_results_preamble(steps, states, 1)
        assert "A" in result
        assert "B" not in result


# ---------------------------------------------------------------------------
# _build_prior_results_env
# ---------------------------------------------------------------------------

class TestBuildPriorResultsEnv:
    def test_no_prior_steps(self):
        assert _build_prior_results_env([], [], 0) == {}

    def test_env_vars_by_index_and_id(self):
        steps = [{"id": "check_disk", "type": "exec"}]
        states = [{"status": "done", "result": "80%"}]
        env = _build_prior_results_env(steps, states, 1)
        # 1-based index to match UI numbering
        assert env["STEP_1_RESULT"] == "80%"
        assert env["STEP_1_STATUS"] == "done"
        assert env["STEP_CHECK_DISK_RESULT"] == "80%"
        assert env["STEP_CHECK_DISK_STATUS"] == "done"

    def test_skips_pending(self):
        steps = [{"id": "s0", "type": "exec"}]
        states = [{"status": "pending", "result": None}]
        assert _build_prior_results_env(steps, states, 1) == {}

    def test_sanitizes_special_chars(self):
        steps = [{"id": "my-step.v2", "type": "exec"}]
        states = [{"status": "done", "result": "ok"}]
        env = _build_prior_results_env(steps, states, 1)
        assert "STEP_MY_STEP_V2_RESULT" in env

    def test_truncates_long_results(self):
        steps = [{"id": "s0", "type": "exec"}]
        states = [{"status": "done", "result": "x" * 10000}]
        env = _build_prior_results_env(steps, states, 1)
        assert len(env["STEP_1_RESULT"]) == 4000


# ---------------------------------------------------------------------------
# _init_step_states
# ---------------------------------------------------------------------------

class TestInitStepStates:
    def test_creates_pending_states(self):
        steps = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        states = _init_step_states(steps)
        assert len(states) == 3
        for s in states:
            assert s["status"] == "pending"
            assert s["result"] is None
            assert s["error"] is None
            assert s["task_id"] is None

    def test_empty_steps(self):
        assert _init_step_states([]) == []


# ---------------------------------------------------------------------------
# Pipeline execution — run_task_pipeline
# ---------------------------------------------------------------------------

def _make_db_ctx():
    """Create a mock async_session context manager for pipeline tests."""
    mock_db = AsyncMock()
    mock_record = MagicMock()
    mock_db.get = AsyncMock(return_value=mock_record)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.refresh = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, mock_db, mock_record


def _make_task(**overrides):
    """Create a mock pipeline task."""
    task = MagicMock()
    task.id = uuid.uuid4()
    task.bot_id = "test-bot"
    task.channel_id = None
    task.session_id = None
    task.dispatch_type = "none"
    task.dispatch_config = {}
    task.step_states = None
    for k, v in overrides.items():
        setattr(task, k, v)
    return task


class TestRunTaskPipeline:
    """Integration-style tests for the full pipeline runner."""

    @pytest.mark.asyncio
    async def test_empty_pipeline_fails(self):
        from app.services.step_executor import run_task_pipeline

        ctx, _, mock_record = _make_db_ctx()
        task = _make_task(steps=[])

        with patch("app.services.step_executor.async_session", return_value=ctx):
            await run_task_pipeline(task)

        assert mock_record.status == "failed"

    @pytest.mark.asyncio
    async def test_single_exec_step_success(self):
        from app.services.step_executor import run_task_pipeline

        ctx, _, mock_record = _make_db_ctx()
        task = _make_task(steps=[{"id": "s0", "type": "exec", "prompt": "echo hello"}])

        with (
            patch("app.services.step_executor.async_session", return_value=ctx),
            patch("app.services.step_executor._run_exec_step", new_callable=AsyncMock, return_value=("done", "output", None)) as mock_exec,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock),
        ):
            await run_task_pipeline(task)

        mock_exec.assert_called_once()
        assert mock_record.status == "complete"

    @pytest.mark.asyncio
    async def test_exec_step_failure_aborts(self):
        from app.services.step_executor import run_task_pipeline

        ctx, _, mock_record = _make_db_ctx()
        task = _make_task(steps=[
            {"id": "s0", "type": "exec", "prompt": "bad_cmd", "on_failure": "abort"},
            {"id": "s1", "type": "exec", "prompt": "echo after"},
        ])

        with (
            patch("app.services.step_executor.async_session", return_value=ctx),
            patch("app.services.step_executor._run_exec_step", new_callable=AsyncMock, return_value=("failed", None, "not found")) as mock_exec,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock),
        ):
            await run_task_pipeline(task)

        assert mock_exec.call_count == 1
        assert mock_record.status == "failed"

    @pytest.mark.asyncio
    async def test_exec_step_failure_continue(self):
        from app.services.step_executor import run_task_pipeline

        ctx, _, mock_record = _make_db_ctx()
        task = _make_task(steps=[
            {"id": "s0", "type": "exec", "prompt": "bad_cmd", "on_failure": "continue"},
            {"id": "s1", "type": "exec", "prompt": "echo ok"},
        ])

        with (
            patch("app.services.step_executor.async_session", return_value=ctx),
            patch("app.services.step_executor._run_exec_step", new_callable=AsyncMock, side_effect=[
                ("failed", "error", "exit 1"),
                ("done", "ok", None),
            ]) as mock_exec,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock),
        ):
            await run_task_pipeline(task)

        assert mock_exec.call_count == 2
        assert mock_record.status == "failed"  # any step failed → pipeline failed

    @pytest.mark.asyncio
    async def test_tool_step_success(self):
        from app.services.step_executor import run_task_pipeline

        ctx, _, mock_record = _make_db_ctx()
        task = _make_task(steps=[{"id": "s0", "type": "tool", "tool_name": "search", "tool_args": {"q": "test"}}])

        with (
            patch("app.services.step_executor.async_session", return_value=ctx),
            patch("app.services.step_executor._run_tool_step", new_callable=AsyncMock, return_value=("done", '{"ok":true}', None)) as mock_tool,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock),
        ):
            await run_task_pipeline(task)

        mock_tool.assert_called_once()
        assert mock_record.status == "complete"

    @pytest.mark.asyncio
    async def test_condition_skips_step(self):
        from app.services.step_executor import run_task_pipeline

        ctx, _, mock_record = _make_db_ctx()
        task = _make_task(steps=[
            {"id": "check", "type": "exec", "prompt": "echo healthy"},
            {"id": "alert", "type": "exec", "prompt": "send-alert",
             "when": {"step": "check", "output_contains": "unhealthy"}},
        ])

        with (
            patch("app.services.step_executor.async_session", return_value=ctx),
            patch("app.services.step_executor._run_exec_step", new_callable=AsyncMock, return_value=("done", "healthy", None)) as mock_exec,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock),
        ):
            await run_task_pipeline(task)

        assert mock_exec.call_count == 1  # second step skipped
        assert mock_record.status == "complete"

    @pytest.mark.asyncio
    async def test_multi_step_sequential(self):
        from app.services.step_executor import run_task_pipeline

        ctx, _, mock_record = _make_db_ctx()
        task = _make_task(steps=[
            {"id": "s0", "type": "exec", "prompt": "cmd1"},
            {"id": "s1", "type": "exec", "prompt": "cmd2"},
            {"id": "s2", "type": "exec", "prompt": "cmd3"},
        ])

        with (
            patch("app.services.step_executor.async_session", return_value=ctx),
            patch("app.services.step_executor._run_exec_step", new_callable=AsyncMock, side_effect=[
                ("done", "1", None), ("done", "2", None), ("done", "3", None),
            ]) as mock_exec,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock),
        ):
            await run_task_pipeline(task)

        assert mock_exec.call_count == 3
        assert mock_record.status == "complete"

    @pytest.mark.asyncio
    async def test_unknown_step_type_fails(self):
        from app.services.step_executor import run_task_pipeline

        ctx, _, mock_record = _make_db_ctx()
        task = _make_task(steps=[{"id": "s0", "type": "unknown_type", "prompt": "???"}])

        with (
            patch("app.services.step_executor.async_session", return_value=ctx),
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock),
        ):
            await run_task_pipeline(task)

        assert mock_record.status == "failed"


# ---------------------------------------------------------------------------
# Agent step spawning
# ---------------------------------------------------------------------------

class TestSpawnAgentStep:

    @pytest.mark.asyncio
    @patch("app.services.step_executor.async_session")
    async def test_creates_child_task(self, mock_session_factory):
        from app.services.step_executor import _spawn_agent_step

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = ctx

        parent = MagicMock()
        parent.id = uuid.uuid4()
        parent.bot_id = "test-bot"
        parent.channel_id = "ch1"
        parent.session_id = "sess1"
        parent.dispatch_type = "channel"
        parent.dispatch_config = {"channel_id": "ch1"}

        step_def = {"id": "llm_step", "type": "agent", "prompt": "Summarize: {{steps.s0.result}}"}
        steps = [{"id": "s0", "type": "exec"}, step_def]
        step_states = [
            {"status": "done", "result": "raw data here", "error": None, "started_at": None, "completed_at": None, "task_id": None},
            {"status": "running", "result": None, "error": None, "started_at": None, "completed_at": None, "task_id": None},
        ]

        await _spawn_agent_step(parent, step_def, 1, steps, step_states)

        # A child task should have been added to the session
        mock_db.add.assert_called_once()
        child = mock_db.add.call_args[0][0]
        assert child.bot_id == "test-bot"
        assert child.prompt == "Summarize: raw data here"  # template rendered
        assert child.callback_config["pipeline_task_id"] == str(parent.id)
        assert child.callback_config["pipeline_step_index"] == 1


# ---------------------------------------------------------------------------
# on_pipeline_step_completed
# ---------------------------------------------------------------------------

class TestOnPipelineStepCompleted:

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_resumes_pipeline_on_success(self, mock_session_factory, mock_persist, mock_finalize, mock_advance):
        from app.services.step_executor import on_pipeline_step_completed

        parent = MagicMock()
        parent.id = uuid.uuid4()
        parent.steps = [
            {"id": "s0", "type": "agent", "prompt": "do something"},
            {"id": "s1", "type": "exec", "prompt": "echo done"},
        ]
        parent.step_states = [
            {"status": "running", "result": None, "error": None, "started_at": None, "completed_at": None, "task_id": "child-1"},
            {"status": "pending", "result": None, "error": None, "started_at": None, "completed_at": None, "task_id": None},
        ]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=parent)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = ctx

        child = MagicMock()
        child.result = "Agent said hello"
        child.error = None

        await on_pipeline_step_completed(str(parent.id), 0, "complete", child)

        mock_persist.assert_called_once()
        mock_advance.assert_called_once()
        # Should resume from step 1
        assert mock_advance.call_args[1].get("start_index", mock_advance.call_args[0][3] if len(mock_advance.call_args[0]) > 3 else None) == 1

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_aborts_on_failed_step(self, mock_session_factory, mock_persist, mock_finalize, mock_advance):
        from app.services.step_executor import on_pipeline_step_completed

        parent = MagicMock()
        parent.id = uuid.uuid4()
        parent.steps = [
            {"id": "s0", "type": "agent", "prompt": "do something", "on_failure": "abort"},
        ]
        parent.step_states = [
            {"status": "running", "result": None, "error": None, "started_at": None, "completed_at": None, "task_id": "child-1"},
        ]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=parent)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = ctx

        child = MagicMock()
        child.result = None
        child.error = "LLM error"

        await on_pipeline_step_completed(str(parent.id), 0, "failed", child)

        mock_persist.assert_called_once()
        mock_finalize.assert_called_once()
        mock_advance.assert_not_called()
