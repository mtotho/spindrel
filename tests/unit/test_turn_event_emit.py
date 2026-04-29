"""Unit tests for turn_event_emit.py — the run_stream → typed bus translator.

No DB needed. Tests feed a synthetic async generator of event dicts through
``emit_run_stream_events`` and assert which typed ChannelEvents land on the bus.
"""
import asyncio
import ast
import inspect
import textwrap
import uuid

import pytest

from app.domain.channel_events import ChannelEventKind
from app.services import channel_events as _bus
from app.services.turn_event_emit import _coerce_tool_arguments, emit_run_stream_events


@pytest.fixture(autouse=True)
def _clean_bus():
    _bus._subscribers.clear()
    _bus._next_seq.clear()
    _bus._replay_buffer.clear()
    yield
    _bus._subscribers.clear()
    _bus._next_seq.clear()
    _bus._replay_buffer.clear()


async def _run(
    source_events: list[dict],
    channel_id: uuid.UUID,
    *,
    session_id: uuid.UUID | None = None,
) -> tuple[list[dict], list]:
    """Drive emit_run_stream_events and collect (yielded_events, bus_events)."""
    q: asyncio.Queue = asyncio.Queue()
    _bus._subscribers[channel_id] = {q}

    async def _gen():
        for ev in source_events:
            yield ev

    yielded = [
        ev async for ev in emit_run_stream_events(
            _gen(),
            channel_id=channel_id,
            bot_id="bot-1",
            turn_id=uuid.uuid4(),
            session_id=session_id,
        )
    ]

    published = []
    while not q.empty():
        published.append(q.get_nowait())

    return yielded, published


# ---------------------------------------------------------------------------
# _coerce_tool_arguments (pure helper)
# ---------------------------------------------------------------------------

class TestCoerceToolArguments:
    def test_when_dict_then_returned_unchanged(self):
        assert _coerce_tool_arguments({"key": "val"}) == {"key": "val"}

    def test_when_json_string_then_parsed_to_dict(self):
        assert _coerce_tool_arguments('{"a": 1}') == {"a": 1}

    def test_when_empty_string_then_returns_empty_dict(self):
        assert _coerce_tool_arguments("") == {}

    def test_when_none_then_returns_empty_dict(self):
        assert _coerce_tool_arguments(None) == {}

    def test_when_invalid_json_then_wraps_raw(self):
        result = _coerce_tool_arguments("not{{json")
        assert result == {"_raw": "not{{json"}


