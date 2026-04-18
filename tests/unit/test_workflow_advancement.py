"""Tests for workflow advancement — hook chain, result capture, recovery, step dispatch.

Phase 1e rewrite (2026-04-17): every DB-touching test runs against real
``db_session`` + ``patched_async_sessions`` with ORM factory rows. External
collaborators (``call_local_tool``, ``fire_hook`` broadcast, step-completion
in ``_fire_task_complete``) are mocked; the session, models, and the
workflow state machine are exercised end-to-end.
"""
from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models import Task, Workflow, WorkflowRun
from tests.factories import build_channel, build_task, build_workflow, build_workflow_run


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _pending_step(task_id: str | None = None) -> dict:
    return {
        "status": "pending", "task_id": task_id, "result": None, "error": None,
        "started_at": None, "completed_at": None, "correlation_id": None,
    }


def _running_step(task_id: str) -> dict:
    return {
        "status": "running", "task_id": task_id, "result": None, "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None, "correlation_id": None,
    }


async def _seed_workflow_and_run(
    db_session,
    *,
    steps: list[dict],
    step_states: list[dict],
    run_status: str = "running",
    run_overrides: dict | None = None,
    workflow_overrides: dict | None = None,
) -> tuple[Workflow, WorkflowRun]:
    """Persist a Workflow + WorkflowRun pair linked by workflow_id."""
    wf = build_workflow(steps=steps, **(workflow_overrides or {}))
    run_kwargs = {
        "workflow_id": wf.id,
        "status": run_status,
        "step_states": step_states,
        "workflow_snapshot": {"steps": steps, "defaults": {}, "secrets": []},
        **(run_overrides or {}),
    }
    run = build_workflow_run(**run_kwargs)
    db_session.add(wf)
    db_session.add(run)
    await db_session.commit()
    return wf, run


# ===========================================================================
# _fire_task_complete — direct workflow advancement
# ===========================================================================

class TestFireTaskComplete:
    """``_fire_task_complete`` calls workflow step completion directly (bypasses
    ``fire_hook`` broadcast error-swallowing) when ``callback_config`` names a
    workflow run, and logs broadcast errors at ERROR level (Bug 1)."""

    @pytest.mark.asyncio
    async def test_when_task_has_workflow_callback_then_step_completion_fires_directly(self):
        from app.agent.tasks import _fire_task_complete
        run_id = str(uuid.uuid4())
        task = build_task(callback_config={"workflow_run_id": run_id, "workflow_step_index": 0})

        with patch("app.services.workflow_executor.on_step_task_completed", new_callable=AsyncMock) as m, \
             patch("app.agent.hooks.fire_hook", new_callable=AsyncMock):
            await _fire_task_complete(task, "complete")

        m.assert_called_once_with(run_id, 0, "complete", task)

    @pytest.mark.asyncio
    async def test_when_task_has_no_workflow_callback_then_step_completion_skipped(self):
        from app.agent.tasks import _fire_task_complete
        task = build_task(callback_config={})

        with patch("app.services.workflow_executor.on_step_task_completed", new_callable=AsyncMock) as m, \
             patch("app.agent.hooks.fire_hook", new_callable=AsyncMock):
            await _fire_task_complete(task, "complete")

        m.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_step_completion_raises_then_task_worker_not_crashed(self):
        from app.agent.tasks import _fire_task_complete
        task = build_task(callback_config={
            "workflow_run_id": str(uuid.uuid4()), "workflow_step_index": 0,
        })

        with patch("app.services.workflow_executor.on_step_task_completed",
                   new_callable=AsyncMock, side_effect=RuntimeError("DB error")), \
             patch("app.agent.hooks.fire_hook", new_callable=AsyncMock):
            await _fire_task_complete(task, "complete")  # must not raise

    @pytest.mark.asyncio
    async def test_when_fire_hook_raises_then_error_is_logged(self):
        from app.agent.tasks import _fire_task_complete
        task = build_task()

        with patch("app.agent.hooks.fire_hook", new_callable=AsyncMock,
                   side_effect=RuntimeError("boom")), \
             patch("app.agent.tasks.logger") as mock_logger:
            await _fire_task_complete(task, "complete")

        mock_logger.error.assert_called_once()
        assert "hook error" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_when_noop_hook_invoked_then_step_completion_not_called(self):
        from app.services.workflow_hooks import _on_task_complete
        task = build_task(callback_config={
            "workflow_run_id": str(uuid.uuid4()), "workflow_step_index": 0,
        })

        with patch("app.services.workflow_executor.on_step_task_completed", new_callable=AsyncMock) as m:
            await _on_task_complete(ctx=None, task=task, status="complete")

        m.assert_not_called()


