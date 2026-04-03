"""Unit tests for workflow tool and exec step type execution paths."""
import copy
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow_executor import advance_workflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_session_ctx(mock_db):
    """Create a properly configured async context manager mock for async_session."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_run(
    steps: list[dict],
    *,
    params: dict | None = None,
    defaults: dict | None = None,
    secrets: list[str] | None = None,
    session_mode: str = "isolated",
):
    """Create a standard mock WorkflowRun + Workflow pair for testing advance_workflow."""
    run_id = uuid.uuid4()
    run = MagicMock()
    run.id = run_id
    run.workflow_id = "test-wf"
    run.status = "running"
    run.bot_id = "test-bot"
    run.channel_id = None
    run.session_id = None
    run.session_mode = session_mode
    run.params = params or {}
    run.step_states = [
        {
            "status": "pending",
            "result": None,
            "task_id": None,
            "error": None,
            "started_at": None,
            "completed_at": None,
        }
        for _ in steps
    ]
    run.workflow_snapshot = {
        "steps": steps,
        "defaults": defaults or {},
        "secrets": secrets or [],
    }
    run.current_step_index = 0
    run.error = None
    run.completed_at = None
    run.dispatch_type = "none"
    run.dispatch_config = None

    workflow = MagicMock()
    workflow.id = "test-wf"
    workflow.name = "Test Workflow"
    workflow.steps = steps
    workflow.defaults = defaults or {}
    workflow.secrets = secrets or []
    workflow.session_mode = session_mode

    return run_id, run, workflow


def _make_mock_db(run, workflow):
    """Create mock DB session that returns the correct objects."""
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(
        side_effect=lambda model, id_, **kw: {
            "WorkflowRun": run,
            "Workflow": workflow,
        }.get(model.__name__, None)
    )
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


# ---------------------------------------------------------------------------
# Tool step tests
# ---------------------------------------------------------------------------

class TestToolStepExecution:
    """Tests for type=tool step inline execution."""

    @pytest.mark.asyncio
    async def test_tool_step_success(self):
        """Tool step calls call_local_tool and stores result."""
        steps = [{"id": "fetch", "type": "tool", "tool_name": "web_search", "tool_args": {"query": "test"}}]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call,
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
            patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock),
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            mock_call.return_value = '{"results": ["item1", "item2"]}'

            await advance_workflow(run_id)

        # Step should be done with result
        assert run.step_states[0]["status"] == "done"
        assert run.step_states[0]["result"] == '{"results": ["item1", "item2"]}'
        assert run.step_states[0]["started_at"] is not None
        assert run.step_states[0]["completed_at"] is not None
        # call_local_tool called with tool_name and JSON args
        mock_call.assert_called_once_with("web_search", json.dumps({"query": "test"}))

    @pytest.mark.asyncio
    async def test_tool_step_missing_tool_name(self):
        """Tool step without tool_name should fail immediately."""
        steps = [{"id": "bad", "type": "tool"}]  # No tool_name
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)

            await advance_workflow(run_id)

        assert run.step_states[0]["status"] == "failed"
        assert "tool_name" in run.step_states[0]["error"]
        assert run.status == "failed"
        assert "tool_name" in run.error

    @pytest.mark.asyncio
    async def test_tool_step_template_substitution(self):
        """Tool args should support {{param}} template variables."""
        steps = [{"id": "search", "type": "tool", "tool_name": "web_search", "tool_args": {"query": "{{topic}}"}}]
        run_id, run, workflow = _make_run(steps, params={"topic": "quantum computing"})
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call,
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
            patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock),
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            mock_call.return_value = "search results"

            await advance_workflow(run_id)

        # Verify the template was rendered in the args
        mock_call.assert_called_once()
        call_args = json.loads(mock_call.call_args[0][1])
        assert call_args["query"] == "quantum computing"

    @pytest.mark.asyncio
    async def test_tool_step_failure_abort(self):
        """Tool step failure with on_failure=abort should fail the run."""
        steps = [{"id": "fail", "type": "tool", "tool_name": "bad_tool", "on_failure": "abort"}]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call,
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            mock_call.side_effect = RuntimeError("Tool not found")

            await advance_workflow(run_id)

        assert run.step_states[0]["status"] == "failed"
        assert "Tool not found" in run.step_states[0]["error"]
        assert run.status == "failed"
        assert run.completed_at is not None

    @pytest.mark.asyncio
    async def test_tool_step_failure_continue(self):
        """Tool step failure with on_failure=continue should proceed to next step."""
        steps = [
            {"id": "fail", "type": "tool", "tool_name": "bad_tool", "on_failure": "continue"},
            {"id": "next", "type": "tool", "tool_name": "good_tool"},
        ]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call,
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
            patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock),
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            # First call fails, second succeeds
            mock_call.side_effect = [RuntimeError("Tool not found"), "success"]

            await advance_workflow(run_id)

        # First step failed but continued
        assert run.step_states[0]["status"] == "failed"
        assert run.step_states[0]["error"] == "Tool not found"
        # Second step succeeded
        assert run.step_states[1]["status"] == "done"
        assert run.step_states[1]["result"] == "success"

    @pytest.mark.asyncio
    async def test_tool_step_result_truncation(self):
        """Tool step result should be truncated to result_max_chars."""
        long_result = "x" * 5000
        steps = [{"id": "big", "type": "tool", "tool_name": "web_search", "result_max_chars": 100}]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call,
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
            patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock),
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            mock_call.return_value = long_result

            await advance_workflow(run_id)

        assert run.step_states[0]["status"] == "done"
        assert len(run.step_states[0]["result"]) == 100

    @pytest.mark.asyncio
    async def test_tool_step_empty_tool_args(self):
        """Tool step with no tool_args should pass empty JSON object."""
        steps = [{"id": "status", "type": "tool", "tool_name": "get_system_status"}]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call,
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
            patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock),
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            mock_call.return_value = '{"status": "ok"}'

            await advance_workflow(run_id)

        mock_call.assert_called_once_with("get_system_status", "{}")

    @pytest.mark.asyncio
    async def test_tool_step_no_execution_cap(self):
        """Tool steps should NOT count toward the execution cap (they don't create tasks)."""
        steps = [{"id": "s", "type": "tool", "tool_name": "get_system_status"}]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call,
            patch("app.services.workflow_executor.settings") as mock_settings,
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
            patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock),
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            mock_call.return_value = "ok"
            # Set cap to 0 — agent steps would be blocked, but tool steps bypass
            mock_settings.WORKFLOW_MAX_TASK_EXECUTIONS = 0

            await advance_workflow(run_id)

        # Tool step still executes despite cap=0
        assert run.step_states[0]["status"] == "done"


