"""Tests for StreamAccumulator, AccumulatedMessage, and ThinkTagParser."""
from unittest.mock import MagicMock

import pytest

from app.agent.llm import AccumulatedMessage, StreamAccumulator, ThinkTagParser, strip_think_tags


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


class TestThinkTagParser:
    def test_no_think_tags(self):
        p = ThinkTagParser()
        content, thinking = p.feed("Hello world")
        assert content == "Hello world"
        assert thinking == ""
        fc, ft = p.flush()
        assert fc == ""
        assert ft == ""

    def test_complete_think_block(self):
        p = ThinkTagParser()
        content, thinking = p.feed("<think>reasoning</think>answer")
        assert content == "answer"
        assert thinking == "reasoning"

    def test_tag_split_across_chunks(self):
        """<think> tag split: '<th' + 'ink>reason</think>answer'"""
        p = ThinkTagParser()
        c1, t1 = p.feed("<th")
        assert c1 == ""
        assert t1 == ""
        c2, t2 = p.feed("ink>reason</think>answer")
        assert t2 == "reason"
        assert c2 == "answer"

    def test_close_tag_split(self):
        """Close tag split: '<think>reason</thi' + 'nk>answer'"""
        p = ThinkTagParser()
        c1, t1 = p.feed("<think>reason</thi")
        assert c1 == ""
        assert t1 == "reason"
        c2, t2 = p.feed("nk>answer")
        assert t2 == ""
        assert c2 == "answer"

    def test_multiple_think_blocks(self):
        p = ThinkTagParser()
        c, t = p.feed("<think>a</think>b<think>c</think>d")
        assert c == "bd"
        assert t == "ac"

    def test_unclosed_think_with_flush(self):
        p = ThinkTagParser()
        c, t = p.feed("<think>still thinking")
        assert c == ""
        assert t == "still thinking"
        fc, ft = p.flush()
        assert fc == ""
        assert ft == ""

    def test_empty_think_block(self):
        p = ThinkTagParser()
        c, t = p.feed("<think></think>content")
        assert c == "content"
        assert t == ""

    def test_angle_brackets_not_think(self):
        """<b>bold</b> should not be confused with <think>."""
        p = ThinkTagParser()
        c, t = p.feed("<b>bold</b>")
        assert t == ""
        fc, _ = p.flush()
        assert c + fc == "<b>bold</b>"

    def test_partial_tag_false_alarm(self):
        """'<thinking' should not match '<think>' — parser uses exact '<think>' match."""
        p = ThinkTagParser()
        c, t = p.feed("<thinking is not a tag")
        assert t == ""
        fc, _ = p.flush()
        assert c + fc == "<thinking is not a tag"

    def test_incremental_single_chars(self):
        """Feed one character at a time."""
        p = ThinkTagParser()
        text = "<think>hi</think>bye"
        all_content = []
        all_thinking = []
        for ch in text:
            c, t = p.feed(ch)
            all_content.append(c)
            all_thinking.append(t)
        fc, ft = p.flush()
        all_content.append(fc)
        all_thinking.append(ft)
        assert "".join(all_content) == "bye"
        assert "".join(all_thinking) == "hi"


class TestStripThinkTags:
    def test_basic(self):
        assert strip_think_tags("<think>reasoning</think>answer") == "answer"

    def test_multiple(self):
        assert strip_think_tags("<think>a</think>b<think>c</think>d") == "bd"

    def test_no_tags(self):
        assert strip_think_tags("just text") == "just text"

    def test_multiline(self):
        assert strip_think_tags("<think>line1\nline2</think>answer") == "answer"


class TestStreamAccumulatorThinkTags:
    def test_think_tags_in_content(self):
        """Content with <think> tags should emit thinking events, not text_delta."""
        acc = StreamAccumulator()
        events, _ = acc.feed(_make_chunk(content="<think>reasoning</think>answer"))
        types = [e["type"] for e in events]
        assert "thinking" in types
        assert "text_delta" in types
        # The thinking event has the reasoning
        thinking_events = [e for e in events if e["type"] == "thinking"]
        assert thinking_events[0]["delta"] == "reasoning"
        # The text event has the answer
        text_events = [e for e in events if e["type"] == "text_delta"]
        assert text_events[0]["delta"] == "answer"

    def test_think_tags_split_across_chunks(self):
        acc = StreamAccumulator()
        e1, _ = acc.feed(_make_chunk(content="<th"))
        e2, _ = acc.feed(_make_chunk(content="ink>reason</think>answer"))
        _, done = acc.feed(_make_chunk(finish_reason="stop"))
        msg = acc.build()
        assert msg.content == "answer"
        assert msg.thinking_content == "reason"

    def test_build_strips_think_content(self):
        """accumulated_msg.content should have no <think> tags."""
        acc = StreamAccumulator()
        acc.feed(_make_chunk(content="<think>thought</think>clean text"))
        acc.feed(_make_chunk(finish_reason="stop"))
        msg = acc.build()
        assert "<think>" not in (msg.content or "")
        assert msg.content == "clean text"
        assert msg.thinking_content == "thought"

    def test_think_tags_with_reasoning_content_attr(self):
        """Both reasoning_content attr and <think> tags should accumulate thinking."""
        acc = StreamAccumulator()
        acc.feed(_make_chunk(reasoning_content="from attr"))
        acc.feed(_make_chunk(content="<think>from tag</think>answer"))
        acc.feed(_make_chunk(finish_reason="stop"))
        msg = acc.build()
        assert msg.content == "answer"
        assert "from attr" in msg.thinking_content
        assert "from tag" in msg.thinking_content