# ===========================================================================
# on_step_task_completed — reads fresh Task row, skips inactive runs
# ===========================================================================

class TestOnStepTaskCompleted:
    """Step completion must (a) use fresh ``Task.result``/``error`` from DB,
    not the stale object passed in from the task worker, and (b) short-circuit
    for runs that are no longer active."""

    @pytest.mark.asyncio
    async def test_when_task_result_in_db_then_step_result_mirrors_fresh_value(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import on_step_task_completed
        task = build_task(id=uuid.uuid4(), result="Step 0 completed successfully",
                          status="complete", correlation_id=uuid.uuid4())
        db_session.add(task)
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "step_0", "prompt": "Do it"}, {"id": "step_1", "prompt": "Do more"}],
            step_states=[_running_step(str(task.id)), _pending_step()],
        )
        stale = build_task(id=task.id, result=None, correlation_id=None)

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock):
            await on_step_task_completed(str(run.id), 0, "complete", stale)

        await db_session.refresh(run)
        assert run.step_states[0]["status"] == "done"
        assert run.step_states[0]["result"] == "Step 0 completed successfully"
        assert run.step_states[0]["correlation_id"] == str(task.correlation_id)

    @pytest.mark.asyncio
    async def test_when_task_error_in_db_then_step_error_mirrors_fresh_value(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import on_step_task_completed
        task = build_task(id=uuid.uuid4(), error="Rate limit exceeded", status="failed")
        db_session.add(task)
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "step_0", "prompt": "Do it", "on_failure": "abort"}],
            step_states=[_running_step(str(task.id))],
        )
        stale = build_task(id=task.id, error=None)

        with patch("app.services.workflow_executor._fire_after_workflow_complete",
                   new_callable=AsyncMock):
            await on_step_task_completed(str(run.id), 0, "failed", stale)

        await db_session.refresh(run)
        assert run.step_states[0]["status"] == "failed"
        assert run.step_states[0]["error"] == "Rate limit exceeded"
        assert run.status == "failed"

    @pytest.mark.asyncio
    async def test_when_run_cancelled_then_step_state_unchanged(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import on_step_task_completed
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s0", "prompt": "x"}],
            step_states=[_pending_step()],
            run_status="cancelled",
        )

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as m:
            await on_step_task_completed(str(run.id), 0, "complete", build_task())

        m.assert_not_called()
        await db_session.refresh(run)
        assert run.step_states[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_when_run_complete_then_advance_not_called(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import on_step_task_completed
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s0", "prompt": "x"}],
            step_states=[_pending_step()],
            run_status="complete",
        )

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as m:
            await on_step_task_completed(str(run.id), 0, "complete", build_task())

        m.assert_not_called()


# ===========================================================================
# recover_stalled_workflow_runs — three scenarios
# ===========================================================================

class TestRecoveryAllPendingStalls:
    """Scenario 3: run is ``running`` but every step is still ``pending``
    (advance_workflow crashed before marking step 0). Recover if older than 5 min."""

    @pytest.mark.asyncio
    async def test_when_all_pending_and_older_than_5m_then_advance_called(
        self, db_session, patched_async_sessions,
    ):
        from app.agent.tasks import recover_stalled_workflow_runs
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s0", "prompt": "x"}, {"id": "s1", "prompt": "y"}],
            step_states=[_pending_step(), _pending_step()],
            run_overrides={"created_at": datetime.now(timezone.utc) - timedelta(minutes=10)},
        )

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as m:
            await recover_stalled_workflow_runs()

        m.assert_called_once_with(run.id)

    @pytest.mark.asyncio
    async def test_when_all_pending_but_younger_than_5m_then_no_advance(
        self, db_session, patched_async_sessions,
    ):
        from app.agent.tasks import recover_stalled_workflow_runs
        await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s0", "prompt": "x"}],
            step_states=[_pending_step()],
            run_overrides={"created_at": datetime.now(timezone.utc) - timedelta(minutes=2)},
        )

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as m:
            await recover_stalled_workflow_runs()

        m.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_running_step_has_live_task_then_no_recovery(
        self, db_session, patched_async_sessions,
    ):
        from app.agent.tasks import recover_stalled_workflow_runs
        live_task = build_task(id=uuid.uuid4(), status="running")
        db_session.add(live_task)
        started = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s0", "prompt": "x"}, {"id": "s1", "prompt": "y"}],
            step_states=[
                {**_pending_step(), "status": "done", "task_id": str(uuid.uuid4()), "started_at": started},
                {**_pending_step(), "status": "running", "task_id": str(live_task.id), "started_at": started},
            ],
            run_overrides={"created_at": datetime.now(timezone.utc) - timedelta(minutes=10)},
        )

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as m_adv, \
             patch("app.services.workflow_executor.on_step_task_completed", new_callable=AsyncMock) as m_step:
            await recover_stalled_workflow_runs()

        m_adv.assert_not_called()
        m_step.assert_not_called()


