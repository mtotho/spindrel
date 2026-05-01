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
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

# Skip the whole file if the SDK is not installed in this environment so the
# rest of the unit suite stays runnable. CI does install it (see pyproject.toml).
pytest.importorskip("claude_agent_sdk")

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from app.db.engine import async_session  # noqa: E402
from app.services.agent_harnesses.base import (  # noqa: E402
    HarnessInputAttachment,
    HarnessInputManifest,
    TurnContext,
)
from integrations.claude_code.harness import _build_claude_query_input  # noqa: E402
from integrations.claude_code.harness import _allowed_tools_for_mode  # noqa: E402
from integrations.claude_code.harness import _bridge_message  # noqa: E402
from integrations.claude_code.harness import _extract_claude_system_slash_commands  # noqa: E402
from integrations.claude_code.harness import _set_partial_message_streaming_kwarg  # noqa: E402


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

    def tool_result(
        self,
        *,
        tool_name: str,
        result_summary: str,
        is_error=False,
        tool_call_id=None,
        envelope=None,
        surface=None,
        summary=None,
    ) -> None:
        self.calls.append(("tool_result", {
            "tool_name": tool_name,
            "result_summary": result_summary,
            "is_error": is_error,
            "tool_call_id": tool_call_id,
            "envelope": envelope,
            "surface": surface,
            "summary": summary,
        }))


def _ctx(
    *,
    mode: str = "default",
    session_plan_mode: str = "chat",
    workdir: str = "/tmp",
    input_manifest: HarnessInputManifest | None = None,
) -> TurnContext:
    """Build a TurnContext for bridge tests. Default mode suppresses the
    bypass-mode audit pair so existing tests stay focused on the primary
    emit path. The bypass-mode test passes ``mode='bypassPermissions'``."""
    return TurnContext(
        spindrel_session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        bot_id="test-bot",
        turn_id=uuid.uuid4(),
        workdir=workdir,
        harness_session_id=None,
        permission_mode=mode,
        db_session_factory=async_session,
        session_plan_mode=session_plan_mode,
        input_manifest=input_manifest or HarnessInputManifest(),
    )


async def _collect_messages(stream: AsyncIterator[dict]) -> list[dict]:
    messages: list[dict] = []
    async for message in stream:
        messages.append(message)
    return messages


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


def test_partial_message_streaming_kwarg_is_enabled_when_sdk_supports_it():
    class Options:
        def __init__(self, include_partial_messages: bool = False) -> None:
            self.include_partial_messages = include_partial_messages

    options_kwargs: dict = {}

    _set_partial_message_streaming_kwarg(Options, options_kwargs)

    assert options_kwargs == {"include_partial_messages": True}


def test_bypass_allowed_tools_include_native_claude_code_sdk_surfaces():
    allowed = set(_allowed_tools_for_mode("bypassPermissions"))

    assert {"Agent", "Skill", "TodoWrite", "ToolSearch"}.issubset(allowed)
    assert "AskUserQuestion" not in allowed


def test_restricted_allowed_tools_do_not_bypass_mutating_or_orchestration_surfaces():
    allowed = set(_allowed_tools_for_mode("default"))

    assert {"Read", "Glob", "Grep", "WebSearch"}.issubset(allowed)
    assert "Skill" not in allowed
    assert "Agent" not in allowed
    assert "TodoWrite" not in allowed
    assert "AskUserQuestion" not in allowed


def test_stream_event_text_deltas_emit_incremental_tokens_and_suppress_duplicate_final_text():
    emitter = _RecordingEmitter()
    final_text_parts: list[str] = []
    result_meta: dict = {}

    for text in ("hello ", "world"):
        _bridge_message(
            StreamEvent(
                uuid="event-id",
                session_id="session-id",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": text},
                },
            ),
            ctx=_ctx(),
            emit=emitter,
            tool_name_by_use_id={},
            final_text_parts=final_text_parts,
            result_meta=result_meta,
        )

    _bridge_message(
        AssistantMessage(content=[TextBlock(text="hello world")], model="claude-sonnet-4-6"),
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=final_text_parts,
        result_meta=result_meta,
    )

    assert emitter.calls == [
        ("token", {"delta": "hello "}),
        ("token", {"delta": "world"}),
    ]
    assert final_text_parts == ["hello ", "world"]


