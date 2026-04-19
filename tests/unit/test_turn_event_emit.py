"""Unit tests for turn_event_emit.py — the run_stream → typed bus translator.

No DB needed. Tests feed a synthetic async generator of event dicts through
``emit_run_stream_events`` and assert which typed ChannelEvents land on the bus.
"""
import asyncio
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


async def _run(source_events: list[dict], channel_id: uuid.UUID) -> tuple[list[dict], list]:
    """Drive emit_run_stream_events and collect (yielded_events, bus_events)."""
    q: asyncio.Queue = asyncio.Queue()
    _bus._subscribers[channel_id] = {q}

    async def _gen():
        for ev in source_events:
            yield ev

    yielded = [ev async for ev in emit_run_stream_events(_gen(), channel_id=channel_id, bot_id="bot-1", turn_id=uuid.uuid4())]

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
            [{"type": "tool_start", "tool": "web_search", "args": '{"query": "cats"}'}], ch
        )

        assert published[0].kind is ChannelEventKind.TURN_STREAM_TOOL_START
        assert published[0].payload.tool_name == "web_search"
        assert published[0].payload.arguments == {"query": "cats"}

    async def test_when_tool_result_with_error_field_then_is_error_true(self):
        ch = uuid.uuid4()

        yielded, published = await _run(
            [{"type": "tool_result", "tool": "web_search", "error": "timeout", "result": None}], ch
        )

        assert published[0].kind is ChannelEventKind.TURN_STREAM_TOOL_RESULT
        assert published[0].payload.is_error is True
        assert published[0].payload.result_summary == "timeout"

    async def test_when_unknown_event_type_then_no_bus_publish_but_still_yielded(self):
        ch = uuid.uuid4()
        passthrough = {"type": "rate_limit_wait", "seconds": 5}

        yielded, published = await _run([passthrough], ch)

        assert len(published) == 0
        assert yielded == [passthrough]

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
