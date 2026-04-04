"""Tests for scheduled task → workflow trigger integration."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tasks import _run_workflow_trigger_task, _spawn_from_schedule


def _make_task(**overrides):
    """Create a mock Task with sensible defaults for workflow trigger tests."""
    task = MagicMock()
    task.id = overrides.get("id", uuid.uuid4())
    task.bot_id = overrides.get("bot_id", "test-bot")
    task.channel_id = overrides.get("channel_id", uuid.uuid4())
    task.workflow_id = overrides.get("workflow_id", "test-workflow")
    task.workflow_session_mode = overrides.get("workflow_session_mode", None)
    task.dispatch_type = overrides.get("dispatch_type", "none")
    task.dispatch_config = overrides.get("dispatch_config", None)
    task.callback_config = overrides.get("callback_config", None)
    task.task_type = overrides.get("task_type", "scheduled")
    task.status = overrides.get("status", "pending")
    return task


def _mock_db_session(task_mock=None):
    """Create a mock async_session context manager."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=task_mock or MagicMock())
    db.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, db


def _mock_dedup_session(active_run_id=None):
    """Create a mock async_session for the dedup check (first call).
    Returns no active run by default (scalar_one_or_none → None).
    """
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = active_run_id
    db.execute = AsyncMock(return_value=result_mock)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, db


class TestRunWorkflowTriggerTask:
    @pytest.mark.asyncio
    async def test_success(self):
        """Workflow trigger task should call trigger_workflow and mark complete."""
        task = _make_task()
        run_mock = MagicMock()
        run_mock.id = uuid.uuid4()

        db_task = MagicMock()
        db_task.id = task.id

        with (
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=run_mock) as mock_trigger,
            patch("app.agent.tasks.async_session") as mock_session,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock) as mock_fire,
        ):
            # 3 async_session() calls: dedup check, mark running, mark complete
            cm_dedup, _ = _mock_dedup_session()
            cm1, db1 = _mock_db_session(db_task)
            cm2, db2 = _mock_db_session(db_task)
            mock_session.side_effect = [cm_dedup, cm1, cm2]

            await _run_workflow_trigger_task(task)

            mock_trigger.assert_awaited_once_with(
                task.workflow_id,
                {},
                bot_id=task.bot_id,
                channel_id=task.channel_id,
                triggered_by="task",
                dispatch_type=None,
                dispatch_config=None,
                session_mode=None,
            )
            assert db_task.status == "complete"
            assert "Triggered workflow run" in db_task.result
            mock_fire.assert_awaited_once_with(task, "complete")

    @pytest.mark.asyncio
    async def test_failure(self):
        """Workflow trigger task should mark failed on exception."""
        task = _make_task()
        db_task = MagicMock()
        db_task.id = task.id

        with (
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, side_effect=ValueError("Workflow 'bad' not found")),
            patch("app.agent.tasks.async_session") as mock_session,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock) as mock_fire,
        ):
            # 3 calls: dedup, mark running, mark failed
            cm_dedup, _ = _mock_dedup_session()
            cm1, db1 = _mock_db_session(db_task)
            cm2, db2 = _mock_db_session(db_task)
            mock_session.side_effect = [cm_dedup, cm1, cm2]

            await _run_workflow_trigger_task(task)

            assert db_task.status == "failed"
            assert "not found" in db_task.error
            mock_fire.assert_awaited_once_with(task, "failed")

    @pytest.mark.asyncio
    async def test_passes_session_mode(self):
        """workflow_session_mode should be forwarded to trigger_workflow."""
        task = _make_task(workflow_session_mode="isolated")
        run_mock = MagicMock()
        run_mock.id = uuid.uuid4()
        db_task = MagicMock()

        with (
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=run_mock) as mock_trigger,
            patch("app.agent.tasks.async_session") as mock_session,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock),
        ):
            cm_dedup, _ = _mock_dedup_session()
            cm1, _ = _mock_db_session(db_task)
            cm2, _ = _mock_db_session(db_task)
            mock_session.side_effect = [cm_dedup, cm1, cm2]

            await _run_workflow_trigger_task(task)

            assert mock_trigger.call_args.kwargs["session_mode"] == "isolated"

    @pytest.mark.asyncio
    async def test_passes_dispatch_config(self):
        """Non-none dispatch_type and dispatch_config should be forwarded."""
        task = _make_task(dispatch_type="slack", dispatch_config={"channel": "C123"})
        run_mock = MagicMock()
        run_mock.id = uuid.uuid4()
        db_task = MagicMock()

        with (
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=run_mock) as mock_trigger,
            patch("app.agent.tasks.async_session") as mock_session,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock),
        ):
            cm_dedup, _ = _mock_dedup_session()
            cm1, _ = _mock_db_session(db_task)
            cm2, _ = _mock_db_session(db_task)
            mock_session.side_effect = [cm_dedup, cm1, cm2]

            await _run_workflow_trigger_task(task)

            assert mock_trigger.call_args.kwargs["dispatch_type"] == "slack"
            assert mock_trigger.call_args.kwargs["dispatch_config"] == {"channel": "C123"}

    @pytest.mark.asyncio
    async def test_dedup_skips_when_active_run(self):
        """Should skip trigger and mark complete when active workflow run exists."""
        task = _make_task()
        active_run_id = uuid.uuid4()
        db_task = MagicMock()
        db_task.id = task.id

        with (
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock) as mock_trigger,
            patch("app.agent.tasks.async_session") as mock_session,
            patch("app.agent.tasks._fire_task_complete", new_callable=AsyncMock) as mock_fire,
        ):
            # dedup returns active run, then one session to mark complete
            cm_dedup, _ = _mock_dedup_session(active_run_id=active_run_id)
            cm_complete, _ = _mock_db_session(db_task)
            mock_session.side_effect = [cm_dedup, cm_complete]

            await _run_workflow_trigger_task(task)

            # trigger_workflow should NOT be called
            mock_trigger.assert_not_awaited()
            assert db_task.status == "complete"
            assert "Skipped" in db_task.result
            mock_fire.assert_awaited_once_with(task, "complete")


