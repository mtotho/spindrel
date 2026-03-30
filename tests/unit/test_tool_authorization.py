"""Unit tests for tool authorization enforcement in dispatch_tool_call."""
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tool_dispatch import dispatch_tool_call


@pytest.fixture
def dispatch_kwargs():
    """Common kwargs for dispatch_tool_call."""
    return dict(
        args="{}",
        tool_call_id="tc_1",
        bot_id="test-bot",
        bot_memory=None,
        session_id=uuid.uuid4(),
        client_id="test-client",
        correlation_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        iteration=1,
        provider_id=None,
        summarize_enabled=False,
        summarize_threshold=10000,
        summarize_model="gpt-4",
        summarize_max_tokens=500,
        summarize_exclude=set(),
        compaction=False,
    )


@pytest.mark.asyncio
async def test_unauthorized_tool_blocked(dispatch_kwargs):
    """Tool not in allowed_tool_names should be blocked."""
    result = await dispatch_tool_call(
        name="reindex_workspace",
        allowed_tool_names={"search_workspace", "exec_command"},
        **dispatch_kwargs,
    )
    parsed = json.loads(result.result)
    assert "error" in parsed
    assert "not available" in parsed["error"]
    assert result.tool_event.get("error") == "Not authorized"


@pytest.mark.asyncio
async def test_authorized_tool_passes(dispatch_kwargs):
    """Tool in allowed_tool_names should proceed normally."""
    with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
         patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
         patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
         patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
        result = await dispatch_tool_call(
            name="search_workspace",
            allowed_tool_names={"search_workspace", "exec_command"},
            **dispatch_kwargs,
        )
    parsed = json.loads(result.result)
    assert "error" not in parsed
    assert parsed.get("ok") is True


@pytest.mark.asyncio
async def test_no_allowed_set_allows_all(dispatch_kwargs):
    """When allowed_tool_names is None, all tools are allowed (no enforcement)."""
    with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
         patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
         patch("app.agent.tool_dispatch.call_local_tool", new_callable=AsyncMock, return_value='{"ok": true}'), \
         patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
        result = await dispatch_tool_call(
            name="reindex_workspace",
            allowed_tool_names=None,
            **dispatch_kwargs,
        )
    parsed = json.loads(result.result)
    assert "error" not in parsed


@pytest.mark.asyncio
async def test_empty_allowed_set_blocks_all(dispatch_kwargs):
    """Empty allowed_tool_names should block everything."""
    result = await dispatch_tool_call(
        name="exec_command",
        allowed_tool_names=set(),
        **dispatch_kwargs,
    )
    parsed = json.loads(result.result)
    assert "error" in parsed
    assert "not available" in parsed["error"]