class TestRecoveryAllTerminalStalls:
    """Scenario 4: all steps terminal (done/skipped/failed) but run is still
    ``running`` — advance_workflow failed after last step. Only recover if the
    run status is actually ``running``."""

    @pytest.mark.asyncio
    async def test_when_all_terminal_and_run_running_then_advance_called(
        self, db_session, patched_async_sessions,
    ):
        from app.agent.tasks import recover_stalled_workflow_runs
        started = "2025-01-01T00:00:00+00:00"
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s0"}, {"id": "s1"}, {"id": "s2"}],
            step_states=[
                {**_pending_step(), "status": "done", "task_id": str(uuid.uuid4()), "started_at": started},
                {**_pending_step(), "status": "failed", "task_id": str(uuid.uuid4()), "started_at": started},
                {**_pending_step(), "status": "skipped"},
            ],
            run_overrides={"created_at": datetime.now(timezone.utc) - timedelta(minutes=10)},
        )

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as m:
            await recover_stalled_workflow_runs()

        m.assert_called_once_with(run.id)

    @pytest.mark.asyncio
    async def test_when_all_terminal_but_awaiting_approval_then_no_recovery(
        self, db_session, patched_async_sessions,
    ):
        from app.agent.tasks import recover_stalled_workflow_runs
        started = "2025-01-01T00:00:00+00:00"
        await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s0"}, {"id": "s1"}],
            step_states=[
                {**_pending_step(), "status": "done", "task_id": str(uuid.uuid4()), "started_at": started},
                {**_pending_step(), "status": "done", "task_id": str(uuid.uuid4()), "started_at": started},
            ],
            run_status="awaiting_approval",
            run_overrides={"created_at": datetime.now(timezone.utc) - timedelta(minutes=10)},
        )

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as m:
            await recover_stalled_workflow_runs()

        m.assert_not_called()


class TestRecoveryRunningStepNoTask:
    """Scenario 2 (regression test for the bug fixed in Phase 1e):
    step is ``running`` but has no ``task_id`` — crash between step state
    commit and task creation. The recovery path MUST use deepcopy +
    ``flag_modified`` so PostgreSQL persists the JSONB mutation."""

    @pytest.mark.asyncio
    async def test_when_running_step_has_no_task_then_marked_failed_via_flag_modified(
        self, db_session, patched_async_sessions,
    ):
        from app.agent.tasks import recover_stalled_workflow_runs
        started = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s0", "prompt": "x"}, {"id": "s1", "prompt": "y"}],
            step_states=[
                {**_pending_step(), "status": "running", "task_id": None, "started_at": started},
                _pending_step(),
            ],
            run_overrides={"created_at": datetime.now(timezone.utc) - timedelta(minutes=10)},
        )

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock):
            await recover_stalled_workflow_runs()

        await db_session.refresh(run)
        assert run.step_states[0]["status"] == "failed"
        assert "Recovered: task was never created" in run.step_states[0]["error"]
        assert run.step_states[1]["status"] == "pending"  # sibling untouched


# ===========================================================================
# run_task — session_id preservation for workflow tasks
# ===========================================================================

