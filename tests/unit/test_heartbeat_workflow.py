"""Tests for heartbeat → workflow integration."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.heartbeat import _fire_heartbeat_workflow, _heartbeat_task_execution_config, fire_heartbeat


def _make_heartbeat(**overrides):
    """Create a mock ChannelHeartbeat with sensible defaults."""
    hb = MagicMock()
    hb.id = uuid.uuid4()
    hb.channel_id = uuid.uuid4()
    hb.workflow_id = overrides.get("workflow_id", "test-workflow")
    hb.interval_minutes = overrides.get("interval_minutes", 60)
    hb.dispatch_results = overrides.get("dispatch_results", False)
    hb.dispatch_mode = overrides.get("dispatch_mode", "always")
    hb.run_count = overrides.get("run_count", 0)
    hb.quiet_start = None
    hb.quiet_end = None
    hb.timezone = None
    hb.max_run_seconds = None
    hb.workflow_session_mode = overrides.get("workflow_session_mode", None)
    hb.skip_tool_approval = overrides.get("skip_tool_approval", False)
    hb.execution_config = overrides.get("execution_config", None)
    hb.model = overrides.get("model", "")
    hb.model_provider_id = overrides.get("model_provider_id", None)
    hb.fallback_models = overrides.get("fallback_models", [])
    hb.harness_effort = overrides.get("harness_effort", None)
    return hb


def _make_channel(bot_id="test-bot"):
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.bot_id = bot_id
    ch.client_id = "heartbeat"
    ch.dispatch_config = None
    ch.integration = None
    ch.active_session_id = None
    ch.name = "test-channel"
    return ch


def _make_dedup_db(has_active_run: bool = False):
    """Create a mock DB session for the dedup check at the top of _fire_heartbeat_workflow."""
    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = uuid.uuid4() if has_active_run else None
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


class TestFireHeartbeatDelegatesToWorkflow:
    """When workflow_id is set, fire_heartbeat should call _fire_heartbeat_workflow."""

    @pytest.mark.asyncio
    async def test_fire_heartbeat_calls_workflow_mode(self):
        hb = _make_heartbeat(workflow_id="my-workflow")

        with patch("app.services.heartbeat._fire_heartbeat_workflow", new_callable=AsyncMock) as mock_wf:
            await fire_heartbeat(hb)
            mock_wf.assert_called_once()
            call_args = mock_wf.call_args
            assert call_args[0][0] is hb  # first positional arg is the heartbeat

    @pytest.mark.asyncio
    async def test_fire_heartbeat_skips_workflow_when_no_id(self):
        """When workflow_id is None, should NOT call workflow mode."""
        hb = _make_heartbeat(workflow_id=None)

        with (
            patch("app.services.heartbeat._fire_heartbeat_workflow", new_callable=AsyncMock) as mock_wf,
            patch("app.services.heartbeat.async_session") as mock_session_factory,
        ):
            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)
            # Return None for channel lookup so it exits early
            mock_db.get = AsyncMock(return_value=None)
            mock_session_factory.return_value = mock_db

            await fire_heartbeat(hb)
            mock_wf.assert_not_called()

    def test_prompt_heartbeat_task_config_preserves_selected_tools(self):
        hb = _make_heartbeat(
            workflow_id=None,
            skip_tool_approval=True,
            execution_config={
                "tools": ["sonarr_calendar", "qbit_torrents"],
                "skills": ["widgets/spatial_stewardship"],
                "session_target": {"mode": "existing", "session_id": str(uuid.uuid4())},
            },
            model="gpt-test",
            model_provider_id="provider-test",
            fallback_models=[{"model": "fallback"}],
        )
        prepared = MagicMock()
        prepared.heartbeat_preamble = "heartbeat preamble"
        prepared.model_override = "gpt-test"
        prepared.provider_id_override = "provider-test"
        prepared.fallback_models = [{"model": "fallback"}]
        prepared.execution_policy = {"tool_surface": "focused_escape"}
        prepared.injected_tools = [{"function": {"name": "report_issue"}}]
        prepared.run_id = uuid.uuid4()
        prepared.dispatch_mode = "always"
        prepared.trigger_rag_loop = False
        prepared.repetition_detected = False

        cfg = _heartbeat_task_execution_config(hb, prepared)

        assert cfg["tools"] == ["sonarr_calendar", "qbit_torrents"]
        assert cfg["skills"] == ["widgets/spatial_stewardship"]
        assert cfg["session_target"]["mode"] == "existing"
        assert cfg["skip_tool_approval"] is True
        assert cfg["system_preamble"] == "heartbeat preamble"
        assert cfg["model_override"] == "gpt-test"
        assert cfg["model_provider_id_override"] == "provider-test"
        assert cfg["run_control_policy"]["tool_surface"] == "focused_escape"
        assert cfg["run_control_policy"]["required_tools"] == [
            "sonarr_calendar",
            "qbit_torrents",
        ]
        assert cfg["additional_tool_schemas"][0]["function"]["name"] == "report_issue"
        assert cfg["heartbeat"]["heartbeat_run_id"] == str(prepared.run_id)


class TestFireHeartbeatWorkflow:
    """Test _fire_heartbeat_workflow directly."""

    @pytest.mark.asyncio
    async def test_triggers_workflow_and_records_success(self):
        hb = _make_heartbeat(workflow_id="test-wf")
        channel = _make_channel()
        now = datetime.now(timezone.utc)

        mock_wf_run = MagicMock()
        mock_wf_run.id = uuid.uuid4()

        mock_run_record = MagicMock()
        mock_run_record.id = uuid.uuid4()

        mock_heartbeat_obj = MagicMock()
        mock_heartbeat_obj.interval_minutes = 60
        mock_heartbeat_obj.quiet_start = None
        mock_heartbeat_obj.quiet_end = None
        mock_heartbeat_obj.timezone = None
        mock_heartbeat_obj.run_count = 5

        # Build a mock DB that handles different get() calls
        session_idx = [0]

        def make_mock_db():
            session_idx[0] += 1
            if session_idx[0] == 1:
                return _make_dedup_db(has_active_run=False)

            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)

            async def mock_get(model, id_):
                name = model.__name__ if hasattr(model, "__name__") else str(model)
                if name == "Channel":
                    return channel
                if name == "ChannelHeartbeat":
                    return mock_heartbeat_obj
                if name == "HeartbeatRun":
                    return mock_run_record
                return None

            mock_db.get = AsyncMock(side_effect=mock_get)
            mock_db.add = MagicMock()
            mock_db.commit = AsyncMock()
            mock_db.refresh = AsyncMock()
            return mock_db

        with (
            patch("app.services.heartbeat.async_session", side_effect=lambda: make_mock_db()),
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=mock_wf_run) as mock_trigger,
        ):
            await _fire_heartbeat_workflow(hb, now)

            # Verify trigger_workflow was called correctly
            mock_trigger.assert_called_once_with(
                "test-wf",
                {},
                bot_id=channel.bot_id,
                channel_id=channel.id,
                triggered_by="heartbeat",
                dispatch_type="none",
                dispatch_config=None,
                session_mode=None,
            )

    @pytest.mark.asyncio
    async def test_records_failure_when_trigger_raises(self):
        hb = _make_heartbeat(workflow_id="bad-wf")
        channel = _make_channel()
        now = datetime.now(timezone.utc)

        mock_run_record = MagicMock()
        mock_run_record.id = uuid.uuid4()
        mock_run_record.result = None
        mock_run_record.error = None
        mock_run_record.status = "running"
        mock_run_record.completed_at = None

        mock_heartbeat_obj = MagicMock()
        mock_heartbeat_obj.interval_minutes = 60
        mock_heartbeat_obj.quiet_start = None
        mock_heartbeat_obj.quiet_end = None
        mock_heartbeat_obj.timezone = None
        mock_heartbeat_obj.run_count = 0

        session_idx = [0]

        def make_mock_db():
            session_idx[0] += 1
            if session_idx[0] == 1:
                return _make_dedup_db(has_active_run=False)

            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)

            async def mock_get(model, id_):
                name = model.__name__ if hasattr(model, "__name__") else str(model)
                if name == "Channel":
                    return channel
                if name == "ChannelHeartbeat":
                    return mock_heartbeat_obj
                if name == "HeartbeatRun":
                    return mock_run_record
                return None

            mock_db.get = AsyncMock(side_effect=mock_get)
            mock_db.add = MagicMock()
            mock_db.commit = AsyncMock()
            mock_db.refresh = AsyncMock()
            return mock_db

        with (
            patch("app.services.heartbeat.async_session", side_effect=lambda: make_mock_db()),
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, side_effect=ValueError("Workflow 'bad-wf' not found")),
        ):
            await _fire_heartbeat_workflow(hb, now)

            # The heartbeat run record should have been marked as failed
            assert mock_run_record.status == "failed"
            assert "not found" in (mock_run_record.error or "")

            # Heartbeat tracking should still be updated
            assert mock_heartbeat_obj.run_count == 1
            assert mock_heartbeat_obj.last_error is not None
            assert "not found" in mock_heartbeat_obj.last_error

    @pytest.mark.asyncio
    async def test_success_records_result_and_increments_count(self):
        """On successful trigger, heartbeat run_count increments and result is set."""
        hb = _make_heartbeat(workflow_id="good-wf")
        channel = _make_channel()
        now = datetime.now(timezone.utc)

        mock_wf_run = MagicMock()
        mock_wf_run.id = uuid.uuid4()

        mock_run_record = MagicMock()
        mock_run_record.id = uuid.uuid4()
        mock_run_record.result = None
        mock_run_record.status = "running"

        mock_heartbeat_obj = MagicMock()
        mock_heartbeat_obj.interval_minutes = 60
        mock_heartbeat_obj.quiet_start = None
        mock_heartbeat_obj.quiet_end = None
        mock_heartbeat_obj.timezone = None
        mock_heartbeat_obj.run_count = 3

        session_idx = [0]

        def make_mock_db():
            session_idx[0] += 1
            if session_idx[0] == 1:
                return _make_dedup_db(has_active_run=False)

            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)

            async def mock_get(model, id_):
                name = model.__name__ if hasattr(model, "__name__") else str(model)
                if name == "Channel":
                    return channel
                if name == "ChannelHeartbeat":
                    return mock_heartbeat_obj
                if name == "HeartbeatRun":
                    return mock_run_record
                return None

            mock_db.get = AsyncMock(side_effect=mock_get)
            mock_db.add = MagicMock()
            mock_db.commit = AsyncMock()
            mock_db.refresh = AsyncMock()
            return mock_db

        with (
            patch("app.services.heartbeat.async_session", side_effect=lambda: make_mock_db()),
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=mock_wf_run),
        ):
            await _fire_heartbeat_workflow(hb, now)

            assert mock_run_record.status == "complete"
            assert str(mock_wf_run.id) in mock_run_record.result
            assert mock_heartbeat_obj.run_count == 4
            assert mock_heartbeat_obj.last_error is None

    @pytest.mark.asyncio
    async def test_channel_not_found_returns_early(self):
        hb = _make_heartbeat(workflow_id="test-wf")
        now = datetime.now(timezone.utc)

        session_idx = [0]

        def make_mock_db():
            session_idx[0] += 1
            if session_idx[0] == 1:
                return _make_dedup_db(has_active_run=False)

            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)
            mock_db.get = AsyncMock(return_value=None)
            return mock_db

        with (
            patch("app.services.heartbeat.async_session", side_effect=lambda: make_mock_db()),
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock) as mock_trigger,
        ):
            await _fire_heartbeat_workflow(hb, now)
            mock_trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_config_passed_through(self):
        """When dispatch_results is True and channel has config, it should be passed to trigger_workflow."""
        channel = _make_channel()
        channel.dispatch_config = {"channel": "C123", "thread_ts": "old-thread"}
        channel.integration = "slack"

        hb = _make_heartbeat(workflow_id="test-wf", dispatch_results=True)

        mock_wf_run = MagicMock()
        mock_wf_run.id = uuid.uuid4()

        mock_run_record = MagicMock()
        mock_run_record.id = uuid.uuid4()

        mock_heartbeat_obj = MagicMock()
        mock_heartbeat_obj.interval_minutes = 60
        mock_heartbeat_obj.quiet_start = None
        mock_heartbeat_obj.quiet_end = None
        mock_heartbeat_obj.timezone = None
        mock_heartbeat_obj.run_count = 0

        session_idx = [0]

        def make_mock_db():
            session_idx[0] += 1
            if session_idx[0] == 1:
                return _make_dedup_db(has_active_run=False)

            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)

            async def mock_get(model, id_):
                name = model.__name__ if hasattr(model, "__name__") else str(model)
                if name == "Channel":
                    return channel
                if name == "ChannelHeartbeat":
                    return mock_heartbeat_obj
                if name == "HeartbeatRun":
                    return mock_run_record
                return None

            mock_db.get = AsyncMock(side_effect=mock_get)
            mock_db.add = MagicMock()
            mock_db.commit = AsyncMock()
            mock_db.refresh = AsyncMock()
            return mock_db

        now = datetime.now(timezone.utc)
        with (
            patch("app.services.heartbeat.async_session", side_effect=lambda: make_mock_db()),
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=mock_wf_run) as mock_trigger,
        ):
            await _fire_heartbeat_workflow(hb, now)

            call_kwargs = mock_trigger.call_args[1]
            assert call_kwargs["dispatch_type"] == "slack"
            # thread_ts should be stripped, reply_in_thread should be False
            assert "thread_ts" not in call_kwargs["dispatch_config"]
            assert call_kwargs["dispatch_config"]["reply_in_thread"] is False
            assert call_kwargs["dispatch_config"]["channel"] == "C123"


# ---------------------------------------------------------------------------
# Test: Heartbeat workflow dedup — skip when active run exists
# ---------------------------------------------------------------------------

class TestHeartbeatWorkflowDedup:
    """Heartbeat should NOT trigger a workflow if there's already an active run."""

    @pytest.mark.asyncio
    async def test_skips_when_active_run_exists(self):
        hb = _make_heartbeat(workflow_id="test-wf")
        now = datetime.now(timezone.utc)

        with (
            patch("app.services.heartbeat.async_session", return_value=_make_dedup_db(has_active_run=True)),
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock) as mock_trigger,
        ):
            await _fire_heartbeat_workflow(hb, now)
            mock_trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggers_when_no_active_run(self):
        hb = _make_heartbeat(workflow_id="test-wf")
        channel = _make_channel()
        now = datetime.now(timezone.utc)

        mock_wf_run = MagicMock()
        mock_wf_run.id = uuid.uuid4()

        mock_run_record = MagicMock()
        mock_run_record.id = uuid.uuid4()

        mock_heartbeat_obj = MagicMock()
        mock_heartbeat_obj.interval_minutes = 60
        mock_heartbeat_obj.quiet_start = None
        mock_heartbeat_obj.quiet_end = None
        mock_heartbeat_obj.timezone = None
        mock_heartbeat_obj.run_count = 0

        session_idx = [0]

        def make_mock_db():
            session_idx[0] += 1
            if session_idx[0] == 1:
                return _make_dedup_db(has_active_run=False)

            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)

            async def mock_get(model, id_):
                name = model.__name__ if hasattr(model, "__name__") else str(model)
                if name == "Channel":
                    return channel
                if name == "ChannelHeartbeat":
                    return mock_heartbeat_obj
                if name == "HeartbeatRun":
                    return mock_run_record
                return None

            mock_db.get = AsyncMock(side_effect=mock_get)
            mock_db.add = MagicMock()
            mock_db.commit = AsyncMock()
            mock_db.refresh = AsyncMock()
            return mock_db

        with (
            patch("app.services.heartbeat.async_session", side_effect=lambda: make_mock_db()),
            patch("app.services.workflow_executor.trigger_workflow", new_callable=AsyncMock, return_value=mock_wf_run) as mock_trigger,
        ):
            await _fire_heartbeat_workflow(hb, now)
            mock_trigger.assert_called_once()
