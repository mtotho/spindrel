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
from app.services.agent_harnesses.interactions import HarnessQuestionResult
from integrations.sdk import HarnessSpindrelToolResult


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

    execute = AsyncMock(return_value=HarnessSpindrelToolResult(text="tool output"))
    monkeypatch.setattr(harness, "execute_harness_spindrel_tool_result", execute)

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

    execute = AsyncMock(return_value=HarnessSpindrelToolResult(text=json.dumps({
        "schema": {
            "type": "function",
            "function": {
                "name": "bennie_loggins_health_summary",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    })))
    monkeypatch.setattr(harness, "execute_harness_spindrel_tool_result", execute)

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


def test_claude_mcp_bridge_caches_rich_spindrel_tool_result(monkeypatch):
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

    execute = AsyncMock(return_value=HarnessSpindrelToolResult(
        text="channels",
        envelope={
            "content_type": "application/json",
            "body": '{"channels": []}',
            "plain_body": "channels",
            "display": "inline",
            "truncated": False,
            "record_id": None,
            "byte_size": 16,
        },
        surface="rich_result",
        summary={"kind": "json", "subject_type": "tool", "label": "Channels"},
    ))
    monkeypatch.setattr(harness, "execute_harness_spindrel_tool_result", execute)

    bridge_results: dict = {}
    harness._attach_claude_mcp_bridge(
        _ctx(),
        {},
        (
            HarnessToolSpec(
                name="list_channels",
                description="List channels",
                parameters={"type": "object", "properties": {}},
                schema={},
            ),
        ),
        bridge_results=bridge_results,
    )

    result = asyncio.run(captured_tools[0].handler({}))

    assert result == {"content": [{"type": "text", "text": "channels"}]}
    assert "list_channels:{}" in bridge_results
    assert bridge_results["list_channels:{}"][0].summary["label"] == "Channels"


def test_claude_ask_user_question_routes_through_harness_question(monkeypatch):
    class FakeAllow:
        def __init__(self, updated_input=None):
            self.updated_input = updated_input

    class FakeDeny:
        def __init__(self, message="", interrupt=False):
            self.message = message
            self.interrupt = interrupt

    fake_sdk = types.SimpleNamespace(
        PermissionResultAllow=FakeAllow,
        PermissionResultDeny=FakeDeny,
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)
    sys.modules.pop("integrations.claude_code.harness", None)
    harness = importlib.import_module("integrations.claude_code.harness")

    captured: dict[str, object] = {}

    async def fake_request_harness_question(*, ctx, runtime_name, tool_input):
        captured["ctx"] = ctx
        captured["runtime_name"] = runtime_name
        captured["tool_input"] = tool_input
        return HarnessQuestionResult(
            interaction_id="question-1",
            questions=[
                {
                    "id": "scope",
                    "question": "Which scope?",
                    "options": [{"label": "Focused"}],
                }
            ],
            answers=[
                {
                    "question_id": "scope",
                    "answer": "Only inspect the harness adapter.",
                    "selected_options": ["Focused"],
                }
            ],
            notes="No file writes.",
        )

    monkeypatch.setattr(harness, "request_harness_question", fake_request_harness_question)
    runtime = harness.ClaudeCodeRuntime()
    ctx = _ctx()
    callback = harness._make_can_use_tool(ctx, runtime=runtime)

    result = asyncio.run(callback(
        "AskUserQuestion",
        {
            "prompt": "Need scope",
            "questions": [{"id": "scope", "question": "Which scope?"}],
        },
        types.SimpleNamespace(),
    ))

    assert isinstance(result, FakeAllow)
    assert captured == {
        "ctx": ctx,
        "runtime_name": "claude-code",
        "tool_input": {
            "prompt": "Need scope",
            "questions": [{"id": "scope", "question": "Which scope?"}],
        },
    }
    assert result.updated_input["answers"] == {
        "Which scope?": "Focused; Only inspect the harness adapter.",
        "Additional notes": "No file writes.",
    }
    assert result.updated_input["spindrel_answers"] == [
        {
            "question_id": "scope",
            "question": "Which scope?",
            "answer": "Focused; Only inspect the harness adapter.",
            "selected_options": ["Focused"],
        }
    ]