class TestRunTaskWorkflowSession:
    """``run_task`` must NOT resolve a workflow task's ``session_id`` to the
    channel's active session — workflows use dedicated per-step sessions to
    avoid polluting the chat feed (Bug 3)."""

    @pytest.mark.asyncio
    async def test_when_task_type_is_workflow_then_session_id_preserved(
        self, db_session, patched_async_sessions,
    ):
        from app.agent import tasks as tasks_mod
        channel_session = uuid.uuid4()
        original_session = uuid.uuid4()
        channel = build_channel(active_session_id=channel_session)
        db_session.add(channel)
        task = build_task(
            id=uuid.uuid4(), channel_id=channel.id, session_id=original_session,
            task_type="workflow", status="pending",
        )
        db_session.add(task)
        await db_session.commit()

        with patch.object(tasks_mod, "session_locks") as locks:
            locks.acquire.return_value = False  # defer → early return
            await tasks_mod.run_task(task)

        assert task.session_id == original_session


# ===========================================================================
# Execution cap — safety net for runaway workflows
# ===========================================================================

class TestExecutionCap:
    """When executed step count ≥ ``WORKFLOW_MAX_TASK_EXECUTIONS``, the run
    must fail rather than creating another task (Safety Net 1)."""

    @pytest.mark.asyncio
    async def test_when_executed_reaches_cap_then_run_fails_with_cap_error(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import _advance_workflow_inner
        steps = [{"id": "s0"}, {"id": "s1"}, {"id": "s2"}]
        _, run = await _seed_workflow_and_run(
            db_session, steps=steps,
            step_states=[
                {**_pending_step(), "status": "done"},
                {**_pending_step(), "status": "done"},
                _pending_step(),
            ],
        )

        with patch("app.services.workflow_executor.settings") as s:
            s.WORKFLOW_MAX_TASK_EXECUTIONS = 2
            await _advance_workflow_inner(run.id)

        await db_session.refresh(run)
        assert run.status == "failed"
        assert "Execution cap reached" in run.error
        assert run.completed_at is not None

    @pytest.mark.asyncio
    async def test_when_retry_would_exceed_cap_then_run_fails(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import on_step_task_completed
        task = build_task(id=uuid.uuid4(), error="Rate limit", status="failed")
        db_session.add(task)
        steps = [
            {"id": "s0", "prompt": "x", "on_failure": "retry:5"},
            {"id": "s1", "prompt": "y"},
        ]
        _, run = await _seed_workflow_and_run(
            db_session, steps=steps,
            step_states=[
                {**_running_step(str(task.id)), "retry_count": 2},
                {**_pending_step(), "status": "done"},
            ],
        )

        with patch("app.services.workflow_executor.settings") as s, \
             patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock):
            s.WORKFLOW_MAX_TASK_EXECUTIONS = 2
            await on_step_task_completed(str(run.id), 0, "failed", task)

        await db_session.refresh(run)
        assert run.status == "failed"
        assert "Execution cap" in run.error


# ===========================================================================
# cancel_workflow — cascades to pending tasks
# ===========================================================================

class TestCancelWorkflow:
    """``cancel_workflow`` must (a) set run.status to ``cancelled`` and
    (b) cancel any pending workflow/exec tasks keyed by workflow_run_id."""

    @pytest.mark.asyncio
    async def test_when_cancelling_then_pending_child_tasks_become_cancelled(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import cancel_workflow
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s0", "prompt": "x"}],
            step_states=[_pending_step()],
        )
        pending_task = build_task(
            id=uuid.uuid4(), status="pending", task_type="workflow",
            callback_config={"workflow_run_id": str(run.id), "workflow_step_index": 0},
        )
        sibling_task = build_task(id=uuid.uuid4(), status="pending", task_type="agent")
        db_session.add_all([pending_task, sibling_task])
        await db_session.commit()

        result = await cancel_workflow(run.id)

        assert result.status == "cancelled"
        await db_session.refresh(pending_task)
        await db_session.refresh(sibling_task)
        assert pending_task.status == "cancelled"
        assert sibling_task.status == "pending"  # untouched


# ===========================================================================
# Startup recovery — workflow tasks skip the hook
# ===========================================================================

class TestRecoverStuckTasks:
    """``recover_stuck_tasks`` must skip ``_fire_task_complete`` for workflow
    tasks (the stalled-run sweep handles them instead) but still fire the
    hook for non-workflow tasks (Safety Net 4)."""

    @pytest.mark.asyncio
    async def test_when_workflow_task_is_stuck_then_hook_not_fired(
        self, db_session, patched_async_sessions,
    ):
        from app.agent import tasks as tasks_mod
        run_at = datetime.now(timezone.utc) - timedelta(hours=1)
        stuck = build_task(
            id=uuid.uuid4(), status="running", run_at=run_at,
            task_type="workflow",
            callback_config={"workflow_run_id": str(uuid.uuid4())},
        )
        db_session.add(stuck)
        await db_session.commit()

        with patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock) as m, \
             patch("app.agent.tasks.resolve_task_timeout", return_value=600):
            await tasks_mod.recover_stuck_tasks()

        m.assert_not_called()
        await db_session.refresh(stuck)
        assert stuck.status == "failed"

    @pytest.mark.asyncio
    async def test_when_non_workflow_task_is_stuck_then_hook_fires(
        self, db_session, patched_async_sessions,
    ):
        from app.agent import tasks as tasks_mod
        run_at = datetime.now(timezone.utc) - timedelta(hours=1)
        stuck = build_task(
            id=uuid.uuid4(), status="running", run_at=run_at,
            task_type="agent", callback_config={},
        )
        db_session.add(stuck)
        await db_session.commit()

        with patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock) as m, \
             patch("app.agent.tasks.resolve_task_timeout", return_value=600):
            await tasks_mod.recover_stuck_tasks()

        m.assert_called_once()


