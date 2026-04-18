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
    _parse_result_json,
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
        # 1-based indexing to match UI numbering
        result = render_prompt("{{steps.1.result}} then {{steps.2.result}}", {}, states, steps)
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

    def test_zero_based_index_no_longer_works(self):
        """0-based indexing was removed to prevent collision with 1-based."""
        steps = [{"id": "s0", "type": "exec"}, {"id": "s1", "type": "exec"}]
        states = [
            {"status": "done", "result": "first"},
            {"status": "done", "result": "second"},
        ]
        # {{steps.0.result}} is unresolved since we only support 1-based
        result = render_prompt("{{steps.0.result}}", {}, states, steps)
        assert result == "{{steps.0.result}}"

    def test_1_based_does_not_collide_with_second_step(self):
        """Regression: 0-based str(1) for step 2 used to overwrite 1-based str(1) for step 1."""
        steps = [{"id": "a", "type": "exec"}, {"id": "b", "type": "exec"}]
        states = [
            {"status": "done", "result": "FIRST"},
            {"status": "running", "result": None},
        ]
        # {{steps.1.result}} must resolve to the first step, not the running second step
        result = render_prompt("{{steps.1.result}}", {}, states, steps)
        assert result == "FIRST"

    def test_shell_escape_quotes_values(self):
        """shell_escape=True wraps substituted values in single quotes."""
        steps = [{"id": "s", "type": "tool"}]
        states = [{"status": "done", "result": '{"key": "value"}'}]
        result = render_prompt("echo {{steps.1.result}}", {}, states, steps, shell_escape=True)
        assert result == """echo '{"key": "value"}'"""

    def test_shell_escape_handles_single_quotes_in_value(self):
        """Single quotes in the value are escaped properly."""
        steps = [{"id": "s", "type": "exec"}]
        states = [{"status": "done", "result": "it's working"}]
        result = render_prompt("echo {{steps.1.result}}", {}, states, steps, shell_escape=True)
        assert result == "echo 'it'\\''s working'"

    def test_shell_escape_multiline(self):
        """Multiline results are safely quoted for shell."""
        steps = [{"id": "s", "type": "tool"}]
        states = [{"status": "done", "result": "line1\nline2\nline3"}]
        result = render_prompt("echo {{steps.1.result}}", {}, states, steps, shell_escape=True)
        assert result == "echo 'line1\nline2\nline3'"

    def test_shell_escape_preserves_unresolved(self):
        """Unresolved templates are not shell-escaped."""
        result = render_prompt("echo {{steps.99.result}}", {}, [], [], shell_escape=True)
        assert result == "echo {{steps.99.result}}"

    def test_shell_escape_params(self):
        """Params are also shell-escaped when flag is set."""
        result = render_prompt("echo {{name}}", {"name": 'hello "world"'}, [], [], shell_escape=True)
        assert result == """echo 'hello "world"'"""

    def test_json_field_access(self):
        """{{steps.1.result.key}} extracts a JSON field from the result."""
        steps = [{"id": "s", "type": "tool"}]
        states = [{"status": "done", "result": '{"count": 30, "summary": "all good"}'}]
        result = render_prompt("Got {{steps.1.result.count}} items: {{steps.1.result.summary}}", {}, states, steps)
        assert result == "Got 30 items: all good"

    def test_json_field_nested(self):
        """Dotted access drills into nested JSON."""
        steps = [{"id": "s", "type": "tool"}]
        states = [{"status": "done", "result": '{"data": {"name": "test"}}'}]
        result = render_prompt("{{steps.1.result.data.name}}", {}, states, steps)
        assert result == "test"

    def test_json_field_missing_key_unresolved(self):
        """Missing JSON key leaves template unresolved."""
        steps = [{"id": "s", "type": "tool"}]
        states = [{"status": "done", "result": '{"count": 30}'}]
        result = render_prompt("{{steps.1.result.missing}}", {}, states, steps)
        assert result == "{{steps.1.result.missing}}"

    def test_json_field_on_non_json_unresolved(self):
        """Field access on non-JSON result leaves template unresolved."""
        steps = [{"id": "s", "type": "exec"}]
        states = [{"status": "done", "result": "plain text output"}]
        result = render_prompt("{{steps.1.result.key}}", {}, states, steps)
        assert result == "{{steps.1.result.key}}"

    def test_json_field_returns_object_as_json(self):
        """If the extracted value is a dict/list, it's serialized as JSON."""
        steps = [{"id": "s", "type": "tool"}]
        states = [{"status": "done", "result": '{"items": [1, 2, 3]}'}]
        result = render_prompt("{{steps.1.result.items}}", {}, states, steps)
        assert result == "[1, 2, 3]"

    def test_json_field_shell_escaped(self):
        """JSON field values are shell-escaped when flag is set."""
        steps = [{"id": "s", "type": "tool"}]
        states = [{"status": "done", "result": '{"msg": "hello \'world\'"}'}]
        result = render_prompt("echo {{steps.1.result.msg}}", {}, states, steps, shell_escape=True)
        assert result == "echo 'hello '\\''world'\\'''"


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

    def test_json_fields_extracted(self):
        """JSON result keys are auto-extracted as individual env vars."""
        steps = [{"id": "s", "type": "tool"}]
        states = [{"status": "done", "result": '{"count": 30, "summary": "all good"}'}]
        env = _build_prior_results_env(steps, states, 1)
        assert env["STEP_1_count"] == "30"
        assert env["STEP_1_summary"] == "all good"
        # Full result still available
        assert "count" in env["STEP_1_RESULT"]

    def test_json_nested_value_serialized(self):
        """Nested JSON values are serialized as JSON strings."""
        steps = [{"id": "s", "type": "tool"}]
        states = [{"status": "done", "result": '{"data": {"a": 1}}'}]
        env = _build_prior_results_env(steps, states, 1)
        assert env["STEP_1_data"] == '{"a": 1}'

    def test_non_json_result_no_extra_keys(self):
        """Plain text results don't generate extra env vars."""
        steps = [{"id": "s", "type": "exec"}]
        states = [{"status": "done", "result": "just text"}]
        env = _build_prior_results_env(steps, states, 1)
        assert "STEP_1_RESULT" in env
        # No extra keys beyond RESULT, STATUS, and id-based variants
        json_keys = [k for k in env if not k.endswith("_RESULT") and not k.endswith("_STATUS")]
        assert json_keys == []


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

    @pytest.mark.asyncio
    @patch("app.services.step_executor.async_session")
    async def test_forwards_skills_tools_carapaces_to_execution_config(self, mock_session_factory):
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
        parent.dispatch_type = "none"
        parent.dispatch_config = {}

        step_def = {
            "id": "analyze",
            "type": "agent",
            "prompt": "analyze",
            "tools": ["web_search"],
            "carapaces": ["researcher"],
            "skills": ["pipeline_authoring"],
        }
        steps = [step_def]
        step_states = [
            {"status": "running", "result": None, "error": None, "started_at": None, "completed_at": None, "task_id": None},
        ]

        await _spawn_agent_step(parent, step_def, 0, steps, step_states)

        child = mock_db.add.call_args[0][0]
        assert child.execution_config["tools"] == ["web_search"]
        assert child.execution_config["carapaces"] == ["researcher"]
        assert child.execution_config["skills"] == ["pipeline_authoring"]


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


