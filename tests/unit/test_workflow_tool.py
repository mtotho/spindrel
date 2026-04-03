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
        """get_run should return run status, progress, step IDs/types, and result previews."""
        run_id = uuid.uuid4()
        run = MagicMock()
        run.id = run_id
        run.workflow_id = "test-wf"
        run.status = "running"
        run.session_mode = "isolated"
        run.error = None
        run.params = {"topic": "auth"}
        run.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        run.completed_at = None
        run.workflow_snapshot = {
            "steps": [
                {"id": "research", "type": "agent", "prompt": "Research {{topic}}"},
                {"id": "compile", "type": "agent", "prompt": "Compile report"},
            ]
        }
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
        assert result["session_mode"] == "isolated"
        assert result["params"] == {"topic": "auth"}
        assert result["done"] == 1
        assert len(result["steps"]) == 2
        # Step should include id and type from snapshot
        assert result["steps"][0]["id"] == "research"
        assert result["steps"][0]["type"] == "agent"
        assert result["steps"][0]["status"] == "done"
        assert "Step 1 done" in result["steps"][0]["result_preview"]
        assert result["steps"][1]["id"] == "compile"

    @pytest.mark.asyncio
    async def test_get_run_include_definitions(self):
        """include_definitions=True should include step prompts, tool_name, conditions."""
        run_id = uuid.uuid4()
        run = MagicMock()
        run.id = run_id
        run.workflow_id = "test-wf"
        run.status = "complete"
        run.session_mode = "isolated"
        run.error = None
        run.params = {}
        run.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        run.completed_at = datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc)
        run.workflow_snapshot = {
            "steps": [
                {"id": "fetch", "type": "tool", "tool_name": "web_search",
                 "tool_args": {"query": "test"}, "prompt": ""},
                {"id": "analyze", "type": "agent", "prompt": "Analyze results",
                 "when": {"step": "fetch", "status": "done"},
                 "tools": ["web_search"], "carapaces": ["researcher"],
                 "on_failure": "continue", "model": "gemini/gemini-2.5-flash"},
            ]
        }
        run.step_states = [
            {"status": "done", "result": "search results here", "error": None,
             "started_at": "2025-01-01T00:00:00", "completed_at": "2025-01-01T00:00:01"},
            {"status": "done", "result": "analysis complete", "error": None,
             "started_at": "2025-01-01T00:00:01", "completed_at": "2025-01-01T00:01:00"},
        ]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=run)

        with patch("app.db.engine.async_session") as mock_session:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock()
            mock_session.return_value = ctx

            result = json.loads(await manage_workflow(
                action="get_run", run_id=str(run_id), include_definitions=True
            ))

        # Step 0: tool step — should include tool_name/tool_args
        step0 = result["steps"][0]
        assert step0["type"] == "tool"
        assert "definition" in step0
        assert step0["definition"]["tool_name"] == "web_search"
        assert step0["definition"]["tool_args"] == {"query": "test"}

        # Step 1: agent step — should include prompt, when, tools, carapaces, etc.
        step1 = result["steps"][1]
        assert step1["type"] == "agent"
        assert "definition" in step1
        assert step1["definition"]["prompt"] == "Analyze results"
        assert step1["definition"]["when"] == {"step": "fetch", "status": "done"}
        assert step1["definition"]["tools"] == ["web_search"]
        assert step1["definition"]["carapaces"] == ["researcher"]
        assert step1["definition"]["on_failure"] == "continue"
        assert step1["definition"]["model"] == "gemini/gemini-2.5-flash"

    @pytest.mark.asyncio
    async def test_get_run_include_definitions_includes_defaults(self):
        """include_definitions=True should also return workflow-level defaults."""
        run_id = uuid.uuid4()
        run = MagicMock()
        run.id = run_id
        run.workflow_id = "test-wf"
        run.status = "complete"
        run.session_mode = "isolated"
        run.error = None
        run.params = {}
        run.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        run.completed_at = datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc)
        run.workflow_snapshot = {
            "steps": [{"id": "s1", "type": "agent", "prompt": "Do thing"}],
            "defaults": {"model": "gemini/gemini-2.5-flash", "tools": ["web_search"], "timeout": 120},
        }
        run.step_states = [
            {"status": "done", "result": "ok", "error": None,
             "started_at": "2025-01-01T00:00:00", "completed_at": "2025-01-01T00:01:00"},
        ]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=run)

        with patch("app.db.engine.async_session") as mock_session:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock()
            mock_session.return_value = ctx

            # With include_definitions — should have defaults
            result = json.loads(await manage_workflow(
                action="get_run", run_id=str(run_id), include_definitions=True
            ))
            assert "defaults" in result
            assert result["defaults"]["model"] == "gemini/gemini-2.5-flash"
            assert result["defaults"]["tools"] == ["web_search"]

            # Without include_definitions — should NOT have defaults
            result_basic = json.loads(await manage_workflow(
                action="get_run", run_id=str(run_id)
            ))
            assert "defaults" not in result_basic

    @pytest.mark.asyncio
    async def test_get_run_full_results(self):
        """full_results=True should return complete step results, not previews."""
        run_id = uuid.uuid4()
        long_result = "A" * 1500  # longer than the 500-char preview limit
        run = MagicMock()
        run.id = run_id
        run.workflow_id = "test-wf"
        run.status = "complete"
        run.session_mode = "isolated"
        run.error = None
        run.params = {}
        run.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        run.completed_at = datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc)
        run.workflow_snapshot = {"steps": [{"id": "step1", "type": "agent", "prompt": "Do work"}]}
        run.step_states = [
            {"status": "done", "result": long_result, "error": None,
             "started_at": "2025-01-01T00:00:00", "completed_at": "2025-01-01T00:01:00"},
        ]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=run)

        with patch("app.db.engine.async_session") as mock_session:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock()
            mock_session.return_value = ctx

            # Without full_results — should be truncated to preview
            result_preview = json.loads(await manage_workflow(
                action="get_run", run_id=str(run_id)
            ))
            assert "result_preview" in result_preview["steps"][0]
            assert len(result_preview["steps"][0]["result_preview"]) == 500

            # With full_results — should be complete
            result_full = json.loads(await manage_workflow(
                action="get_run", run_id=str(run_id), full_results=True
            ))
            assert "result" in result_full["steps"][0]
            assert "result_preview" not in result_full["steps"][0]
            assert len(result_full["steps"][0]["result"]) == 1500

    @pytest.mark.asyncio
    async def test_get_run_without_snapshot_uses_fallback_ids(self):
        """When workflow_snapshot is missing, step IDs should use fallback naming."""
        run_id = uuid.uuid4()
        run = MagicMock()
        run.id = run_id
        run.workflow_id = "test-wf"
        run.status = "complete"
        run.session_mode = "isolated"
        run.error = None
        run.params = {}
        run.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        run.completed_at = datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc)
        run.workflow_snapshot = None  # old run without snapshot
        run.step_states = [
            {"status": "done", "result": "ok", "error": None,
             "started_at": None, "completed_at": None},
        ]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=run)

        with patch("app.db.engine.async_session") as mock_session:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock()
            mock_session.return_value = ctx

            result = json.loads(await manage_workflow(action="get_run", run_id=str(run_id)))

        assert result["steps"][0]["id"] == "step_0"
        assert result["steps"][0]["type"] == "agent"

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