def test_system_init_slash_inventory_extracts_nested_sdk_payload():
    payload = {
        "subtype": "init",
        "data": {
            "runtime": {
                "slashCommands": [
                    {"name": "skills", "description": "List skills"},
                    {"name": "project-local", "source": "project"},
                ]
            }
        },
    }

    commands = _extract_claude_system_slash_commands(payload)

    assert [command["name"] for command in commands] == ["skills", "project-local"]


@pytest.mark.asyncio
async def test_claude_query_input_keeps_plain_string_without_images():
    query_input, runtime_items, warnings = _build_claude_query_input("Hello", _ctx())

    assert query_input == "Hello"
    assert runtime_items == ()
    assert warnings == ()


@pytest.mark.asyncio
async def test_claude_query_input_maps_inline_images_to_sdk_content_blocks():
    manifest = HarnessInputManifest(
        attachments=(
            HarnessInputAttachment(
                kind="image",
                source="inline_attachment",
                name="screen.png",
                mime_type="image/png",
                content_base64="AAA",
            ),
        )
    )

    query_input, runtime_items, warnings = _build_claude_query_input(
        "Look at this.",
        _ctx(input_manifest=manifest),
    )
    assert not isinstance(query_input, str)
    messages = await _collect_messages(query_input)

    content = messages[0]["message"]["content"]
    assert content[0] == {"type": "text", "text": "Look at this."}
    assert content[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAA"},
    }
    assert runtime_items == (
        {
            "type": "image",
            "name": "screen.png",
            "path": None,
            "source": "inline_attachment",
        },
    )
    assert warnings == ()
    assert "AAA" not in str(manifest.metadata(runtime_items=runtime_items))


@pytest.mark.asyncio
async def test_claude_query_input_reads_workspace_image_inside_cwd(tmp_path):
    image_path = tmp_path / ".uploads" / "pixel.jpg"
    image_path.parent.mkdir()
    image_path.write_bytes(b"jpg-bytes")
    manifest = HarnessInputManifest(
        attachments=(
            HarnessInputAttachment(
                kind="image",
                source="channel_workspace",
                name="pixel.jpg",
                mime_type="image/jpeg",
                path=str(image_path),
                size_bytes=9,
            ),
        )
    )

    query_input, runtime_items, warnings = _build_claude_query_input(
        "Describe it.",
        _ctx(workdir=str(tmp_path), input_manifest=manifest),
    )
    assert not isinstance(query_input, str)
    messages = await _collect_messages(query_input)

    image_block = messages[0]["message"]["content"][1]
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert image_block["source"]["data"] == "anBnLWJ5dGVz"
    assert runtime_items == (
        {
            "type": "image",
            "name": "pixel.jpg",
            "path": str(image_path),
            "source": "channel_workspace",
        },
    )
    assert warnings == ()


def test_claude_query_input_skips_workspace_image_outside_cwd(tmp_path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"png")
    manifest = HarnessInputManifest(
        attachments=(
            HarnessInputAttachment(
                kind="image",
                source="channel_workspace",
                name="outside.png",
                mime_type="image/png",
                path=str(outside),
            ),
        )
    )

    query_input, runtime_items, warnings = _build_claude_query_input(
        "Look.",
        _ctx(workdir=str(tmp_path), input_manifest=manifest),
    )

    assert query_input == "Look."
    assert runtime_items == ()
    assert "outside harness cwd" in warnings[0]


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
            "envelope": {
                "content_type": "text/plain",
                "body": "file contents here",
                "plain_body": "file contents here",
                "display": "inline",
                "truncated": False,
                "record_id": None,
                "byte_size": 18,
                "tool_name": "Read",
                "tool_call_id": "tu_1",
            },
            "surface": "rich_result",
            "summary": {
                "kind": "result",
                "subject_type": "generic",
                "label": "file contents here",
                "preview_text": "file contents here",
            },
        }),
    ]


