from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import ast
from pathlib import Path

import pytest

from app.schemas.widget_actions import WidgetActionRequest
from app.services import widget_action_dispatch as dispatch_mod


@pytest.mark.asyncio
async def test_tool_dispatch_stops_when_policy_requires_approval():
    req = WidgetActionRequest(
        dispatch="tool",
        tool="dangerous_tool",
        args={"target": "prod"},
        bot_id="bot-1",
    )

    decision = SimpleNamespace(
        action="require_approval",
        reason="dangerous action",
    )

    with patch.object(dispatch_mod, "_resolve_tool_name", return_value="dangerous_tool"), \
         patch.object(dispatch_mod, "is_local_tool", return_value=True), \
         patch.object(dispatch_mod, "call_local_tool", new=AsyncMock(return_value="{}")) as call_local, \
         patch("app.tools.registry.get_tool_execution_policy", return_value="normal"), \
         patch("app.tools.registry.get_tool_safety_tier", return_value="exec_capable"), \
         patch("app.agent.tool_dispatch._check_tool_policy", new=AsyncMock(return_value=decision)):
        resp = await dispatch_mod._dispatch_tool(req, db=object())

    assert resp.ok is False
    assert resp.error_kind == "conflict"
    assert resp.error == "dangerous action"
    call_local.assert_not_awaited()


@pytest.mark.asyncio
async def test_exec_capable_tool_requires_bot_context():
    req = WidgetActionRequest(
        dispatch="tool",
        tool="dangerous_tool",
        args={},
    )

    with patch.object(dispatch_mod, "_resolve_tool_name", return_value="dangerous_tool"), \
         patch.object(dispatch_mod, "is_local_tool", return_value=True), \
         patch.object(dispatch_mod, "call_local_tool", new=AsyncMock(return_value="{}")) as call_local, \
         patch("app.tools.registry.get_tool_execution_policy", return_value="normal"), \
         patch("app.tools.registry.get_tool_safety_tier", return_value="exec_capable"):
        resp = await dispatch_mod._dispatch_tool(req, db=object())

    assert resp.ok is False
    assert resp.error_kind == "forbidden"
    assert "bot context" in (resp.error or "")
    call_local.assert_not_awaited()


def test_widget_actions_router_stays_thin() -> None:
    router_path = Path(__file__).resolve().parents[2] / "app" / "routers" / "api_v1_widget_actions.py"
    tree = ast.parse(router_path.read_text(encoding="utf-8"))
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert function_names == {
        "dispatch_widget_action",
        "widget_event_stream_endpoint",
        "refresh_widget_states_batch",
        "refresh_widget_state",
    }

    forbidden = {
        "call_local_tool",
        "call_mcp_tool",
        "get_state_poll_config",
        "apply_state_poll",
        "apply_widget_template",
        "sqlite3",
        "dispatch_native_widget_action",
        "update_pin_envelope",
    }
    source = router_path.read_text(encoding="utf-8")
    assert all(name not in source for name in forbidden)
