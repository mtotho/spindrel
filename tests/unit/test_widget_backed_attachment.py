"""Tests for ``create_widget_backed_attachment``.

The helper wraps ``create_attachment`` and drops ``channel_id`` whenever the
calling tool has a widget template registered — the single invariant that
keeps widget-rendered binary output from double-displaying via orphan-link.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import attachments as attachments_mod


class _FakeAttachment:
    def __init__(self, id_="att-id"):
        self.id = id_


@pytest.fixture
def mock_create():
    fake = AsyncMock(return_value=_FakeAttachment())
    with patch.object(attachments_mod, "create_attachment", new=fake):
        yield fake


@pytest.mark.asyncio
async def test_drops_channel_id_when_widget_registered(mock_create):
    """Tool with a registered widget → channel_id coerced to None."""
    with patch(
        "app.services.widget_templates.get_widget_template",
        return_value={"html_template_body": "<div/>"},
    ):
        await attachments_mod.create_widget_backed_attachment(
            tool_name="frigate_snapshot",
            channel_id="chan-123",
            filename="snap.jpg",
            mime_type="image/jpeg",
            size_bytes=100,
            posted_by="bot-x",
            source_integration="frigate",
            file_data=b"bytes",
        )
    assert mock_create.await_count == 1
    kwargs = mock_create.await_args.kwargs
    assert kwargs["channel_id"] is None
    assert kwargs["filename"] == "snap.jpg"
    assert kwargs["message_id"] is None


@pytest.mark.asyncio
async def test_passes_channel_id_when_no_widget(mock_create):
    """No registered widget → channel_id passes through (legacy orphan-link path)."""
    with patch(
        "app.services.widget_templates.get_widget_template",
        return_value=None,
    ):
        await attachments_mod.create_widget_backed_attachment(
            tool_name="some_untemplated_tool",
            channel_id="chan-123",
            filename="out.png",
            mime_type="image/png",
            size_bytes=50,
            posted_by="bot-x",
            source_integration="misc",
            file_data=b"bytes",
        )
    assert mock_create.await_args.kwargs["channel_id"] == "chan-123"


@pytest.mark.asyncio
async def test_empty_tool_name_treats_as_untemplated(mock_create):
    """Blank tool_name → no widget lookup match → channel_id passes through.

    Guards the frigate call site: legacy callers pass ``tool_name=""`` when
    the surrounding tool is untemplated; they must not be silently opted into
    orphan suppression.
    """
    with patch(
        "app.services.widget_templates.get_widget_template",
        return_value=None,
    ):
        await attachments_mod.create_widget_backed_attachment(
            tool_name="",
            channel_id="chan-123",
            filename="f.png",
            mime_type="image/png",
            size_bytes=10,
            posted_by="bot",
            source_integration="x",
        )
    assert mock_create.await_args.kwargs["channel_id"] == "chan-123"


@pytest.mark.asyncio
async def test_returns_attachment_from_wrapped_call(mock_create):
    """Return value round-trips from the wrapped create_attachment call."""
    mock_create.return_value = _FakeAttachment("att-xyz")
    with patch(
        "app.services.widget_templates.get_widget_template",
        return_value=None,
    ):
        att = await attachments_mod.create_widget_backed_attachment(
            tool_name="t",
            channel_id=None,
            filename="f",
            mime_type="image/png",
            size_bytes=1,
            posted_by="x",
            source_integration="y",
        )
    assert att.id == "att-xyz"
