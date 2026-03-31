"""Tests for integrations.claude_code.tools.run_claude_code — sync tool path."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.claude_code.runner import ClaudeCodeResult


class TestRunClaudeCodeSync:
    """Test the sync execution path of run_claude_code."""

    @pytest.mark.asyncio
    async def test_sync_returns_structured_json(self):
        from integrations.claude_code.tools.run_claude_code import run_claude_code

        mock_result = ClaudeCodeResult(
            result="Bug fixed",
            session_id="sess-123",
            is_error=False,
            cost_usd=0.03,
            num_turns=4,
            duration_ms=2000,
            duration_api_ms=1200,
            exit_code=0,
        )

        with patch("app.agent.context.current_bot_id") as mock_ctx, \
             patch("integrations.claude_code.runner.run_in_container", new_callable=AsyncMock, return_value=mock_result):
            mock_ctx.get.return_value = "test_bot"

            raw = await run_claude_code(prompt="fix the bug")

        data = json.loads(raw)
        assert data["result"] == "Bug fixed"
        assert data["session_id"] == "sess-123"
        assert data["is_error"] is False
        assert data["cost_usd"] == 0.03
        assert data["num_turns"] == 4

    @pytest.mark.asyncio
    async def test_sync_no_bot_context(self):
        from integrations.claude_code.tools.run_claude_code import run_claude_code

        with patch("app.agent.context.current_bot_id") as mock_ctx:
            mock_ctx.get.return_value = None

            raw = await run_claude_code(prompt="hello")

        data = json.loads(raw)
        assert "error" in data
        assert "bot context" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_sync_workspace_error(self):
        from integrations.claude_code.tools.run_claude_code import run_claude_code

        with patch("app.agent.context.current_bot_id") as mock_ctx, \
             patch("integrations.claude_code.runner.run_in_container", new_callable=AsyncMock,
                   side_effect=ValueError("Bot 'x' has no workspace enabled.")):
            mock_ctx.get.return_value = "test_bot"

            raw = await run_claude_code(prompt="hello")

        data = json.loads(raw)
        assert "error" in data
        assert "no workspace" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_sync_general_exception(self):
        from integrations.claude_code.tools.run_claude_code import run_claude_code

        with patch("app.agent.context.current_bot_id") as mock_ctx, \
             patch("integrations.claude_code.runner.run_in_container", new_callable=AsyncMock,
                   side_effect=RuntimeError("docker broke")):
            mock_ctx.get.return_value = "test_bot"

            raw = await run_claude_code(prompt="hello")

        data = json.loads(raw)
        assert "error" in data
        assert "RuntimeError" in data["error"]

    @pytest.mark.asyncio
    async def test_working_directory_traversal_rejected(self):
        from integrations.claude_code.tools.run_claude_code import run_claude_code

        raw = await run_claude_code(prompt="x", working_directory="../escape")
        data = json.loads(raw)
        assert "error" in data
        assert "traversal" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_absolute_working_directory_rejected(self):
        from integrations.claude_code.tools.run_claude_code import run_claude_code

        raw = await run_claude_code(prompt="x", working_directory="/etc/passwd")
        data = json.loads(raw)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_parse_bool_handling(self):
        """LLMs may pass string booleans."""
        from integrations.claude_code.tools.run_claude_code import _parse_bool

        assert _parse_bool("true") is True
        assert _parse_bool("false") is False
        assert _parse_bool("True") is True
        assert _parse_bool("0") is False
        assert _parse_bool(None, default=True) is True
        assert _parse_bool(True) is True
        assert _parse_bool(False) is False


class TestRunClaudeCodeDeferred:
    """Test the deferred execution path of run_claude_code."""

    @pytest.mark.asyncio
    async def test_deferred_creates_task(self):
        from integrations.claude_code.tools.run_claude_code import run_claude_code

        mock_task_inst = MagicMock()
        mock_task_inst.id = "task-456"

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.context.current_bot_id") as mock_bot_id, \
             patch("app.agent.context.current_session_id") as mock_sess, \
             patch("app.agent.context.current_client_id") as mock_client, \
             patch("app.agent.context.current_channel_id") as mock_chan, \
             patch("app.agent.context.current_dispatch_type") as mock_dt, \
             patch("app.agent.context.current_dispatch_config") as mock_dc, \
             patch("app.agent.context.current_correlation_id") as mock_corr, \
             patch("app.agent.context.current_model_override") as mock_mo, \
             patch("app.agent.context.current_provider_id_override") as mock_po, \
             patch("app.db.engine.async_session", return_value=mock_db), \
             patch("app.db.models.Task", return_value=mock_task_inst):

            mock_bot_id.get.return_value = "my_bot"
            mock_sess.get.return_value = "sess-1"
            mock_client.get.return_value = "client-1"
            mock_chan.get.return_value = "chan-1"
            mock_dt.get.return_value = "slack"
            mock_dc.get.return_value = {"channel": "C123"}
            mock_corr.get.return_value = None
            mock_mo.get.return_value = None
            mock_po.get.return_value = None

            raw = await run_claude_code(prompt="do stuff", mode="deferred")

        data = json.loads(raw)
        assert data["status"] == "deferred"
        assert data["task_id"] == "task-456"