def test_bash_tool_result_emits_text_envelope():
    emitter = _RecordingEmitter()
    msg = UserMessage(
        content=[ToolResultBlock(
            tool_use_id="tu_bash",
            content="stdout line\n",
            is_error=False,
        )],
    )

    _bridge_message(
        msg,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id={"tu_bash": "Bash"},
        final_text_parts=[],
        result_meta={},
    )

    result = emitter.calls[0][1]
    assert result["surface"] == "rich_result"
    assert result["envelope"]["content_type"] == "text/plain"
    assert result["envelope"]["body"] == "stdout line"
    assert result["envelope"]["tool_call_id"] == "tu_bash"


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


def test_edit_tool_result_emits_runtime_supplied_diff_envelope():
    emitter = _RecordingEmitter()
    result_meta: dict = {}
    msg_start = AssistantMessage(
        content=[
            ToolUseBlock(
                id="tu_edit",
                name="Edit",
                input={
                    "file_path": "app.py",
                    "old_string": "print('old')\n",
                    "new_string": "print('new')\n",
                },
            )
        ],
        model="claude-sonnet-4-6",
    )
    msg_result = UserMessage(
        content=[ToolResultBlock(tool_use_id="tu_edit", content="updated", is_error=False)],
    )

    _bridge_message(
        msg_start,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=[],
        result_meta=result_meta,
    )
    _bridge_message(
        msg_result,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id={"tu_edit": "Edit"},
        final_text_parts=[],
        result_meta=result_meta,
    )

    result = emitter.calls[-1][1]
    assert result["surface"] == "rich_result"
    assert result["envelope"]["content_type"] == "application/vnd.spindrel.diff+text"
    assert "--- a/app.py" in result["envelope"]["body"]
    assert "-print('old')" in result["envelope"]["body"]
    assert "+print('new')" in result["envelope"]["body"]
    assert result["summary"]["kind"] == "diff"
    assert result["summary"]["path"] == "app.py"


def test_write_tool_result_emits_runtime_supplied_code_envelope():
    emitter = _RecordingEmitter()
    result_meta: dict = {}
    msg_start = AssistantMessage(
        content=[
            ToolUseBlock(
                id="tu_write",
                name="Write",
                input={
                    "file_path": "index.html",
                    "content": "<!DOCTYPE html>\n<html>\n</html>\n",
                },
            )
        ],
        model="claude-sonnet-4-6",
    )
    msg_result = UserMessage(
        content=[ToolResultBlock(tool_use_id="tu_write", content="written", is_error=False)],
    )

    _bridge_message(
        msg_start,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id={},
        final_text_parts=[],
        result_meta=result_meta,
    )
    _bridge_message(
        msg_result,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id={"tu_write": "Write"},
        final_text_parts=[],
        result_meta=result_meta,
    )

    result = emitter.calls[-1][1]
    assert result["surface"] == "rich_result"
    assert result["envelope"]["content_type"] == "text/plain"
    assert result["envelope"]["plain_body"] == "Wrote index.html"
    assert result["envelope"]["display_label"] == "index.html"
    assert result["envelope"]["body"].startswith("<!DOCTYPE html>")
    assert result["summary"]["kind"] == "write"
    assert result["summary"]["subject_type"] == "file"
    assert result["summary"]["label"] == "Wrote index.html"
    assert result["summary"]["path"] == "index.html"
    assert "preview_text" not in result["summary"]


def test_spindrel_mcp_tool_result_reuses_dispatcher_envelope():
    emitter = _RecordingEmitter()
    result_meta = {
        "claude_spindrel_tool_results": {
            "list_channels:{}": [
                SimpleNamespace(
                    envelope={
                        "content_type": "application/json",
                        "body": '{"channels": []}',
                        "plain_body": "Listed channels",
                        "display": "inline",
                        "truncated": False,
                        "record_id": None,
                        "byte_size": 16,
                    },
                    summary={"kind": "json", "subject_type": "tool", "label": "Channels"},
                )
            ],
        },
    }
    msg_start = AssistantMessage(
        content=[
            ToolUseBlock(id="tu_mcp", name="mcp__spindrel__list_channels", input={})
        ],
        model="claude-sonnet-4-6",
    )
    msg_result = UserMessage(
        content=[ToolResultBlock(tool_use_id="tu_mcp", content="Listed channels", is_error=False)],
    )

    tool_name_by_use_id: dict[str, str] = {}
    _bridge_message(
        msg_start,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta=result_meta,
    )
    _bridge_message(
        msg_result,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta=result_meta,
    )

    result = emitter.calls[-1][1]
    assert result["surface"] == "rich_result"
    assert result["envelope"]["content_type"] == "application/json"
    assert result["envelope"]["tool_call_id"] == "tu_mcp"
    assert result["summary"]["label"] == "Channels"


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