# ---------------------------------------------------------------------------
# Exec step tests
# ---------------------------------------------------------------------------

class TestExecStepExecution:
    """Tests for type=exec step task creation."""

    @pytest.mark.asyncio
    async def test_exec_step_creates_task(self):
        """Exec step should create a Task with task_type=exec and command in execution_config."""
        steps = [{"id": "run-cmd", "type": "exec", "prompt": "echo hello"}]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        mock_task = MagicMock()
        mock_task.id = uuid.uuid4()

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.services.workflow_executor._build_step_task", return_value=mock_task) as mock_build,
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)

            await advance_workflow(run_id)

        # Step should be running with a task
        assert run.step_states[0]["status"] == "running"
        assert run.step_states[0]["task_id"] == str(mock_task.id)
        assert run.step_states[0]["started_at"] is not None
        mock_db.add.assert_called_once_with(mock_task)
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_exec_step_task_has_command(self):
        """_build_step_task should put the rendered prompt as command in execution_config."""
        from app.services.workflow_executor import _build_step_task

        run = MagicMock()
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"
        run.bot_id = "test-bot"
        run.channel_id = None
        run.session_id = None
        run.session_mode = "isolated"
        run.params = {"name": "world"}
        run.step_states = [
            {"status": "pending", "result": None, "task_id": None,
             "error": None, "started_at": None, "completed_at": None},
        ]

        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.name = "Test"
        workflow.defaults = {}
        workflow.secrets = []

        step_def = {"id": "greet", "type": "exec", "prompt": "echo hello {{name}}"}
        steps = [step_def]

        task = _build_step_task(run, workflow, step_def, 0, steps, {})

        assert task.task_type == "exec"
        assert task.execution_config["command"] == "echo hello world"

    @pytest.mark.asyncio
    async def test_exec_step_working_directory(self):
        """_build_step_task should include working_directory for exec steps."""
        from app.services.workflow_executor import _build_step_task

        run = MagicMock()
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"
        run.bot_id = "test-bot"
        run.channel_id = None
        run.session_id = None
        run.session_mode = "isolated"
        run.params = {}
        run.step_states = [
            {"status": "pending", "result": None, "task_id": None,
             "error": None, "started_at": None, "completed_at": None},
        ]

        workflow = MagicMock()
        workflow.id = "test-wf"
        workflow.name = "Test"
        workflow.defaults = {}
        workflow.secrets = []

        step_def = {
            "id": "deploy",
            "type": "exec",
            "prompt": "make deploy",
            "working_directory": "/opt/app",
            "args": ["--verbose"],
        }

        task = _build_step_task(run, workflow, step_def, 0, [step_def], {})

        assert task.task_type == "exec"
        assert task.execution_config["command"] == "make deploy"
        assert task.execution_config["working_directory"] == "/opt/app"
        assert task.execution_config["args"] == ["--verbose"]

    @pytest.mark.asyncio
    async def test_exec_step_subject_to_execution_cap(self):
        """Exec steps should count toward execution cap (they create tasks)."""
        steps = [{"id": "cmd", "type": "exec", "prompt": "echo test"}]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.services.workflow_executor.settings") as mock_settings,
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            mock_settings.WORKFLOW_MAX_TASK_EXECUTIONS = 0  # Cap reached

            await advance_workflow(run_id)

        # Run should be failed due to execution cap
        assert run.status == "failed"
        assert "Execution cap" in run.error


