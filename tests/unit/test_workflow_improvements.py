"""Tests for workflow improvement changes:
- Trigger enforcement
- Deletion guard
- approve_step task_id storage
- advance_workflow single-session + loop behavior
- Unknown condition warning
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow_executor import (
    evaluate_condition,
    trigger_workflow,
    approve_step,
    advance_workflow,
)


# ---------------------------------------------------------------------------
# Trigger enforcement
# ---------------------------------------------------------------------------

class TestTriggerEnforcement:
    """trigger_workflow should respect the triggers field."""

    @pytest.mark.asyncio
    async def test_trigger_allowed_when_source_enabled(self):
        """Trigger should proceed when triggered_by source is enabled."""
        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.triggers = {"api": True, "tool": True}
        workflow.params = {}
        workflow.secrets = []
        workflow.defaults = {"bot_id": "default-bot"}
        workflow.steps = [{"id": "step1", "prompt": "Do thing"}]
        workflow.session_mode = "isolated"

        run = MagicMock()
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"
        run.status = "running"
        run.step_states = [{"status": "pending"}]
        run.params = {}
        run.session_id = None

        with patch("app.services.workflows.get_workflow", return_value=workflow):
            with patch("app.services.workflow_executor.validate_secrets"):
                with patch("app.services.workflow_executor.async_session") as mock_session:
                    mock_db = AsyncMock()
                    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                    mock_session.return_value.__aexit__ = AsyncMock()
                    mock_db.refresh = AsyncMock(return_value=None)
                    with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock):
                        with patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock):
                            result = await trigger_workflow(
                                "test-wf", {}, bot_id="default-bot", triggered_by="api",
                            )
                            assert result is not None

    @pytest.mark.asyncio
    async def test_trigger_rejected_when_source_disabled(self):
        """Trigger should raise ValueError when triggered_by source is disabled."""
        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.triggers = {"api": False, "tool": True}
        workflow.params = {}

        with patch("app.services.workflows.get_workflow", return_value=workflow):
            with pytest.raises(ValueError, match="does not allow 'api' triggers"):
                await trigger_workflow("test-wf", {}, bot_id="bot", triggered_by="api")

    @pytest.mark.asyncio
    async def test_trigger_allowed_when_source_not_in_triggers(self):
        """Unknown trigger source should be allowed (not restricted)."""
        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.triggers = {"api": True}  # tool not mentioned
        workflow.params = {}
        workflow.secrets = []
        workflow.defaults = {"bot_id": "default-bot"}
        workflow.steps = [{"id": "step1", "prompt": "Do."}]
        workflow.session_mode = "isolated"

        with patch("app.services.workflows.get_workflow", return_value=workflow):
            with patch("app.services.workflow_executor.validate_secrets"):
                with patch("app.services.workflow_executor.async_session") as mock_session:
                    mock_db = AsyncMock()
                    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                    mock_session.return_value.__aexit__ = AsyncMock()
                    mock_db.refresh = AsyncMock(return_value=None)
                    with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock):
                        with patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock):
                            result = await trigger_workflow(
                                "test-wf", {}, bot_id="default-bot", triggered_by="tool",
                            )
                            assert result is not None

    @pytest.mark.asyncio
    async def test_trigger_allowed_when_empty_triggers(self):
        """Empty triggers dict should not restrict anything."""
        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.triggers = {}
        workflow.params = {}
        workflow.secrets = []
        workflow.defaults = {"bot_id": "bot"}
        workflow.steps = [{"id": "step1", "prompt": "Do."}]
        workflow.session_mode = "isolated"

        with patch("app.services.workflows.get_workflow", return_value=workflow):
            with patch("app.services.workflow_executor.validate_secrets"):
                with patch("app.services.workflow_executor.async_session") as mock_session:
                    mock_db = AsyncMock()
                    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                    mock_session.return_value.__aexit__ = AsyncMock()
                    mock_db.refresh = AsyncMock(return_value=None)
                    with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock):
                        with patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock):
                            result = await trigger_workflow(
                                "test-wf", {}, bot_id="bot", triggered_by="heartbeat",
                            )
                            assert result is not None


# ---------------------------------------------------------------------------
# Unknown condition keys warning
# ---------------------------------------------------------------------------

class TestUnknownConditionWarning:
    """Unknown condition keys should return False and log a warning."""

    def test_typo_condition_key_returns_false(self):
        assert evaluate_condition({"stpe": "search", "status": "done"}, {}) is False

    def test_completely_unknown_key_returns_false(self):
        assert evaluate_condition({"foobar": 123}, {}) is False

    def test_unknown_key_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="app.services.workflow_executor"):
            evaluate_condition({"unknown_key": "value"}, {})
        assert "Unrecognized condition keys" in caplog.text


# ---------------------------------------------------------------------------
# Deletion guard
# ---------------------------------------------------------------------------

class TestDeletionGuard:
    """delete_workflow should refuse if active runs exist."""

    @pytest.mark.asyncio
    async def test_delete_blocked_by_active_runs(self):
        from app.services.workflows import delete_workflow

        workflow = MagicMock()
        workflow.id = "test-wf"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=workflow)

        # Mock the count query — execute() returns a Result whose .scalar() returns the count
        mock_exec_result = MagicMock()
        mock_exec_result.scalar = MagicMock(return_value=2)
        mock_db.execute = AsyncMock(return_value=mock_exec_result)

        def make_ctx():
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch("app.services.workflows.async_session", side_effect=lambda: make_ctx()):
            with pytest.raises(ValueError, match="Cannot delete.*2 active run"):
                await delete_workflow("test-wf")

    @pytest.mark.asyncio
    async def test_delete_allowed_when_no_active_runs(self):
        from app.services.workflows import delete_workflow

        workflow = MagicMock()
        workflow.id = "test-wf"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=workflow)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_exec_result = MagicMock()
        mock_exec_result.scalar = MagicMock(return_value=0)
        mock_db.execute = AsyncMock(return_value=mock_exec_result)

        def make_ctx():
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch("app.services.workflows.async_session", side_effect=lambda: make_ctx()):
            result = await delete_workflow("test-wf")
            assert result is True
            mock_db.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        from app.services.workflows import delete_workflow

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        def make_ctx():
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch("app.services.workflows.async_session", side_effect=lambda: make_ctx()):
            result = await delete_workflow("missing-wf")
            assert result is False


# ---------------------------------------------------------------------------
# approve_step task_id storage
# ---------------------------------------------------------------------------

class TestApproveStepTaskId:
    """approve_step should store the created task_id in step_states."""

    @pytest.mark.asyncio
    async def test_approve_stores_task_id(self):
        run_id = uuid.uuid4()
        task_id = uuid.uuid4()

        step_states = [
            {"status": "pending", "task_id": None, "result": None, "error": None,
             "started_at": None, "completed_at": None},
        ]

        run = MagicMock()
        run.id = run_id
        run.status = "awaiting_approval"
        run.workflow_id = "test-wf"
        run.step_states = step_states
        run.params = {}
        run.session_id = None
        run.bot_id = "bot"
        run.channel_id = None
        run.session_mode = "isolated"

        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.steps = [{"id": "step1", "prompt": "Do thing"}]
        workflow.defaults = {}
        workflow.secrets = []
        workflow.name = "Test WF"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=lambda model, id_, **kw: run)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        def make_ctx():
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch("app.services.workflow_executor.async_session", side_effect=lambda: make_ctx()):
            with patch("app.services.workflows.get_workflow", return_value=workflow):
                mock_task = MagicMock()
                mock_task.id = task_id
                with patch("app.services.workflow_executor._build_step_task",
                           return_value=mock_task):
                    result = await approve_step(run_id, 0)

        # Verify task_id was stored
        assert run.step_states[0]["task_id"] == str(task_id)
        assert run.step_states[0]["status"] == "running"
        assert run.step_states[0]["started_at"] is not None


# ---------------------------------------------------------------------------
# advance_workflow loop behavior (no recursion)
# ---------------------------------------------------------------------------

class TestAdvanceWorkflowLoop:
    """advance_workflow should use a loop for skipped steps, not recursion."""

    @pytest.mark.asyncio
    async def test_multiple_skips_handled_in_loop(self):
        """When multiple consecutive steps are skipped, the loop should handle all
        without recursion and then find the next actionable step."""
        run_id = uuid.uuid4()
        task_id = uuid.uuid4()

        step_states = [
            {"status": "pending", "task_id": None, "result": None, "error": None,
             "started_at": None, "completed_at": None},
            {"status": "pending", "task_id": None, "result": None, "error": None,
             "started_at": None, "completed_at": None},
            {"status": "pending", "task_id": None, "result": None, "error": None,
             "started_at": None, "completed_at": None},
        ]

        run = MagicMock()
        run.id = run_id
        run.status = "running"
        run.workflow_id = "test-wf"
        run.step_states = step_states
        run.params = {"skip_first": True}
        run.session_id = None
        run.bot_id = "bot"
        run.channel_id = None
        run.session_mode = "isolated"

        steps = [
            {"id": "step1", "prompt": "Skip me", "when": {"param": "skip_first", "equals": False}},
            {"id": "step2", "prompt": "Skip me too", "when": {"param": "skip_first", "equals": False}},
            {"id": "step3", "prompt": "Run me"},
        ]

        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.steps = steps
        workflow.defaults = {}
        workflow.secrets = []
        workflow.name = "Test WF"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=lambda model, id_, **kw: run if hasattr(model, "__name__") and model.__name__ == "WorkflowRun" else workflow)
        mock_db.commit = AsyncMock()

        with patch("app.services.workflow_executor.async_session") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            mock_task = MagicMock()
            mock_task.id = task_id
            mock_db.add = MagicMock()
            with patch("app.services.workflow_executor._build_step_task",
                       return_value=mock_task):
                await advance_workflow(run_id)

        # First two steps should be skipped, third should be running
        assert run.step_states[0]["status"] == "skipped"
        assert run.step_states[1]["status"] == "skipped"
        assert run.step_states[2]["status"] == "running"
        assert run.step_states[2]["task_id"] == str(task_id)

    @pytest.mark.asyncio
    async def test_all_steps_skipped_completes_run(self):
        """When all steps are skipped, the run should complete."""
        run_id = uuid.uuid4()

        step_states = [
            {"status": "pending", "task_id": None, "result": None, "error": None,
             "started_at": None, "completed_at": None},
            {"status": "pending", "task_id": None, "result": None, "error": None,
             "started_at": None, "completed_at": None},
        ]

        run = MagicMock()
        run.id = run_id
        run.status = "running"
        run.workflow_id = "test-wf"
        run.step_states = step_states
        run.params = {}
        run.session_id = None
        run.bot_id = "bot"
        run.channel_id = None
        run.session_mode = "isolated"
        run.completed_at = None

        steps = [
            {"id": "step1", "prompt": "Skip", "when": {"param": "nonexistent"}},
            {"id": "step2", "prompt": "Skip", "when": {"param": "nonexistent"}},
        ]

        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.steps = steps
        workflow.defaults = {}
        workflow.secrets = []
        workflow.name = "Test WF"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=lambda model, id_, **kw: run if hasattr(model, "__name__") and model.__name__ == "WorkflowRun" else workflow)
        mock_db.commit = AsyncMock()

        with patch("app.services.workflow_executor.async_session") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            with patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock):
                with patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock):
                    await advance_workflow(run_id)

        assert run.step_states[0]["status"] == "skipped"
        assert run.step_states[1]["status"] == "skipped"
        assert run.status == "complete"
        assert run.completed_at is not None

    @pytest.mark.asyncio
    async def test_approval_gate_stops_advancement(self):
        """Approval gate should stop advancement and set awaiting_approval status."""
        run_id = uuid.uuid4()

        step_states = [
            {"status": "pending", "task_id": None, "result": None, "error": None,
             "started_at": None, "completed_at": None},
        ]

        run = MagicMock()
        run.id = run_id
        run.status = "running"
        run.workflow_id = "test-wf"
        run.step_states = step_states
        run.params = {}

        steps = [{"id": "step1", "prompt": "Approve me", "requires_approval": True}]

        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.steps = steps
        workflow.defaults = {}

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=lambda model, id_, **kw: run if hasattr(model, "__name__") and model.__name__ == "WorkflowRun" else workflow)
        mock_db.commit = AsyncMock()

        with patch("app.services.workflow_executor.async_session") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            await advance_workflow(run_id)

        assert run.status == "awaiting_approval"
        assert run.current_step_index == 0

    @pytest.mark.asyncio
    async def test_non_running_run_exits_early(self):
        """advance_workflow should return immediately if run is not running."""
        run_id = uuid.uuid4()

        run = MagicMock()
        run.id = run_id
        run.status = "complete"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=run)

        with patch("app.services.workflow_executor.async_session") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            # Should not raise or loop forever
            await advance_workflow(run_id)


# ---------------------------------------------------------------------------
# Update workflow auto-detach
# ---------------------------------------------------------------------------

class TestUpdateWorkflowAutoDetach:
    """update_workflow should auto-detach file-sourced workflows."""

    @pytest.mark.asyncio
    async def test_file_sourced_becomes_manual_on_update(self):
        from app.services.workflows import update_workflow

        row = MagicMock()
        row.id = "test-wf"
        row.source_type = "file"
        row.content_hash = "abc123"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=row)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch("app.services.workflows.async_session") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            result = await update_workflow("test-wf", {"name": "Updated"})

        assert row.source_type == "manual"
        assert row.content_hash is None
        assert row.name == "Updated"

    @pytest.mark.asyncio
    async def test_manual_source_stays_manual_on_update(self):
        from app.services.workflows import update_workflow

        row = MagicMock()
        row.id = "test-wf"
        row.source_type = "manual"
        row.content_hash = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=row)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch("app.services.workflows.async_session") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            result = await update_workflow("test-wf", {"description": "New desc"})

        assert row.source_type == "manual"
        assert row.description == "New desc"
