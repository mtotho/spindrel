"""Tests for configurable channel workspace injection prompt."""
from unittest.mock import patch

import pytest


# Patch the settings attribute where it's looked up (context_assembly imports settings from app.config)
_PATCH_TARGET = "app.agent.context_assembly.settings.CHANNEL_WORKSPACE_PROMPT"


class TestRenderChannelWorkspacePrompt:
    """Test _render_channel_workspace_prompt from context_assembly."""

    def _render(self, **kwargs):
        from app.agent.context_assembly import _render_channel_workspace_prompt

        defaults = {
            "workspace_path": "/workspace/channels/abc-123",
            "channel_id": "abc-123",
            "data_listing": "",
        }
        defaults.update(kwargs)
        return _render_channel_workspace_prompt(**defaults)

    def test_default_template_includes_workspace_path(self):
        result = self._render(workspace_path="/workspace/channels/test-id")
        assert "/workspace/channels/test-id" in result

    def test_default_template_includes_channel_id(self):
        result = self._render(channel_id="my-channel-uuid")
        assert "my-channel-uuid" in result

    def test_default_template_includes_data_listing(self):
        listing = "\nData files:\n  - report.pdf\n"
        result = self._render(data_listing=listing)
        assert "report.pdf" in result

    def test_default_template_mentions_file_tool(self):
        """Default prompt should mention the `file` tool, not just exec_command."""
        result = self._render()
        assert "file" in result.lower()

    def test_default_template_mentions_search_tools(self):
        result = self._render()
        assert "search_channel_archive" in result
        assert "search_channel_workspace" in result
        assert "list_workspace_channels" in result

    def test_default_template_empty_data_listing(self):
        """Empty data listing should not cause errors."""
        result = self._render(data_listing="")
        assert "Channel workspace" in result

    @patch(_PATCH_TARGET, "Custom workspace at {workspace_path} for channel {channel_id}.{data_listing}")
    def test_custom_template_used_when_set(self):
        """Custom CHANNEL_WORKSPACE_PROMPT overrides the default."""
        result = self._render(
            workspace_path="/custom/path",
            channel_id="ch-42",
            data_listing="",
        )
        assert result == "Custom workspace at /custom/path for channel ch-42."

    @patch(_PATCH_TARGET, "Path: {workspace_path}\n{data_listing}")
    def test_custom_template_with_data_listing(self):
        result = self._render(
            workspace_path="/ws",
            data_listing="\n- file.pdf\n",
        )
        assert "Path: /ws" in result
        assert "file.pdf" in result

    @patch(_PATCH_TARGET, "Bad template: {nonexistent_var}")
    def test_fallback_on_bad_template(self):
        """Invalid template (unknown placeholder) falls back to default."""
        result = self._render()
        # Should fall back to default which always works
        assert "Channel workspace" in result
        assert "abc-123" in result

    @patch(_PATCH_TARGET, "")
    def test_empty_custom_template_uses_default(self):
        """Empty string falls back to default."""
        result = self._render()
        assert "Channel workspace" in result

    @patch(_PATCH_TARGET, "   \n  ")
    def test_whitespace_only_template_uses_default(self):
        """Whitespace-only string falls back to default."""
        result = self._render()
        assert "Channel workspace" in result

    @patch(_PATCH_TARGET, "WS={workspace_path} CH={channel_id} DATA={data_listing}")
    def test_custom_template_all_placeholders(self):
        """All three placeholders can be used in a custom template."""
        result = self._render(
            workspace_path="/p",
            channel_id="c",
            data_listing="d",
        )
        assert result == "WS=/p CH=c DATA=d"

    @patch(_PATCH_TARGET, "Workspace: {workspace_path}")
    def test_custom_template_partial_placeholders(self):
        """Template that only uses some placeholders is fine."""
        result = self._render(workspace_path="/my/path")
        assert result == "Workspace: /my/path"

    @patch(_PATCH_TARGET, 'Path: {workspace_path} JSON: {{"key": "val"}}')
    def test_custom_template_with_literal_braces(self):
        """Template with literal braces (doubled) works."""
        result = self._render(workspace_path="/ws")
        assert '{"key": "val"}' in result
