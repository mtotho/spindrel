from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
import uuid
from unittest.mock import AsyncMock

from app.db.engine import async_session
from app.services.agent_harnesses.base import HarnessToolSpec, TurnContext


def _ctx() -> TurnContext:
    return TurnContext(
        spindrel_session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        bot_id="test-bot",
        turn_id=uuid.uuid4(),
        workdir="/tmp",
        harness_session_id=None,
        permission_mode="default",
        db_session_factory=async_session,
    )


def test_claude_mcp_bridge_handler_returns_sdk_result_dict(monkeypatch):
    captured_tools: list[types.SimpleNamespace] = []

    def fake_tool(name, description, input_schema):
        def decorator(handler):
            wrapped = types.SimpleNamespace(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=handler,
            )
            captured_tools.append(wrapped)
            return wrapped

        return decorator

    fake_sdk = types.SimpleNamespace(
        tool=fake_tool,
        create_sdk_mcp_server=lambda **kwargs: kwargs,
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)
    sys.modules.pop("integrations.claude_code.harness", None)
    harness = importlib.import_module("integrations.claude_code.harness")

    execute = AsyncMock(return_value="tool output")
    monkeypatch.setattr(harness, "execute_harness_spindrel_tool", execute)

    options: dict = {}
    exported = harness._attach_claude_mcp_bridge(
        _ctx(),
        options,
        (
            HarnessToolSpec(
                name="create_excalidraw",
                description="Create an Excalidraw drawing",
                parameters={"type": "object", "properties": {"elements": {"type": "array"}}},
                schema={},
            ),
        ),
    )

    assert exported == ["create_excalidraw"]
    assert options["allowed_tools"] == ["mcp__spindrel__create_excalidraw"]
    assert captured_tools[0].name == "create_excalidraw"

    result = asyncio.run(captured_tools[0].handler({"elements": []}))

    assert result == {"content": [{"type": "text", "text": "tool output"}]}
    execute.assert_awaited_once()


def test_claude_mcp_bridge_rewrites_get_tool_info_callable_name(monkeypatch):
    captured_tools: list[types.SimpleNamespace] = []

    def fake_tool(name, description, input_schema):
        def decorator(handler):
            wrapped = types.SimpleNamespace(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=handler,
            )
            captured_tools.append(wrapped)
            return wrapped

        return decorator

    fake_sdk = types.SimpleNamespace(
        tool=fake_tool,
        create_sdk_mcp_server=lambda **kwargs: kwargs,
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)
    sys.modules.pop("integrations.claude_code.harness", None)
    harness = importlib.import_module("integrations.claude_code.harness")

    execute = AsyncMock(return_value=json.dumps({
        "schema": {
            "type": "function",
            "function": {
                "name": "bennie_loggins_health_summary",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    }))
    monkeypatch.setattr(harness, "execute_harness_spindrel_tool", execute)

    options: dict = {}
    harness._attach_claude_mcp_bridge(
        _ctx(),
        options,
        (
            HarnessToolSpec(
                name="get_tool_info",
                description="Look up a tool",
                parameters={"type": "object", "properties": {"tool_name": {"type": "string"}}},
                schema={},
            ),
        ),
    )

    result = asyncio.run(captured_tools[0].handler({"tool_name": "bennie_loggins_health_summary"}))
    payload = json.loads(result["content"][0]["text"])

    assert payload["schema"]["function"]["name"] == "mcp__spindrel__bennie_loggins_health_summary"
    assert payload["callable_name"] == "mcp__spindrel__bennie_loggins_health_summary"
    assert payload["harness_bridge"]["canonical_tool_name"] == "bennie_loggins_health_summary"
