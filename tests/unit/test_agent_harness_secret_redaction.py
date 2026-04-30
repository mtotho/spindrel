from __future__ import annotations

import re
import uuid
from unittest.mock import patch

from app.services import secret_registry
from app.services.agent_harnesses.base import ChannelEventEmitter


def _enable_secret(value: str) -> None:
    secret_registry._known_secrets = {value}
    secret_registry._pattern = re.compile(re.escape(value))


def test_harness_emitter_redacts_streamed_text_and_tool_result():
    _enable_secret("ghp_secret_token_123")
    events = []

    with patch("app.services.agent_harnesses.base.publish_typed") as publish:
        publish.side_effect = lambda _channel_id, event: events.append(event)
        emitter = ChannelEventEmitter(
            channel_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            bot_id="bot",
            session_id=uuid.uuid4(),
        )

        emitter.token("token is ghp_secret_token_123")
        emitter.tool_result(
            tool_name="Bash",
            tool_call_id="tu_1",
            result_summary="GITHUB_TOKEN=ghp_secret_token_123",
        )

    assert events[0].payload.delta == "token is [REDACTED]"
    assert events[-1].payload.result_summary == "GITHUB_TOKEN=[REDACTED]"


def test_harness_emitter_accumulates_redacted_thinking_text():
    _enable_secret("ghp_secret_token_think")
    events = []

    with patch("app.services.agent_harnesses.base.publish_typed") as publish:
        publish.side_effect = lambda _channel_id, event: events.append(event)
        emitter = ChannelEventEmitter(
            channel_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            bot_id="bot",
            session_id=uuid.uuid4(),
        )

        emitter.thinking("checking ghp_secret_token_think")
        emitter.thinking(" then reading files")

    assert events[0].payload.delta == "checking [REDACTED]"
    assert emitter.thinking_text() == "checking [REDACTED] then reading files"


def test_harness_emitter_redacts_nested_tool_arguments():
    _enable_secret("ghp_secret_token_456")
    events = []

    with patch("app.services.agent_harnesses.base.publish_typed") as publish:
        publish.side_effect = lambda _channel_id, event: events.append(event)
        emitter = ChannelEventEmitter(
            channel_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            bot_id="bot",
            session_id=uuid.uuid4(),
        )

        emitter.tool_start(
            tool_name="Bash",
            tool_call_id="tu_2",
            arguments={
                "command": "echo ghp_secret_token_456",
                "env": {"GITHUB_TOKEN": "ghp_secret_token_456"},
            },
        )

    assert events[0].payload.arguments == {
        "command": "echo [REDACTED]",
        "env": {"GITHUB_TOKEN": "[REDACTED]"},
    }


def test_harness_emitter_deduplicates_repeated_tool_start_ids():
    events = []

    with patch("app.services.agent_harnesses.base.publish_typed") as publish:
        publish.side_effect = lambda _channel_id, event: events.append(event)
        emitter = ChannelEventEmitter(
            channel_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            bot_id="bot",
            session_id=uuid.uuid4(),
        )

        emitter.tool_start(
            tool_name="dynamicTool",
            tool_call_id="call-1",
            arguments={},
        )
        emitter.tool_start(
            tool_name="search_memory",
            tool_call_id="call-1",
            arguments={"query": "Bennie"},
        )
        emitter.tool_result(
            tool_name="search_memory",
            tool_call_id="call-1",
            result_summary="ok",
        )

    assert [event.payload.tool_name for event in events] == ["dynamicTool", "search_memory"]
    assert emitter.persisted_tool_calls() == [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "search_memory",
                "arguments": {"query": "Bennie"},
            },
            "surface": "transcript",
            "summary": {
                "kind": "result",
                "subject_type": "tool",
                "label": "search_memory",
                "preview_text": "ok",
            },
        }
    ]


