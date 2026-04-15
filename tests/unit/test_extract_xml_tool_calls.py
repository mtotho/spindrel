"""Tests for XML tool call recovery — extract_xml_tool_calls + ToolCallXmlFilter suppression storage."""
import json

import pytest

from app.agent.llm import ToolCallXmlFilter, extract_xml_tool_calls


KNOWN_TOOLS = {"mermaid_to_excalidraw", "web_search", "get_weather"}


class TestExtractXmlToolCalls:
    """Tests for extract_xml_tool_calls parsing suppressed XML blocks."""

    def test_invoke_with_json_args(self):
        blocks = ['<invoke name="web_search">{"query": "hello world"}</invoke>']
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["type"] == "function"
        assert tcs[0]["function"]["name"] == "web_search"
        assert json.loads(tcs[0]["function"]["arguments"]) == {"query": "hello world"}
        assert tcs[0]["id"].startswith("xml-tc-")

    def test_invoke_unknown_tool_skipped(self):
        blocks = ['<invoke name="unknown_tool">{"arg": "val"}</invoke>']
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 0

    def test_tool_call_with_name_and_arguments(self):
        obj = {"name": "get_weather", "arguments": {"city": "NYC"}}
        blocks = [f"<tool_call>{json.dumps(obj)}</tool_call>"]
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["function"]["name"] == "get_weather"
        assert json.loads(tcs[0]["function"]["arguments"]) == {"city": "NYC"}

    def test_namespaced_tool_call(self):
        obj = {"name": "web_search", "arguments": {"query": "test"}}
        blocks = [f"<minimax:tool_call>{json.dumps(obj)}</minimax:tool_call>"]
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["function"]["name"] == "web_search"

    def test_multiple_blocks(self):
        blocks = [
            '<invoke name="web_search">{"query": "a"}</invoke>',
            '<invoke name="get_weather">{"city": "NYC"}</invoke>',
        ]
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 2
        names = {tc["function"]["name"] for tc in tcs}
        assert names == {"web_search", "get_weather"}

    def test_unique_ids(self):
        blocks = [
            '<invoke name="web_search">{"query": "a"}</invoke>',
            '<invoke name="get_weather">{"city": "NYC"}</invoke>',
        ]
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert tcs[0]["id"] != tcs[1]["id"]

    def test_empty_blocks(self):
        assert extract_xml_tool_calls([], KNOWN_TOOLS) == []

    def test_empty_known_tools(self):
        blocks = ['<invoke name="web_search">{"query": "a"}</invoke>']
        assert extract_xml_tool_calls(blocks, set()) == []

    def test_invoke_with_malformed_json_passes_raw(self):
        blocks = ['<invoke name="web_search">not json at all</invoke>']
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["function"]["arguments"] == "not json at all"

    def test_tool_call_with_malformed_json_skipped(self):
        blocks = ["<tool_call>not json</tool_call>"]
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 0

    def test_invoke_with_whitespace_around_name(self):
        blocks = ['<invoke  name = "web_search" >{"query": "x"}</invoke>']
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 1

    def test_invoke_with_xml_parameters(self):
        """MiniMax M2.7 sends <parameter> elements instead of JSON."""
        blocks = [
            '<invoke name="web_search">'
            '<parameter name="query">hello world</parameter>'
            '</invoke>'
        ]
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["function"]["name"] == "web_search"
        assert json.loads(tcs[0]["function"]["arguments"]) == {"query": "hello world"}

    def test_invoke_with_multiple_xml_parameters(self):
        blocks = [
            '<invoke name="get_weather">'
            '<parameter name="city">NYC</parameter>'
            '<parameter name="units">metric</parameter>'
            '</invoke>'
        ]
        tcs = extract_xml_tool_calls(blocks, KNOWN_TOOLS)
        assert len(tcs) == 1
        args = json.loads(tcs[0]["function"]["arguments"])
        assert args == {"city": "NYC", "units": "metric"}