# ===========================================================================
# Atomic fetch — mark-and-return pending tasks
# ===========================================================================

class TestFetchDueTasks:
    """``fetch_due_tasks`` atomically marks pending tasks as running and
    returns them, preventing duplicate pickup across concurrent polls."""

    @pytest.mark.asyncio
    async def test_when_pending_tasks_exist_then_all_returned_marked_running(
        self, db_session, patched_async_sessions,
    ):
        from app.agent.tasks import fetch_due_tasks
        t1 = build_task(id=uuid.uuid4(), status="pending")
        t2 = build_task(id=uuid.uuid4(), status="pending")
        db_session.add_all([t1, t2])
        await db_session.commit()

        fetched = await fetch_due_tasks()

        assert {t.id for t in fetched} == {t1.id, t2.id}
        await db_session.refresh(t1)
        await db_session.refresh(t2)
        assert t1.status == "running"
        assert t2.status == "running"
        assert t1.run_at is not None and t2.run_at is not None


# ===========================================================================
# Advancement lock — serializes concurrent advance_workflow calls
# ===========================================================================

class TestAdvancementLock:
    """Two concurrent ``advance_workflow`` calls for the same run must
    serialize through the per-run ``asyncio.Lock``, and the lock entry must
    be cleaned up afterward (Safety Net 5)."""

    @pytest.mark.asyncio
    async def test_when_two_concurrent_calls_then_serialized_and_lock_cleaned(self):
        from app.services.workflow_executor import advance_workflow, _advance_locks
        run_id = uuid.uuid4()
        call_order = []

        async def mock_inner(rid):
            call_order.append("start")
            await asyncio.sleep(0)  # yield so the other call could interleave if unlocked
            await asyncio.sleep(0)
            call_order.append("end")

        with patch("app.services.workflow_executor._advance_workflow_inner", new=mock_inner):
            await asyncio.gather(advance_workflow(run_id), advance_workflow(run_id))

        assert call_order == ["start", "end", "start", "end"]
        assert run_id not in _advance_locks


# ===========================================================================
# Workflow snapshot — preserves definition at trigger time
# ===========================================================================