# ---------------------------------------------------------------------------
# emit_run_stream_events — bus publish side-effects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEmitRunStreamEvents:
    async def test_when_text_delta_then_publishes_turn_stream_token(self):
        ch = uuid.uuid4()

        yielded, published = await _run([{"type": "text_delta", "delta": "hello"}], ch)

        assert len(published) == 1
        assert published[0].kind is ChannelEventKind.TURN_STREAM_TOKEN
        assert published[0].payload.delta == "hello"

    async def test_when_thinking_delta_then_publishes_turn_stream_thinking(self):
        # Regression: reasoning deltas from providers that stream summaries
        # (OpenAI Responses, Anthropic thinking_delta) must cross the bus, or
        # the web UI's thinking display stays empty even when the run_stream
        # is yielding `thinking` events.
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{"type": "thinking", "delta": "pondering..."}], ch
        )

        assert len(published) == 1
        assert published[0].kind is ChannelEventKind.TURN_STREAM_THINKING
        assert published[0].payload.delta == "pondering..."
        assert yielded == [{"type": "thinking", "delta": "pondering..."}]

    async def test_when_empty_thinking_delta_then_no_publish(self):
        ch = uuid.uuid4()

        yielded, published = await _run([{"type": "thinking", "delta": ""}], ch)

        assert published == []
        assert len(yielded) == 1

    async def test_when_thinking_content_then_not_republished_to_bus(self):
        # `thinking_content` is the end-of-iteration accumulation of the
        # deltas this helper already published — bus-publishing it would
        # double-append in the UI.
        ch = uuid.uuid4()

        yielded, published = await _run(
            [
                {"type": "thinking", "delta": "hi"},
                {"type": "thinking_content", "text": "hi"},
            ],
            ch,
        )

        assert len(published) == 1
        assert published[0].kind is ChannelEventKind.TURN_STREAM_THINKING
        assert len(yielded) == 2  # both still forwarded to caller

    async def test_when_tool_start_then_publishes_tool_start_with_parsed_args(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{"type": "tool_start", "tool": "get_skill", "tool_call_id": "call-1", "args": '{"skill_id": "widgets"}'}], ch
        )

        assert published[0].kind is ChannelEventKind.TURN_STREAM_TOOL_START
        assert published[0].payload.tool_name == "get_skill"
        assert published[0].payload.tool_call_id == "call-1"
        assert published[0].payload.arguments == {"skill_id": "widgets"}
        assert published[0].payload.surface == "transcript"
        assert published[0].payload.summary == {
            "kind": "read",
            "subject_type": "skill",
            "label": "Loaded skill",
            "target_id": "widgets",
            "target_label": "widgets",
        }

    async def test_when_tool_result_with_error_field_then_is_error_true(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{"type": "tool_result", "tool": "web_search", "error": "timeout", "result": None}], ch
        )

        assert published[0].kind is ChannelEventKind.TURN_STREAM_TOOL_RESULT
        assert published[0].payload.is_error is True
        assert published[0].payload.result_summary == "timeout"

    async def test_when_inline_widget_tool_result_errors_then_widget_surface_is_preserved(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{
                "type": "tool_result",
                "tool": "web_search",
                "tool_call_id": "call-search",
                "args": '{"q": "weather in Lambertville NJ today"}',
                "error": "Cannot connect to SearXNG",
                "result": '{"error": "Cannot connect to SearXNG"}',
                "envelope": {
                    "content_type": "application/vnd.spindrel.html+interactive",
                    "display": "inline",
                    "display_label": "Web search",
                    "plain_body": "Web search",
                },
            }],
            ch,
        )

        assert yielded[0]["type"] == "tool_result"
        assert published[0].kind is ChannelEventKind.TURN_STREAM_TOOL_RESULT
        assert published[0].payload.tool_call_id == "call-search"
        assert published[0].payload.surface == "widget"
        assert published[0].payload.summary == {
            "kind": "error",
            "subject_type": "widget",
            "label": "Widget unavailable",
            "target_label": "Web search",
            "error": "Cannot connect to SearXNG",
        }

    async def test_when_tool_result_includes_presentation_then_payload_preserves_it(self):
        ch = uuid.uuid4()
        diff_body = "\n".join([
            "--- a/index.html",
            "+++ b/index.html",
            "@@ -1 +1 @@",
            "-old line",
            "+new line",
        ])

        yielded, published = await _run(
            [{
                "type": "tool_result",
                "tool": "file",
                "tool_call_id": "call-edit",
                "result": "ok",
                "envelope": {
                    "content_type": "application/vnd.spindrel.diff+text",
                    "body": diff_body,
                    "plain_body": "Edited index.html",
                    "display": "inline",
                },
                "surface": "transcript",
                "summary": {
                    "kind": "diff",
                    "subject_type": "file",
                    "label": "Edited index.html",
                    "path": "index.html",
                    "diff_stats": {"additions": 1, "deletions": 1},
                },
            }],
            ch,
        )

        assert yielded[0]["type"] == "tool_result"
        assert published[0].kind is ChannelEventKind.TURN_STREAM_TOOL_RESULT
        assert published[0].payload.tool_call_id == "call-edit"
        assert published[0].payload.surface == "transcript"
        assert published[0].payload.summary == {
            "kind": "diff",
            "subject_type": "file",
            "label": "Edited index.html",
            "path": "index.html",
            "diff_stats": {"additions": 1, "deletions": 1},
        }

    async def test_when_tool_result_derives_time_preview_then_payload_keeps_it(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{
                "type": "tool_result",
                "tool": "get_current_local_time",
                "tool_call_id": "call-time",
                "result": "2026-04-22 14:05 EDT",
                "envelope": {
                    "content_type": "text/plain",
                    "body": "2026-04-22 14:05 EDT",
                    "plain_body": "2026-04-22 14:05 EDT",
                    "display": "badge",
                },
            }],
            ch,
        )

        assert yielded[0]["type"] == "tool_result"
        assert published[0].kind is ChannelEventKind.TURN_STREAM_TOOL_RESULT
        assert published[0].payload.tool_call_id == "call-time"
        assert published[0].payload.surface == "transcript"
        assert published[0].payload.summary == {
            "kind": "result",
            "subject_type": "generic",
            "label": "Got current local time",
            "preview_text": "2026-04-22 14:05 EDT",
        }

    async def test_when_unknown_event_type_then_no_bus_publish_but_still_yielded(self):
        ch = uuid.uuid4()
        passthrough = {"type": "rate_limit_wait", "seconds": 5}

        yielded, published = await _run([passthrough], ch)

        assert len(published) == 0
        assert yielded == [passthrough]

    async def test_when_context_budget_then_payload_carries_session_id(self):
        ch = uuid.uuid4()
        sid = uuid.uuid4()

        yielded, published = await _run(
            [{
                "type": "context_budget",
                "consumed_tokens": 249_000,
                "total_tokens": 272_000,
                "utilization": 0.915,
            }],
            ch,
            session_id=sid,
        )

        assert yielded[0]["type"] == "context_budget"
        assert published[0].kind is ChannelEventKind.CONTEXT_BUDGET
        assert published[0].payload.session_id == sid

    async def test_when_memory_scheme_bootstrap_then_publishes_memory_payload(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{
                "type": "memory_scheme_bootstrap",
                "memory_scheme": "workspace-files",
                "files_loaded": 3,
            }],
            ch,
        )

        assert yielded[0]["type"] == "memory_scheme_bootstrap"
        assert published[0].kind is ChannelEventKind.MEMORY_SCHEME_BOOTSTRAP
        assert published[0].payload.scheme == "workspace-files"
        assert published[0].payload.files_loaded == 3

    async def test_when_llm_retry_then_publishes_retry_status(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{
                "type": "llm_retry",
                "model": "gpt-main",
                "reason": "rate_limit",
                "attempt": 2,
                "max_retries": 4,
                "wait_seconds": 1.5,
            }],
            ch,
        )

        assert yielded[0]["type"] == "llm_retry"
        assert published[0].kind is ChannelEventKind.LLM_STATUS
        assert published[0].payload.status == "retry"
        assert published[0].payload.model == "gpt-main"
        assert published[0].payload.reason == "rate_limit"
        assert published[0].payload.attempt == 2
        assert published[0].payload.max_retries == 4
        assert published[0].payload.wait_seconds == 1.5

    async def test_when_llm_fallback_then_publishes_fallback_status(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{
                "type": "llm_fallback",
                "from_model": "gpt-main",
                "to_model": "gpt-backup",
                "reason": "vision_not_supported",
            }],
            ch,
        )

        assert yielded[0]["type"] == "llm_fallback"
        assert published[0].kind is ChannelEventKind.LLM_STATUS
        assert published[0].payload.status == "fallback"
        assert published[0].payload.model == "gpt-main"
        assert published[0].payload.fallback_model == "gpt-backup"
        assert published[0].payload.reason == "vision_not_supported"

    async def test_when_llm_cooldown_skip_then_publishes_cooldown_status(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{"type": "llm_cooldown_skip", "model": "gpt-main", "using": "gpt-backup"}],
            ch,
        )

        assert yielded[0]["type"] == "llm_cooldown_skip"
        assert published[0].kind is ChannelEventKind.LLM_STATUS
        assert published[0].payload.status == "cooldown_skip"
        assert published[0].payload.model == "gpt-main"
        assert published[0].payload.fallback_model == "gpt-backup"

    async def test_when_llm_error_then_publishes_error_status(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{
                "type": "llm_error",
                "model": "gpt-main",
                "reason": "all_failed",
                "error": "provider unavailable",
            }],
            ch,
        )

        assert yielded[0]["type"] == "llm_error"
        assert published[0].kind is ChannelEventKind.LLM_STATUS
        assert published[0].payload.status == "error"
        assert published[0].payload.model == "gpt-main"
        assert published[0].payload.reason == "all_failed"
        assert published[0].payload.error == "provider unavailable"

    async def test_when_auto_inject_then_publishes_skill_event(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{
                "type": "auto_inject",
                "skill_id": "skill-1",
                "skill_name": "Skill One",
                "similarity": 0.91,
                "source": "rag",
            }],
            ch,
        )

        assert yielded[0]["type"] == "auto_inject"
        assert published[0].kind is ChannelEventKind.SKILL_AUTO_INJECT
        assert published[0].payload.skill_id == "skill-1"
        assert published[0].payload.skill_name == "Skill One"
        assert published[0].payload.similarity == 0.91
        assert published[0].payload.source == "rag"

    async def test_when_multiple_events_then_all_yielded_and_typed_events_published(self):
        ch = uuid.uuid4()
        events = [
            {"type": "text_delta", "delta": "a"},
            {"type": "rate_limit_wait"},
            {"type": "text_delta", "delta": "b"},
        ]

        yielded, published = await _run(events, ch)

        assert yielded == events
        assert len(published) == 2
        assert [p.payload.delta for p in published] == ["a", "b"]

    async def test_when_approval_request_then_publishes_approval_requested(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{"type": "approval_request", "approval_id": "ap-1", "tool": "delete_file", "args": "{}"}], ch
        )

        assert published[0].kind is ChannelEventKind.APPROVAL_REQUESTED
        assert published[0].payload.approval_id == "ap-1"
        assert published[0].payload.tool_name == "delete_file"

    async def test_when_approval_resolved_with_verdict_field_then_decision_translated(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{"type": "approval_resolved", "approval_id": "ap-1", "verdict": "approved"}], ch
        )

        assert published[0].kind is ChannelEventKind.APPROVAL_RESOLVED
        assert published[0].payload.decision == "approved"


class TestTurnEventEmitArchitecture:
    def test_emit_run_stream_events_stays_publish_only_coordinator(self):
        import app.services.turn_event_emit as mod

        source = textwrap.dedent(inspect.getsource(mod.emit_run_stream_events))
        tree = ast.parse(source)
        fn = tree.body[0]

        assert isinstance(fn, ast.AsyncFunctionDef)
        assert fn.end_lineno - fn.lineno + 1 <= 55
        assert "_typed_event_from_run_stream_event" in source
        for forbidden in (
            "TurnStreamTokenPayload",
            "ContextBudgetPayload",
            "LlmStatusPayload",
            "SkillAutoInjectPayload",
            "ApprovalRequestedPayload",
        ):
            assert forbidden not in source

    def test_publish_typed_only_called_by_stream_coordinator(self):
        import app.services.turn_event_emit as mod

        tree = ast.parse(inspect.getsource(mod))
        callers: set[str] = set()
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "publish_typed"
            ):
                continue
            current: ast.AST = node
            while current in parents and not isinstance(
                parents[current],
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                current = parents[current]
            if current in parents:
                callers.add(parents[current].name)

        assert callers == {"emit_run_stream_events"}
