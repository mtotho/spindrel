"""Unit tests for manage_bot tool delete action."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


class TestManageBotDelete:
    async def test_delete_missing_bot_id(self):
        """Delete without bot_id returns error."""
        from app.tools.local.admin_bots import manage_bot
        result = json.loads(await manage_bot(action="delete"))
        assert "error" in result
        assert "bot_id" in result["error"].lower()

    async def test_delete_not_found(self):
        """Delete of nonexistent bot returns error."""
        from app.tools.local.admin_bots import manage_bot

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.admin_bots.async_session", return_value=mock_ctx):
            result = json.loads(await manage_bot(action="delete", bot_id="ghost-bot"))

        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_delete_system_bot_rejected(self):
        """System bots cannot be deleted via tool."""
        from app.tools.local.admin_bots import manage_bot

        mock_row = MagicMock()
        mock_row.source_type = "system"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_row)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.admin_bots.async_session", return_value=mock_ctx):
            result = json.loads(await manage_bot(action="delete", bot_id="system-bot"))

        assert "error" in result
        assert "system" in result["error"].lower()

    async def test_delete_with_channels_blocked(self):
        """Bot with channels cannot be deleted via tool (no force option)."""
        from app.tools.local.admin_bots import manage_bot

        mock_row = MagicMock()
        mock_row.source_type = "manual"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_row)
        # Mock the channel count query to return 2
        mock_result = MagicMock()
        mock_result.scalar.return_value = 2
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tools.local.admin_bots.async_session", return_value=mock_ctx):
            result = json.loads(await manage_bot(action="delete", bot_id="busy-bot"))

        assert "error" in result
        assert "channel" in result["error"].lower()

    async def test_delete_success(self):
        """Delete action removes bot and reloads registry."""
        from app.tools.local.admin_bots import manage_bot

        mock_row = MagicMock()
        mock_row.source_type = "manual"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_row)
        # Channel count = 0
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tools.local.admin_bots.async_session", return_value=mock_ctx),
            patch("app.agent.bots.load_bots", new_callable=AsyncMock) as mock_load,
        ):
            result = json.loads(await manage_bot(action="delete", bot_id="test-bot"))

        assert result["ok"] is True
        assert "deleted" in result["message"].lower()
        mock_load.assert_awaited_once()