# ---------------------------------------------------------------------------
# Shell script integration tests — actually run commands through sh
#
# These catch the class of bugs where templates render correctly as strings
# but break when the shell interprets them (quoting, backticks, newlines, etc.)
# ---------------------------------------------------------------------------

import asyncio
import shlex
import re as _re


def _build_pipeline_script(
    command: str,
    prior_steps: list[dict],
    prior_states: list[dict],
    step_index: int | None = None,
) -> str:
    """Build the exact script that _run_exec_step would produce, minus bot/workspace.

    Returns the full shell script string including env var exports.
    """
    if step_index is None:
        step_index = len(prior_steps)

    all_steps = prior_steps + [{"id": f"step_{step_index}", "type": "exec"}]
    all_states = prior_states + [{"status": "running", "result": None}]

    rendered = render_prompt(command, {}, all_states, all_steps, shell_escape=True)

    # Build script without shlex.join (matching _run_exec_step)
    script = rendered

    # Add env var exports (matching _run_exec_step)
    env_vars = _build_prior_results_env(all_steps, all_states, step_index)
    if env_vars:
        def _sq(v: str) -> str:
            return "'" + v.replace("'", "'\\''") + "'"
        exports = "\n".join(f'export {k}={_sq(v)}' for k, v in env_vars.items())
        script = exports + "\n" + script

    return script


