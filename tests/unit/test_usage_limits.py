"""Tests for usage_limits.start_refresh_task."""
from unittest.mock import MagicMock, patch

import app.services.usage_limits as _mod


class TestStartRefreshTask:
    def setup_method(self):
        self._original = _mod._refresh_task

    def teardown_method(self):
        _mod._refresh_task = self._original

    def test_when_no_existing_task_then_creates_one(self):
        _mod._refresh_task = None

        with patch("app.services.usage_limits._refresh_loop", MagicMock()), \
             patch("app.services.usage_limits.asyncio.create_task", return_value=MagicMock()) as mock_ct:
            _mod.start_refresh_task()

        mock_ct.assert_called_once()
        assert _mod._refresh_task is not None

    def test_when_task_still_running_then_no_new_task(self):
        running = MagicMock()
        running.done.return_value = False
        _mod._refresh_task = running

        with patch("app.services.usage_limits.asyncio.create_task") as mock_ct:
            _mod.start_refresh_task()

        mock_ct.assert_not_called()
        assert _mod._refresh_task is running

    def test_when_task_done_then_replaces_it(self):
        done_task = MagicMock()
        done_task.done.return_value = True
        new_task = MagicMock()
        _mod._refresh_task = done_task

        with patch("app.services.usage_limits._refresh_loop"), \
             patch("app.services.usage_limits.asyncio.create_task", return_value=new_task) as mock_ct:
            _mod.start_refresh_task()

        mock_ct.assert_called_once()
        assert _mod._refresh_task is new_task
