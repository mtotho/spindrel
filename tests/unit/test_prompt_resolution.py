"""Tests for prompt resolution: workspace_file > template > inline priority chain."""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.prompt_resolution import (
    resolve_prompt,
    resolve_prompt_template,
    resolve_workspace_file_prompt,
)

SWS_PATCH = "app.services.shared_workspace.shared_workspace_service"


# ---------------------------------------------------------------------------
# resolve_workspace_file_prompt
# ---------------------------------------------------------------------------

class TestResolveWorkspaceFilePrompt:
    def test_returns_fallback_when_no_workspace_id(self):
        result = resolve_workspace_file_prompt(None, "file.md", "fallback")
        assert result == "fallback"

    def test_returns_fallback_when_no_file_path(self):
        result = resolve_workspace_file_prompt("ws-id", None, "fallback")
        assert result == "fallback"

    def test_returns_fallback_when_both_none(self):
        result = resolve_workspace_file_prompt(None, None, "fallback")
        assert result == "fallback"

    @patch(SWS_PATCH)
    def test_reads_file_content(self, mock_sws):
        mock_sws.read_file.return_value = {"content": "file content", "size": 12}
        result = resolve_workspace_file_prompt("ws-123", "prompts/task.md", "fallback")
        assert result == "file content"
        mock_sws.read_file.assert_called_once_with("ws-123", "prompts/task.md")

    @patch(SWS_PATCH)
    def test_returns_fallback_on_read_error(self, mock_sws):
        mock_sws.read_file.side_effect = Exception("file not found")
        result = resolve_workspace_file_prompt("ws-123", "missing.md", "fallback text")
        assert result == "fallback text"


# ---------------------------------------------------------------------------
# resolve_prompt (priority chain)
# ---------------------------------------------------------------------------

class TestResolvePrompt:
    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    @patch(SWS_PATCH)
    def test_workspace_file_wins_over_template_and_inline(self, mock_sws):
        mock_sws.read_file.return_value = {"content": "ws content", "size": 10}
        db = AsyncMock()
        result = self._run(resolve_prompt(
            workspace_id="ws-1",
            workspace_file_path="prompt.md",
            template_id=str(uuid.uuid4()),
            inline_prompt="inline text",
            db=db,
        ))
        assert result == "ws content"

    def test_template_wins_over_inline_when_no_workspace(self):
        db = AsyncMock()
        tid = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.source_type = "manual"
        mock_row.content = "template content"
        db.get = AsyncMock(return_value=mock_row)

        result = self._run(resolve_prompt(
            workspace_id=None,
            workspace_file_path=None,
            template_id=str(tid),
            inline_prompt="inline text",
            db=db,
        ))
        assert result == "template content"

    def test_inline_when_no_workspace_no_template(self):
        db = AsyncMock()
        result = self._run(resolve_prompt(
            workspace_id=None,
            workspace_file_path=None,
            template_id=None,
            inline_prompt="inline text",
            db=db,
        ))
        assert result == "inline text"

    @patch(SWS_PATCH)
    def test_falls_through_to_template_on_workspace_read_error(self, mock_sws):
        mock_sws.read_file.side_effect = Exception("read error")
        db = AsyncMock()
        tid = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.source_type = "manual"
        mock_row.content = "template fallback"
        db.get = AsyncMock(return_value=mock_row)

        result = self._run(resolve_prompt(
            workspace_id="ws-1",
            workspace_file_path="bad.md",
            template_id=str(tid),
            inline_prompt="inline",
            db=db,
        ))
        assert result == "template fallback"

    @patch(SWS_PATCH)
    def test_falls_through_to_inline_on_all_failures(self, mock_sws):
        mock_sws.read_file.side_effect = Exception("read error")
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        result = self._run(resolve_prompt(
            workspace_id="ws-1",
            workspace_file_path="bad.md",
            template_id=str(uuid.uuid4()),
            inline_prompt="last resort",
            db=db,
        ))
        assert result == "last resort"


# ---------------------------------------------------------------------------
# resolve_prompt_template (existing behavior preserved)
# ---------------------------------------------------------------------------

class TestResolvePromptTemplate:
    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_returns_fallback_when_template_id_none(self):
        db = AsyncMock()
        result = self._run(resolve_prompt_template(None, "fallback", db))
        assert result == "fallback"

    def test_returns_fallback_when_template_id_invalid(self):
        db = AsyncMock()
        result = self._run(resolve_prompt_template("not-a-uuid", "fallback", db))
        assert result == "fallback"

    def test_returns_fallback_when_template_not_found(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        result = self._run(resolve_prompt_template(str(uuid.uuid4()), "fallback", db))
        assert result == "fallback"

    def test_returns_content_for_manual_template(self):
        db = AsyncMock()
        mock_row = MagicMock()
        mock_row.source_type = "manual"
        mock_row.content = "manual content"
        db.get = AsyncMock(return_value=mock_row)

        result = self._run(resolve_prompt_template(str(uuid.uuid4()), "fallback", db))
        assert result == "manual content"
