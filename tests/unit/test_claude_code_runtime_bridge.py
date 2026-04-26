"""Bridge translation: Claude Agent SDK message → ChannelEventEmitter calls.

The bridge is the most fragile point of the integration — if the SDK renames
``ResultMessage.total_cost_usd`` or restructures content blocks, our turns
break. These tests use the real SDK dataclass types so a rename surfaces as
an import error or attribute error in CI, not a silent zero-cost / blank-text
production turn.
"""
from __future__ import annotations

import pytest

# Skip the whole file if the SDK is not installed in this environment so the
# rest of the unit suite stays runnable. CI does install it (see pyproject.toml).
pytest.importorskip("claude_agent_sdk")

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from integrations.claude_code.harness import _bridge_message  # noqa: E402


class _RecordingEmitter:
    """ChannelEventEmitter stand-in that records every call for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def token(self, delta: str) -> None:
        self.calls.append(("token", {"delta": delta}))

    def thinking(self, delta: str) -> None:
        self.calls.append(("thinking", {"delta": delta}))

    def tool_start(self, *, tool_name: str, arguments=None, tool_call_id=None) -> None:
        self.calls.append(("tool_start", {
            "tool_name": tool_name,
            "arguments": arguments or {},
            "tool_call_id": tool_call_id,
        }))

    def tool_result(self, *, tool_name: str, result_summary: str, is_error=False, tool_call_id=None) -> None:
        self.calls.append(("tool_result", {
            "tool_name": tool_name,
            "result_summary": result_summary,
            "is_error": is_error,
            "tool_call_id": tool_call_id,
        }))


def _empty_state():
    return {}, [], []  # tool_name_by_use_id, final_text_parts, calls (placeholder)


def test_text_block_emits_token_and_appends_to_final_text():
    emitter = _RecordingEmitter()
    final_text_parts: list[str] = []
    msg = AssistantMessage(content=[TextBlock(text="hello world")], model="claude-sonnet-4-6")

    _bridge_message(
        msg,
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=final_text_parts,
        result_meta={},
    )

    assert emitter.calls == [("token", {"delta": "hello world"})]
    assert final_text_parts == ["hello world"]


def test_thinking_block_emits_thinking_only():
    emitter = _RecordingEmitter()
    final_text_parts: list[str] = []
    msg = AssistantMessage(
        content=[ThinkingBlock(thinking="reasoning step", signature="sig")],
        model="claude-sonnet-4-6",
    )

    _bridge_message(
        msg,
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=final_text_parts,
        result_meta={},
    )

    assert emitter.calls == [("thinking", {"delta": "reasoning step"})]
    assert final_text_parts == []


def test_tool_use_emits_tool_start_and_records_lookup():
    emitter = _RecordingEmitter()
    tool_name_by_use_id: dict[str, str] = {}
    msg = AssistantMessage(
        content=[ToolUseBlock(id="tu_1", name="Read", input={"path": "foo.py"})],
        model="claude-sonnet-4-6",
    )

    _bridge_message(
        msg,
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta={},
    )

    assert tool_name_by_use_id == {"tu_1": "Read"}
    assert emitter.calls == [
        ("tool_start", {
            "tool_name": "Read",
            "arguments": {"path": "foo.py"},
            "tool_call_id": "tu_1",
        }),
    ]


def test_tool_result_uses_lookup_to_resolve_tool_name():
    emitter = _RecordingEmitter()
    msg = UserMessage(
        content=[ToolResultBlock(
            tool_use_id="tu_1",
            content="file contents here",
            is_error=False,
        )],
    )

    _bridge_message(
        msg,
        emit=emitter,
        tool_name_by_use_id={"tu_1": "Read"},
        final_text_parts=[],
        result_meta={},
    )

    assert emitter.calls == [
        ("tool_result", {
            "tool_name": "Read",
            "result_summary": "file contents here",
            "is_error": False,
            "tool_call_id": "tu_1",
        }),
    ]


def test_tool_result_with_unknown_use_id_falls_back_to_unknown():
    emitter = _RecordingEmitter()
    msg = UserMessage(
        content=[ToolResultBlock(tool_use_id="tu_unknown", content="x", is_error=True)],
    )

    _bridge_message(
        msg,
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=[],
        result_meta={},
    )

    assert emitter.calls[0][1]["tool_name"] == "unknown"
    assert emitter.calls[0][1]["is_error"] is True


def test_tool_result_list_content_joins_text_items():
    emitter = _RecordingEmitter()
    msg = UserMessage(
        content=[ToolResultBlock(
            tool_use_id="tu_2",
            content=[
                {"type": "text", "text": "line one"},
                {"type": "text", "text": "line two"},
            ],
        )],
    )

    _bridge_message(
        msg,
        emit=emitter,
        tool_name_by_use_id={"tu_2": "Bash"},
        final_text_parts=[],
        result_meta={},
    )

    assert emitter.calls[0][1]["result_summary"] == "line one\nline two"


def test_result_message_populates_meta():
    emitter = _RecordingEmitter()
    result_meta: dict = {}
    msg = ResultMessage(
        subtype="success",
        duration_ms=1234,
        duration_api_ms=900,
        is_error=False,
        num_turns=3,
        session_id="sess_abc",
        total_cost_usd=0.0123,
        usage={"input_tokens": 100, "output_tokens": 50},
        result="all done",
    )

    _bridge_message(
        msg,
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=[],
        result_meta=result_meta,
    )

    assert emitter.calls == []
    assert result_meta["session_id"] == "sess_abc"
    assert result_meta["total_cost_usd"] == 0.0123
    assert result_meta["usage"] == {"input_tokens": 100, "output_tokens": 50}
    assert result_meta["is_error"] is False
    assert result_meta["result"] == "all done"


def test_system_message_is_silently_ignored():
    emitter = _RecordingEmitter()
    msg = SystemMessage(subtype="init", data={"some": "metadata"})

    _bridge_message(
        msg,
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=[],
        result_meta={},
    )

    assert emitter.calls == []


def test_mixed_assistant_blocks_in_one_message():
    """One AssistantMessage carrying text + thinking + tool_use produces all three."""
    emitter = _RecordingEmitter()
    final_text_parts: list[str] = []
    tool_name_by_use_id: dict[str, str] = {}
    msg = AssistantMessage(
        content=[
            ThinkingBlock(thinking="planning", signature="sig"),
            TextBlock(text="Reading the file..."),
            ToolUseBlock(id="tu_3", name="Read", input={"path": "a.py"}),
        ],
        model="claude-sonnet-4-6",
    )

    _bridge_message(
        msg,
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=final_text_parts,
        result_meta={},
    )

    kinds = [c[0] for c in emitter.calls]
    assert kinds == ["thinking", "token", "tool_start"]
    assert final_text_parts == ["Reading the file..."]
    assert tool_name_by_use_id == {"tu_3": "Read"}