async def _run_shell(script: str) -> tuple[int, str, str]:
    """Run a script through sh and return (exit_code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "sh", "-c", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
    return proc.returncode or 0, stdout.decode(), stderr.decode()


class TestShellScriptIntegration:
    """Tests that actually execute the generated scripts through sh.

    These catch bugs that unit tests miss: quoting, backticks, newlines,
    variable expansion, and shlex double-quoting.
    """

    @pytest.mark.asyncio
    async def test_simple_echo(self):
        """Basic command runs without error."""
        script = _build_pipeline_script("echo hello", [], [])
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert stdout.strip() == "hello"

    @pytest.mark.asyncio
    async def test_env_var_simple_result(self):
        """$STEP_1_RESULT works for plain text results."""
        prior_steps = [{"id": "s1", "type": "exec"}]
        prior_states = [{"status": "done", "result": "file1.txt file2.txt"}]
        script = _build_pipeline_script('echo "$STEP_1_RESULT"', prior_steps, prior_states)
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert "file1.txt file2.txt" in stdout

    @pytest.mark.asyncio
    async def test_env_var_with_backticks(self):
        """Backticks in results don't trigger command substitution."""
        result_with_backticks = "- `abc123` Fix bug\n- `def456` Add feature"
        prior_steps = [{"id": "s1", "type": "exec"}]
        prior_states = [{"status": "done", "result": result_with_backticks}]
        script = _build_pipeline_script('echo "$STEP_1_RESULT"', prior_steps, prior_states)
        code, stdout, stderr = await _run_shell(script)
        assert code == 0
        assert "abc123" in stdout
        assert "not found" not in stderr

    @pytest.mark.asyncio
    async def test_env_var_with_dollar_signs(self):
        """Dollar signs in results don't trigger variable expansion."""
        result = "price is $100 and $PATH should not expand"
        prior_steps = [{"id": "s1", "type": "exec"}]
        prior_states = [{"status": "done", "result": result}]
        script = _build_pipeline_script('echo "$STEP_1_RESULT"', prior_steps, prior_states)
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert "$100" in stdout

    @pytest.mark.asyncio
    async def test_env_var_with_single_quotes(self):
        """Single quotes in results are properly escaped."""
        result = "it's a test with 'quotes'"
        prior_steps = [{"id": "s1", "type": "exec"}]
        prior_states = [{"status": "done", "result": result}]
        script = _build_pipeline_script('echo "$STEP_1_RESULT"', prior_steps, prior_states)
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert "it's a test" in stdout

    @pytest.mark.asyncio
    async def test_env_var_multiline_result(self):
        """Multiline results are preserved in env vars."""
        result = "line1\nline2\nline3"
        prior_steps = [{"id": "s1", "type": "exec"}]
        prior_states = [{"status": "done", "result": result}]
        script = _build_pipeline_script('echo "$STEP_1_RESULT"', prior_steps, prior_states)
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert "line1" in stdout
        assert "line3" in stdout

    @pytest.mark.asyncio
    async def test_env_var_json_result(self):
        """JSON results with special chars work in env vars."""
        result = '{"llm": "30 commit(s):\\n- `abc` Fix\\n- `def` Add", "count": 30}'
        prior_steps = [{"id": "s1", "type": "tool"}]
        prior_states = [{"status": "done", "result": result}]
        script = _build_pipeline_script('echo "$STEP_1_RESULT"', prior_steps, prior_states)
        code, stdout, stderr = await _run_shell(script)
        assert code == 0
        assert "not found" not in stderr

    @pytest.mark.asyncio
    async def test_env_var_json_field_extraction(self):
        """Auto-extracted JSON fields are available as env vars."""
        result = '{"count": 42, "status": "ok"}'
        prior_steps = [{"id": "s1", "type": "tool"}]
        prior_states = [{"status": "done", "result": result}]
        script = _build_pipeline_script('echo "$STEP_1_count"', prior_steps, prior_states)
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert stdout.strip() == "42"

    @pytest.mark.asyncio
    async def test_template_substitution_in_shell(self):
        """{{steps.1.result}} renders and executes correctly in shell."""
        prior_steps = [{"id": "s1", "type": "exec"}]
        prior_states = [{"status": "done", "result": "hello world"}]
        script = _build_pipeline_script("echo {{steps.1.result}}", prior_steps, prior_states)
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert "hello world" in stdout

    @pytest.mark.asyncio
    async def test_template_substitution_with_special_chars(self):
        """{{steps.1.result}} with backticks and quotes is shell-safe."""
        result = '`commit1` said "hello $USER"'
        prior_steps = [{"id": "s1", "type": "exec"}]
        prior_states = [{"status": "done", "result": result}]
        script = _build_pipeline_script("echo {{steps.1.result}}", prior_steps, prior_states)
        code, stdout, stderr = await _run_shell(script)
        assert code == 0
        assert "commit1" in stdout
        assert "not found" not in stderr

    @pytest.mark.asyncio
    async def test_template_json_field_in_shell(self):
        """{{steps.1.result.key}} JSON field extraction works in shell."""
        result = '{"message": "deploy complete", "version": "1.2.3"}'
        prior_steps = [{"id": "s1", "type": "tool"}]
        prior_states = [{"status": "done", "result": result}]
        script = _build_pipeline_script("echo {{steps.1.result.version}}", prior_steps, prior_states)
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert "1.2.3" in stdout

    @pytest.mark.asyncio
    async def test_command_not_re_quoted(self):
        """Multi-word commands like 'echo hello' are not re-quoted into a single token."""
        script = _build_pipeline_script("echo hello world", [], [])
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert "hello world" in stdout

    @pytest.mark.asyncio
    async def test_pipe_between_commands(self):
        """Shell pipes work in step commands."""
        script = _build_pipeline_script("echo 'a b c' | wc -w", [], [])
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert stdout.strip() == "3"

    @pytest.mark.asyncio
    async def test_chained_steps_env_vars(self):
        """Step 2 can use step 1's result, step 3 can use both."""
        s1_result = "alpha"
        s2_result = "beta"
        prior_steps = [
            {"id": "s1", "type": "exec"},
            {"id": "s2", "type": "exec"},
        ]
        prior_states = [
            {"status": "done", "result": s1_result},
            {"status": "done", "result": s2_result},
        ]
        script = _build_pipeline_script(
            'echo "$STEP_1_RESULT $STEP_2_RESULT"',
            prior_steps, prior_states, step_index=2,
        )
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert "alpha beta" in stdout

    @pytest.mark.asyncio
    async def test_trailing_whitespace_stripped(self):
        """Trailing whitespace in command doesn't break execution."""
        script = _build_pipeline_script("echo hello   ", [], [])
        code, stdout, _ = await _run_shell(script)
        assert code == 0
        assert "hello" in stdout


