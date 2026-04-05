"""Unit tests for auto-template selection on integration activation
and fallback workspace hints."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.api_v1_channels import _auto_select_workspace_template


def _make_channel(**overrides):
    ch = MagicMock()
    ch.id = overrides.get("id", uuid.uuid4())
    ch.channel_workspace_enabled = overrides.get("channel_workspace_enabled", True)
    ch.workspace_schema_template_id = overrides.get("workspace_schema_template_id", None)
    ch.workspace_schema_content = overrides.get("workspace_schema_content", None)
    return ch


def _make_template(tag="mission-control"):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.category = "workspace_schema"
    t.tags = [tag]
    return t


class TestAutoSelectWorkspaceTemplate:

    @pytest.mark.asyncio
    async def test_assigns_matching_template(self):
        """When integration has compatible_templates and a matching template exists, assign it."""
        channel = _make_channel()
        template = _make_template("mission-control")
        manifest = {"compatible_templates": ["mission-control"]}

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = template
        db.execute.return_value = result_mock

        await _auto_select_workspace_template(channel, "mission_control", manifest, db)
        assert channel.workspace_schema_template_id == template.id

    @pytest.mark.asyncio
    async def test_skips_when_workspace_disabled(self):
        """No template assigned when workspace is not enabled."""
        channel = _make_channel(channel_workspace_enabled=False)
        manifest = {"compatible_templates": ["mission-control"]}
        db = AsyncMock()

        await _auto_select_workspace_template(channel, "mission_control", manifest, db)
        assert channel.workspace_schema_template_id is None
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_template_already_set(self):
        """No change when channel already has a template."""
        channel = _make_channel(workspace_schema_template_id=uuid.uuid4())
        manifest = {"compatible_templates": ["mission-control"]}
        db = AsyncMock()

        await _auto_select_workspace_template(channel, "mission_control", manifest, db)
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_schema_override_set(self):
        """No change when channel has a manual schema override."""
        channel = _make_channel(workspace_schema_content="# Custom schema")
        manifest = {"compatible_templates": ["mission-control"]}
        db = AsyncMock()

        await _auto_select_workspace_template(channel, "mission_control", manifest, db)
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_compatible_templates(self):
        """No change when manifest has no compatible_templates."""
        channel = _make_channel()
        manifest = {}
        db = AsyncMock()

        await _auto_select_workspace_template(channel, "github", manifest, db)
        assert channel.workspace_schema_template_id is None
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_matching_template_found(self):
        """No change when compatible_templates declared but no template matches."""
        channel = _make_channel()
        manifest = {"compatible_templates": ["nonexistent-tag"]}

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        await _auto_select_workspace_template(channel, "test", manifest, db)
        assert channel.workspace_schema_template_id is None