class TestToolCallXmlFilterSuppression:
    """Tests that ToolCallXmlFilter stores suppressed blocks for recovery."""

    def test_invoke_block_captured(self):
        f = ToolCallXmlFilter()
        result = f.feed('<invoke name="foo">{"arg": 1}</invoke>')
        assert result == ""
        assert len(f.suppressed_blocks) == 1
        assert '<invoke name="foo">' in f.suppressed_blocks[0]
        assert "</invoke>" in f.suppressed_blocks[0]

    def test_normal_text_not_captured(self):
        f = ToolCallXmlFilter()
        result = f.feed("Hello, this is normal text.")
        assert result == "Hello, this is normal text."
        assert f.suppressed_blocks == []

    def test_mixed_text_and_xml(self):
        f = ToolCallXmlFilter()
        result = f.feed('Hello <invoke name="x">body</invoke> world')
        assert "Hello" in result
        assert "world" in result
        assert "invoke" not in result
        assert len(f.suppressed_blocks) == 1

    def test_namespaced_tool_call_captured(self):
        f = ToolCallXmlFilter()
        result = f.feed('<minimax:tool_call>{"name":"x"}</minimax:tool_call>')
        assert result == ""
        assert len(f.suppressed_blocks) == 1

    def test_streaming_chunks_assembled(self):
        """Simulate receiving XML in multiple streaming chunks."""
        f = ToolCallXmlFilter()
        # First chunk: opening tag starts
        out1 = f.feed('<invoke name="web')
        # Second chunk: rest of opening tag + body
        out2 = f.feed('_search">{"query": "test"}')
        # Third chunk: closing tag
        out3 = f.feed("</invoke>")
        full_output = out1 + out2 + out3
        assert full_output == ""
        assert len(f.suppressed_blocks) == 1
        assert "web_search" in f.suppressed_blocks[0]

    def test_flush_captures_incomplete_block(self):
        f = ToolCallXmlFilter()
        f.feed('<invoke name="x">incomplete body')
        remaining = f.flush()
        assert remaining == ""
        assert len(f.suppressed_blocks) == 1

    def test_flush_emits_non_tool_buffer(self):
        f = ToolCallXmlFilter()
        f.feed("some text")
        remaining = f.flush()
        assert remaining == ""  # feed already consumed it
        assert f.suppressed_blocks == []

    def test_self_closing_tag_captured(self):
        f = ToolCallXmlFilter()
        result = f.feed('<invoke name="x" />')
        assert result == ""
        assert len(f.suppressed_blocks) == 1


class TestEndToEndRecovery:
    """Integration test: ToolCallXmlFilter suppresses → extract_xml_tool_calls recovers."""

    def test_minimax_invoke_round_trip(self):
        """Simulate MiniMax emitting a tool call as XML text."""
        f = ToolCallXmlFilter()
        # MiniMax emits tool call as content text
        raw = '<invoke name="mermaid_to_excalidraw">{"code": "graph TD; A-->B"}</invoke>'
        emitted = f.feed(raw)
        emitted += f.flush()
        assert emitted == ""  # nothing visible to user

        # Now recover tool calls from suppressed blocks
        tcs = extract_xml_tool_calls(f.suppressed_blocks, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["function"]["name"] == "mermaid_to_excalidraw"
        assert json.loads(tcs[0]["function"]["arguments"]) == {"code": "graph TD; A-->B"}

    def test_minimax_parameter_xml_round_trip(self):
        """MiniMax M2.7 emits <parameter> elements inside <invoke>."""
        f = ToolCallXmlFilter()
        raw = (
            '<invoke name="web_search">'
            '<parameter name="query">python asyncio</parameter>'
            '</invoke>'
        )
        emitted = f.feed(raw)
        emitted += f.flush()
        assert emitted == ""

        tcs = extract_xml_tool_calls(f.suppressed_blocks, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["function"]["name"] == "web_search"
        assert json.loads(tcs[0]["function"]["arguments"]) == {"query": "python asyncio"}

    def test_no_recovery_for_unknown_tools(self):
        f = ToolCallXmlFilter()
        raw = '<invoke name="destroy_world">{"target": "all"}</invoke>'
        f.feed(raw)
        f.flush()
        tcs = extract_xml_tool_calls(f.suppressed_blocks, KNOWN_TOOLS)
        assert len(tcs) == 0