def test_harness_emitter_persists_rich_tool_result_envelope():
    events = []

    with patch("app.services.agent_harnesses.base.publish_typed") as publish:
        publish.side_effect = lambda _channel_id, event: events.append(event)
        emitter = ChannelEventEmitter(
            channel_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            bot_id="bot",
            session_id=uuid.uuid4(),
        )

        emitter.tool_start(
            tool_name="Edit",
            tool_call_id="tu_diff",
            arguments={"file_path": "app.py"},
        )
        emitter.tool_result(
            tool_name="Edit",
            tool_call_id="tu_diff",
            result_summary="Changed app.py: +1 -1 lines",
            envelope={
                "content_type": "application/vnd.spindrel.diff+text",
                "body": "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new",
                "plain_body": "Changed app.py: +1 -1 lines",
                "display": "inline",
                "truncated": False,
                "record_id": None,
                "byte_size": 48,
                "tool_call_id": "tu_diff",
            },
            surface="rich_result",
            summary={"kind": "diff", "subject_type": "file", "label": "Changed app.py", "path": "app.py"},
        )

    assert events[-1].payload.surface == "rich_result"
    assert events[-1].payload.envelope["content_type"] == "application/vnd.spindrel.diff+text"
    assert emitter.tool_envelopes()[0]["tool_call_id"] == "tu_diff"
    persisted = emitter.persisted_tool_calls()[0]
    assert persisted["surface"] == "rich_result"
    assert persisted["summary"]["kind"] == "diff"


def test_harness_emitter_synthesizes_missing_tool_start_for_result_only_events():
    events = []

    with patch("app.services.agent_harnesses.base.publish_typed") as publish:
        publish.side_effect = lambda _channel_id, event: events.append(event)
        emitter = ChannelEventEmitter(
            channel_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            bot_id="bot",
            session_id=uuid.uuid4(),
        )

        emitter.tool_result(
            tool_name="codex-event",
            tool_call_id="item-1",
            result_summary="completed without a start event",
        )

    assert [event.kind.value for event in events] == [
        "turn_stream_tool_start",
        "turn_stream_tool_result",
    ]
    assert events[0].payload.tool_call_id == "item-1"
    assert events[1].payload.tool_call_id == "item-1"
    assert emitter.persisted_tool_calls() == [
        {
            "id": "item-1",
            "type": "function",
            "function": {
                "name": "codex-event",
                "arguments": {},
            },
            "surface": "transcript",
            "summary": {
                "kind": "result",
                "subject_type": "tool",
                "label": "codex-event",
                "preview_text": "completed without a start event",
            },
        }
    ]


def test_harness_emitter_persists_result_only_structured_native_summary():
    events = []

    with patch("app.services.agent_harnesses.base.publish_typed") as publish:
        publish.side_effect = lambda _channel_id, event: events.append(event)
        emitter = ChannelEventEmitter(
            channel_id=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            bot_id="bot",
            session_id=uuid.uuid4(),
        )

        emitter.tool_result(
            tool_name="Codex subagent",
            tool_call_id="agent-1",
            result_summary="Codex subagent spawn agent",
            summary={
                "kind": "action",
                "subject_type": "session",
                "label": "Codex subagent spawn agent",
                "target_id": "thread-child",
                "target_label": "spawn_agent",
                "preview_text": "Inspect the renderer.",
            },
        )

    assert [event.kind.value for event in events] == [
        "turn_stream_tool_start",
        "turn_stream_tool_result",
    ]
    persisted = emitter.persisted_tool_calls()
    assert persisted == [
        {
            "id": "agent-1",
            "type": "function",
            "function": {
                "name": "Codex subagent",
                "arguments": {},
            },
            "surface": "transcript",
            "summary": {
                "kind": "action",
                "subject_type": "session",
                "label": "Codex subagent spawn agent",
                "target_id": "thread-child",
                "target_label": "spawn_agent",
                "preview_text": "Inspect the renderer.",
            },
        }
    ]
    assert emitter.assistant_turn_body(text="Done") == {
        "version": 1,
        "items": [
            {"id": "text:final", "kind": "text", "text": "Done"},
            {"id": "tool:agent-1", "kind": "tool_call", "toolCallId": "agent-1"},
        ],
    }
