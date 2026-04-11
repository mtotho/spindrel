"""Regression test for the tool-dispatch wall-clock guard.

A hung tool coroutine must be cancelled at ``settings.TOOL_DISPATCH_TIMEOUT``
seconds so the turn can never wedge forever waiting on a stuck tool. This
matters especially for MCP tools whose underlying httpx client could in
theory stall even past its own timeout — the guard is the turn-level
backstop.
"""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tool_dispatch import dispatch_tool_call
from app.config import settings


@pytest.fixture
def dispatch_kwargs():
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
async def test_local_tool_hang_is_cancelled_by_wall_clock_guard(
    dispatch_kwargs, monkeypatch,
):
    """A local tool that never returns must be cancelled and yield a timeout error."""
    monkeypatch.setattr(settings, "TOOL_DISPATCH_TIMEOUT", 0.1)

    async def _hang(*_args, **_kwargs):
        await asyncio.sleep(60)
        return "never"

    with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
         patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
         patch("app.agent.tool_dispatch.call_local_tool", side_effect=_hang), \
         patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
        result = await dispatch_tool_call(
            name="slow_tool",
            allowed_tool_names=None,
            **dispatch_kwargs,
        )

    parsed = json.loads(result.result)
    assert "error" in parsed
    assert "wall-clock" in parsed["error"]
    assert "slow_tool" in parsed["error"]


@pytest.mark.asyncio
async def test_mcp_tool_hang_is_cancelled_by_wall_clock_guard(
    dispatch_kwargs, monkeypatch,
):
    """An MCP tool that never returns must be cancelled and yield a timeout error."""
    monkeypatch.setattr(settings, "TOOL_DISPATCH_TIMEOUT", 0.1)

    async def _hang(*_args, **_kwargs):
        await asyncio.sleep(60)
        return "never"

    with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
         patch("app.agent.tool_dispatch.is_local_tool", return_value=False), \
         patch("app.agent.tool_dispatch.is_mcp_tool", return_value=True), \
         patch("app.agent.tool_dispatch.get_mcp_server_for_tool", return_value="firecrawl"), \
         patch("app.agent.tool_dispatch.call_mcp_tool", side_effect=_hang), \
         patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
        result = await dispatch_tool_call(
            name="firecrawl_search",
            allowed_tool_names=None,
            **dispatch_kwargs,
        )

    parsed = json.loads(result.result)
    assert "error" in parsed
    assert "wall-clock" in parsed["error"]
    assert "firecrawl_search" in parsed["error"]


@pytest.mark.asyncio
async def test_fast_local_tool_not_affected_by_guard(dispatch_kwargs, monkeypatch):
    """A normal tool that returns well within the budget must not be disturbed."""
    monkeypatch.setattr(settings, "TOOL_DISPATCH_TIMEOUT", 5.0)

    with patch("app.agent.tool_dispatch.is_client_tool", return_value=False), \
         patch("app.agent.tool_dispatch.is_local_tool", return_value=True), \
         patch(
             "app.agent.tool_dispatch.call_local_tool",
             new_callable=AsyncMock, return_value='{"ok": true}',
         ), \
         patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
        result = await dispatch_tool_call(
            name="fast_tool",
            allowed_tool_names=None,
            **dispatch_kwargs,
        )

    parsed = json.loads(result.result)
    assert parsed.get("ok") is True
    assert "error" not in parsed
