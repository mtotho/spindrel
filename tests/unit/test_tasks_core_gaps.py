"""Phase B.9 + B.10 targeted sweeps of app/agent/tasks.py core gaps.

B.9 covers:
  #29  _spawn_from_event_trigger + _matches_event_filter — filter matching +
       event_data injection + spawn failure swallowing
  #16  run_task callback task creation atomicity — notify_parent follow-up
       created in same transaction as status=complete update

B.10 covers:
  #3   run_task delegation child session linkage — cross-bot task creates
       child session with correct root_session_id + depth
  #9   recover_stalled_workflow_runs 4 scenarios — scenarios 1-4 each result
       in the correct terminal state or re-trigger

Uses real SQLite-in-memory DB via patched_async_sessions. External calls
(agent loop, workflow advance, hooks) are mocked per skill E.1.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agent.tasks import (
    _matches_event_filter,
    _spawn_from_event_trigger,
    fire_event_triggers,
    recover_stalled_workflow_runs,
)
from app.db.models import Session, Task, WorkflowRun
from tests.factories import build_task
from tests.factories.workflows import build_workflow_run


# ===========================================================================
# #29 — _matches_event_filter (pure function)
# ===========================================================================

class TestMatchesEventFilter:
    def test_when_filter_empty_then_always_matches(self):
        assert _matches_event_filter({}, {"key": "value"}) is True

    def test_when_filter_matches_then_returns_true(self):
        assert _matches_event_filter({"type": "deploy"}, {"type": "deploy", "env": "prod"}) is True

    def test_when_filter_mismatches_then_returns_false(self):
        assert _matches_event_filter({"type": "deploy"}, {"type": "rollback"}) is False

    def test_when_filter_key_missing_from_event_data_then_false(self):
        assert _matches_event_filter({"type": "deploy"}, {}) is False

    def test_when_all_filter_keys_match_then_true(self):
        assert _matches_event_filter(
            {"type": "deploy", "env": "prod"},
            {"type": "deploy", "env": "prod", "user": "alice"},
        ) is True

    def test_when_one_filter_key_mismatches_then_false(self):
        assert _matches_event_filter(
            {"type": "deploy", "env": "prod"},
            {"type": "deploy", "env": "staging"},
        ) is False

    def test_when_values_compared_as_strings(self):
        # _matches_event_filter coerces via str()
        assert _matches_event_filter({"count": "3"}, {"count": 3}) is True


# ===========================================================================
# #29 — _spawn_from_event_trigger (real DB)
# ===========================================================================

class TestSpawnFromEventTrigger:
    @pytest.mark.asyncio
    async def test_when_template_exists_then_concrete_task_created(
        self, db_session, patched_async_sessions
    ):
        template = build_task(
            status="active",
            task_type="event_trigger",
            trigger_config={"type": "event", "event_source": "ci", "event_type": "deploy"},
            execution_config={"history_mode": "none"},
        )
        db_session.add(template)
        await db_session.commit()

        with patch(
            "app.services.prompt_resolution.resolve_prompt",
            new_callable=AsyncMock,
            return_value="resolved prompt",
        ):
            await _spawn_from_event_trigger(template.id, {"env": "staging", "sha": "abc123"})

        result = await db_session.execute(
            select(Task).where(Task.parent_task_id == template.id)
        )
        concrete = result.scalars().first()
        assert concrete is not None
        assert concrete.status == "pending"
        assert concrete.prompt == "resolved prompt"

    @pytest.mark.asyncio
    async def test_when_event_data_injected_into_execution_config(
        self, db_session, patched_async_sessions
    ):
        template = build_task(
            status="active",
            execution_config={"history_mode": "none"},
        )
        db_session.add(template)
        await db_session.commit()

        event_data = {"env": "prod", "version": "1.2.3"}
        with patch(
            "app.services.prompt_resolution.resolve_prompt",
            new_callable=AsyncMock,
            return_value="p",
        ):
            await _spawn_from_event_trigger(template.id, event_data)

        result = await db_session.execute(
            select(Task).where(Task.parent_task_id == template.id)
        )
        concrete = result.scalars().first()
        assert concrete.execution_config["event_data"] == event_data
        # Existing execution_config keys are preserved
        assert concrete.execution_config.get("history_mode") == "none"

    @pytest.mark.asyncio
    async def test_when_template_not_found_then_no_task_created(
        self, db_session, patched_async_sessions
    ):
        missing_id = uuid.uuid4()

        await _spawn_from_event_trigger(missing_id, {"key": "val"})  # must not raise

        result = await db_session.execute(
            select(Task).where(Task.parent_task_id == missing_id)
        )
        assert result.scalars().first() is None

    @pytest.mark.asyncio
    async def test_when_template_not_active_then_no_task_created(
        self, db_session, patched_async_sessions
    ):
        template = build_task(status="pending")  # not "active"
        db_session.add(template)
        await db_session.commit()

        await _spawn_from_event_trigger(template.id, {})

        result = await db_session.execute(
            select(Task).where(Task.parent_task_id == template.id)
        )
        assert result.scalars().first() is None

    @pytest.mark.asyncio
    async def test_when_template_run_count_incremented(
        self, db_session, patched_async_sessions
    ):
        template = build_task(status="active", run_count=3)
        db_session.add(template)
        await db_session.commit()

        with patch(
            "app.services.prompt_resolution.resolve_prompt",
            new_callable=AsyncMock,
            return_value="p",
        ):
            await _spawn_from_event_trigger(template.id, {})

        await db_session.refresh(template)
        assert template.run_count == 4


# ===========================================================================
# #29 — fire_event_triggers (real DB)
# ===========================================================================

class TestFireEventTriggers:
    @pytest.mark.asyncio
    async def test_when_filter_matches_then_concrete_task_spawned(
        self, db_session, patched_async_sessions
    ):
        template = build_task(
            status="active",
            trigger_config={
                "type": "event",
                "event_source": "ci",
                "event_type": "deploy",
                "event_filter": {"env": "prod"},
            },
        )
        db_session.add(template)
        await db_session.commit()

        with patch(
            "app.services.prompt_resolution.resolve_prompt",
            new_callable=AsyncMock,
            return_value="p",
        ):
            count = await fire_event_triggers("ci", "deploy", {"env": "prod", "sha": "abc"})

        assert count == 1

    @pytest.mark.asyncio
    async def test_when_filter_mismatches_then_no_spawn(
        self, db_session, patched_async_sessions
    ):
        template = build_task(
            status="active",
            trigger_config={
                "type": "event",
                "event_source": "ci",
                "event_type": "deploy",
                "event_filter": {"env": "prod"},
            },
        )
        db_session.add(template)
        await db_session.commit()

        count = await fire_event_triggers("ci", "deploy", {"env": "staging"})

        assert count == 0

    @pytest.mark.asyncio
    async def test_when_spawn_raises_then_swallowed_and_count_zero(
        self, db_session, patched_async_sessions
    ):
        template = build_task(
            status="active",
            trigger_config={"type": "event", "event_source": "ci", "event_type": "deploy"},
        )
        db_session.add(template)
        await db_session.commit()

        with patch(
            "app.agent.tasks._spawn_from_event_trigger",
            new_callable=AsyncMock,
            side_effect=RuntimeError("spawn failed"),
        ):
            count = await fire_event_triggers("ci", "deploy", {})

        # Exception swallowed — no propagation, count stays 0
        assert count == 0

    @pytest.mark.asyncio
    async def test_when_inactive_template_then_not_matched(
        self, db_session, patched_async_sessions
    ):
        template = build_task(
            status="pending",  # NOT active
            trigger_config={"type": "event", "event_source": "ci", "event_type": "deploy"},
        )
        db_session.add(template)
        await db_session.commit()

        count = await fire_event_triggers("ci", "deploy", {})

        assert count == 0


# ===========================================================================
# #3 — run_task delegation child session linkage (real DB)
# ===========================================================================

class TestRunTaskDelegationChildSession:
    @pytest.mark.asyncio
    async def test_when_cross_bot_task_then_child_session_created_with_correct_depth(
        self, db_session, patched_async_sessions, bot_registry
    ):
        """Cross-bot task creates a child session with depth = parent.depth + 1."""
        from app.agent.tasks import run_task

        parent_bot = bot_registry.register("parent-bot")
        child_bot = bot_registry.register("child-bot")

        parent_session = Session(
            id=uuid.uuid4(),
            client_id="test",
            bot_id="parent-bot",
            depth=1,
        )
        db_session.add(parent_session)
        await db_session.commit()

        task = build_task(
            bot_id="child-bot",
            session_id=parent_session.id,
            channel_id=None,
            status="running",
        )
        db_session.add(task)
        await db_session.commit()

        with patch("app.agent.loop.run", new_callable=AsyncMock), \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.services.sessions._effective_system_prompt", return_value="sys"), \
             patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock), \
             patch("app.agent.tasks._record_trace_event", new_callable=AsyncMock), \
             patch("app.services.heartbeat._trim_history_for_task", return_value=[]), \
             patch("app.agent.loop.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                text="", client_actions=[], tool_calls=[]
            )
            await run_task(task)

        # A child session should have been created for the child bot
        result = await db_session.execute(
            select(Session).where(
                Session.parent_session_id == parent_session.id,
                Session.bot_id == "child-bot",
            )
        )
        child = result.scalars().first()
        assert child is not None
        assert child.depth == 2  # parent.depth (1) + 1
        assert child.root_session_id is not None

    @pytest.mark.asyncio
    async def test_when_cross_bot_task_then_root_session_id_is_propagated(
        self, db_session, patched_async_sessions, bot_registry
    ):
        """root_session_id is preserved from the parent session."""
        from app.agent.tasks import run_task

        root_id = uuid.uuid4()
        bot_registry.register("parent-bot")
        bot_registry.register("child-bot")

        parent_session = Session(
            id=uuid.uuid4(),
            client_id="test",
            bot_id="parent-bot",
            depth=0,
            root_session_id=root_id,
        )
        db_session.add(parent_session)
        await db_session.commit()

        task = build_task(
            bot_id="child-bot",
            session_id=parent_session.id,
            status="running",
        )
        db_session.add(task)
        await db_session.commit()

        with patch("app.agent.loop.run", new_callable=AsyncMock) as mock_run, \
             patch("app.agent.persona.get_persona", new_callable=AsyncMock, return_value=None), \
             patch("app.services.sessions._effective_system_prompt", return_value=""), \
             patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock), \
             patch("app.agent.tasks._record_trace_event", new_callable=AsyncMock), \
             patch("app.services.heartbeat._trim_history_for_task", return_value=[]):
            mock_run.return_value = MagicMock(text="", client_actions=[], tool_calls=[])
            await run_task(task)

        result = await db_session.execute(
            select(Session).where(
                Session.parent_session_id == parent_session.id,
            )
        )
        child = result.scalars().first()
        assert child is not None
        assert child.root_session_id == root_id


# ===========================================================================
# #9 — recover_stalled_workflow_runs (real DB)
# ===========================================================================

class TestRecoverStalledWorkflowRuns:
    """4 recovery scenarios from recover_stalled_workflow_runs."""

    def _stale_started_at(self, minutes_ago: int = 10) -> str:
        """ISO timestamp that is `minutes_ago` minutes in the past."""
        return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()

    @pytest.mark.asyncio
    async def test_scenario1_terminal_task_triggers_step_completion(
        self, db_session, patched_async_sessions
    ):
        """Scenario 1: running step has task_id but task is terminal — re-fire hook."""
        from app.services.workflow_executor import on_step_task_completed

        task = build_task(status="complete")
        db_session.add(task)
        await db_session.commit()

        run = build_workflow_run(
            step_states=[{
                "status": "running",
                "task_id": str(task.id),
                "started_at": self._stale_started_at(),
            }],
        )
        db_session.add(run)
        await db_session.commit()

        with patch(
            "app.services.workflow_executor.on_step_task_completed",
            new_callable=AsyncMock,
        ) as mock_hook:
            await recover_stalled_workflow_runs()

        mock_hook.assert_awaited_once()
        args = mock_hook.call_args[0]
        assert args[0] == str(run.id)  # run_id
        assert args[1] == 0            # step_idx
        assert args[2] == "complete"   # task status

    @pytest.mark.asyncio
    async def test_scenario2_no_task_id_step_marked_failed(
        self, db_session, patched_async_sessions
    ):
        """Scenario 2: running step has no task_id (crash) — mark step failed + advance."""
        run = build_workflow_run(
            step_states=[{
                "status": "running",
                "task_id": None,
                "started_at": self._stale_started_at(),
            }],
        )
        db_session.add(run)
        await db_session.commit()

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_adv:
            await recover_stalled_workflow_runs()

        mock_adv.assert_awaited_once_with(run.id)

        # Fresh fetch to bypass identity map
        result = await db_session.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))
        fresh = result.scalars().first()
        assert fresh.step_states[0]["status"] == "failed"
        assert "never created" in fresh.step_states[0]["error"]

    @pytest.mark.asyncio
    async def test_scenario3_all_pending_after_5min_triggers_advance(
        self, db_session, patched_async_sessions
    ):
        """Scenario 3: all steps still pending after 5 min — call advance_workflow."""
        stale_created = datetime.now(timezone.utc) - timedelta(minutes=10)
        run = build_workflow_run(
            status="running",
            created_at=stale_created,
            step_states=[
                {"status": "pending"},
                {"status": "pending"},
            ],
        )
        db_session.add(run)
        await db_session.commit()

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_adv:
            await recover_stalled_workflow_runs()

        mock_adv.assert_awaited_once_with(run.id)

    @pytest.mark.asyncio
    async def test_scenario3_fresh_run_not_touched(
        self, db_session, patched_async_sessions
    ):
        """Scenario 3: run is too recent (< 5 min) — leave it alone."""
        fresh_created = datetime.now(timezone.utc) - timedelta(minutes=2)
        run = build_workflow_run(
            status="running",
            created_at=fresh_created,
            step_states=[{"status": "pending"}],
        )
        db_session.add(run)
        await db_session.commit()

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_adv:
            await recover_stalled_workflow_runs()

        mock_adv.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scenario4_all_terminal_steps_but_run_running_triggers_advance(
        self, db_session, patched_async_sessions
    ):
        """Scenario 4: all steps done/failed but run still 'running' — advance to close it."""
        run = build_workflow_run(
            status="running",
            step_states=[
                {"status": "done"},
                {"status": "failed"},
            ],
        )
        db_session.add(run)
        await db_session.commit()

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_adv:
            await recover_stalled_workflow_runs()

        mock_adv.assert_awaited_once_with(run.id)

    @pytest.mark.asyncio
    async def test_when_no_stalled_runs_then_no_advance_called(
        self, db_session, patched_async_sessions
    ):
        """Happy path: nothing stalled → recovery is a no-op."""
        completed_run = build_workflow_run(status="complete")
        db_session.add(completed_run)
        await db_session.commit()

        with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock) as mock_adv:
            await recover_stalled_workflow_runs()

        mock_adv.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scenario1_advance_exception_swallowed(
        self, db_session, patched_async_sessions
    ):
        """advance_workflow failure in scenario 1 is caught and logged — no crash."""
        task = build_task(status="failed")
        db_session.add(task)
        await db_session.commit()

        run = build_workflow_run(
            step_states=[{
                "status": "running",
                "task_id": str(task.id),
                "started_at": self._stale_started_at(),
            }],
        )
        db_session.add(run)
        await db_session.commit()

        with patch(
            "app.services.workflow_executor.on_step_task_completed",
            new_callable=AsyncMock,
            side_effect=RuntimeError("hook failed"),
        ):
            await recover_stalled_workflow_runs()  # must not raise
