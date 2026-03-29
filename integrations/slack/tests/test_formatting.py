"""Tests for Slack formatting helpers."""
from formatting import (
    format_response_for_slack,
    format_thinking_for_slack,
    format_tool_status,
    split_for_slack,
)


class TestFormatThinking:
    def test_empty_string(self):
        assert format_thinking_for_slack("") == "> 💭 _thinking…_"

    def test_whitespace_only(self):
        assert format_thinking_for_slack("   ") == "> 💭 _thinking…_"

    def test_none(self):
        assert format_thinking_for_slack(None) == "> 💭 _thinking…_"

    def test_single_line(self):
        result = format_thinking_for_slack("Let me search for that.")
        assert result.startswith("> 💭 *Thinking:*\n")
        assert "> Let me search for that." in result

    def test_multi_line(self):
        result = format_thinking_for_slack("Step 1: Search\nStep 2: Summarize")
        lines = result.splitlines()
        assert lines[0] == "> 💭 *Thinking:*"
        assert lines[1] == "> Step 1: Search"
        assert lines[2] == "> Step 2: Summarize"

    def test_all_lines_blockquoted(self):
        text = "Line one\nLine two\nLine three"
        result = format_thinking_for_slack(text)
        for line in result.splitlines():
            assert line.startswith(">")

    def test_strips_surrounding_whitespace(self):
        result = format_thinking_for_slack("  hello  \n  world  ")
        # Outer text is stripped; individual lines keep their internal whitespace
        assert "> hello" in result
        assert ">   world" in result


class TestFormatResponse:
    def test_normal_text(self):
        assert format_response_for_slack("Hello!") == "Hello!"

    def test_empty(self):
        assert format_response_for_slack("") == "_(no response)_"

    def test_silent_tags(self):
        result = format_response_for_slack("[silent]internal note[/silent]")
        assert "🔇" in result
        assert "internal note" in result


class TestSplitForSlack:
    def test_short_text_not_split(self):
        assert split_for_slack("short") == ["short"]

    def test_long_text_split(self):
        text = "a" * 4000
        chunks = split_for_slack(text, limit=3500)
        assert len(chunks) > 1
        assert all(len(c) <= 3500 + 10 for c in chunks)  # small tolerance for fence handling


class TestFormatToolStatus:
    def test_exec_command(self):
        result = format_tool_status("exec_command", '{"command": "ls -la"}')
        assert "exec_command" in result
        assert "ls -la" in result

    def test_generic_tool(self):
        result = format_tool_status("web_search", '{"query": "python docs"}')
        assert "web_search" in result
        assert "python docs" in result

    def test_no_args(self):
        result = format_tool_status("some_tool")
        assert "some_tool" in result