class TestSpawnFromScheduleCopiesWorkflowId:
    @pytest.mark.asyncio
    async def test_copies_workflow_fields(self):
        """_spawn_from_schedule should copy workflow_id and workflow_session_mode."""
        schedule_id = uuid.uuid4()
        scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=5)

        schedule = MagicMock()
        schedule.id = schedule_id
        schedule.bot_id = "test-bot"
        schedule.client_id = "client1"
        schedule.session_id = uuid.uuid4()
        schedule.channel_id = None
        schedule.prompt = "do thing"
        schedule.title = None
        schedule.prompt_template_id = None
        schedule.workspace_file_path = None
        schedule.workspace_id = None
        schedule.dispatch_type = "none"
        schedule.dispatch_config = None
        schedule.callback_config = None
        schedule.execution_config = None
        schedule.recurrence = "+1h"
        schedule.task_type = "scheduled"
        schedule.status = "active"
        schedule.scheduled_at = scheduled_at
        schedule.run_count = 0
        schedule.max_run_seconds = None
        schedule.workflow_id = "my-workflow"
        schedule.workflow_session_mode = "shared"

        db = AsyncMock()
        db.add = MagicMock()
        db.get = AsyncMock(return_value=schedule)
        db.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.agent.tasks.async_session", return_value=cm),
            patch("app.services.prompt_resolution.resolve_prompt", new_callable=AsyncMock, return_value="do thing"),
        ):
            await _spawn_from_schedule(schedule_id)

            db.add.assert_called_once()
            concrete = db.add.call_args[0][0]
            assert concrete.workflow_id == "my-workflow"
            assert concrete.workflow_session_mode == "shared"
            assert concrete.parent_task_id == schedule_id
            assert concrete.recurrence is None


class TestTaskCreateValidation:
    """Test the API schema validation for workflow_id vs prompt."""

    def test_accepts_workflow_id_without_prompt(self):
        from app.routers.api_v1_admin.tasks import TaskCreateIn
        body = TaskCreateIn(bot_id="bot1", workflow_id="my-wf")
        assert body.workflow_id == "my-wf"
        assert body.prompt == ""

    def test_rejects_no_prompt_no_workflow(self):
        from app.routers.api_v1_admin.tasks import TaskCreateIn
        with pytest.raises(Exception):
            TaskCreateIn(bot_id="bot1")

    def test_accepts_prompt_without_workflow(self):
        from app.routers.api_v1_admin.tasks import TaskCreateIn
        body = TaskCreateIn(bot_id="bot1", prompt="do something")
        assert body.prompt == "do something"
        assert body.workflow_id is None

    def test_accepts_template_without_prompt(self):
        from app.routers.api_v1_admin.tasks import TaskCreateIn
        tid = uuid.uuid4()
        body = TaskCreateIn(bot_id="bot1", prompt_template_id=tid)
        assert body.prompt_template_id == tid
