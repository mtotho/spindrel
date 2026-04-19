"""Endpoint wiring test for GET /channels/{id}/workspace/html-widgets.

Smoke-level — confirms the endpoint resolves the channel, calls the scanner,
and returns the expected envelope shape. Heavier auth/scope coverage lives
with the other channel-workspace endpoints.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_list_html_widgets_returns_scanner_output():
    from app.routers import api_v1_channel_workspace as mod

    channel_id = uuid.uuid4()
    fake_channel = SimpleNamespace(id=channel_id, channel_workspace_enabled=True, bot_id="bot-1")
    fake_bot = SimpleNamespace(id="bot-1", shared_workspace_id="ws-1")

    sample = [
        {
            "path": "data/widgets/project-status/index.html",
            "slug": "project-status",
            "name": "Project status",
            "description": "...",
            "display_label": "Project status",
            "version": "1.2.0",
            "author": "crumb",
            "tags": ["dashboard"],
            "icon": "activity",
            "is_bundle": True,
            "is_loose": False,
            "size": 400,
            "modified_at": 0.0,
        }
    ]

    with patch.object(
        mod,
        "_require_channel_workspace",
        AsyncMock(return_value=(fake_channel, fake_bot)),
    ), patch(
        "app.services.html_widget_scanner.scan_channel",
        return_value=sample,
    ):
        result = await mod.list_html_widgets(channel_id=channel_id, db=None, _auth=None)

    assert result == {"widgets": sample}


@pytest.mark.asyncio
async def test_list_html_widgets_404_when_channel_missing():
    """_require_channel_workspace raises HTTPException(404); endpoint must propagate."""
    from fastapi import HTTPException
    from app.routers import api_v1_channel_workspace as mod

    channel_id = uuid.uuid4()
    with patch.object(
        mod,
        "_require_channel_workspace",
        AsyncMock(side_effect=HTTPException(404, "Channel not found")),
    ):
        with pytest.raises(HTTPException) as exc:
            await mod.list_html_widgets(channel_id=channel_id, db=None, _auth=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_html_widgets_empty_result_shape():
    from app.routers import api_v1_channel_workspace as mod

    channel_id = uuid.uuid4()
    fake_channel = SimpleNamespace(id=channel_id, channel_workspace_enabled=True, bot_id="bot-1")
    fake_bot = SimpleNamespace(id="bot-1", shared_workspace_id="ws-1")

    with patch.object(
        mod,
        "_require_channel_workspace",
        AsyncMock(return_value=(fake_channel, fake_bot)),
    ), patch("app.services.html_widget_scanner.scan_channel", return_value=[]):
        result = await mod.list_html_widgets(channel_id=channel_id, db=None, _auth=None)

    assert result == {"widgets": []}
