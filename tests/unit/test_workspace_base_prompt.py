"""Unit tests for workspace base prompt resolution and inheritance."""
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.base_prompt import resolve_workspace_base_prompt


class TestResolveWorkspaceBasePrompt:
    @patch("app.services.shared_workspace.shared_workspace_service")
    def test_common_base_prompt_returns_workspace_addition(self, mock_svc):
        """When common/prompts/base.md exists, it should be returned."""
        mock_svc.read_file.return_value = {"content": "# Workspace Base Prompt\nYou are a workspace bot."}
        result = resolve_workspace_base_prompt("ws-123", "coder")
        assert result is not None
        assert "Workspace Base Prompt" in result
        mock_svc.read_file.assert_any_call("ws-123", "common/prompts/base.md")

    @patch("app.services.shared_workspace.shared_workspace_service")
    def test_bot_base_prompt_concatenated_after_common(self, mock_svc):
        """When both common and bot-specific prompts exist, they should be concatenated."""

        def mock_read(ws_id, path):
            if path == "common/prompts/base.md":
                return {"content": "Common prompt."}
            if path == "bots/coder/prompts/base.md":
                return {"content": "Bot-specific additions."}
            raise Exception("not found")

        mock_svc.read_file.side_effect = mock_read
        result = resolve_workspace_base_prompt("ws-123", "coder")
        assert result is not None
        assert "Common prompt." in result
        assert "Bot-specific additions." in result
        assert result.index("Common prompt.") < result.index("Bot-specific additions.")

    @patch("app.services.shared_workspace.shared_workspace_service")
    def test_missing_common_base_returns_none(self, mock_svc):
        """When common/prompts/base.md doesn't exist, return None."""
        from app.services.shared_workspace import SharedWorkspaceError

        mock_svc.read_file.side_effect = SharedWorkspaceError("not found")
        result = resolve_workspace_base_prompt("ws-123", "coder")
        assert result is None

    @patch("app.services.shared_workspace.shared_workspace_service")
    def test_missing_bot_base_uses_common_only(self, mock_svc):
        """When common exists but bot-specific doesn't, only common is returned."""
        from app.services.shared_workspace import SharedWorkspaceError

        def mock_read(ws_id, path):
            if path == "common/prompts/base.md":
                return {"content": "Common only."}
            raise SharedWorkspaceError("not found")

        mock_svc.read_file.side_effect = mock_read
        result = resolve_workspace_base_prompt("ws-123", "coder")
        assert result == "Common only."


class TestEffectiveSystemPromptWorkspace:
    def _make_bot(self, **kwargs):
        """Create a minimal BotConfig-like object."""
        defaults = {
            "id": "coder",
            "name": "Coder",
            "model": "gpt-4",
            "model_provider_id": None,
            "system_prompt": "You are a coder.",
            "skills": None,
            "memory": SimpleNamespace(enabled=False, prompt=None),
            "memory_scheme": None,
            "knowledge": SimpleNamespace(enabled=False),
            "delegate_bots": [],
            "shared_workspace_id": None,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    @patch("app.config.settings.GLOBAL_BASE_PROMPT", "Global base.")
    @patch("app.agent.base_prompt.resolve_workspace_base_prompt")
    def test_disabled_workspace_base_prompt_uses_global_only(self, mock_resolve):
        """When workspace_base_prompt_enabled=False, workspace prompt is skipped."""
        from app.services.sessions import _effective_system_prompt

        mock_resolve.return_value = "Workspace base."
        bot = self._make_bot(shared_workspace_id="ws-123")
        result = _effective_system_prompt(bot, workspace_base_prompt_enabled=False)
        assert "Global base." in result
        assert "Workspace base." not in result
        mock_resolve.assert_not_called()

    @patch("app.config.settings.GLOBAL_BASE_PROMPT", "Global base.")
    @patch("app.agent.base_prompt.resolve_workspace_base_prompt")
    def test_enabled_workspace_base_prompt_is_additive_after_global(self, mock_resolve):
        """When workspace prompt exists, it is appended after the global base prompt."""
        from app.services.sessions import _effective_system_prompt

        mock_resolve.return_value = "Workspace base."
        bot = self._make_bot(shared_workspace_id="ws-123")
        result = _effective_system_prompt(bot, workspace_base_prompt_enabled=True)
        assert "Global base." in result
        assert "Workspace base." in result
        assert result.index("Global base.") < result.index("Workspace base.")

    @patch("app.config.settings.GLOBAL_BASE_PROMPT", "Global base.")
    @patch("app.agent.base_prompt.resolve_workspace_base_prompt")
    def test_enabled_but_no_workspace_prompt_keeps_global(self, mock_resolve):
        """When enabled but workspace prompt file doesn't exist, global remains."""
        from app.services.sessions import _effective_system_prompt

        mock_resolve.return_value = None
        bot = self._make_bot(shared_workspace_id="ws-123")
        result = _effective_system_prompt(bot, workspace_base_prompt_enabled=True)
        assert "Global base." in result

    @patch("app.config.settings.GLOBAL_BASE_PROMPT", "Global base.")
    @patch("app.agent.base_prompt.resolve_workspace_base_prompt")
    def test_workspace_prompt_none_keeps_global(self, mock_resolve):
        """When workspace prompt resolution returns None, global remains."""
        from app.services.sessions import _effective_system_prompt

        mock_resolve.return_value = None
        bot = self._make_bot(shared_workspace_id="ws-123")
        result = _effective_system_prompt(bot, workspace_base_prompt_enabled=True)
        assert "Global base." in result
