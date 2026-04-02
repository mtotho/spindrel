"""Tests for the workflow advancement pipeline: hook chain, result capture, and recovery."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(**overrides):
    """Create a mock Task with sensible defaults."""
    t = MagicMock()
    t.id = overrides.get("id", uuid.uuid4())
    t.bot_id = overrides.get("bot_id", "test-bot")
    t.channel_id = overrides.get("channel_id", uuid.uuid4())
    t.task_type = overrides.get("task_type", "workflow")
    t.callback_config = overrides.get("callback_config", {})
    t.result = overrides.get("result", None)
    t.error = overrides.get("error", None)
    t.correlation_id = overrides.get("correlation_id", None)
    t.status = overrides.get("status", "complete")
    return t


def _make_workflow_run(step_count=2, **overrides):
    """Create a mock WorkflowRun with sensible defaults."""
    run = MagicMock()
    run.id = overrides.get("id", uuid.uuid4())
    run.workflow_id = overrides.get("workflow_id", "test-wf")
    run.bot_id = overrides.get("bot_id", "test-bot")
    run.channel_id = overrides.get("channel_id", uuid.uuid4())
    run.status = overrides.get("status", "running")
    run.step_states = overrides.get("step_states", [
        {"status": "pending", "task_id": None, "result": None, "error": None,
         "started_at": None, "completed_at": None, "correlation_id": None}
        for _ in range(step_count)
    ])
    run.params = overrides.get("params", {})
    run.session_mode = overrides.get("session_mode", "isolated")
    run.session_id = overrides.get("session_id", None)
    run.dispatch_type = overrides.get("dispatch_type", "none")
    run.dispatch_config = overrides.get("dispatch_config", None)
    run.workflow_snapshot = overrides.get("workflow_snapshot", None)
    run.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    run.completed_at = overrides.get("completed_at", None)
    run.error = overrides.get("run_error", None)
    return run


def _make_workflow(steps=None, **overrides):
    """Create a mock Workflow."""
    wf = MagicMock()
    wf.id = overrides.get("id", "test-wf")
    wf.name = overrides.get("name", "Test Workflow")
    wf.steps = steps or [
        {"id": "step_0", "prompt": "Do step 0"},
        {"id": "step_1", "prompt": "Do step 1"},
    ]
    wf.defaults = overrides.get("defaults", {})
    wf.params = overrides.get("params", {})
    wf.secrets = overrides.get("secrets", [])
    wf.triggers = overrides.get("triggers", {})
    return wf


# ---------------------------------------------------------------------------
# Test: _on_task_complete hook reads callback_config and calls executor
# ---------------------------------------------------------------------------

class TestOnTaskCompleteHook:
    """Tests for workflow_hooks._on_task_complete."""

    @pytest.mark.asyncio
    async def test_calls_on_step_task_completed_with_correct_args(self):
        """Hook should extract run_id and step_index from callback_config."""
        from app.services.workflow_hooks import _on_task_complete

        run_id = str(uuid.uuid4())
        task = _make_task(callback_config={
            "workflow_run_id": run_id,
            "workflow_step_index": 0,
        })
        ctx = MagicMock()

        with patch("app.services.workflow_executor.on_step_task_completed", new_callable=AsyncMock) as mock_exec:
            await _on_task_complete(ctx, task=task, status="complete")
            mock_exec.assert_called_once_with(run_id, 0, "complete", task)

    @pytest.mark.asyncio
    async def test_skips_when_no_callback_config(self):
        """Tasks without workflow callback_config should be ignored."""
        from app.services.workflow_hooks import _on_task_complete

        task = _make_task(callback_config={})
        ctx = MagicMock()

        with patch("app.services.workflow_executor.on_step_task_completed", new_callable=AsyncMock) as mock_exec:
            await _on_task_complete(ctx, task=task, status="complete")
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_task(self):
        """Should return early if task is None."""
        from app.services.workflow_hooks import _on_task_complete

        ctx = MagicMock()
        with patch("app.services.workflow_executor.on_step_task_completed", new_callable=AsyncMock) as mock_exec:
            await _on_task_complete(ctx, task=None, status="complete")
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_reraises_executor_exceptions(self):
        """Errors from on_step_task_completed should propagate (not be silently swallowed)."""
        from app.services.workflow_hooks import _on_task_complete

        run_id = str(uuid.uuid4())
        task = _make_task(callback_config={
            "workflow_run_id": run_id,
            "workflow_step_index": 0,
        })
        ctx = MagicMock()

        with patch(
            "app.services.workflow_executor.on_step_task_completed",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            with pytest.raises(RuntimeError, match="DB error"):
                await _on_task_complete(ctx, task=task, status="complete")


# ---------------------------------------------------------------------------
# Test: on_step_task_completed uses fresh DB result (not stale task.result)
# ---------------------------------------------------------------------------

class TestStepCompletionUseFreshResult:
    """Bug 2: on_step_task_completed must read result from fresh DB task."""

    @pytest.mark.asyncio
    async def test_uses_fresh_task_result_not_stale(self):
        """The stale task object has result=None; fresh DB task has the actual result."""
        from app.services.workflow_executor import on_step_task_completed

        run_id = uuid.uuid4()
        task_id = uuid.uuid4()

        # Stale task object (as passed from run_task before result was set)
        stale_task = _make_task(id=task_id, result=None, correlation_id=None)

        # Fresh task in DB (result set after execution)
        fresh_task = _make_task(id=task_id, result="Step 0 completed successfully", correlation_id=uuid.uuid4())

        run = _make_workflow_run(id=run_id, step_count=2)
        # Mark step 0 as "running" (it was started)
        run.step_states[0]["status"] = "running"
        run.step_states[0]["task_id"] = str(task_id)

        workflow = _make_workflow()

        # Track what step_states gets written back
        committed_states = []

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            if name == "Task" and id_ == task_id:
                return fresh_task
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)

        async def mock_commit():
            # Capture step_states at commit time
            committed_states.append([dict(s) for s in run.step_states])

        mock_db.commit = AsyncMock(side_effect=mock_commit)

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock),
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
        ):
            await on_step_task_completed(str(run_id), 0, "complete", stale_task)

        # The committed state should have the fresh result, not empty string
        assert committed_states, "No commit was made"
        step_0 = committed_states[0][0]
        assert step_0["status"] == "done"
        assert step_0["result"] == "Step 0 completed successfully"

    @pytest.mark.asyncio
    async def test_uses_fresh_task_error_on_failure(self):
        """On failure, error should come from fresh DB task too."""
        from app.services.workflow_executor import on_step_task_completed

        run_id = uuid.uuid4()
        task_id = uuid.uuid4()

        stale_task = _make_task(id=task_id, error=None)
        fresh_task = _make_task(id=task_id, error="Rate limit exceeded", result=None)

        run = _make_workflow_run(id=run_id, step_count=1)
        run.step_states[0]["status"] = "running"

        workflow = _make_workflow(steps=[{"id": "step_0", "prompt": "Do it", "on_failure": "abort"}])

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            if name == "Task" and id_ == task_id:
                return fresh_task
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock),
        ):
            await on_step_task_completed(str(run_id), 0, "failed", stale_task)

        assert run.step_states[0]["status"] == "failed"
        assert run.step_states[0]["error"] == "Rate limit exceeded"


# ---------------------------------------------------------------------------
# Test: on_step_task_completed skips cancelled runs (Bug 4)
# ---------------------------------------------------------------------------

class TestStepCompletionSkipsCancelledRun:
    """Bug 4: If run is cancelled, step completion should be a no-op."""

    @pytest.mark.asyncio
    async def test_skips_cancelled_run(self):
        from app.services.workflow_executor import on_step_task_completed

        run_id = uuid.uuid4()
        task = _make_task(callback_config={
            "workflow_run_id": str(run_id),
            "workflow_step_index": 0,
        })

        run = _make_workflow_run(id=run_id, status="cancelled")

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_advance,
        ):
            await on_step_task_completed(str(run_id), 0, "complete", task)
            mock_advance.assert_not_called()

        # Step state should NOT have been modified
        assert run.step_states[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_skips_complete_run(self):
        from app.services.workflow_executor import on_step_task_completed

        run_id = uuid.uuid4()
        task = _make_task()

        run = _make_workflow_run(id=run_id, status="complete")

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_advance,
        ):
            await on_step_task_completed(str(run_id), 0, "complete", task)
            mock_advance.assert_not_called()


# ---------------------------------------------------------------------------
# Test: recovery sweep catches "all pending" stalls (Bug 5)
# ---------------------------------------------------------------------------

class TestRecoveryAllPendingStalls:
    """Bug 5: recover_stalled_workflow_runs should detect runs with all-pending steps."""

    @pytest.mark.asyncio
    async def test_recovers_all_pending_run_older_than_5_minutes(self):
        from app.agent.tasks import recover_stalled_workflow_runs
        from app.db.models import WorkflowRun

        run_id = uuid.uuid4()
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        run = MagicMock()
        run.id = run_id
        run.status = "running"
        run.step_states = [
            {"status": "pending", "task_id": None},
            {"status": "pending", "task_id": None},
        ]
        run.created_at = old_time

        # Mock the DB query to return our stalled run
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [run]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.agent.tasks.async_session", return_value=mock_db),
            patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_advance,
        ):
            await recover_stalled_workflow_runs()
            mock_advance.assert_called_once_with(run_id)

    @pytest.mark.asyncio
    async def test_does_not_recover_recent_all_pending_run(self):
        """Runs created less than 5 minutes ago should not be recovered."""
        from app.agent.tasks import recover_stalled_workflow_runs

        run_id = uuid.uuid4()
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        run = MagicMock()
        run.id = run_id
        run.status = "running"
        run.step_states = [
            {"status": "pending", "task_id": None},
        ]
        run.created_at = recent_time

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [run]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.agent.tasks.async_session", return_value=mock_db),
            patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_advance,
        ):
            await recover_stalled_workflow_runs()
            mock_advance.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_recover_run_with_some_done_steps(self):
        """Runs that have some non-pending steps should use existing recovery, not this path."""
        from app.agent.tasks import recover_stalled_workflow_runs

        run_id = uuid.uuid4()
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        run = MagicMock()
        run.id = run_id
        run.status = "running"
        run.step_states = [
            {"status": "done", "task_id": str(uuid.uuid4()), "started_at": old_time.isoformat()},
            {"status": "running", "task_id": str(uuid.uuid4()), "started_at": old_time.isoformat()},
        ]
        run.created_at = old_time

        # The running step has a task that's still running (not terminal)
        running_task = _make_task(status="running")

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [run]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.get = AsyncMock(return_value=running_task)

        with (
            patch("app.agent.tasks.async_session", return_value=mock_db),
            patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_advance,
            patch("app.services.workflow_executor.on_step_task_completed", new_callable=AsyncMock),
        ):
            await recover_stalled_workflow_runs()
            # advance_workflow should NOT be called for the all-pending path
            # (the running step's task is still running, so no recovery needed)
            mock_advance.assert_not_called()


# ---------------------------------------------------------------------------
# Test: _fire_task_complete error logging (Bug 1)
# ---------------------------------------------------------------------------

class TestFireTaskCompleteErrorLogging:
    """Bug 1: Errors in after_task_complete hook should be logged at ERROR level."""

    @pytest.mark.asyncio
    async def test_error_in_hook_is_logged_not_swallowed(self):
        """When fire_hook raises, _fire_task_complete should log at error level (not debug)."""
        from app.agent.tasks import _fire_task_complete

        task = _make_task()

        with (
            patch("app.agent.hooks.fire_hook", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("app.agent.tasks.logger") as mock_logger,
        ):
            # Should NOT raise — the function catches exceptions
            await _fire_task_complete(task, "complete")

            # Should log at error level, not debug
            mock_logger.error.assert_called_once()
            assert "hook error" in mock_logger.error.call_args[0][0]


# ---------------------------------------------------------------------------
# Test: Session ID not overwritten for workflow tasks (Bug 3)
# ---------------------------------------------------------------------------

class TestWorkflowTaskSessionPreservation:
    """Bug 3: run_task should not overwrite session_id for workflow tasks."""

    @pytest.mark.asyncio
    async def test_workflow_task_keeps_its_session_id(self):
        """Workflow tasks have dedicated per-step sessions; run_task must not overwrite them."""
        from app.agent.tasks import run_task

        original_session = uuid.uuid4()
        channel_active_session = uuid.uuid4()
        task = MagicMock()
        task.id = uuid.uuid4()
        task.bot_id = "test-bot"
        task.channel_id = uuid.uuid4()
        task.session_id = original_session
        task.task_type = "workflow"
        task.dispatch_type = "none"
        task.execution_config = {}
        task.callback_config = {}
        task.max_run_seconds = None
        task.prompt = "test"
        task.status = "pending"

        channel = MagicMock()
        channel.id = task.channel_id
        channel.active_session_id = channel_active_session
        channel.bot_id = "test-bot"

        # We only need to verify that session_id is NOT changed to channel's active session.
        # We can let run_task fail after that point — the session resolution check happens early.
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(return_value=channel)
        mock_db.commit = AsyncMock()

        # Make session_locks.acquire return False to stop execution early (task gets deferred)
        with (
            patch("app.agent.tasks.async_session", return_value=mock_db),
            patch("app.agent.tasks.session_locks") as mock_locks,
        ):
            mock_locks.acquire.return_value = False
            await run_task(task)

        # Session ID should NOT have been changed to the channel's active session
        assert task.session_id == original_session
        assert task.session_id != channel_active_session


# ---------------------------------------------------------------------------
# Test: Execution cap fails the run (Safety Net 1)
# ---------------------------------------------------------------------------

class TestExecutionCapFailsRun:
    """When executed step count >= WORKFLOW_MAX_TASK_EXECUTIONS, advance_workflow should fail the run."""

    @pytest.mark.asyncio
    async def test_execution_cap_fails_run(self):
        from app.services.workflow_executor import _advance_workflow_inner

        run_id = uuid.uuid4()
        # Create a run with 3 steps, 2 already done (at cap=2)
        run = _make_workflow_run(id=run_id, step_count=3)
        run.step_states[0]["status"] = "done"
        run.step_states[1]["status"] = "done"
        # step 2 is still pending

        workflow = _make_workflow(steps=[
            {"id": "s0", "prompt": "Do s0"},
            {"id": "s1", "prompt": "Do s1"},
            {"id": "s2", "prompt": "Do s2"},
        ])

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor.settings") as mock_settings,
        ):
            mock_settings.WORKFLOW_MAX_TASK_EXECUTIONS = 2
            await _advance_workflow_inner(run_id)

        assert run.status == "failed"
        assert "Execution cap reached" in run.error
        assert run.completed_at is not None

    @pytest.mark.asyncio
    async def test_execution_cap_in_retry_path(self):
        """Retry should be blocked when the run has hit the execution cap."""
        from app.services.workflow_executor import on_step_task_completed

        run_id = uuid.uuid4()
        task_id = uuid.uuid4()

        # Run with 2 steps — step 0 has already been executed many times via retry
        run = _make_workflow_run(id=run_id, step_count=2)
        run.step_states[0]["status"] = "running"
        run.step_states[0]["task_id"] = str(task_id)
        run.step_states[0]["retry_count"] = 2
        run.step_states[1]["status"] = "done"  # count as executed

        workflow = _make_workflow(steps=[
            {"id": "s0", "prompt": "Do s0", "on_failure": "retry:5"},
            {"id": "s1", "prompt": "Do s1"},
        ])

        fresh_task = _make_task(id=task_id, error="Rate limit", result=None)

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            if name == "Task":
                return fresh_task
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock),
            patch("app.services.workflow_executor.settings") as mock_settings,
        ):
            # Cap is 2, and we already have 2 executed (step 0 running + step 1 done)
            mock_settings.WORKFLOW_MAX_TASK_EXECUTIONS = 2
            await on_step_task_completed(str(run_id), 0, "failed", _make_task(id=task_id))

        assert run.status == "failed"
        assert "Execution cap" in run.error


# ---------------------------------------------------------------------------
# Test: Cancel cascade cancels pending tasks (Safety Net 3)
# ---------------------------------------------------------------------------

class TestCancelCascadesToPendingTasks:
    """cancel_workflow should also cancel any pending tasks for the run."""

    @pytest.mark.asyncio
    async def test_cancel_cascades_to_pending_tasks(self):
        from app.services.workflow_executor import cancel_workflow

        run_id = uuid.uuid4()
        run = _make_workflow_run(id=run_id, status="running")

        execute_calls = []

        async def mock_get(model_or_id, id_=None, **kwargs):
            # When called as db.get(WorkflowRun, run_id)
            return run

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        async def mock_execute(stmt):
            execute_calls.append(stmt)
            return MagicMock()

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        mock_db.refresh = AsyncMock()

        with patch("app.services.workflow_executor.async_session", return_value=mock_db):
            result = await cancel_workflow(run_id)

        assert result.status == "cancelled"
        # Should have executed an UPDATE statement to cancel pending tasks
        assert len(execute_calls) == 1, "Expected one UPDATE to cancel pending tasks"


# ---------------------------------------------------------------------------
# Test: Startup recovery skips workflow hook (Safety Net 4)
# ---------------------------------------------------------------------------

class TestStartupRecoverySkipsWorkflowHook:
    """recover_stuck_tasks should NOT fire _fire_task_complete for workflow tasks."""

    @pytest.mark.asyncio
    async def test_workflow_task_hook_skipped_on_recovery(self):
        from app.agent.tasks import recover_stuck_tasks

        task_id = uuid.uuid4()
        run_id = uuid.uuid4()
        task = MagicMock()
        task.id = task_id
        task.status = "running"
        task.run_at = datetime.now(timezone.utc) - timedelta(hours=1)
        task.channel_id = None
        task.max_run_seconds = None
        task.task_type = "workflow"
        task.callback_config = {"workflow_run_id": str(run_id)}

        # Mock DB for the select query
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [task]
        mock_db.execute = AsyncMock(return_value=select_result)

        # Mock the inner session for the update
        fresh_task = MagicMock()
        fresh_task.status = "running"
        mock_inner_db = AsyncMock()
        mock_inner_db.__aenter__ = AsyncMock(return_value=mock_inner_db)
        mock_inner_db.__aexit__ = AsyncMock(return_value=False)
        mock_inner_db.get = AsyncMock(return_value=fresh_task)
        mock_inner_db.commit = AsyncMock()

        call_count = [0]
        def session_factory():
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_db
            return mock_inner_db

        with (
            patch("app.agent.tasks.async_session", side_effect=session_factory),
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock) as mock_fire,
            patch("app.agent.tasks.resolve_task_timeout", return_value=600),
        ):
            await recover_stuck_tasks()

        # Hook should NOT have been fired for workflow task
        mock_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_workflow_task_hook_still_fires(self):
        """Non-workflow tasks should still get the hook fired on recovery."""
        from app.agent.tasks import recover_stuck_tasks

        task = MagicMock()
        task.id = uuid.uuid4()
        task.status = "running"
        task.run_at = datetime.now(timezone.utc) - timedelta(hours=1)
        task.channel_id = None
        task.max_run_seconds = None
        task.task_type = "agent"
        task.callback_config = {}  # No workflow_run_id

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [task]
        mock_db.execute = AsyncMock(return_value=select_result)

        fresh_task = MagicMock()
        fresh_task.status = "running"
        mock_inner_db = AsyncMock()
        mock_inner_db.__aenter__ = AsyncMock(return_value=mock_inner_db)
        mock_inner_db.__aexit__ = AsyncMock(return_value=False)
        mock_inner_db.get = AsyncMock(return_value=fresh_task)
        mock_inner_db.commit = AsyncMock()

        call_count = [0]
        def session_factory():
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_db
            return mock_inner_db

        with (
            patch("app.agent.tasks.async_session", side_effect=session_factory),
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock) as mock_fire,
            patch("app.agent.tasks.resolve_task_timeout", return_value=600),
        ):
            await recover_stuck_tasks()

        # Hook SHOULD fire for non-workflow tasks
        mock_fire.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Atomic fetch marks tasks as running (Safety Net 2)
# ---------------------------------------------------------------------------

class TestAtomicFetchMarksRunning:
    """fetch_due_tasks should return tasks already marked as running."""

    @pytest.mark.asyncio
    async def test_fetch_marks_running_and_expunges(self):
        from app.agent.tasks import fetch_due_tasks

        task1 = MagicMock()
        task1.status = "pending"
        task1.run_at = None
        task2 = MagicMock()
        task2.status = "pending"
        task2.run_at = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [task1, task2]

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.expunge = MagicMock()

        with patch("app.agent.tasks.async_session", return_value=mock_db):
            tasks = await fetch_due_tasks()

        assert len(tasks) == 2
        # All tasks should be marked running
        assert task1.status == "running"
        assert task2.status == "running"
        assert task1.run_at is not None
        assert task2.run_at is not None
        # Commit should have been called
        mock_db.commit.assert_called_once()
        # Expunge should have been called for each task
        assert mock_db.expunge.call_count == 2


# ---------------------------------------------------------------------------
# Test: In-process advancement lock (Safety Net 5)
# ---------------------------------------------------------------------------

class TestAdvancementLock:
    """advance_workflow should use per-run locks to prevent concurrent advancement."""

    @pytest.mark.asyncio
    async def test_advance_workflow_uses_lock(self):
        """Two concurrent advance_workflow calls for the same run_id should serialize."""
        from app.services.workflow_executor import advance_workflow, _advance_locks

        run_id = uuid.uuid4()
        call_order = []

        async def mock_inner(rid):
            call_order.append("start")
            await asyncio.sleep(0.05)
            call_order.append("end")

        with patch("app.services.workflow_executor._advance_workflow_inner", new=mock_inner):
            await asyncio.gather(
                advance_workflow(run_id),
                advance_workflow(run_id),
            )

        # With locking, we should see start/end/start/end (serialized)
        # Without locking, we'd see start/start/end/end (interleaved)
        assert call_order == ["start", "end", "start", "end"]

        # Lock should be cleaned up
        assert run_id not in _advance_locks


# ---------------------------------------------------------------------------
# Tests: Workflow Definition Snapshot
# ---------------------------------------------------------------------------

class TestWorkflowSnapshot:
    """Tests for workflow definition snapshot at trigger time."""

    @pytest.mark.asyncio
    async def test_workflow_snapshot_stored_at_trigger(self):
        """trigger_workflow should populate workflow_snapshot on the run."""
        from app.services.workflow_executor import trigger_workflow

        wf = _make_workflow(
            steps=[{"id": "s0", "prompt": "Go"}],
            defaults={"model": "gpt-4"},
            secrets=["API_KEY"],
        )
        wf.params = {}
        wf.triggers = {}

        created_run = None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        def capture_add(obj):
            nonlocal created_run
            created_run = obj

        mock_db.add = MagicMock(side_effect=capture_add)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflows.get_workflow", return_value=wf),
            patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock),
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor.validate_secrets"),
        ):
            result = await trigger_workflow("test-wf", {}, bot_id="test-bot")

        assert created_run is not None
        snap = created_run.workflow_snapshot
        assert snap is not None
        assert snap["steps"] == [{"id": "s0", "prompt": "Go"}]
        assert snap["defaults"] == {"model": "gpt-4"}
        assert snap["secrets"] == ["API_KEY"]

    def test_get_run_definition_uses_snapshot(self):
        """_get_run_definition should read from snapshot when available."""
        from app.services.workflow_executor import _get_run_definition

        run = _make_workflow_run()
        run.workflow_snapshot = {
            "steps": [{"id": "snap_step", "prompt": "Snap"}],
            "defaults": {"timeout": 60},
            "secrets": ["SECRET1"],
        }

        workflow = _make_workflow(
            steps=[{"id": "live_step", "prompt": "Live"}],
            defaults={"timeout": 120},
            secrets=["SECRET2"],
        )

        steps, defaults, secrets = _get_run_definition(run, workflow)
        assert steps == [{"id": "snap_step", "prompt": "Snap"}]
        assert defaults == {"timeout": 60}
        assert secrets == ["SECRET1"]

    def test_get_run_definition_fallback_for_old_runs(self):
        """Runs with workflow_snapshot=None should fall back to live workflow."""
        from app.services.workflow_executor import _get_run_definition

        run = _make_workflow_run()
        run.workflow_snapshot = None

        workflow = _make_workflow(
            steps=[{"id": "live_step", "prompt": "Live"}],
            defaults={"timeout": 120},
            secrets=["SECRET2"],
        )

        steps, defaults, secrets = _get_run_definition(run, workflow)
        assert steps == [{"id": "live_step", "prompt": "Live"}]
        assert defaults == {"timeout": 120}
        assert secrets == ["SECRET2"]

    @pytest.mark.asyncio
    async def test_snapshot_used_during_advancement(self):
        """_advance_workflow_inner should read steps from snapshot, not live workflow."""
        from app.services.workflow_executor import _advance_workflow_inner

        run_id = uuid.uuid4()
        snapshot_steps = [{"id": "snap_0", "prompt": "Snapshot step"}]
        live_steps = [{"id": "live_0", "prompt": "Live step"}]

        run = _make_workflow_run(id=run_id, step_count=1)
        run.workflow_snapshot = {
            "steps": snapshot_steps,
            "defaults": {},
            "secrets": [],
        }

        workflow = _make_workflow(steps=live_steps)

        created_task_prompts = []

        def mock_build_step_task(run_, wf_, step_def_, idx_, steps_=None, defaults_=None):
            created_task_prompts.append(step_def_["prompt"])
            mock_task = MagicMock()
            mock_task.id = uuid.uuid4()
            return mock_task

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor._build_step_task", new=mock_build_step_task),
        ):
            await _advance_workflow_inner(run_id)

        assert created_task_prompts == ["Snapshot step"]


# ---------------------------------------------------------------------------
# Tests: Step-Level Dispatch Types (exec / tool)
# ---------------------------------------------------------------------------

class TestExecStepType:
    """Tests for step type 'exec' — shell command via task."""

    @pytest.mark.asyncio
    async def test_exec_step_creates_exec_task(self):
        """Step with type: exec should create task_type='exec' with command in execution_config."""
        from app.services.workflow_executor import _build_step_task

        run = _make_workflow_run()
        run.workflow_snapshot = None
        workflow = _make_workflow(steps=[
            {"id": "backup", "type": "exec", "prompt": "pg_dump mydb", "timeout": 120},
        ])

        step_def = {"id": "backup", "type": "exec", "prompt": "pg_dump mydb", "timeout": 120}

        task = _build_step_task(
            run, workflow, step_def, 0,
            workflow.steps, workflow.defaults or {},
        )

        assert task.task_type == "exec"
        assert task.execution_config["command"] == "pg_dump mydb"
        assert task.max_run_seconds == 120


class TestToolStepType:
    """Tests for step type 'tool' — inline local tool call."""

    @pytest.mark.asyncio
    async def test_tool_step_executes_inline(self):
        """Step with type: tool should call call_local_tool directly, no Task created."""
        from app.services.workflow_executor import _advance_workflow_inner

        run_id = uuid.uuid4()
        steps = [
            {"id": "search", "type": "tool", "tool_name": "web_search", "tool_args": {"query": "test"}},
            {"id": "analyze", "prompt": "Analyze results"},
        ]

        run = _make_workflow_run(id=run_id, step_count=2)
        run.workflow_snapshot = {"steps": steps, "defaults": {}, "secrets": []}

        workflow = _make_workflow(steps=steps)

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        create_task_calls = []

        def mock_build_step_task(run_, wf_, step_def_, idx_, steps_=None, defaults_=None):
            create_task_calls.append(step_def_)
            mock_task = MagicMock()
            mock_task.id = uuid.uuid4()
            return mock_task

        mock_db.add = MagicMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor._build_step_task", new=mock_build_step_task),
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock, return_value='{"results": ["found"]}'),
        ):
            await _advance_workflow_inner(run_id)

        # Tool step should have completed inline
        assert run.step_states[0]["status"] == "done"
        assert run.step_states[0]["result"] == '{"results": ["found"]}'
        # Second step (agent) should have triggered task creation
        assert len(create_task_calls) == 1
        assert create_task_calls[0]["id"] == "analyze"

    @pytest.mark.asyncio
    async def test_tool_step_failure_aborts(self):
        """Tool step failure with on_failure: abort should fail the run."""
        from app.services.workflow_executor import _advance_workflow_inner

        run_id = uuid.uuid4()
        steps = [
            {"id": "fail_tool", "type": "tool", "tool_name": "bad_tool", "tool_args": {}, "on_failure": "abort"},
        ]

        run = _make_workflow_run(id=run_id, step_count=1)
        run.workflow_snapshot = {"steps": steps, "defaults": {}, "secrets": []}
        workflow = _make_workflow(steps=steps)

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock, side_effect=RuntimeError("tool exploded")),
        ):
            await _advance_workflow_inner(run_id)

        assert run.status == "failed"
        assert "fail_tool" in run.error
        assert run.step_states[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_tool_step_failure_continues(self):
        """Tool step failure with on_failure: continue should advance to next step."""
        from app.services.workflow_executor import _advance_workflow_inner

        run_id = uuid.uuid4()
        steps = [
            {"id": "fail_tool", "type": "tool", "tool_name": "bad_tool", "tool_args": {}, "on_failure": "continue"},
            {"id": "next", "prompt": "Continue"},
        ]

        run = _make_workflow_run(id=run_id, step_count=2)
        run.workflow_snapshot = {"steps": steps, "defaults": {}, "secrets": []}
        workflow = _make_workflow(steps=steps)

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        create_task_calls = []

        def mock_build_step_task(run_, wf_, step_def_, idx_, steps_=None, defaults_=None):
            create_task_calls.append(step_def_["id"])
            mock_task = MagicMock()
            mock_task.id = uuid.uuid4()
            return mock_task

        mock_db.add = MagicMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor._build_step_task", new=mock_build_step_task),
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock, side_effect=RuntimeError("tool exploded")),
        ):
            await _advance_workflow_inner(run_id)

        # First step failed but continued
        assert run.step_states[0]["status"] == "failed"
        # Second step should have triggered task creation
        assert create_task_calls == ["next"]

    @pytest.mark.asyncio
    async def test_tool_step_renders_args(self):
        """{{param}} in tool_args values should be resolved."""
        from app.services.workflow_executor import _advance_workflow_inner

        run_id = uuid.uuid4()
        steps = [
            {"id": "search", "type": "tool", "tool_name": "web_search",
             "tool_args": {"query": "{{topic}}", "count": "{{num}}"}},
        ]

        run = _make_workflow_run(id=run_id, step_count=1)
        run.params = {"topic": "AI safety", "num": "5"}
        run.workflow_snapshot = {"steps": steps, "defaults": {}, "secrets": []}
        workflow = _make_workflow(steps=steps)

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        captured_args = []

        async def mock_call_local_tool(name, arguments):
            import json
            captured_args.append(json.loads(arguments))
            return '{"ok": true}'

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.tools.registry.call_local_tool", new=mock_call_local_tool),
        ):
            await _advance_workflow_inner(run_id)

        assert len(captured_args) == 1
        assert captured_args[0] == {"query": "AI safety", "count": "5"}

    @pytest.mark.asyncio
    async def test_mixed_step_types(self):
        """Workflow with agent + exec + tool steps should sequence correctly."""
        from app.services.workflow_executor import _advance_workflow_inner

        run_id = uuid.uuid4()
        steps = [
            {"id": "tool_step", "type": "tool", "tool_name": "web_search", "tool_args": {"q": "test"}},
            {"id": "exec_step", "type": "exec", "prompt": "echo hello"},
            {"id": "agent_step", "prompt": "Summarize"},
        ]

        run = _make_workflow_run(id=run_id, step_count=3)
        run.workflow_snapshot = {"steps": steps, "defaults": {}, "secrets": []}
        workflow = _make_workflow(steps=steps)

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()

        created_tasks = []

        def mock_build_step_task(run_, wf_, step_def_, idx_, steps_=None, defaults_=None):
            created_tasks.append({"id": step_def_["id"], "type": step_def_.get("type", "agent")})
            mock_task = MagicMock()
            mock_task.id = uuid.uuid4()
            return mock_task

        mock_db.add = MagicMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor._build_step_task", new=mock_build_step_task),
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'),
        ):
            await _advance_workflow_inner(run_id)

        # Tool step executes inline (no task), then exec step creates a task and waits
        assert run.step_states[0]["status"] == "done"
        assert len(created_tasks) == 1
        assert created_tasks[0] == {"id": "exec_step", "type": "exec"}


# ---------------------------------------------------------------------------
# Tests: Atomic task creation (race condition fix)
# ---------------------------------------------------------------------------

class TestAtomicTaskCreation:
    """Task creation and step state update must be atomic (single transaction).

    Before the fix, _create_step_task committed the task in its own session,
    then the outer session committed the step state. This race condition
    allowed the task worker to pick up and complete a task while the step
    was still "pending", causing duplicate task creation.
    """

    @pytest.mark.asyncio
    async def test_task_added_to_same_session_as_step_state(self):
        """db.add(task) must happen on the same session that commits step_states."""
        from app.services.workflow_executor import _advance_workflow_inner

        run_id = uuid.uuid4()
        steps = [{"id": "s1", "prompt": "Do work"}]
        run = _make_workflow_run(id=run_id, step_count=1)
        run.workflow_snapshot = {"steps": steps, "defaults": {}, "secrets": []}
        workflow = _make_workflow(steps=steps)

        mock_task = MagicMock()
        mock_task.id = uuid.uuid4()

        async def mock_get(model, id_, **kwargs):
            name = model.__name__ if hasattr(model, "__name__") else str(model)
            if name == "WorkflowRun":
                return run
            if name == "Workflow":
                return workflow
            return None

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        with (
            patch("app.services.workflow_executor.async_session", return_value=mock_db),
            patch("app.services.workflow_executor._build_step_task", return_value=mock_task),
        ):
            await _advance_workflow_inner(run_id)

        # Task must be added to the SAME session as the step state update
        mock_db.add.assert_called_once_with(mock_task)

        # Step state must be "running" at the time of commit (not after)
        assert run.step_states[0]["status"] == "running"
        assert run.step_states[0]["task_id"] == str(mock_task.id)

        # Only ONE commit should happen (atomic: task + step state together)
        assert mock_db.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_no_separate_session_for_task_creation(self):
        """_build_step_task should NOT open its own DB session."""
        from app.services.workflow_executor import _build_step_task

        run = _make_workflow_run()
        run.workflow_snapshot = None
        workflow = _make_workflow(steps=[{"id": "s1", "prompt": "Do."}])

        # _build_step_task is synchronous — no DB session needed
        task = _build_step_task(run, workflow, workflow.steps[0], 0)

        # Verify it returns a real Task object, not a UUID
        from app.db.models import Task as TaskModel
        assert isinstance(task, TaskModel)
        assert isinstance(task.id, uuid.UUID)
