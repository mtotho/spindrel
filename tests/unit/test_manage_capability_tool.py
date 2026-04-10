"""Unit tests for manage_capability tool — update preserves unset fields."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_row(
    id: str = "test-carapace",
    name: str = "Test",
    description: str = "A description",
    local_tools=None,
    mcp_tools=None,
    pinned_tools=None,
    system_prompt_fragment: str = "Be helpful.",
    includes=None,
    tags=None,
    source_type: str = "manual",
):
    """Create a mock CarapaceRow with realistic field values."""
    row = MagicMock()
    row.id = id
    row.name = name
    row.description = description
    row.local_tools = local_tools or ["exec_command", "file"]
    row.mcp_tools = mcp_tools or ["homeassistant"]
    row.pinned_tools = pinned_tools or ["exec_command"]
    row.system_prompt_fragment = system_prompt_fragment
    row.includes = includes or ["base"]
    row.tags = tags or ["qa", "testing"]
    row.source_type = source_type
    row.updated_at = datetime.now(timezone.utc)
    return row


class TestUpdatePreservesUnsetFields:
    """Verify that update action only modifies explicitly-provided fields."""

    @pytest.mark.asyncio
    async def test_update_name_only_preserves_other_fields(self):
        """Updating only the name should NOT clear tools, fragment, etc."""
        from app.tools.local.carapaces import manage_capability

        row = _make_row()
        original_local_tools = list(row.local_tools)
        original_mcp_tools = list(row.mcp_tools)
        original_pinned_tools = list(row.pinned_tools)
        original_fragment = row.system_prompt_fragment
        original_includes = list(row.includes)
        original_tags = list(row.tags)
        original_description = row.description

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=row)
        mock_db.commit = AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_session):
            with patch("app.agent.carapaces.reload_carapaces", new_callable=AsyncMock):
                result = await manage_capability(action="update", id="test-carapace", name="New Name")

        parsed = json.loads(result)
        assert parsed["ok"] is True

        # Name should be updated
        assert row.name == "New Name"
        # All other fields should be PRESERVED (not wiped)
        assert row.local_tools == original_local_tools
        assert row.mcp_tools == original_mcp_tools
        assert row.pinned_tools == original_pinned_tools
        assert row.system_prompt_fragment == original_fragment
        assert row.includes == original_includes
        assert row.tags == original_tags
        assert row.description == original_description

    @pytest.mark.asyncio
    async def test_update_description_only(self):
        """Updating description should not touch tools."""
        from app.tools.local.carapaces import manage_capability

        row = _make_row()
        original_local_tools = list(row.local_tools)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=row)
        mock_db.commit = AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_session):
            with patch("app.agent.carapaces.reload_carapaces", new_callable=AsyncMock):
                result = await manage_capability(
                    action="update", id="test-carapace",
                    description="New desc",
                )

        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert row.description == "New desc"
        assert row.local_tools == original_local_tools

    @pytest.mark.asyncio
    async def test_update_rejects_file_managed(self):
        """File-managed carapaces should not be editable."""
        from app.tools.local.carapaces import manage_capability

        row = _make_row(source_type="file")

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=row)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.engine.async_session", return_value=mock_session):
            result = await manage_capability(action="update", id="test-carapace", name="Hacked")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "file-managed" in parsed["error"]