# ---------------------------------------------------------------------------
# Phase 5: step failure signaling (tool-error detection + fail_if)
# ---------------------------------------------------------------------------


class TestDetectErrorPayload:
    """_detect_error_payload: flag tool results whose JSON has a non-null error."""

    def test_non_json_passes_through(self):
        from app.services.step_executor import _detect_error_payload
        assert _detect_error_payload("not json at all") is None

    def test_plain_string(self):
        from app.services.step_executor import _detect_error_payload
        assert _detect_error_payload('{"result": "ok"}') is None

    def test_error_null_is_success(self):
        from app.services.step_executor import _detect_error_payload
        # Tools that always include an `error` key with null for success
        # must NOT be flagged as failed.
        assert _detect_error_payload('{"error": null, "data": [1,2]}') is None

    def test_error_empty_string_is_success(self):
        from app.services.step_executor import _detect_error_payload
        assert _detect_error_payload('{"error": "", "data": "x"}') is None

    def test_error_string_is_failure(self):
        from app.services.step_executor import _detect_error_payload
        assert _detect_error_payload('{"error": "TypeError: x"}') == "TypeError: x"

    def test_error_object_is_failure(self):
        from app.services.step_executor import _detect_error_payload
        # Non-string error values get JSON-serialized.
        out = _detect_error_payload('{"error": {"code": 500, "msg": "boom"}}')
        assert out is not None
        assert "boom" in out

    def test_non_dict_json(self):
        from app.services.step_executor import _detect_error_payload
        assert _detect_error_payload('[1, 2, 3]') is None
        assert _detect_error_payload('"plain string"') is None


class TestEvaluateFailIf:
    """_evaluate_fail_if — post-completion fail predicate on a step."""

    def _task_stub(self):
        t = MagicMock()
        t.execution_config = None
        return t

    def test_no_fail_if_is_pass(self):
        from app.services.step_executor import _evaluate_fail_if
        step_def = {"id": "s1", "type": "tool"}
        should_fail, _reason = _evaluate_fail_if(step_def, 0, [step_def], [{"status": "done", "result": "ok"}], self._task_stub())
        assert should_fail is False

    def test_result_empty_keys_triggers_fail(self):
        from app.services.step_executor import _evaluate_fail_if
        step_def = {
            "id": "analyze", "type": "agent",
            "fail_if": {"result_empty_keys": ["proposals"]},
        }
        states = [{"status": "done", "result": json.dumps({"proposals": []})}]
        should_fail, reason = _evaluate_fail_if(step_def, 0, [step_def], states, self._task_stub())
        assert should_fail is True
        assert "proposals" in (reason or "")

    def test_result_empty_keys_passes_when_populated(self):
        from app.services.step_executor import _evaluate_fail_if
        step_def = {
            "id": "analyze", "type": "agent",
            "fail_if": {"result_empty_keys": ["proposals"]},
        }
        states = [{"status": "done", "result": json.dumps({"proposals": [{"id": "x"}]})}]
        should_fail, _ = _evaluate_fail_if(step_def, 0, [step_def], states, self._task_stub())
        assert should_fail is False

    def test_implicit_self_step_for_output_contains(self):
        """fail_if: {output_contains: "unable to"} with no `step:` defaults to current step."""
        from app.services.step_executor import _evaluate_fail_if
        step_def = {
            "id": "analyze", "type": "agent",
            "fail_if": {"output_contains": "unable to"},
        }
        states = [{"status": "done", "result": "I was unable to analyze the data"}]
        should_fail, _ = _evaluate_fail_if(step_def, 0, [step_def], states, self._task_stub())
        assert should_fail is True


