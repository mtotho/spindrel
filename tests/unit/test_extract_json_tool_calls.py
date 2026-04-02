"""Tests for extract_json_tool_calls — recovers JSON tool calls from text content."""
import json

import pytest

from app.agent.llm import extract_json_tool_calls


KNOWN_TOOLS = {"web_search", "client_action", "exec_command", "get_weather"}


class TestBasicExtraction:
    def test_single_tool_call_dict_arguments(self):
        text = '{"name": "web_search", "arguments": {"query": "hello world"}}'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["type"] == "function"
        assert tcs[0]["function"]["name"] == "web_search"
        assert json.loads(tcs[0]["function"]["arguments"]) == {"query": "hello world"}
        assert tcs[0]["id"].startswith("json-tc-")
        assert remaining.strip() == ""

    def test_single_tool_call_string_arguments(self):
        args = json.dumps({"query": "hello"})
        text = json.dumps({"name": "web_search", "arguments": args})
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["function"]["arguments"] == args

    def test_multiple_tool_calls(self):
        text = (
            '{"name": "web_search", "arguments": {"query": "a"}}\n'
            '{"name": "get_weather", "arguments": {"city": "NYC"}}'
        )
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 2
        names = {tc["function"]["name"] for tc in tcs}
        assert names == {"web_search", "get_weather"}
        assert remaining.strip() == ""

    def test_unique_ids(self):
        text = (
            '{"name": "web_search", "arguments": {"query": "a"}}\n'
            '{"name": "get_weather", "arguments": {"city": "NYC"}}'
        )
        tcs, _ = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert tcs[0]["id"] != tcs[1]["id"]


class TestMixedContent:
    def test_text_before_json(self):
        text = 'Let me search for that. {"name": "web_search", "arguments": {"query": "test"}}'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert "Let me search" in remaining
        assert '{"name"' not in remaining

    def test_text_after_json(self):
        text = '{"name": "web_search", "arguments": {"query": "test"}} I found the results.'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert "I found the results." in remaining

    def test_text_around_json(self):
        text = 'Before. {"name": "web_search", "arguments": {"query": "q"}} After.'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert "Before." in remaining
        assert "After." in remaining
        assert '{"name"' not in remaining


class TestUnknownAndInvalid:
    def test_unknown_tool_name_left_in_text(self):
        text = '{"name": "unknown_tool", "arguments": {"x": 1}}'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert tcs == []
        assert remaining == text

    def test_malformed_json_left_in_text(self):
        text = '{"name": "web_search", "arguments": {"query": "test"'  # missing closing brace
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert tcs == []
        assert remaining == text

    def test_json_without_name_field(self):
        text = '{"tool": "web_search", "arguments": {"query": "test"}}'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert tcs == []
        assert remaining == text

    def test_json_without_arguments_field(self):
        text = '{"name": "web_search", "params": {"query": "test"}}'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert tcs == []
        assert remaining == text

    def test_non_string_name(self):
        text = '{"name": 42, "arguments": {}}'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert tcs == []


class TestEdgeCases:
    def test_empty_text(self):
        tcs, remaining = extract_json_tool_calls("", KNOWN_TOOLS)
        assert tcs == []
        assert remaining == ""

    def test_no_json(self):
        text = "This is a plain text response with no JSON."
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert tcs == []
        assert remaining == text

    def test_empty_known_tools(self):
        text = '{"name": "web_search", "arguments": {"query": "test"}}'
        tcs, remaining = extract_json_tool_calls(text, set())
        assert tcs == []
        assert remaining == text

    def test_json_inside_code_block_skipped(self):
        text = (
            "Here's an example:\n"
            '```json\n{"name": "web_search", "arguments": {"query": "test"}}\n```\n'
            "That's how it works."
        )
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert tcs == []
        assert remaining == text

    def test_json_inside_plain_code_block_skipped(self):
        text = (
            "Example:\n"
            '```\n{"name": "web_search", "arguments": {"query": "test"}}\n```'
        )
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert tcs == []
        assert remaining == text

    def test_nested_json_in_arguments(self):
        text = '{"name": "client_action", "arguments": {"action": "run", "config": {"nested": true}}}'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 1
        args = json.loads(tcs[0]["function"]["arguments"])
        assert args["config"]["nested"] is True

    def test_json_with_escaped_quotes(self):
        text = '{"name": "web_search", "arguments": {"query": "say \\"hello\\""}}'
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 1
        args = json.loads(tcs[0]["function"]["arguments"])
        assert args["query"] == 'say "hello"'

    def test_mixed_valid_and_invalid_json(self):
        """Valid tool call extracted, random JSON object left in text."""
        text = (
            '{"irrelevant": true}\n'
            '{"name": "web_search", "arguments": {"query": "test"}}'
        )
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert tcs[0]["function"]["name"] == "web_search"
        assert '{"irrelevant": true}' in remaining

    def test_arguments_normalized_to_json_string(self):
        """Dict arguments are serialized to a JSON string."""
        text = '{"name": "web_search", "arguments": {"query": "test"}}'
        tcs, _ = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert isinstance(tcs[0]["function"]["arguments"], str)
        assert json.loads(tcs[0]["function"]["arguments"]) == {"query": "test"}

    def test_tool_call_outside_code_block_extracted(self):
        """Tool call outside code block is extracted even when code blocks exist."""
        text = (
            "```\nsome code\n```\n"
            '{"name": "web_search", "arguments": {"query": "test"}}'
        )
        tcs, remaining = extract_json_tool_calls(text, KNOWN_TOOLS)
        assert len(tcs) == 1
        assert "some code" in remaining