# ---------------------------------------------------------------------------
# Action redirect (LLM-confusion mitigation)
# ---------------------------------------------------------------------------

class TestActionRedirect:
    """When bots pass run_id to 'get' or 'list_runs', redirect to get_run."""

    @pytest.mark.asyncio
    async def test_get_with_run_id_redirects_to_get_run(self):
        """action=get with run_id but no id should redirect to get_run."""
        run_id = uuid.uuid4()
        run = MagicMock()
        run.id = run_id
        run.workflow_id = "test-wf"
        run.status = "running"
        run.session_mode = "isolated"
        run.error = None
        run.params = {}
        run.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        run.completed_at = None
        run.workflow_snapshot = {"steps": [{"id": "s1", "type": "agent", "prompt": "Do thing"}]}
        run.step_states = [
            {"status": "done", "result": "ok", "error": None,
             "started_at": "2025-01-01T00:00:00", "completed_at": "2025-01-01T00:01:00"},
        ]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=run)

        with patch("app.db.engine.async_session") as mock_session:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock()
            mock_session.return_value = ctx

            result = json.loads(await manage_workflow(action="get", run_id=str(run_id)))

        # Should have been redirected to get_run, returning run status
        assert result["run_id"] == str(run_id)
        assert result["status"] == "running"
        assert "steps" in result

    @pytest.mark.asyncio
    async def test_list_runs_with_run_id_redirects_to_get_run(self):
        """action=list_runs with run_id but no id should redirect to get_run."""
        run_id = uuid.uuid4()
        run = MagicMock()
        run.id = run_id
        run.workflow_id = "test-wf"
        run.status = "complete"
        run.session_mode = "isolated"
        run.error = None
        run.params = {}
        run.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        run.completed_at = datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc)
        run.workflow_snapshot = {"steps": [{"id": "s1", "type": "agent", "prompt": "Do thing"}]}
        run.step_states = [{"status": "done", "result": "ok", "error": None,
                            "started_at": None, "completed_at": None}]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=run)

        with patch("app.db.engine.async_session") as mock_session:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_db)
            ctx.__aexit__ = AsyncMock()
            mock_session.return_value = ctx

            result = json.loads(await manage_workflow(action="list_runs", run_id=str(run_id)))

        # Should have been redirected to get_run
        assert result["run_id"] == str(run_id)
        assert result["status"] == "complete"

    @pytest.mark.asyncio
    async def test_trigger_session_mode_override(self):
        """trigger with session_mode should pass it to trigger_workflow."""
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

            result = json.loads(await manage_workflow(action="trigger", id="test-wf", session_mode="shared"))
            assert result["status"] == "running"

            _, kwargs = mock_trigger.call_args
            assert kwargs.get("session_mode") == "shared"

    @pytest.mark.asyncio
    async def test_trigger_invalid_session_mode_returns_error(self):
        """trigger with invalid session_mode should return error without calling trigger_workflow."""
        result = json.loads(await manage_workflow(action="trigger", id="test-wf", session_mode="bogus"))
        assert "error" in result
        assert "session_mode" in result["error"]

    @pytest.mark.asyncio
    async def test_trigger_returns_hint(self):
        """trigger response should include a hint for monitoring."""
        run = MagicMock()
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"
        run.status = "running"
        run.step_states = [{"status": "pending"}]

        with (
            patch("app.agent.context.current_bot_id") as mock_bot_ctx,
            patch("app.agent.context.current_channel_id") as mock_ch_ctx,
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=run),
        ):
            mock_bot_ctx.get.return_value = "my-bot"
            mock_ch_ctx.get.return_value = None

            result = json.loads(await manage_workflow(action="trigger", id="test-wf"))

        assert "hint" in result
        assert "get_run" in result["hint"]