class TestApplyFailIfToState:
    """_apply_fail_if_to_state — mutates step state on failure."""

    def test_flips_done_to_failed_on_match(self):
        from app.services.step_executor import _apply_fail_if_to_state
        step_def = {
            "id": "s1", "type": "agent",
            "fail_if": {"result_empty_keys": ["proposals"]},
        }
        state = {"status": "done", "result": json.dumps({"proposals": []}), "error": None}
        flipped = _apply_fail_if_to_state(state, step_def, 0, [step_def], [state], MagicMock())
        assert flipped is True
        assert state["status"] == "failed"
        assert "proposals" in state["error"]

    def test_preserves_result_on_flip(self):
        """The raw result payload is still visible after fail_if marks the step failed."""
        from app.services.step_executor import _apply_fail_if_to_state
        step_def = {"id": "s1", "type": "tool", "fail_if": {"result_empty_keys": ["data"]}}
        state = {"status": "done", "result": json.dumps({"data": []}), "error": None}
        _apply_fail_if_to_state(state, step_def, 0, [step_def], [state], MagicMock())
        assert state["status"] == "failed"
        # result stays readable
        assert json.loads(state["result"]) == {"data": []}

    def test_noop_on_non_done_state(self):
        """fail_if only runs against a `done` step — skipped/failed already states stay put."""
        from app.services.step_executor import _apply_fail_if_to_state
        step_def = {"id": "s1", "fail_if": {"result_empty_keys": ["x"]}}
        state = {"status": "skipped"}
        flipped = _apply_fail_if_to_state(state, step_def, 0, [step_def], [state], MagicMock())
        assert flipped is False
        assert state["status"] == "skipped"


# ---------------------------------------------------------------------------
# _parse_result_json — plain JSON + fenced-block fallback
# ---------------------------------------------------------------------------

class TestParseResultJson:
    """LLMs often emit prose + fenced JSON blocks even when told "return ONLY JSON";
    the parser must fall back to fenced extraction so `{{steps.X.result.key}}`
    and `fail_if: {result_empty_keys: [...]}` keep working on those outputs."""

    def test_none_returns_none(self):
        assert _parse_result_json(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_result_json("") is None

    def test_plain_json_object(self):
        assert _parse_result_json('{"a": 1}') == {"a": 1}

    def test_json_array_returns_none(self):
        # the caller expects a dict; arrays are skipped
        assert _parse_result_json("[1, 2, 3]") is None

    def test_non_json_returns_none(self):
        assert _parse_result_json("just prose, no JSON at all") is None

    def test_prose_with_fenced_json_block(self):
        text = (
            "Based on my analysis, here are the proposals:\n\n"
            "```json\n"
            '{"proposals": [{"id": "p1"}]}\n'
            "```"
        )
        assert _parse_result_json(text) == {"proposals": [{"id": "p1"}]}

    def test_fenced_block_without_json_language_tag(self):
        text = "Output:\n\n```\n{\"ok\": true}\n```"
        assert _parse_result_json(text) == {"ok": True}

    def test_picks_largest_dict_when_multiple_fenced_blocks(self):
        text = (
            "```json\n{\"a\": 1}\n```\n\n"
            "```json\n{\"b\": 2, \"c\": 3, \"d\": 4}\n```"
        )
        result = _parse_result_json(text)
        assert result == {"b": 2, "c": 3, "d": 4}

    def test_ignores_fenced_array_falls_through(self):
        text = "```json\n[1, 2, 3]\n```"
        # array fences dont satisfy "dict" — no dict candidates — None
        assert _parse_result_json(text) is None

