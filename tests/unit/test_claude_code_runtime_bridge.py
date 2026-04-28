"""Bridge translation: Claude Agent SDK message → ChannelEventEmitter calls.

The bridge is the most fragile point of the integration — if the SDK renames
``ResultMessage.total_cost_usd`` or restructures content blocks, our turns
break. These tests use the real SDK dataclass types so a rename surfaces as
an import error or attribute error in CI, not a silent zero-cost / blank-text
production turn.

Phase 3: bridge takes a ``TurnContext`` so it can emit a synthetic
``auto-approved`` audit pair in ``bypassPermissions`` mode (where there's
no real approval card to provide visibility). Other modes route through
``request_harness_approval`` and the audit pair is suppressed — the real
approval card carries the signal.
"""
from __future__ import annotations

import uuid

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

from app.db.engine import async_session  # noqa: E402
from app.services.agent_harnesses.base import TurnContext  # noqa: E402
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


def _ctx(*, mode: str = "default", session_plan_mode: str = "chat") -> TurnContext:
    """Build a TurnContext for bridge tests. Default mode suppresses the
    bypass-mode audit pair so existing tests stay focused on the primary
    emit path. The bypass-mode test passes ``mode='bypassPermissions'``."""
    return TurnContext(
        spindrel_session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        bot_id="test-bot",
        turn_id=uuid.uuid4(),
        workdir="/tmp",
        harness_session_id=None,
        permission_mode=mode,
        db_session_factory=async_session,
        session_plan_mode=session_plan_mode,
    )


def test_text_block_emits_token_and_appends_to_final_text():
    emitter = _RecordingEmitter()
    final_text_parts: list[str] = []
    msg = AssistantMessage(content=[TextBlock(text="hello world")], model="claude-sonnet-4-6")

    _bridge_message(
        msg,
        ctx=_ctx(),
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
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=final_text_parts,
        result_meta={},
    )

    assert emitter.calls == [("thinking", {"delta": "reasoning step"})]
    assert final_text_parts == []


def test_tool_use_in_default_mode_emits_only_tool_start_no_audit():
    """Non-bypass modes route through request_harness_approval — no audit pair."""
    emitter = _RecordingEmitter()
    tool_name_by_use_id: dict[str, str] = {}
    msg = AssistantMessage(
        content=[ToolUseBlock(id="tu_1", name="Read", input={"path": "foo.py"})],
        model="claude-sonnet-4-6",
    )

    _bridge_message(
        msg,
        ctx=_ctx(mode="default"),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta={},
    )

    assert tool_name_by_use_id == {"tu_1": "Read"}
    # Single tool_start, no auto-approved pair.
    assert [c[0] for c in emitter.calls] == ["tool_start"]
    assert emitter.calls[0][1]["tool_name"] == "Read"


def test_tool_use_in_bypass_mode_emits_audit_pair():
    """In bypassPermissions there's no approval card — emit a paired
    tool_start + tool_result so the operator still sees an audit row."""
    emitter = _RecordingEmitter()
    msg = AssistantMessage(
        content=[ToolUseBlock(id="tu_99", name="Bash", input={"cmd": "ls"})],
        model="claude-sonnet-4-6",
    )

    _bridge_message(
        msg,
        ctx=_ctx(mode="bypassPermissions"),
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=[],
        result_meta={},
    )

    kinds = [c[0] for c in emitter.calls]
    # Real tool_start, then synthetic audit pair (matched tool_call_id so
    # the UI reducer correlates them as a single row).
    assert kinds == ["tool_start", "tool_start", "tool_result"]
    assert emitter.calls[0][1]["tool_name"] == "Bash"
    assert emitter.calls[1][1]["tool_name"] == "auto-approved"
    assert emitter.calls[1][1]["tool_call_id"] == "auto:tu_99"
    assert emitter.calls[2][1]["tool_name"] == "auto-approved"
    assert emitter.calls[2][1]["tool_call_id"] == "auto:tu_99"
    assert "Bash" in emitter.calls[2][1]["result_summary"]
    assert "bypassPermissions" in emitter.calls[2][1]["result_summary"]


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
        ctx=_ctx(),
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
        ctx=_ctx(),
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
        ctx=_ctx(),
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
        ctx=_ctx(),
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
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=[],
        result_meta={},
    )

    assert emitter.calls == []


def test_mixed_assistant_blocks_in_default_mode():
    """One AssistantMessage carrying text + thinking + tool_use produces all three (no audit pair)."""
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
        ctx=_ctx(mode="default"),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=final_text_parts,
        result_meta={},
    )

    kinds = [c[0] for c in emitter.calls]
    assert kinds == ["thinking", "token", "tool_start"]
    assert final_text_parts == ["Reading the file..."]
    assert tool_name_by_use_id == {"tu_3": "Read"}


# ----------------------------------------------------------------------------
# Tool classification methods on ClaudeCodeRuntime — fed into request_harness_approval
# ----------------------------------------------------------------------------


def test_runtime_classifies_readonly_tools():
    from integrations.claude_code.harness import ClaudeCodeRuntime
    rt = ClaudeCodeRuntime()
    readonly = rt.readonly_tools()
    assert "Read" in readonly
    assert "Glob" in readonly
    assert "Grep" in readonly
    assert "WebSearch" in readonly
    # Side-effecting tools are NOT in the readonly set.
    assert "Bash" not in readonly
    assert "Edit" not in readonly
    assert "Write" not in readonly


def test_runtime_prompts_in_accept_edits_for_side_effects_only():
    """In acceptEdits mode the SDK auto-approves Edit/Write — only Bash and
    other non-readonly side-effecting tools should ask."""
    from integrations.claude_code.harness import ClaudeCodeRuntime
    rt = ClaudeCodeRuntime()
    # Edit/Write: SDK handles natively, helper should NOT ask.
    assert rt.prompts_in_accept_edits("Edit") is False
    assert rt.prompts_in_accept_edits("Write") is False
    # Read/Glob/Grep/WebSearch: read-only, helper should NOT ask.
    assert rt.prompts_in_accept_edits("Read") is False
    assert rt.prompts_in_accept_edits("WebSearch") is False
    # Bash, WebFetch, Task, ExitPlanMode: helper SHOULD ask.
    assert rt.prompts_in_accept_edits("Bash") is True
    assert rt.prompts_in_accept_edits("WebFetch") is True
    assert rt.prompts_in_accept_edits("Task") is True
    assert rt.prompts_in_accept_edits("ExitPlanMode") is True


def test_runtime_autoapprove_in_plan_only_for_exit_plan_mode():
    """In plan mode the SDK renders the plan natively — ExitPlanMode is the
    only tool that shouldn't surface an approval card."""
    from integrations.claude_code.harness import ClaudeCodeRuntime
    rt = ClaudeCodeRuntime()
    assert rt.autoapprove_in_plan("ExitPlanMode") is True
    assert rt.autoapprove_in_plan("Bash") is False
    assert rt.autoapprove_in_plan("Edit") is False


def test_spindrel_plan_mode_maps_to_claude_native_plan_permission():
    from integrations.claude_code.harness import _effective_permission_mode

    assert _effective_permission_mode(
        _ctx(mode="bypassPermissions", session_plan_mode="planning")
    ) == "plan"
    assert _effective_permission_mode(
        _ctx(mode="default", session_plan_mode="chat")
    ) == "default"