# ---------------------------------------------------------------------------
# Mixed step type workflows
# ---------------------------------------------------------------------------

class TestMixedStepTypeWorkflows:
    """Tests for workflows with multiple step types."""

    @pytest.mark.asyncio
    async def test_tool_then_agent_step(self):
        """Tool step completes inline, then agent step creates a task."""
        steps = [
            {"id": "gather", "type": "tool", "tool_name": "get_system_status"},
            {"id": "analyze", "type": "agent", "prompt": "Analyze: {{steps.gather.result}}"},
        ]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        mock_task = MagicMock()
        mock_task.id = uuid.uuid4()

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call,
            patch("app.services.workflow_executor._build_step_task", return_value=mock_task) as mock_build,
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            mock_call.return_value = '{"cpu": 45, "memory": 72}'

            await advance_workflow(run_id)

        # First step (tool) done inline
        assert run.step_states[0]["status"] == "done"
        assert run.step_states[0]["result"] == '{"cpu": 45, "memory": 72}'
        # Second step (agent) created a task
        assert run.step_states[1]["status"] == "running"
        assert run.step_states[1]["task_id"] == str(mock_task.id)

    @pytest.mark.asyncio
    async def test_multiple_tool_steps_complete_in_one_pass(self):
        """Multiple consecutive tool steps should all complete in a single advance call."""
        steps = [
            {"id": "s1", "type": "tool", "tool_name": "get_system_status"},
            {"id": "s2", "type": "tool", "tool_name": "list_tasks", "tool_args": {"status": "running"}},
        ]
        run_id, run, workflow = _make_run(steps)
        mock_db = _make_mock_db(run, workflow)

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.tools.registry.call_local_tool", new_callable=AsyncMock) as mock_call,
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
            patch("app.services.workflow_executor._fire_after_workflow_complete", new_callable=AsyncMock),
        ):
            mock_session.return_value = _mock_session_ctx(mock_db)
            mock_call.side_effect = ['{"status": "ok"}', '{"tasks": []}']

            await advance_workflow(run_id)

        # Both tool steps should be done
        assert run.step_states[0]["status"] == "done"
        assert run.step_states[1]["status"] == "done"
        # Workflow should be complete
        assert run.status == "complete"
