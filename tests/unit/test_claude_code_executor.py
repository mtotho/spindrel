"""Tests for integrations.claude_code.executor — deferred task execution."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.claude_code.runner import ClaudeCodeResult


def _make_task(**overrides):
    """Create a mock Task for testing."""
    task = MagicMock()
    task.id = overrides.pop("id", uuid.uuid4())
    task.bot_id = overrides.pop("bot_id", "test_bot")
    task.prompt = overrides.pop("prompt", "fix the bug")
    task.dispatch_type = overrides.pop("dispatch_type", "none")
    task.dispatch_config = overrides.pop("dispatch_config", {})
    task.execution_config = overrides.pop("execution_config", {})
    task.callback_config = overrides.pop("callback_config", {})
    task.workspace_id = overrides.pop("workspace_id", None)
    task.workspace_file_path = overrides.pop("workspace_file_path", None)
    task.prompt_template_id = overrides.pop("prompt_template_id", None)
    task.channel_id = overrides.pop("channel_id", None)
    for k, v in overrides.items():
        setattr(task, k, v)
    return task


class TestRunClaudeCodeTask:

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        from integrations.claude_code.executor import run_claude_code_task

        mock_result = ClaudeCodeResult(
            result="All tests pass",
            session_id="sess-ok",
            is_error=False,
            cost_usd=0.04,
            num_turns=3,
            duration_ms=5000,
            exit_code=0,
        )

        task = _make_task(
            execution_config={"working_directory": "repo"},
            callback_config={},
        )

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_task_row = MagicMock()
        mock_task_row.execution_config = dict(task.execution_config)
        mock_db.get = AsyncMock(return_value=mock_task_row)
        mock_db.commit = AsyncMock()

        mock_dispatcher = MagicMock()
        mock_dispatcher.deliver = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.TIMEOUT = 1800
        mock_settings.MAX_RESUME_RETRIES = 1

        with patch("app.db.engine.async_session", return_value=mock_db), \
             patch("app.agent.tasks.resolve_task_timeout", return_value=300), \
             patch("app.agent.dispatchers") as mock_dispatchers, \
             patch("app.services.prompt_resolution.resolve_prompt", new_callable=AsyncMock, return_value="fix the bug"), \
             patch("integrations.claude_code.runner.run_in_container", new_callable=AsyncMock, return_value=mock_result), \
             patch("integrations.claude_code.config.settings", mock_settings):
            mock_dispatchers.get.return_value = mock_dispatcher

            await run_claude_code_task(task)

        assert mock_task_row.status == "complete"
        assert mock_task_row.result is not None
        assert "All tests pass" in mock_task_row.result
        mock_dispatcher.deliver.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_with_resume_retry(self):
        from integrations.claude_code.executor import run_claude_code_task

        task = _make_task(
            execution_config={
                "claude_session_id": "sess-fail",
                "resume_retries": 0,
            },
            callback_config={},
        )

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_task_row = MagicMock()
        mock_task_row.execution_config = dict(task.execution_config)
        mock_db.get = AsyncMock(return_value=mock_task_row)
        mock_db.commit = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.TIMEOUT = 1800
        mock_settings.MAX_RESUME_RETRIES = 1

        with patch("app.db.engine.async_session", return_value=mock_db), \
             patch("app.agent.tasks.resolve_task_timeout", return_value=300), \
             patch("integrations.claude_code.runner.run_in_container", new_callable=AsyncMock,
                   side_effect=RuntimeError("connection reset")), \
             patch("app.services.prompt_resolution.resolve_prompt", new_callable=AsyncMock, return_value="fix"), \
             patch("integrations.claude_code.config.settings", mock_settings):

            await run_claude_code_task(task)

        assert mock_task_row.status == "pending"
        assert mock_task_row.execution_config.get("resume_session_id") == "sess-fail"
        assert mock_task_row.execution_config.get("resume_retries") == 1

    @pytest.mark.asyncio
    async def test_error_max_retries_exhausted(self):
        from integrations.claude_code.executor import run_claude_code_task

        task = _make_task(
            execution_config={
                "claude_session_id": "sess-fail",
                "resume_retries": 1,
            },
            callback_config={},
        )

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_task_row = MagicMock()
        mock_task_row.execution_config = dict(task.execution_config)
        mock_db.get = AsyncMock(return_value=mock_task_row)
        mock_db.commit = AsyncMock()

        mock_dispatcher = MagicMock()
        mock_dispatcher.deliver = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.TIMEOUT = 1800
        mock_settings.MAX_RESUME_RETRIES = 1

        with patch("app.db.engine.async_session", return_value=mock_db), \
             patch("app.agent.tasks.resolve_task_timeout", return_value=300), \
             patch("integrations.claude_code.runner.run_in_container", new_callable=AsyncMock,
                   side_effect=RuntimeError("still broken")), \
             patch("app.services.prompt_resolution.resolve_prompt", new_callable=AsyncMock, return_value="fix"), \
             patch("app.agent.dispatchers") as mock_dispatchers, \
             patch("integrations.claude_code.config.settings", mock_settings):
            mock_dispatchers.get.return_value = mock_dispatcher

            await run_claude_code_task(task)

        assert mock_task_row.status == "failed"
        assert "still broken" in mock_task_row.error

    @pytest.mark.asyncio
    async def test_notify_parent_creates_callback(self):
        from integrations.claude_code.executor import run_claude_code_task

        parent_session = str(uuid.uuid4())
        mock_result = ClaudeCodeResult(
            result="Done",
            session_id="sess-1",
            is_error=False,
            cost_usd=0.01,
            num_turns=1,
            duration_ms=500,
            exit_code=0,
        )

        task = _make_task(
            execution_config={},
            callback_config={
                "notify_parent": True,
                "parent_bot_id": "parent_bot",
                "parent_session_id": parent_session,
            },
            channel_id="chan-1",
        )

        created_tasks = []

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_task_row = MagicMock()
        mock_task_row.execution_config = {}
        mock_db.get = AsyncMock(return_value=mock_task_row)
        mock_db.commit = AsyncMock()
        def track_add(obj):
            created_tasks.append(obj)
        mock_db.add = track_add
        mock_db.refresh = AsyncMock()

        mock_dispatcher = MagicMock()
        mock_dispatcher.deliver = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.TIMEOUT = 1800

        with patch("app.db.engine.async_session", return_value=mock_db), \
             patch("app.agent.tasks.resolve_task_timeout", return_value=300), \
             patch("app.agent.dispatchers") as mock_dispatchers, \
             patch("app.services.prompt_resolution.resolve_prompt", new_callable=AsyncMock, return_value="do it"), \
             patch("integrations.claude_code.runner.run_in_container", new_callable=AsyncMock, return_value=mock_result), \
             patch("integrations.claude_code.config.settings", mock_settings):
            mock_dispatchers.get.return_value = mock_dispatcher

            await run_claude_code_task(task)

        assert len(created_tasks) == 1
        cb = created_tasks[0]
        assert cb.bot_id == "parent_bot"
        assert cb.task_type == "callback"
        assert "Claude Code completed" in cb.prompt
