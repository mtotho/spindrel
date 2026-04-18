"""Phase B.2 targeted sweep of step_executor.py core gaps.

Covers audit entries:
  #7  _run_foreach_step  when-gate at iteration scope
  #8  on_pipeline_step_completed  child result freshness + OOB guard
  #12 _finalize_pipeline  anchor/summary publish + exception swallow
  #15 _run_exec_step  workspace vs bot_sandbox branching
  #17 _run_foreach_step  sub-step failures with on_failure=continue
  #26 _run_evaluate_step  evaluator dispatch + cases resolution
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_task(**overrides):
    task = MagicMock()
    task.id = uuid.uuid4()
    task.bot_id = "test-bot"
    task.channel_id = None
    task.session_id = None
    task.dispatch_type = "none"
    task.dispatch_config = {}
    task.step_states = None
    task.execution_config = {}
    for k, v in overrides.items():
        setattr(task, k, v)
    return task


def _make_db_ctx(task_row=None):
    """Mock async_session context manager returning task_row on db.get()."""
    db = AsyncMock()
    record = task_row or MagicMock()
    db.get = AsyncMock(return_value=record)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, db, record


# ---------------------------------------------------------------------------
# #7 + #17  _run_foreach_step  when-gate and on_failure=continue
# ---------------------------------------------------------------------------

def _make_foreach_task(items):
    """Task with items param for foreach over expression."""
    return _make_task(execution_config={"params": {"items": items}})


def _make_foreach_step_states():
    return [{"status": "pending", "result": None, "error": None, "started_at": None}]


class TestForeachWhenGate:
    """#7 — per-iteration when-gate evaluated with item bound in iter_params."""

    @pytest.mark.asyncio
    @patch("app.services.step_executor._call_tool_with_args", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    async def test_when_gate_skips_iterations_selectively(self, mock_persist, mock_tool):
        from app.services.step_executor import _run_foreach_step

        mock_tool.return_value = ("done", "ok", None)
        items = ["run", "skip"]
        task = _make_foreach_task(items)
        # when condition uses item_index (bound in iter_params) — index 0 runs, 1 skips
        step_def = {
            "id": "fe",
            "type": "foreach",
            "over": "{{items}}",
            "on_failure": "abort",
            "do": [{"type": "tool", "tool_name": "dummy", "when": {"param": "item_index", "equals": 0}}],
        }
        steps = [step_def]
        step_states = _make_foreach_step_states()

        result = await _run_foreach_step(task, step_def, 0, steps, step_states)

        assert result == "done"
        state = step_states[0]
        assert state["iterations"][0][0]["status"] == "done"    # ran
        assert state["iterations"][1][0]["status"] == "skipped"  # gated out

    @pytest.mark.asyncio
    @patch("app.services.step_executor._call_tool_with_args", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    async def test_when_gate_none_runs_all(self, mock_persist, mock_tool):
        mock_tool.return_value = ("done", "ok", None)
        from app.services.step_executor import _run_foreach_step

        items = ["a", "b", "c"]
        task = _make_foreach_task(items)
        step_def = {
            "id": "fe",
            "type": "foreach",
            "over": "{{items}}",
            "do": [{"type": "tool", "tool_name": "dummy"}],
        }
        steps = [step_def]
        step_states = _make_foreach_step_states()

        result = await _run_foreach_step(task, step_def, 0, steps, step_states)

        assert result == "done"
        assert mock_tool.call_count == 3
        for i in range(3):
            assert step_states[0]["iterations"][i][0]["status"] == "done"

    @pytest.mark.asyncio
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    async def test_empty_items_returns_skipped(self, mock_persist):
        from app.services.step_executor import _run_foreach_step

        task = _make_foreach_task([])
        step_def = {"id": "fe", "type": "foreach", "over": "{{items}}", "do": []}
        steps = [step_def]
        step_states = _make_foreach_step_states()

        result = await _run_foreach_step(task, step_def, 0, steps, step_states)

        assert result == "skipped"
        assert step_states[0]["status"] == "skipped"


class TestForeachOnFailureContinue:
    """#17 — on_failure=continue: all iterations run, state captures error text."""

    @pytest.mark.asyncio
    @patch("app.services.step_executor._call_tool_with_args", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    async def test_continue_runs_all_iterations_despite_failure(self, mock_persist, mock_tool):
        from app.services.step_executor import _run_foreach_step

        # First iteration's tool fails; second runs normally.
        mock_tool.side_effect = [
            ("failed", None, "tool crashed"),
            ("done", "ok", None),
        ]
        items = ["item0", "item1"]
        task = _make_foreach_task(items)
        step_def = {
            "id": "fe",
            "type": "foreach",
            "over": "{{items}}",
            "on_failure": "continue",
            "do": [{"type": "tool", "tool_name": "dummy"}],
        }
        steps = [step_def]
        step_states = _make_foreach_step_states()

        result = await _run_foreach_step(task, step_def, 0, steps, step_states)

        assert result == "done"
        assert mock_tool.call_count == 2  # both iterations ran
        state = step_states[0]
        assert state["status"] == "done"
        # Line 778-779: error annotation set when any sub-step failed
        assert state["error"] == "one or more foreach iterations failed"

    @pytest.mark.asyncio
    @patch("app.services.step_executor._call_tool_with_args", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    async def test_continue_result_counts_failures(self, mock_persist, mock_tool):
        from app.services.step_executor import _run_foreach_step

        mock_tool.side_effect = [
            ("failed", None, "err"),
            ("failed", None, "err"),
            ("done", "ok", None),
        ]
        items = ["a", "b", "c"]
        task = _make_foreach_task(items)
        step_def = {
            "id": "fe", "type": "foreach", "over": "{{items}}",
            "on_failure": "continue",
            "do": [{"type": "tool", "tool_name": "dummy"}],
        }
        steps = [step_def]
        step_states = _make_foreach_step_states()

        result = await _run_foreach_step(task, step_def, 0, steps, step_states)

        assert result == "done"
        result_obj = json.loads(step_states[0]["result"])
        assert result_obj["iterations"] == 3
        assert result_obj["failures"] == 2

    @pytest.mark.asyncio
    @patch("app.services.step_executor._call_tool_with_args", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    async def test_abort_skips_remaining_iterations(self, mock_persist, mock_tool):
        from app.services.step_executor import _run_foreach_step

        mock_tool.side_effect = [("failed", None, "boom")]
        items = ["a", "b", "c"]
        task = _make_foreach_task(items)
        step_def = {
            "id": "fe", "type": "foreach", "over": "{{items}}",
            "on_failure": "abort",
            "do": [{"type": "tool", "tool_name": "dummy"}],
        }
        steps = [step_def]
        step_states = _make_foreach_step_states()

        result = await _run_foreach_step(task, step_def, 0, steps, step_states)

        assert result == "failed"
        assert mock_tool.call_count == 1  # only first ran
        # Remaining iterations should be skipped
        assert step_states[0]["iterations"][1][0]["status"] == "skipped"
        assert step_states[0]["iterations"][2][0]["status"] == "skipped"


# ---------------------------------------------------------------------------
# #8  on_pipeline_step_completed  child result freshness + OOB guard
# ---------------------------------------------------------------------------

class TestOnPipelineStepCompleted:
    """#8 — fresh_child refetch from DB; out-of-bounds step_index guard."""

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_step_index_out_of_bounds_returns_early(
        self, mock_session, mock_persist, mock_finalize, mock_advance
    ):
        from app.services.step_executor import on_pipeline_step_completed

        parent = MagicMock()
        parent.id = uuid.uuid4()
        parent.steps = [{"id": "s0", "type": "agent"}]
        parent.step_states = [{"status": "running", "result": None, "error": None}]

        ctx, db, _ = _make_db_ctx(parent)
        db.get = AsyncMock(side_effect=lambda model, pk: parent if model.__name__ != "Task" or pk == parent.id else None)
        mock_session.return_value = ctx

        child = MagicMock()
        child.id = uuid.uuid4()
        child.result = "stale"
        child.error = None

        # step_index=5 is out of bounds for a 1-element step_states
        await on_pipeline_step_completed(str(parent.id), 5, "complete", child)

        mock_persist.assert_not_called()
        mock_advance.assert_not_called()
        mock_finalize.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_fresh_child_result_used_not_stale_arg(
        self, mock_session, mock_persist, mock_finalize, mock_advance
    ):
        from app.services.step_executor import on_pipeline_step_completed

        parent = MagicMock()
        parent.id = uuid.uuid4()
        parent.steps = [{"id": "s0", "type": "agent"}]
        parent.step_states = [{"status": "running", "result": None, "error": None, "started_at": None}]

        fresh_child = MagicMock()
        fresh_child.result = "FRESH from DB"
        fresh_child.error = None
        fresh_child_id = uuid.uuid4()

        stale_child = MagicMock()
        stale_child.id = fresh_child_id
        stale_child.result = "stale in-memory"
        stale_child.error = None

        def _get(model, pk):
            if pk == parent.id:
                return parent
            if pk == fresh_child_id:
                return fresh_child
            return None

        ctx, db, _ = _make_db_ctx()
        db.get = AsyncMock(side_effect=_get)
        mock_session.return_value = ctx

        await on_pipeline_step_completed(str(parent.id), 0, "complete", stale_child)

        mock_persist.assert_called_once()
        persisted_states = mock_persist.call_args[0][1]
        assert persisted_states[0]["result"] == "FRESH from DB"

    @pytest.mark.asyncio
    @patch("app.services.step_executor._advance_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._finalize_pipeline", new_callable=AsyncMock)
    @patch("app.services.step_executor._persist_step_states", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_fresh_child_none_falls_back_to_arg_result(
        self, mock_session, mock_persist, mock_finalize, mock_advance
    ):
        from app.services.step_executor import on_pipeline_step_completed

        parent = MagicMock()
        parent.id = uuid.uuid4()
        parent.steps = [{"id": "s0", "type": "agent"}]
        parent.step_states = [{"status": "running", "result": None, "error": None, "started_at": None}]

        child_id = uuid.uuid4()
        stale_child = MagicMock()
        stale_child.id = child_id
        stale_child.result = "fallback result"
        stale_child.error = None

        def _get(model, pk):
            if pk == parent.id:
                return parent
            return None  # fresh_child not found → fallback

        ctx, db, _ = _make_db_ctx()
        db.get = AsyncMock(side_effect=_get)
        mock_session.return_value = ctx

        await on_pipeline_step_completed(str(parent.id), 0, "complete", stale_child)

        mock_persist.assert_called_once()
        persisted_states = mock_persist.call_args[0][1]
        assert persisted_states[0]["result"] == "fallback result"


# ---------------------------------------------------------------------------
# #12  _finalize_pipeline  anchor publish + exception swallow
# ---------------------------------------------------------------------------

class TestFinalizePipeline:
    """#12 — exception in anchor publish is swallowed; post_final_to_channel gate."""

    @pytest.mark.asyncio
    @patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_no_channel_id_skips_anchor(self, mock_session, mock_fire):
        from app.services.step_executor import _finalize_pipeline

        task = _make_task(channel_id=None)
        ctx, db, record = _make_db_ctx()
        mock_session.return_value = ctx

        steps = [{"id": "s0", "type": "exec"}]
        step_states = [{"status": "done", "result": "ok", "error": None}]

        with patch("app.services.task_run_anchor.update_anchor", new_callable=AsyncMock) as mock_anchor:
            await _finalize_pipeline(task, steps, step_states, failed=False)

        mock_anchor.assert_not_called()
        mock_fire.assert_called_once_with(task, "complete")

    @pytest.mark.asyncio
    @patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_anchor_exception_swallowed_pipeline_still_completes(self, mock_session, mock_fire):
        from app.services.step_executor import _finalize_pipeline

        channel_id = uuid.uuid4()
        task = _make_task(channel_id=channel_id)

        final_task = MagicMock()
        final_task.execution_config = {}
        final_task.channel_id = channel_id

        # First session call: commit the task. Second: fetch _t_final.
        ctx1, db1, record1 = _make_db_ctx()
        ctx2, db2, _ = _make_db_ctx()
        db2.get = AsyncMock(return_value=final_task)
        mock_session.side_effect = [ctx1, ctx2]

        steps = [{"id": "s0", "type": "exec"}]
        step_states = [{"status": "done", "result": "ok", "error": None}]

        with (
            patch("app.services.task_run_anchor.update_anchor", new_callable=AsyncMock, side_effect=RuntimeError("anchor down")),
            patch("app.services.task_run_anchor.create_summary_message", new_callable=AsyncMock),
        ):
            # Must not raise despite update_anchor failing
            await _finalize_pipeline(task, steps, step_states, failed=False)

        mock_fire.assert_called_once_with(task, "complete")

    @pytest.mark.asyncio
    @patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_post_final_to_channel_calls_summary(self, mock_session, mock_fire):
        from app.services.step_executor import _finalize_pipeline

        channel_id = uuid.uuid4()
        task = _make_task(channel_id=channel_id)

        final_task = MagicMock()
        final_task.execution_config = {"post_final_to_channel": True}
        final_task.channel_id = channel_id

        ctx1, db1, _ = _make_db_ctx()
        ctx2, db2, _ = _make_db_ctx()
        db2.get = AsyncMock(return_value=final_task)
        mock_session.side_effect = [ctx1, ctx2]

        steps = [{"id": "s0"}]
        step_states = [{"status": "done", "result": "ok", "error": None}]

        with (
            patch("app.services.task_run_anchor.update_anchor", new_callable=AsyncMock),
            patch("app.services.task_run_anchor.create_summary_message", new_callable=AsyncMock) as mock_summary,
        ):
            await _finalize_pipeline(task, steps, step_states, failed=False)

        mock_summary.assert_called_once_with(final_task)

    @pytest.mark.asyncio
    @patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_post_final_false_no_summary(self, mock_session, mock_fire):
        from app.services.step_executor import _finalize_pipeline

        channel_id = uuid.uuid4()
        task = _make_task(channel_id=channel_id)

        final_task = MagicMock()
        final_task.execution_config = {}
        final_task.channel_id = channel_id

        ctx1, _, _ = _make_db_ctx()
        ctx2, db2, _ = _make_db_ctx()
        db2.get = AsyncMock(return_value=final_task)
        mock_session.side_effect = [ctx1, ctx2]

        steps = [{"id": "s0"}]
        step_states = [{"status": "done", "result": "ok", "error": None}]

        with (
            patch("app.services.task_run_anchor.update_anchor", new_callable=AsyncMock),
            patch("app.services.task_run_anchor.create_summary_message", new_callable=AsyncMock) as mock_summary,
        ):
            await _finalize_pipeline(task, steps, step_states, failed=False)

        mock_summary.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock)
    @patch("app.services.step_executor.async_session")
    async def test_failed_pipeline_sets_error_on_task(self, mock_session, mock_fire):
        from app.services.step_executor import _finalize_pipeline

        task = _make_task(channel_id=None)
        ctx, db, record = _make_db_ctx()
        mock_session.return_value = ctx

        steps = [{"id": "s0"}, {"id": "s1"}]
        step_states = [
            {"status": "done", "result": "ok", "error": None},
            {"status": "failed", "result": None, "error": "step 1 crashed"},
        ]

        await _finalize_pipeline(task, steps, step_states, failed=True)

        assert record.status == "failed"
        assert "step 1 crashed" in record.error
        mock_fire.assert_called_once_with(task, "failed")


# ---------------------------------------------------------------------------
# #15  _run_exec_step  workspace vs bot_sandbox branching
# ---------------------------------------------------------------------------

class TestRunExecStepBranching:
    """#15 — workspace.enabled / bot_sandbox.enabled / neither path branching."""

    def _make_exec_result(self, stdout="output", exit_code=0):
        r = MagicMock()
        r.stdout = stdout
        r.stderr = ""
        r.exit_code = exit_code
        r.truncated = False
        r.duration_ms = 50
        return r

    @pytest.mark.asyncio
    async def test_workspace_enabled_uses_workspace_service(self):
        from app.services.step_executor import _run_exec_step

        task = _make_task()
        step_def = {"id": "s0", "type": "exec", "prompt": "echo hello"}
        steps = [step_def]
        step_states = [{"status": "running", "result": None}]

        bot = MagicMock()
        bot.id = "test-bot"
        bot.workspace.enabled = True
        bot.shared_workspace_id = None

        ws_result = self._make_exec_result("hello world")

        with (
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service") as mock_ws,
        ):
            mock_ws.exec = AsyncMock(return_value=ws_result)
            status, result, error = await _run_exec_step(task, step_def, 0, steps, step_states)

        assert status == "done"
        assert "hello world" in result
        assert error is None
        mock_ws.exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_bot_sandbox_fallback_when_no_workspace(self):
        from app.services.step_executor import _run_exec_step

        task = _make_task()
        step_def = {"id": "s0", "type": "exec", "prompt": "echo hi"}
        steps = [step_def]
        step_states = [{"status": "running", "result": None}]

        bot = MagicMock()
        bot.id = "test-bot"
        bot.workspace.enabled = False
        bot.shared_workspace_id = None
        bot.bot_sandbox.enabled = True

        sandbox_result = self._make_exec_result("hi")

        with (
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.sandbox.sandbox_service") as mock_sb,
        ):
            mock_sb.exec_bot_local = AsyncMock(return_value=sandbox_result)
            status, result, error = await _run_exec_step(task, step_def, 0, steps, step_states)

        assert status == "done"
        assert error is None
        mock_sb.exec_bot_local.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_sandbox_returns_failed(self):
        from app.services.step_executor import _run_exec_step

        task = _make_task()
        step_def = {"id": "s0", "type": "exec", "prompt": "echo x"}
        steps = [step_def]
        step_states = [{"status": "running", "result": None}]

        bot = MagicMock()
        bot.id = "test-bot"
        bot.workspace.enabled = False
        bot.shared_workspace_id = None
        bot.bot_sandbox.enabled = False

        with patch("app.agent.bots.get_bot", return_value=bot):
            status, result, error = await _run_exec_step(task, step_def, 0, steps, step_states)

        assert status == "failed"
        assert result is None
        assert "No sandbox available" in error

    @pytest.mark.asyncio
    async def test_non_zero_exit_code_returns_failed(self):
        from app.services.step_executor import _run_exec_step

        task = _make_task()
        step_def = {"id": "s0", "type": "exec", "prompt": "exit 1"}
        steps = [step_def]
        step_states = [{"status": "running", "result": None}]

        bot = MagicMock()
        bot.id = "test-bot"
        bot.workspace.enabled = False
        bot.shared_workspace_id = None
        bot.bot_sandbox.enabled = True

        err_result = self._make_exec_result("", exit_code=1)
        err_result.stderr = "something failed"

        with (
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.sandbox.sandbox_service") as mock_sb,
        ):
            mock_sb.exec_bot_local = AsyncMock(return_value=err_result)
            status, result, error = await _run_exec_step(task, step_def, 0, steps, step_states)

        assert status == "failed"
        assert "Non-zero exit code" in error


# ---------------------------------------------------------------------------
# #26  _run_evaluate_step  evaluator dispatch + cases resolution
# ---------------------------------------------------------------------------

class TestRunEvaluateStep:
    """#26 — evaluator dispatch paths and cases JSON resolution."""

    def _call(self, step_def: dict, steps=None, step_states=None, task=None):
        from app.services.step_executor import _run_evaluate_step
        if task is None:
            task = _make_task()
        if steps is None:
            steps = [step_def]
        if step_states is None:
            step_states = [{"status": "running", "result": None, "error": None}]
        idx = len(steps) - 1
        return _run_evaluate_step(task, step_def, idx, steps, step_states)

    @pytest.mark.asyncio
    async def test_missing_evaluator_returns_failed(self):
        step_def = {"id": "e", "type": "evaluate", "cases": [{"input": "x"}]}
        status, result, error = await self._call(step_def)
        assert status == "failed"
        assert "evaluator" in error

    @pytest.mark.asyncio
    async def test_cases_as_python_list_passed_directly(self):
        """When cases is already a Python list (not a template string), it's used as-is."""
        cases = [{"input": "a"}, {"input": "b"}]
        step_def = {
            "id": "e", "type": "evaluate",
            "evaluator": "exec",
            "cases": cases,
            "command": "echo {{case.input}}",
        }

        eval_results = [{"case": c, "captured": {}, "error": None} for c in cases]
        with patch("app.services.eval_evaluator.run_evaluator", new_callable=AsyncMock, return_value=eval_results) as mock_run:
            status, result, error = await self._call(step_def)

        assert status == "done"
        call_cases = mock_run.call_args[0][1]
        assert len(call_cases) == 2
        assert call_cases[0]["input"] == "a"

    @pytest.mark.asyncio
    async def test_cases_json_string_from_prior_step_parsed(self):
        """When cases references a prior step whose result is a JSON list string."""
        cases = [{"input": "a"}, {"input": "b"}]
        prior = {"id": "load", "type": "tool"}
        step_def = {
            "id": "e", "type": "evaluate",
            "evaluator": "exec",
            "cases": "{{steps.load.result}}",
            "command": "echo {{case.input}}",
        }
        steps = [prior, step_def]
        step_states = [
            {"status": "done", "result": json.dumps(cases), "error": None},
            {"status": "running", "result": None, "error": None},
        ]

        eval_results = [{"case": c, "captured": {}, "error": None} for c in cases]
        with patch("app.services.eval_evaluator.run_evaluator", new_callable=AsyncMock, return_value=eval_results) as mock_run:
            status, result, error = await self._call(step_def, steps=steps, step_states=step_states)

        assert status == "done"
        call_cases = mock_run.call_args[0][1]
        assert len(call_cases) == 2
        assert call_cases[0]["input"] == "a"

    @pytest.mark.asyncio
    async def test_cases_wrapped_in_cases_key_unwrapped(self):
        """When prior step returns JSON with a 'cases' wrapper key."""
        inner = [{"input": "x"}]
        prior = {"id": "load", "type": "tool"}
        step_def = {
            "id": "e", "type": "evaluate",
            "evaluator": "exec",
            "cases": "{{steps.load.result}}",
            "command": "echo hi",
        }
        steps = [prior, step_def]
        step_states = [
            {"status": "done", "result": json.dumps({"cases": inner}), "error": None},
            {"status": "running", "result": None, "error": None},
        ]

        with patch("app.services.eval_evaluator.run_evaluator", new_callable=AsyncMock, return_value=[]) as mock_run:
            status, result, error = await self._call(step_def, steps=steps, step_states=step_states)

        assert status == "done"
        call_cases = mock_run.call_args[0][1]
        assert call_cases == inner

    @pytest.mark.asyncio
    async def test_cases_none_ref_returns_failed(self):
        """Missing cases ref resolves to None → failed with descriptive error."""
        step_def = {
            "id": "e", "type": "evaluate",
            "evaluator": "exec",
            "cases": "{{steps.nonexistent.result}}",
            "command": "echo hi",
        }
        status, result, error = await self._call(step_def)
        assert status == "failed"
        assert "None" in error

    @pytest.mark.asyncio
    async def test_evaluator_dispatch_success_returns_done(self):
        cases = [{"input": "test"}]
        step_def = {
            "id": "e", "type": "evaluate",
            "evaluator": "exec",
            "cases": cases,
            "command": "echo {{case.input}}",
        }

        eval_results = [{"case": {"input": "test"}, "captured": {"output": "test"}, "error": None}]
        with patch("app.services.eval_evaluator.run_evaluator", new_callable=AsyncMock, return_value=eval_results) as mock_run:
            status, result, error = await self._call(step_def)

        assert status == "done"
        assert error is None
        parsed = json.loads(result)
        assert len(parsed) == 1
        mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluator_exception_returns_failed(self):
        step_def = {
            "id": "e", "type": "evaluate",
            "evaluator": "exec",
            "cases": [{"input": "x"}],
            "command": "echo hi",
        }

        with patch("app.services.eval_evaluator.run_evaluator", new_callable=AsyncMock, side_effect=RuntimeError("evaluator crashed")):
            status, result, error = await self._call(step_def)

        assert status == "failed"
        assert result is None
        assert "evaluator crashed" in error
