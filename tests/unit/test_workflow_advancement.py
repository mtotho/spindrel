"""Tests for the workflow advancement pipeline: hook chain, result capture, and recovery."""

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
