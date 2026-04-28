from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import api_v1_widget_actions as router_mod


@pytest.mark.asyncio
async def test_tool_dispatch_stops_when_policy_requires_approval():
    req = router_mod.WidgetActionRequest(
        dispatch="tool",
        tool="dangerous_tool",
        args={"target": "prod"},
        bot_id="bot-1",
    )

    decision = SimpleNamespace(
        action="require_approval",
        reason="dangerous action",
    )

    with patch.object(router_mod, "_resolve_tool_name", return_value="dangerous_tool"), \
         patch.object(router_mod, "is_local_tool", return_value=True), \
         patch.object(router_mod, "call_local_tool", new=AsyncMock(return_value="{}")) as call_local, \
         patch("app.tools.registry.get_tool_execution_policy", return_value="normal"), \
         patch("app.tools.registry.get_tool_safety_tier", return_value="exec_capable"), \
         patch("app.agent.tool_dispatch._check_tool_policy", new=AsyncMock(return_value=decision)):
        resp = await router_mod._dispatch_tool(req, db=object())

    assert resp.ok is False
    assert resp.error_kind == "conflict"
    assert resp.error == "dangerous action"
    call_local.assert_not_awaited()


@pytest.mark.asyncio
async def test_exec_capable_tool_requires_bot_context():
    req = router_mod.WidgetActionRequest(
        dispatch="tool",
        tool="dangerous_tool",
        args={},
    )

    with patch.object(router_mod, "_resolve_tool_name", return_value="dangerous_tool"), \
         patch.object(router_mod, "is_local_tool", return_value=True), \
         patch.object(router_mod, "call_local_tool", new=AsyncMock(return_value="{}")) as call_local, \
         patch("app.tools.registry.get_tool_execution_policy", return_value="normal"), \
         patch("app.tools.registry.get_tool_safety_tier", return_value="exec_capable"):
        resp = await router_mod._dispatch_tool(req, db=object())

    assert resp.ok is False
    assert resp.error_kind == "forbidden"
    assert "bot context" in (resp.error or "")
    call_local.assert_not_awaited()
