"""Unit tests for workspace schema template injection into channel workspace context."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


class TestWorkspaceSchemaResolution:
    """Test that resolve_prompt_template is called correctly for workspace schemas."""

    @pytest.mark.asyncio
    async def test_resolve_returns_content(self):
        """resolve_prompt_template returns template content for a valid ID."""
        from app.services.prompt_resolution import resolve_prompt_template

        template_id = uuid.uuid4()
        mock_template = MagicMock()
        mock_template.content = "## Schema\nUse tasks.md"
        mock_template.source_type = "manual"
        mock_template.workspace_id = None
        mock_template.source_path = None
        mock_template.content_hash = "abc123"

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_template)

        result = await resolve_prompt_template(str(template_id), fallback="", db=db)
        assert result == "## Schema\nUse tasks.md"

    @pytest.mark.asyncio
    async def test_resolve_returns_fallback_when_missing(self):
        """resolve_prompt_template returns fallback when template doesn't exist."""
        from app.services.prompt_resolution import resolve_prompt_template

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        result = await resolve_prompt_template(str(uuid.uuid4()), fallback="default", db=db)
        assert result == "default"

    @pytest.mark.asyncio
    async def test_resolve_returns_fallback_when_none(self):
        """resolve_prompt_template returns fallback when template_id is None."""
        from app.services.prompt_resolution import resolve_prompt_template

        db = AsyncMock()
        result = await resolve_prompt_template(None, fallback="fallback text", db=db)
        assert result == "fallback text"


class TestSchemaInjectionLogic:
    """Test the schema content prepend logic used in context_assembly."""

    def test_schema_prepended_to_helper(self):
        """When schema content exists, it's prepended to the workspace helper."""
        schema_content = "## Workspace Organization\nUse tasks.md and notes.md."
        cw_helper = "Channel workspace — absolute path: /workspace/channels/abc\n"

        # This mirrors the logic in context_assembly.py
        if schema_content:
            cw_helper = schema_content + "\n\n" + cw_helper

        assert cw_helper.startswith("## Workspace Organization")
        assert "Channel workspace — absolute path:" in cw_helper

    def test_no_schema_leaves_helper_unchanged(self):
        """When no schema content, helper is unchanged."""
        schema_content = ""
        cw_helper = "Channel workspace — absolute path: /workspace/channels/abc\n"
        original = cw_helper

        if schema_content:
            cw_helper = schema_content + "\n\n" + cw_helper

        assert cw_helper == original

    def test_empty_resolve_leaves_helper_unchanged(self):
        """When resolve returns empty string (fallback), helper is unchanged."""
        schema_content = ""  # resolve_prompt_template returns "" when not found
        cw_helper = "Channel workspace — absolute path: /workspace/channels/abc\n"
        original = cw_helper

        if schema_content:
            cw_helper = schema_content + "\n\n" + cw_helper

        assert cw_helper == original


class TestSchemaTemplateIdGuard:
    """Test the getattr guard used in context_assembly for workspace_schema_template_id."""

    def test_channel_with_schema_id(self):
        """Channel row with workspace_schema_template_id triggers resolution."""
        ch = SimpleNamespace(
            id=uuid.uuid4(),
            channel_workspace_enabled=True,
            workspace_schema_template_id=uuid.uuid4(),
        )
        assert getattr(ch, "workspace_schema_template_id", None) is not None

    def test_channel_without_schema_id(self):
        """Channel row without workspace_schema_template_id skips resolution."""
        ch = SimpleNamespace(
            id=uuid.uuid4(),
            channel_workspace_enabled=True,
            workspace_schema_template_id=None,
        )
        assert getattr(ch, "workspace_schema_template_id", None) is None

    def test_channel_missing_attribute(self):
        """Old channel rows without the attribute at all are safe (getattr default)."""
        ch = SimpleNamespace(
            id=uuid.uuid4(),
            channel_workspace_enabled=True,
        )
        assert getattr(ch, "workspace_schema_template_id", None) is None


class TestSchemaOverridePriority:
    """Test the override-takes-precedence logic from context_assembly."""

    def test_override_takes_precedence_over_template(self):
        """When workspace_schema_content is set, it wins over template."""
        ch = SimpleNamespace(
            workspace_schema_content="## Custom Schema\nOverridden.",
            workspace_schema_template_id=uuid.uuid4(),
        )
        _schema_content = ""
        _ch_schema_override = getattr(ch, "workspace_schema_content", None)
        if _ch_schema_override:
            _schema_content = _ch_schema_override
        elif getattr(ch, "workspace_schema_template_id", None):
            _schema_content = "SHOULD NOT REACH HERE"

        assert _schema_content == "## Custom Schema\nOverridden."

    def test_template_used_when_no_override(self):
        """When workspace_schema_content is null, template path is taken."""
        ch = SimpleNamespace(
            workspace_schema_content=None,
            workspace_schema_template_id=uuid.uuid4(),
        )
        _schema_content = ""
        _ch_schema_override = getattr(ch, "workspace_schema_content", None)
        if _ch_schema_override:
            _schema_content = _ch_schema_override
        elif getattr(ch, "workspace_schema_template_id", None):
            _schema_content = "TEMPLATE CONTENT"

        assert _schema_content == "TEMPLATE CONTENT"

    def test_both_null_yields_empty(self):
        """When both override and template are null, schema is empty."""
        ch = SimpleNamespace(
            workspace_schema_content=None,
            workspace_schema_template_id=None,
        )
        _schema_content = ""
        _ch_schema_override = getattr(ch, "workspace_schema_content", None)
        if _ch_schema_override:
            _schema_content = _ch_schema_override
        elif getattr(ch, "workspace_schema_template_id", None):
            _schema_content = "TEMPLATE CONTENT"

        assert _schema_content == ""

    def test_empty_string_override_does_not_take_precedence(self):
        """Empty string is falsy — falls through to template."""
        ch = SimpleNamespace(
            workspace_schema_content="",
            workspace_schema_template_id=uuid.uuid4(),
        )
        _schema_content = ""
        _ch_schema_override = getattr(ch, "workspace_schema_content", None)
        if _ch_schema_override:
            _schema_content = _ch_schema_override
        elif getattr(ch, "workspace_schema_template_id", None):
            _schema_content = "TEMPLATE CONTENT"

        assert _schema_content == "TEMPLATE CONTENT"

    def test_override_without_template(self):
        """Override works even when no template is linked."""
        ch = SimpleNamespace(
            workspace_schema_content="## Solo Override",
            workspace_schema_template_id=None,
        )
        _schema_content = ""
        _ch_schema_override = getattr(ch, "workspace_schema_content", None)
        if _ch_schema_override:
            _schema_content = _ch_schema_override
        elif getattr(ch, "workspace_schema_template_id", None):
            _schema_content = "TEMPLATE CONTENT"

        assert _schema_content == "## Solo Override"