class TestWorkflowSnapshot:
    """``trigger_workflow`` captures the workflow definition into
    ``run.workflow_snapshot``; subsequent advancement reads from the snapshot
    (not the live registry) so live edits don't break in-flight runs."""

    @pytest.mark.asyncio
    async def test_when_trigger_creates_run_then_snapshot_matches_workflow(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import trigger_workflow
        wf = build_workflow(
            steps=[{"id": "s0", "prompt": "Go"}],
            defaults={"bot_id": "test-bot", "model": "gpt-4"},
            secrets=["API_KEY"],
        )
        db_session.add(wf)
        await db_session.commit()

        with patch("app.services.workflows.get_workflow", return_value=wf), \
             patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock), \
             patch("app.services.workflow_executor.validate_secrets"):
            result = await trigger_workflow(wf.id, {}, bot_id="test-bot")

        assert result.workflow_snapshot["steps"] == [{"id": "s0", "prompt": "Go"}]
        assert result.workflow_snapshot["defaults"] == {"bot_id": "test-bot", "model": "gpt-4"}
        assert result.workflow_snapshot["secrets"] == ["API_KEY"]

    def test_when_snapshot_present_then_get_run_definition_returns_snapshot(self):
        from app.services.workflow_executor import _get_run_definition
        run = build_workflow_run(
            workflow_snapshot={
                "steps": [{"id": "snap_step", "prompt": "Snap"}],
                "defaults": {"timeout": 60},
                "secrets": ["SECRET1"],
            },
        )
        live = build_workflow(steps=[{"id": "live_step"}], defaults={"timeout": 120}, secrets=["OTHER"])

        steps, defaults, secrets = _get_run_definition(run, live)

        assert steps == [{"id": "snap_step", "prompt": "Snap"}]
        assert defaults == {"timeout": 60}
        assert secrets == ["SECRET1"]

    def test_when_snapshot_missing_then_get_run_definition_falls_back_to_live(self):
        from app.services.workflow_executor import _get_run_definition
        run = build_workflow_run(workflow_snapshot=None)
        live = build_workflow(
            steps=[{"id": "live_step", "prompt": "Live"}],
            defaults={"timeout": 120}, secrets=["SECRET2"],
        )

        steps, defaults, secrets = _get_run_definition(run, live)

        assert steps == [{"id": "live_step", "prompt": "Live"}]
        assert defaults == {"timeout": 120}
        assert secrets == ["SECRET2"]

    @pytest.mark.asyncio
    async def test_when_advancing_then_steps_read_from_snapshot_not_live(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import _advance_workflow_inner
        snapshot_steps = [{"id": "snap_0", "prompt": "Snapshot step"}]
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "live_0", "prompt": "Live step"}],
            step_states=[_pending_step()],
            run_overrides={"workflow_snapshot": {"steps": snapshot_steps, "defaults": {}, "secrets": []}},
        )
        captured: list[str] = []

        def fake_build(run_, wf_, step_def_, idx_, steps_=None, defaults_=None):
            captured.append(step_def_["prompt"])
            return build_task(id=uuid.uuid4(), task_type="workflow", prompt=step_def_["prompt"])

        with patch("app.services.workflow_executor._build_step_task", new=fake_build):
            await _advance_workflow_inner(run.id)

        assert captured == ["Snapshot step"]


# ===========================================================================
# Step dispatch types — exec (shell) and tool (inline local tool)
# ===========================================================================

class TestExecStepType:
    """``type: exec`` steps become ``task_type='exec'`` with the command
    stashed in ``execution_config`` (no LLM loop)."""

    def test_when_step_type_is_exec_then_task_type_is_exec_with_command(self):
        from app.services.workflow_executor import _build_step_task
        run = build_workflow_run(workflow_snapshot=None)
        wf = build_workflow(steps=[{"id": "backup", "type": "exec", "prompt": "pg_dump mydb", "timeout": 120}])

        task = _build_step_task(run, wf, wf.steps[0], 0, wf.steps, wf.defaults or {})

        assert task.task_type == "exec"
        assert task.execution_config["command"] == "pg_dump mydb"
        assert task.max_run_seconds == 120


