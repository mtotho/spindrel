"""Tests for StreamAccumulator and AccumulatedMessage."""
from unittest.mock import MagicMock

import pytest

from app.agent.llm import AccumulatedMessage, StreamAccumulator


def _make_chunk(
    content=None,
    tool_calls=None,
    finish_reason=None,
    usage=None,
    reasoning_content=None,
):
    """Build a mock streaming chunk."""
    chunk = MagicMock()
    if content is None and tool_calls is None and finish_reason is None and reasoning_content is None:
        # Usage-only chunk (no choices)
        if usage is not None:
            chunk.choices = []
            chunk.usage = usage
            return chunk

    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls
    # reasoning_content as an attribute on delta
    if reasoning_content is not None:
        delta.reasoning_content = reasoning_content
    else:
        delta.reasoning_content = None
    delta.reasoning = None

    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason

    chunk.choices = [choice]
    chunk.usage = usage
    return chunk


def _make_tc_delta(index=0, tc_id=None, name=None, arguments=None):
    """Build a mock tool call delta."""
    d = MagicMock()
    d.index = index
    d.id = tc_id
    d.function = MagicMock()
    d.function.name = name
    d.function.arguments = arguments
    return d


class TestStreamAccumulator:
    def test_text_content_accumulation(self):
        acc = StreamAccumulator()
        events1, done1 = acc.feed(_make_chunk(content="Hello "))
        assert not done1
        assert events1 == [{"type": "text_delta", "delta": "Hello "}]

        events2, done2 = acc.feed(_make_chunk(content="world"))
        assert not done2
        assert events2 == [{"type": "text_delta", "delta": "world"}]

        events3, done3 = acc.feed(_make_chunk(finish_reason="stop"))
        assert done3

        msg = acc.build()
        assert msg.content == "Hello world"
        assert msg.tool_calls is None
        assert msg.thinking_content is None

    def test_tool_call_accumulation(self):
        acc = StreamAccumulator()

        # First delta: tool call ID + name
        tc1 = _make_tc_delta(index=0, tc_id="tc_1", name="search", arguments="")
        events1, _ = acc.feed(_make_chunk(tool_calls=[tc1]))
        assert events1 == []  # tool call deltas don't produce events

        # Second delta: argument chunk
        tc2 = _make_tc_delta(index=0, arguments='{"query": ')
        acc.feed(_make_chunk(tool_calls=[tc2]))

        # Third delta: more arguments
        tc3 = _make_tc_delta(index=0, arguments='"test"}')
        acc.feed(_make_chunk(tool_calls=[tc3]))

        acc.feed(_make_chunk(finish_reason="tool_calls"))
        msg = acc.build()

        assert msg.content is None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["id"] == "tc_1"
        assert msg.tool_calls[0]["function"]["name"] == "search"
        assert msg.tool_calls[0]["function"]["arguments"] == '{"query": "test"}'

    def test_multiple_tool_calls(self):
        acc = StreamAccumulator()

        tc_a = _make_tc_delta(index=0, tc_id="tc_a", name="tool_a", arguments='{}')
        tc_b = _make_tc_delta(index=1, tc_id="tc_b", name="tool_b", arguments='{"x": 1}')
        acc.feed(_make_chunk(tool_calls=[tc_a, tc_b]))
        acc.feed(_make_chunk(finish_reason="tool_calls"))

        msg = acc.build()
        assert len(msg.tool_calls) == 2
        assert msg.tool_calls[0]["function"]["name"] == "tool_a"
        assert msg.tool_calls[1]["function"]["name"] == "tool_b"

    def test_thinking_content(self):
        acc = StreamAccumulator()

        events1, _ = acc.feed(_make_chunk(reasoning_content="Let me think..."))
        assert events1 == [{"type": "thinking", "delta": "Let me think..."}]

        events2, _ = acc.feed(_make_chunk(content="Here's my answer"))
        assert events2 == [{"type": "text_delta", "delta": "Here's my answer"}]

        acc.feed(_make_chunk(finish_reason="stop"))
        msg = acc.build()
        assert msg.thinking_content == "Let me think..."
        assert msg.content == "Here's my answer"

    def test_mixed_content_and_tool_calls(self):
        acc = StreamAccumulator()

        acc.feed(_make_chunk(content="I'll search for that."))
        tc = _make_tc_delta(index=0, tc_id="tc_1", name="search", arguments='{"q": "test"}')
        acc.feed(_make_chunk(tool_calls=[tc]))
        acc.feed(_make_chunk(finish_reason="tool_calls"))

        msg = acc.build()
        assert msg.content == "I'll search for that."
        assert len(msg.tool_calls) == 1

    def test_empty_stream(self):
        acc = StreamAccumulator()
        events, done = acc.feed(_make_chunk(finish_reason="stop"))
        assert done
        assert events == []

        msg = acc.build()
        assert msg.content is None
        assert msg.tool_calls is None

    def test_usage_capture(self):
        acc = StreamAccumulator()
        acc.feed(_make_chunk(content="Hi"))
        acc.feed(_make_chunk(finish_reason="stop"))

        usage = MagicMock()
        usage.prompt_tokens = 10
        usage.completion_tokens = 5
        usage.total_tokens = 15
        # Usage-only final chunk (no choices)
        acc.feed(_make_chunk(usage=usage))

        msg = acc.build()
        assert msg.usage is usage
        assert msg.usage.total_tokens == 15

    def test_usage_on_finish_chunk(self):
        """Usage attached to the same chunk as finish_reason."""
        acc = StreamAccumulator()
        usage = MagicMock()
        usage.total_tokens = 42
        acc.feed(_make_chunk(content="Hi", finish_reason="stop", usage=usage))
        msg = acc.build()
        assert msg.usage.total_tokens == 42


class TestAccumulatedMessage:
    def test_to_msg_dict_text_only(self):
        msg = AccumulatedMessage(content="Hello")
        d = msg.to_msg_dict()
        assert d == {"role": "assistant", "content": "Hello"}

    def test_to_msg_dict_with_tool_calls(self):
        msg = AccumulatedMessage(
            content="Let me do that.",
            tool_calls=[
                {"id": "tc_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
            ],
        )
        d = msg.to_msg_dict()
        assert d["role"] == "assistant"
        assert d["content"] == "Let me do that."
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["function"]["name"] == "search"

    def test_to_msg_dict_no_content(self):
        msg = AccumulatedMessage(
            tool_calls=[
                {"id": "tc_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
            ],
        )
        d = msg.to_msg_dict()
        assert "content" not in d
        assert "tool_calls" in d

    def test_thinking_not_in_msg_dict(self):
        """Thinking content should NOT appear in the message dict sent to LLM."""
        msg = AccumulatedMessage(content="Answer", thinking_content="My reasoning")
        d = msg.to_msg_dict()
        assert "thinking_content" not in d
        assert d["content"] == "Answer"
