"""Unit tests for workspace persona resolution and indexing exclusions."""
from unittest.mock import patch

import pytest

from app.agent.persona import resolve_workspace_persona
from app.agent.fs_indexer import _is_auto_injected


class TestResolveWorkspacePersona:
    @patch("app.services.shared_workspace.shared_workspace_service")
    def test_returns_file_content_when_exists(self, mock_svc):
        mock_svc.read_file.return_value = {"content": "I am a friendly assistant."}
        result = resolve_workspace_persona("ws-123", "coder")
        assert result == "I am a friendly assistant."
        mock_svc.read_file.assert_called_once_with("ws-123", "bots/coder/persona.md")

    @patch("app.services.shared_workspace.shared_workspace_service")
    def test_returns_none_when_file_missing(self, mock_svc):
        from app.services.shared_workspace import SharedWorkspaceError
        mock_svc.read_file.side_effect = SharedWorkspaceError("not found")
        result = resolve_workspace_persona("ws-123", "coder")
        assert result is None

    @patch("app.services.shared_workspace.shared_workspace_service")
    def test_returns_none_on_os_error(self, mock_svc):
        mock_svc.read_file.side_effect = OSError("permission denied")
        result = resolve_workspace_persona("ws-123", "coder")
        assert result is None


class TestGetPersonaWithWorkspace:
    @pytest.mark.asyncio
    @patch("app.agent.persona.resolve_workspace_persona")
    @patch("app.agent.persona.async_session")
    async def test_workspace_persona_preferred_over_db(self, mock_session, mock_resolve):
        from app.agent.persona import get_persona
        mock_resolve.return_value = "Workspace persona content."
        result = await get_persona("coder", workspace_id="ws-123")
        assert result == "Workspace persona content."
        mock_resolve.assert_called_once_with("ws-123", "coder")
        mock_session.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.agent.persona.resolve_workspace_persona")
    @patch("app.agent.persona.async_session")
    async def test_falls_back_to_db_when_no_workspace_file(self, mock_session, mock_resolve):
        from unittest.mock import AsyncMock, MagicMock
        from app.agent.persona import get_persona

        mock_resolve.return_value = None

        mock_row = MagicMock()
        mock_row.persona_layer = "DB persona content."
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        result = await get_persona("coder", workspace_id="ws-123")
        assert result == "DB persona content."

    @pytest.mark.asyncio
    @patch("app.agent.persona.async_session")
    async def test_no_workspace_id_returns_db_persona(self, mock_session):
        from unittest.mock import AsyncMock, MagicMock
        from app.agent.persona import get_persona

        mock_row = MagicMock()
        mock_row.persona_layer = "DB only persona."
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        result = await get_persona("coder")
        assert result == "DB only persona."

    @pytest.mark.asyncio
    @patch("app.agent.persona.async_session")
    async def test_no_workspace_no_db_returns_none(self, mock_session):
        from unittest.mock import AsyncMock, MagicMock
        from app.agent.persona import get_persona

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_session.return_value = mock_db

        result = await get_persona("coder")
        assert result is None


class TestAutoInjectedExclusion:
    """Convention files should be excluded from filesystem indexing."""

    # --- persona.md ---
    def test_persona_at_bot_root(self):
        assert _is_auto_injected(("persona.md",)) is True

    def test_persona_under_bots_dir_not_seen(self):
        """bots/ prefix paths never appear in practice since each bot indexes from its own root."""
        assert _is_auto_injected(("bots", "coder", "persona.md")) is False

    # --- skills/ ---
    def test_skills_subtree_at_bot_root(self):
        assert _is_auto_injected(("skills", "pinned", "coding.md")) is True

    def test_skills_top_level(self):
        assert _is_auto_injected(("skills", "reference.md")) is True

    def test_common_skills(self):
        assert _is_auto_injected(("common", "skills", "rag", "faq.md")) is True

    def test_bot_skills_under_bots_dir_not_seen(self):
        """bots/ prefix paths never appear since each bot indexes from its own root."""
        assert _is_auto_injected(("bots", "coder", "skills", "on-demand", "tool.md")) is False

    # --- prompts/base.md ---
    def test_base_prompt_at_bot_root(self):
        assert _is_auto_injected(("prompts", "base.md")) is True

    def test_common_base_prompt(self):
        assert _is_auto_injected(("common", "prompts", "base.md")) is True

    def test_bot_base_prompt_under_bots_dir_not_seen(self):
        """bots/ prefix paths never appear since each bot indexes from its own root."""
        assert _is_auto_injected(("bots", "coder", "prompts", "base.md")) is False

    # --- non-convention files should NOT be excluded ---
    def test_regular_python_file(self):
        assert _is_auto_injected(("src", "main.py")) is False

    def test_regular_md_file(self):
        assert _is_auto_injected(("docs", "readme.md")) is False

    def test_prompts_other_file(self):
        assert _is_auto_injected(("prompts", "other.md")) is False

    def test_non_persona_root_file(self):
        assert _is_auto_injected(("config.yaml",)) is False

    def test_bots_regular_file(self):
        assert _is_auto_injected(("bots", "coder", "src", "main.py")) is False