class TestToolStepType:
    """``type: tool`` steps execute inline via ``call_local_tool`` (no Task
    row) and honor ``on_failure: abort|continue`` semantics."""

    @pytest.mark.asyncio
    async def test_when_tool_step_succeeds_then_completes_inline_and_creates_task_for_next_step(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import _advance_workflow_inner
        steps = [
            {"id": "search", "type": "tool", "tool_name": "web_search", "tool_args": {"query": "test"}},
            {"id": "analyze", "prompt": "Analyze results"},
        ]
        _, run = await _seed_workflow_and_run(
            db_session, steps=steps,
            step_states=[_pending_step(), _pending_step()],
        )
        built: list[str] = []

        def fake_build(run_, wf_, step_def_, idx_, steps_=None, defaults_=None):
            built.append(step_def_["id"])
            return build_task(id=uuid.uuid4(), task_type="workflow", prompt=step_def_.get("prompt", ""))

        with patch("app.services.workflow_executor._build_step_task", new=fake_build), \
             patch("app.tools.registry.call_local_tool", new_callable=AsyncMock,
                   return_value='{"results": ["found"]}'):
            await _advance_workflow_inner(run.id)

        await db_session.refresh(run)
        assert run.step_states[0]["status"] == "done"
        assert run.step_states[0]["result"] == '{"results": ["found"]}'
        assert built == ["analyze"]

    @pytest.mark.asyncio
    async def test_when_tool_step_fails_and_on_failure_abort_then_run_fails(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import _advance_workflow_inner
        steps = [{"id": "fail_tool", "type": "tool", "tool_name": "bad_tool",
                  "tool_args": {}, "on_failure": "abort"}]
        _, run = await _seed_workflow_and_run(
            db_session, steps=steps, step_states=[_pending_step()],
        )

        with patch("app.tools.registry.call_local_tool", new_callable=AsyncMock,
                   side_effect=RuntimeError("tool exploded")):
            await _advance_workflow_inner(run.id)

        await db_session.refresh(run)
        assert run.status == "failed"
        assert "fail_tool" in run.error
        assert run.step_states[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_when_tool_step_fails_and_on_failure_continue_then_next_step_runs(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import _advance_workflow_inner
        steps = [
            {"id": "fail_tool", "type": "tool", "tool_name": "bad_tool",
             "tool_args": {}, "on_failure": "continue"},
            {"id": "next", "prompt": "Continue"},
        ]
        _, run = await _seed_workflow_and_run(
            db_session, steps=steps, step_states=[_pending_step(), _pending_step()],
        )
        built: list[str] = []

        def fake_build(run_, wf_, step_def_, idx_, steps_=None, defaults_=None):
            built.append(step_def_["id"])
            return build_task(id=uuid.uuid4(), task_type="workflow", prompt="x")

        with patch("app.services.workflow_executor._build_step_task", new=fake_build), \
             patch("app.tools.registry.call_local_tool", new_callable=AsyncMock,
                   side_effect=RuntimeError("tool exploded")):
            await _advance_workflow_inner(run.id)

        await db_session.refresh(run)
        assert run.step_states[0]["status"] == "failed"
        assert built == ["next"]

    @pytest.mark.asyncio
    async def test_when_tool_args_contain_params_then_they_are_rendered(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import _advance_workflow_inner
        steps = [{"id": "search", "type": "tool", "tool_name": "web_search",
                  "tool_args": {"query": "{{topic}}", "count": "{{num}}"}}]
        _, run = await _seed_workflow_and_run(
            db_session, steps=steps, step_states=[_pending_step()],
            run_overrides={"params": {"topic": "AI safety", "num": "5"}},
        )
        captured: list[dict] = []

        async def fake_call(name, arguments):
            captured.append(json.loads(arguments))
            return '{"ok": true}'

        with patch("app.tools.registry.call_local_tool", new=fake_call):
            await _advance_workflow_inner(run.id)

        assert captured == [{"query": "AI safety", "count": "5"}]


# ===========================================================================
# Atomic task creation — race-condition regression
# ===========================================================================

class TestAtomicTaskCreation:
    """Before the fix, ``_build_step_task`` committed the task in its own
    session before the outer session committed the step state, allowing the
    worker to pick up and complete a task while the step was still
    ``pending`` (duplicate pickup). Task INSERT + step state UPDATE must
    commit atomically on the SAME session."""

    @pytest.mark.asyncio
    async def test_when_advancing_agent_step_then_task_and_step_commit_together(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import _advance_workflow_inner
        _, run = await _seed_workflow_and_run(
            db_session,
            steps=[{"id": "s1", "prompt": "Do work"}],
            step_states=[_pending_step()],
        )

        await _advance_workflow_inner(run.id)

        await db_session.refresh(run)
        assert run.step_states[0]["status"] == "running"
        assert run.step_states[0]["task_id"] is not None
        persisted = (await db_session.execute(
            select(Task).where(Task.id == uuid.UUID(run.step_states[0]["task_id"]))
        )).scalar_one_or_none()
        assert persisted is not None
        assert persisted.status == "pending"

    def test_when_build_step_task_called_then_returns_unsaved_task_instance(self):
        from app.services.workflow_executor import _build_step_task
        run = build_workflow_run(workflow_snapshot=None)
        wf = build_workflow(steps=[{"id": "s1", "prompt": "Do."}])

        task = _build_step_task(run, wf, wf.steps[0], 0)

        assert isinstance(task, Task)
        assert isinstance(task.id, uuid.UUID)


# ===========================================================================
# trigger_workflow — returns DB-fresh run (captures advance_workflow effects)
# ===========================================================================

class TestTriggerWorkflowFreshReturn:
    """After calling ``advance_workflow``, ``trigger_workflow`` re-reads
    the run so callers observe the state machine's updates (step 0 marked
    running, task_id populated)."""

    @pytest.mark.asyncio
    async def test_when_trigger_returns_then_run_reflects_post_advance_state(
        self, db_session, patched_async_sessions,
    ):
        from app.services.workflow_executor import trigger_workflow
        wf = build_workflow(
            steps=[{"id": "s1", "prompt": "Do."}],
            defaults={"bot_id": "test-bot"},
        )
        db_session.add(wf)
        await db_session.commit()

        async def fake_advance(run_id):
            run = (await db_session.execute(
                select(WorkflowRun).where(WorkflowRun.id == run_id)
            )).scalar_one()
            ss = copy.deepcopy(run.step_states)
            ss[0]["status"] = "running"
            ss[0]["task_id"] = "t1"
            run.step_states = ss
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(run, "step_states")
            await db_session.commit()

        with patch("app.services.workflows.get_workflow", return_value=wf), \
             patch("app.services.workflow_executor.advance_workflow", side_effect=fake_advance), \
             patch("app.services.workflow_executor.validate_secrets"):
            result = await trigger_workflow(wf.id, {}, bot_id="test-bot")

        assert result.step_states[0]["status"] == "running"
        assert result.step_states[0]["task_id"] == "t1"


# ===========================================================================
# _set_step_states helper — invariant: always calls flag_modified
# ===========================================================================

class TestSetStepStates:
    """``_set_step_states`` assigns the new list and forces SA's JSONB
    change detection via ``flag_modified``. Asserting on the helper's
    contract (not an implementation detail — the helper's *reason to exist*
    is to guarantee flag_modified is called)."""

    def test_when_set_step_states_called_then_flag_modified_invoked(self):
        from app.services.workflow_executor import _set_step_states
        run = build_workflow_run()
        new_states = [{"status": "running"}, {"status": "pending"}]

        with patch("app.services.workflow_executor.flag_modified") as m:
            _set_step_states(run, new_states)

        assert run.step_states == new_states
        m.assert_called_once_with(run, "step_states")


# ===========================================================================
# Source-code regression guards — prevent re-introducing known JSONB bugs
# ===========================================================================

class TestNoShallowCopyRegression:
    """Prevent re-introduction of the shallow-copy + direct-assignment bug.

    ``list(run.step_states)`` creates a shallow list copy whose inner dicts
    alias the SQLAlchemy-tracked originals. Combined with
    ``run.step_states = ss`` (no ``flag_modified``), PostgreSQL sees no
    change and skips the UPDATE — the exact pattern ``_set_step_states``
    was introduced to eliminate."""

    def test_workflow_executor_has_no_shallow_copy_of_step_states(self):
        import inspect, re
        import app.services.workflow_executor as mod
        matches = re.findall(r"list\s*\(\s*run\.step_states\s*\)", inspect.getsource(mod))
        assert not matches, (
            f"Found {len(matches)} occurrence(s) of list(run.step_states) in workflow_executor.py. "
            "Use copy.deepcopy(run.step_states) instead."
        )

    def test_workflow_executor_all_step_states_assignments_use_helper(self):
        import inspect, re
        import app.services.workflow_executor as mod
        source = inspect.getsource(mod)
        helper = inspect.getsource(mod._set_step_states)
        remaining = source.replace(helper, "")
        direct = re.findall(r"run\.step_states\s*=\s*", remaining)
        assert not direct, (
            f"Found {len(direct)} direct assignment(s) to run.step_states outside _set_step_states()."
        )
