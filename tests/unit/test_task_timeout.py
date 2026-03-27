"""Unit tests for task/heartbeat timeout resolution and stuck task recovery."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agent.tasks import resolve_task_timeout, recover_stuck_tasks
from app.services.heartbeat import resolve_heartbeat_timeout
from app.db.models import Channel, ChannelHeartbeat, Task


def _make_task(**kwargs) -> Task:
    """Create a minimal Task mock."""
    t = MagicMock(spec=Task)
    t.id = kwargs.get("id", uuid.uuid4())
    t.max_run_seconds = kwargs.get("max_run_seconds", None)
    t.channel_id = kwargs.get("channel_id", None)
    t.run_at = kwargs.get("run_at", None)
    t.status = kwargs.get("status", "pending")
    return t


def _make_channel(**kwargs) -> Channel:
    """Create a minimal Channel mock."""
    ch = MagicMock(spec=Channel)
    ch.id = kwargs.get("id", uuid.uuid4())
    ch.task_max_run_seconds = kwargs.get("task_max_run_seconds", None)
    return ch


def _make_heartbeat(**kwargs) -> ChannelHeartbeat:
    """Create a minimal ChannelHeartbeat mock."""
    hb = MagicMock(spec=ChannelHeartbeat)
    hb.id = kwargs.get("id", uuid.uuid4())
    hb.max_run_seconds = kwargs.get("max_run_seconds", None)
    return hb


class TestResolveTaskTimeout:
    """Test the cascade: task > channel > global."""

    def test_task_override_wins(self):
        task = _make_task(max_run_seconds=60)
        channel = _make_channel(task_max_run_seconds=300)
        assert resolve_task_timeout(task, channel) == 60

    def test_channel_override_when_no_task(self):
        task = _make_task(max_run_seconds=None)
        channel = _make_channel(task_max_run_seconds=300)
        assert resolve_task_timeout(task, channel) == 300

    def test_global_default_when_no_overrides(self):
        task = _make_task(max_run_seconds=None)
        channel = _make_channel(task_max_run_seconds=None)
        with patch("app.agent.tasks.settings") as mock_settings:
            mock_settings.TASK_MAX_RUN_SECONDS = 1200
            assert resolve_task_timeout(task, channel) == 1200

    def test_global_default_no_channel(self):
        task = _make_task(max_run_seconds=None)
        with patch("app.agent.tasks.settings") as mock_settings:
            mock_settings.TASK_MAX_RUN_SECONDS = 1200
            assert resolve_task_timeout(task, None) == 1200

    def test_task_override_no_channel(self):
        task = _make_task(max_run_seconds=120)
        assert resolve_task_timeout(task, None) == 120


class TestResolveHeartbeatTimeout:
    """Test heartbeat timeout: hb > global."""

    def test_heartbeat_override(self):
        hb = _make_heartbeat(max_run_seconds=600)
        assert resolve_heartbeat_timeout(hb) == 600

    def test_global_default(self):
        hb = _make_heartbeat(max_run_seconds=None)
        with patch("app.services.heartbeat.settings") as mock_settings:
            mock_settings.TASK_MAX_RUN_SECONDS = 1200
            assert resolve_heartbeat_timeout(hb) == 1200


class TestRecoverStuckTasks:
    """Test recover_stuck_tasks identifies and marks stuck tasks."""

    @pytest.mark.asyncio
    async def test_recovers_stuck_task(self):
        """A task running longer than its timeout should be marked failed."""
        task_id = uuid.uuid4()
        old_run_at = datetime.now(timezone.utc) - timedelta(seconds=2000)

        task = Task()
        task.id = task_id
        task.status = "running"
        task.run_at = old_run_at
        task.max_run_seconds = None
        task.channel_id = None

        # Track the status update
        updated_status = {}

        async def mock_get(model, id_val):
            if id_val == task_id:
                t = MagicMock()
                t.status = "running"
                t.id = task_id
                def set_status(val):
                    updated_status["status"] = val
                type(t).status = property(lambda s: updated_status.get("status", "running"), lambda s, v: set_status(v))
                type(t).error = property(lambda s: "", lambda s, v: None)
                type(t).completed_at = property(lambda s: None, lambda s, v: None)
                return t
            return None

        class MockDB:
            async def execute(self, stmt):
                class Result:
                    def scalars(self):
                        return self
                    def all(self):
                        return [task]
                return Result()
            async def get(self, model, id_val):
                return await mock_get(model, id_val)
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        with patch("app.agent.tasks.async_session", return_value=MockDB()):
            with patch("app.agent.tasks.settings") as mock_settings:
                mock_settings.TASK_MAX_RUN_SECONDS = 1200
                await recover_stuck_tasks()

        assert updated_status.get("status") == "failed"

    @pytest.mark.asyncio
    async def test_does_not_recover_within_timeout(self):
        """A task still within its timeout should not be recovered."""
        task_id = uuid.uuid4()
        # Only 100 seconds old, well within 1200s default
        recent_run_at = datetime.now(timezone.utc) - timedelta(seconds=100)

        task = Task()
        task.id = task_id
        task.status = "running"
        task.run_at = recent_run_at
        task.max_run_seconds = None
        task.channel_id = None

        get_called = {"count": 0}

        class MockDB:
            async def execute(self, stmt):
                class Result:
                    def scalars(self):
                        return self
                    def all(self):
                        return [task]
                return Result()
            async def get(self, model, id_val):
                get_called["count"] += 1
                return None
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        with patch("app.agent.tasks.async_session", return_value=MockDB()):
            with patch("app.agent.tasks.settings") as mock_settings:
                mock_settings.TASK_MAX_RUN_SECONDS = 1200
                await recover_stuck_tasks()

        # db.get should NOT have been called for the task since it's within timeout
        assert get_called["count"] == 0

    @pytest.mark.asyncio
    async def test_no_running_tasks(self):
        """No running tasks → no recovery needed."""
        class MockDB:
            async def execute(self, stmt):
                class Result:
                    def scalars(self):
                        return self
                    def all(self):
                        return []
                return Result()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        with patch("app.agent.tasks.async_session", return_value=MockDB()):
            await recover_stuck_tasks()  # should not raise
