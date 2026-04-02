"""Tests for manage_workflow tool — context defaults, get_run, list_runs."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.workflows import manage_workflow


# ---------------------------------------------------------------------------
# Context defaults for trigger
# ---------------------------------------------------------------------------

class TestTriggerContextDefaults:
    """trigger action should default bot_id/channel_id from context vars."""

    @pytest.mark.asyncio
    async def test_bot_id_defaults_from_context(self):
        """When bot_id is omitted, should use current_bot_id from context."""
        run = MagicMock()
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"
        run.status = "running"
        run.step_states = [{"status": "pending"}]

        with (
            patch("app.agent.context.current_bot_id") as mock_bot_ctx,
            patch("app.agent.context.current_channel_id") as mock_ch_ctx,
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=run) as mock_trigger,
        ):
            mock_bot_ctx.get.return_value = "my-bot"
            mock_ch_ctx.get.return_value = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

            result = json.loads(await manage_workflow(action="trigger", id="test-wf"))
            assert result["status"] == "running"

            # Verify bot_id was passed from context
            mock_trigger.assert_called_once()
            _, kwargs = mock_trigger.call_args
            assert kwargs.get("bot_id") == "my-bot"

    @pytest.mark.asyncio
    async def test_explicit_bot_id_overrides_context(self):
        """When bot_id is explicitly provided, should use that over context."""
        run = MagicMock()
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"
        run.status = "running"
        run.step_states = [{"status": "pending"}]

        with (
            patch("app.agent.context.current_bot_id") as mock_bot_ctx,
            patch("app.agent.context.current_channel_id") as mock_ch_ctx,
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=run) as mock_trigger,
        ):
            mock_bot_ctx.get.return_value = "my-bot"
            mock_ch_ctx.get.return_value = None

            result = json.loads(await manage_workflow(action="trigger", id="test-wf", bot_id="override-bot"))
            assert result["status"] == "running"

            _, kwargs = mock_trigger.call_args
            assert kwargs.get("bot_id") == "override-bot"

    @pytest.mark.asyncio
    async def test_channel_id_defaults_from_context(self):
        """When channel_id is omitted, should use current_channel_id from context."""
        run = MagicMock()
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"
        run.status = "running"
        run.step_states = [{"status": "pending"}]

        ctx_channel = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        with (
            patch("app.agent.context.current_bot_id") as mock_bot_ctx,
            patch("app.agent.context.current_channel_id") as mock_ch_ctx,
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=run) as mock_trigger,
        ):
            mock_bot_ctx.get.return_value = "my-bot"
            mock_ch_ctx.get.return_value = ctx_channel

            result = json.loads(await manage_workflow(action="trigger", id="test-wf"))
            assert result["status"] == "running"

            _, kwargs = mock_trigger.call_args
            assert kwargs.get("channel_id") == ctx_channel


# ---------------------------------------------------------------------------
# get_run
# ---------------------------------------------------------------------------

class TestGetRun:
    """get_run action should return run status and step details."""

    @pytest.mark.asyncio
    async def test_get_run_returns_status_and_steps(self):
        """get_run should return run status, progress, and step summaries."""
        run_id = uuid.uuid4()
        run = MagicMock()
        run.id = run_id
        run.workflow_id = "test-wf"
        run.status = "running"
        run.error = None
        run.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        run.completed_at = None
        run.step_states = [
            {"status": "done", "result": "Step 1 done", "error": None,
             "started_at": "2025-01-01T00:00:00", "completed_at": "2025-01-01T00:01:00"},
            {"status": "running", "result": None, "error": None,
             "started_at": "2025-01-01T00:01:00", "completed_at": None},
        ]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=run)

        with patch("app.db.engine.async_session") as mock_session:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock()
            mock_session.return_value = ctx

            result = json.loads(await manage_workflow(action="get_run", run_id=str(run_id)))

        assert result["status"] == "running"
        assert result["done"] == 1
        assert len(result["steps"]) == 2
        assert result["steps"][0]["status"] == "done"
        assert "Step 1 done" in result["steps"][0]["result_preview"]

    @pytest.mark.asyncio
    async def test_get_run_missing_run_id(self):
        """get_run without run_id should return error."""
        result = json.loads(await manage_workflow(action="get_run"))
        assert "error" in result
        assert "run_id is required" in result["error"]

    @pytest.mark.asyncio
    async def test_get_run_invalid_uuid(self):
        """get_run with invalid UUID should return error."""
        result = json.loads(await manage_workflow(action="get_run", run_id="not-a-uuid"))
        assert "error" in result
        assert "Invalid run_id" in result["error"]

    @pytest.mark.asyncio
    async def test_get_run_not_found(self):
        """get_run with nonexistent run should return error."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        with patch("app.db.engine.async_session") as mock_session:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock()
            mock_session.return_value = ctx

            result = json.loads(await manage_workflow(action="get_run", run_id=str(uuid.uuid4())))

        assert "error" in result
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------

class TestListRuns:
    """list_runs action should return recent runs for a workflow."""

    @pytest.mark.asyncio
    async def test_list_runs_returns_recent(self):
        """list_runs should return recent runs with status/progress."""
        run1 = MagicMock()
        run1.id = uuid.uuid4()
        run1.status = "complete"
        run1.triggered_by = "tool"
        run1.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        run1.completed_at = datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc)
        run1.step_states = [
            {"status": "done"}, {"status": "done"}, {"status": "skipped"},
        ]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [run1]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.db.engine.async_session") as mock_session:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock()
            mock_session.return_value = ctx

            result = json.loads(await manage_workflow(action="list_runs", id="test-wf"))

        assert result["count"] == 1
        assert result["runs"][0]["status"] == "complete"
        assert "2/3 done" in result["runs"][0]["progress"]

    @pytest.mark.asyncio
    async def test_list_runs_missing_id(self):
        """list_runs without id should return error."""
        result = json.loads(await manage_workflow(action="list_runs"))
        assert "error" in result
        assert "id is required" in result["error"]