def test_todo_write_result_persists_progress_summary():
    emitter = _RecordingEmitter()
    result_meta: dict = {}
    tool_name_by_use_id: dict[str, str] = {}
    msg_start = AssistantMessage(
        content=[
            ToolUseBlock(
                id="tu_todo",
                name="TodoWrite",
                input={
                    "todos": [
                        {"content": "Inspect SDK docs", "status": "completed"},
                        {"content": "Add parity tests", "status": "in_progress"},
                    ]
                },
            )
        ],
        model="claude-sonnet-4-6",
    )
    msg_result = UserMessage(
        content=[ToolResultBlock(tool_use_id="tu_todo", content="Todo list updated", is_error=False)]
    )

    _bridge_message(
        msg_start,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta=result_meta,
    )
    _bridge_message(
        msg_result,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta=result_meta,
    )

    result_call = [call for call in emitter.calls if call[0] == "tool_result"][-1][1]
    assert result_call["tool_name"] == "TodoWrite"
    assert result_call["surface"] == "rich_result"
    assert result_call["summary"]["kind"] == "progress"
    assert result_call["summary"]["subject_type"] == "todo"
    assert result_call["summary"]["todo_count"] == 2
    assert result_call["envelope"]["tool_call_id"] == "tu_todo"


def test_toolsearch_result_persists_discovery_summary():
    emitter = _RecordingEmitter()
    result_meta: dict = {}
    tool_name_by_use_id: dict[str, str] = {}
    msg_start = AssistantMessage(
        content=[
            ToolUseBlock(
                id="tu_search",
                name="ToolSearch",
                input={"query": "TodoWrite"},
            )
        ],
        model="claude-sonnet-4-6",
    )
    msg_result = UserMessage(
        content=[ToolResultBlock(
            tool_use_id="tu_search",
            content="Found tool: TodoWrite",
            is_error=False,
        )]
    )

    _bridge_message(
        msg_start,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta=result_meta,
    )
    _bridge_message(
        msg_result,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta=result_meta,
    )

    result_call = [call for call in emitter.calls if call[0] == "tool_result"][-1][1]
    assert result_call["tool_name"] == "ToolSearch"
    assert result_call["surface"] == "rich_result"
    assert result_call["summary"]["kind"] == "discovery"
    assert result_call["summary"]["subject_type"] == "tool"
    assert result_call["summary"]["query"] == "TodoWrite"
    assert result_call["envelope"]["tool_call_id"] == "tu_search"


def test_claude_task_result_persists_subagent_summary():
    emitter = _RecordingEmitter()
    result_meta: dict = {}
    tool_name_by_use_id: dict[str, str] = {}
    msg_start = AssistantMessage(
        content=[
            ToolUseBlock(
                id="tu_task",
                name="Task",
                input={
                    "description": "Review harness parity",
                    "subagent_type": "general-purpose",
                    "prompt": "Inspect SDK parity gaps and summarize.",
                },
            )
        ],
        model="claude-sonnet-4-6",
    )
    msg_result = UserMessage(
        content=[ToolResultBlock(tool_use_id="tu_task", content="Found two gaps.", is_error=False)]
    )

    _bridge_message(
        msg_start,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta=result_meta,
    )
    _bridge_message(
        msg_result,
        ctx=_ctx(),
        emit=emitter,
        tool_name_by_use_id=tool_name_by_use_id,
        final_text_parts=[],
        result_meta=result_meta,
    )

    result_call = [call for call in emitter.calls if call[0] == "tool_result"][-1][1]
    assert result_call["tool_name"] == "Task"
    assert result_call["surface"] == "rich_result"
    assert result_call["summary"]["kind"] == "subagent"
    assert result_call["summary"]["subject_type"] == "agent"
    assert result_call["summary"]["subagent_type"] == "general-purpose"
    assert "Inspect SDK parity" in result_call["summary"]["prompt_preview"]


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
