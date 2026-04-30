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

from app.agent.tool_dispatch import ToolCallResult, _execute_tool_call, dispatch_tool_call
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
         patch("app.agent.tool_dispatch._plan_mode_guard", new_callable=AsyncMock, return_value=None), \
         patch("app.agent.tool_dispatch._start_tool_call", new_callable=AsyncMock), \
         patch("app.agent.tool_dispatch._complete_tool_call", new_callable=AsyncMock), \
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
    assert parsed["error_code"] == "tool_dispatch_timeout"
    assert parsed["error_kind"] == "timeout"
    assert parsed["retryable"] is True
    assert result.tool_event["error_kind"] == "timeout"


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
         patch("app.agent.tool_dispatch._plan_mode_guard", new_callable=AsyncMock, return_value=None), \
         patch("app.agent.tool_dispatch._start_tool_call", new_callable=AsyncMock), \
         patch("app.agent.tool_dispatch._complete_tool_call", new_callable=AsyncMock), \
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
    assert parsed["error_code"] == "tool_dispatch_timeout"
    assert parsed["error_kind"] == "timeout"
    assert parsed["retryable"] is True


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
         patch("app.agent.tool_dispatch._plan_mode_guard", new_callable=AsyncMock, return_value=None), \
         patch("app.agent.tool_dispatch._start_tool_call", new_callable=AsyncMock), \
         patch("app.agent.tool_dispatch._complete_tool_call", new_callable=AsyncMock), \
         patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock):
        result = await dispatch_tool_call(
            name="fast_tool",
            allowed_tool_names=None,
            **dispatch_kwargs,
        )

    parsed = json.loads(result.result)
    assert parsed.get("ok") is True
    assert "error" not in parsed


@pytest.mark.asyncio
async def test_client_tool_timeout_removes_pending_request(monkeypatch):
    """Timed-out client-tool requests must not leak unresolved registry entries."""
    from app.agent import pending

    pending.clear_pending()
    monkeypatch.setattr("app.agent.tool_dispatch.CLIENT_TOOL_TIMEOUT", 0.01)

    result_obj = ToolCallResult()
    with patch("app.agent.tool_dispatch.is_client_tool", return_value=True):
        raw_result, tc_type, tc_server = await _execute_tool_call(
            result_obj,
            name="client_only_tool",
            args="{}",
            bot_id="test-bot",
            session_id=None,
            client_id="test-client",
            correlation_id=None,
            channel_id=None,
            iteration=0,
            pre_hook_type="client",
            compaction=False,
        )

    parsed = json.loads(raw_result)
    assert tc_type == "client"
    assert tc_server is None
    assert parsed["error"] == "Client did not respond in time"
    assert parsed["error_code"] == "client_tool_timeout"
    assert parsed["error_kind"] == "timeout"
    assert parsed["retryable"] is True
    assert pending.pending_count() == 0
