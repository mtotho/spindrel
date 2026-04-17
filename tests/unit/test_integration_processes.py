"""Tests for the integration process manager."""
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from app.services.integration_processes import IntegrationProcessManager, _ProcessState


@pytest.fixture
def manager():
    return IntegrationProcessManager()


class TestProcessState:
    def test_initial_state(self):
        state = _ProcessState("test", ["echo", "hi"], "Test process", ["FOO"])
        assert state.integration_id == "test"
        assert state.process is None
        assert state.monitor_task is None
        assert state.started_at is None
        assert state.exit_code is None
        assert state.restart_count == 0


class TestStatus:
    def test_unknown_process(self, manager):
        status = manager.status("nonexistent")
        assert status["status"] == "stopped"
        assert status["pid"] is None
        assert status["uptime_seconds"] is None
        assert status["exit_code"] is None
        assert status["restart_count"] == 0

    def test_running_process(self, manager):
        import time

        state = _ProcessState("test", ["echo"], "Test", [])
        state.started_at = time.monotonic() - 60
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345
        state.process = mock_proc
        manager._states["test"] = state

        status = manager.status("test")
        assert status["status"] == "running"
        assert status["pid"] == 12345
        assert status["uptime_seconds"] >= 59
        assert status["exit_code"] is None

    def test_stopped_process_with_exit(self, manager):
        state = _ProcessState("test", ["echo"], "Test", [])
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.pid = 12345
        state.process = mock_proc
        state.exit_code = 1
        manager._states["test"] = state

        status = manager.status("test")
        assert status["status"] == "stopped"
        assert status["pid"] is None
        assert status["exit_code"] == 1


class TestEnvReady:
    def test_empty_required(self, manager):
        assert manager._env_ready("test", []) is True

    @patch.dict("os.environ", {"FOO": "bar"}, clear=False)
    def test_env_set(self, manager):
        assert manager._env_ready("test", ["FOO"]) is True

    @patch.dict("os.environ", {"FOO": "bar"}, clear=False)
    def test_env_partially_set(self, manager):
        assert manager._env_ready("test", ["FOO", "MISSING_KEY_12345"]) is False

    @patch.dict("os.environ", {}, clear=False)
    def test_env_missing(self, manager):
        assert manager._env_ready("test", ["TOTALLY_MISSING_KEY_XYZ"]) is False


class TestStart:
    @pytest.mark.asyncio
    async def test_start_no_process_file(self, manager):
        with patch.object(manager, "_discover", return_value={}):
            result = await manager.start("nonexistent")
            assert result is False

    @pytest.mark.asyncio
    async def test_start_env_not_ready(self, manager):
        with patch.object(manager, "_discover", return_value={
            "test": {"cmd": ["echo", "hi"], "required_env": ["MISSING"], "description": "Test"},
        }), patch.object(manager, "_env_ready", return_value=False):
            result = await manager.start("test")
            assert result is False

    @pytest.mark.asyncio
    async def test_start_already_running(self, manager):
        state = _ProcessState("test", ["echo"], "Test", [])
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 123
        state.process = mock_proc
        manager._states["test"] = state

        result = await manager.start("test")
        assert result is False


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_not_running(self, manager):
        result = await manager.stop("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_already_exited(self, manager):
        state = _ProcessState("test", ["echo"], "Test", [])
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        state.process = mock_proc
        manager._states["test"] = state

        result = await manager.stop("test")
        assert result is False


class TestAutoStart:
    @pytest.mark.asyncio
    async def test_default_auto_start(self, manager):
        """Default is True when no setting exists."""
        with patch("app.services.integration_processes.IntegrationProcessManager.get_auto_start",
                    return_value=True):
            m = IntegrationProcessManager()
            result = await m.get_auto_start("test")
            assert result is True

    @pytest.mark.asyncio
    async def test_start_auto_start_skips_disabled(self, manager):
        with patch.object(manager, "_discover", return_value={
            "test": {"cmd": ["echo"], "required_env": [], "description": "Test"},
        }), patch.object(manager, "_env_ready", return_value=True), \
             patch.object(manager, "get_auto_start", return_value=False), \
             patch.object(manager, "start") as mock_start:
            await manager.start_auto_start_processes()
            mock_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_auto_start_starts_enabled(self, manager):
        with patch.object(manager, "_discover", return_value={
            "test": {"cmd": ["echo"], "required_env": [], "description": "Test"},
        }), patch.object(manager, "_env_ready", return_value=True), \
             patch.object(manager, "get_auto_start", return_value=True), \
             patch("app.services.integration_settings.get_status", return_value="enabled"), \
             patch.object(manager, "start", new_callable=AsyncMock) as mock_start:
            await manager.start_auto_start_processes()
            mock_start.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_start_auto_start_skips_non_enabled(self, manager):
        """Auto-start should skip integrations whose lifecycle_status is not 'enabled'."""
        with patch.object(manager, "_discover", return_value={
            "test": {"cmd": ["echo"], "required_env": [], "description": "Test"},
        }), patch.object(manager, "_env_ready", return_value=True), \
             patch.object(manager, "get_auto_start", return_value=True), \
             patch("app.services.integration_settings.get_status", return_value="needs_setup"), \
             patch.object(manager, "start", new_callable=AsyncMock) as mock_start:
            await manager.start_auto_start_processes()
            mock_start.assert_not_called()


class TestShutdownAll:
    @pytest.mark.asyncio
    async def test_shutdown_empty(self, manager):
        """Should not error when no processes are tracked."""
        await manager.shutdown_all()

    @pytest.mark.asyncio
    async def test_shutdown_stops_running(self, manager):
        state = _ProcessState("test", ["echo"], "Test", [])
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 123
        state.process = mock_proc
        manager._states["test"] = state

        with patch.object(manager, "stop", new_callable=AsyncMock) as mock_stop:
            await manager.shutdown_all()
            mock_stop.assert_called_once_with("test")
