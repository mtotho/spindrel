"""Tests for Slack formatting helpers."""
from formatting import (
    format_response_for_slack,
    format_thinking_for_slack,
    format_tool_status,
    markdown_to_slack_mrkdwn,
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


class TestMarkdownToSlackMrkdwn:
    # --- Bold ---
    def test_double_star_bold(self):
        assert markdown_to_slack_mrkdwn("**hello**") == "*hello*"

    def test_bold_in_sentence(self):
        assert markdown_to_slack_mrkdwn("This is **important** stuff") == "This is *important* stuff"

    def test_multiple_bolds(self):
        assert markdown_to_slack_mrkdwn("**a** and **b**") == "*a* and *b*"

    def test_single_star_italic_untouched(self):
        assert markdown_to_slack_mrkdwn("*italic*") == "*italic*"

    # --- Strikethrough ---
    def test_double_tilde_strike(self):
        assert markdown_to_slack_mrkdwn("~~deleted~~") == "~deleted~"

    def test_single_tilde_untouched(self):
        assert markdown_to_slack_mrkdwn("~already slack~") == "~already slack~"

    def test_strike_in_sentence(self):
        assert markdown_to_slack_mrkdwn("was ~~wrong~~ right") == "was ~wrong~ right"

    # --- Links ---
    def test_markdown_link(self):
        assert markdown_to_slack_mrkdwn("[Click here](https://example.com)") == "<https://example.com|Click here>"

    def test_link_with_path(self):
        result = markdown_to_slack_mrkdwn("[docs](https://example.com/path?q=1)")
        assert result == "<https://example.com/path?q=1|docs>"

    def test_http_link(self):
        assert markdown_to_slack_mrkdwn("[x](http://example.com)") == "<http://example.com|x>"

    def test_non_http_link_untouched(self):
        """Links without http/https scheme should not be converted."""
        original = "[file](ftp://server/file.txt)"
        assert markdown_to_slack_mrkdwn(original) == original

    # --- Code protection ---
    def test_bold_inside_code_block_untouched(self):
        text = "```\n**not bold**\n```"
        assert markdown_to_slack_mrkdwn(text) == text

    def test_bold_inside_inline_code_untouched(self):
        text = "use `**kwargs` in Python"
        assert markdown_to_slack_mrkdwn(text) == text

    def test_strike_inside_code_block_untouched(self):
        text = "```\n~~not strike~~\n```"
        assert markdown_to_slack_mrkdwn(text) == text

    def test_link_inside_code_block_untouched(self):
        text = "```\n[not a link](https://example.com)\n```"
        assert markdown_to_slack_mrkdwn(text) == text

    def test_mixed_code_and_text(self):
        text = "**bold** then `**code**` then **more bold**"
        assert markdown_to_slack_mrkdwn(text) == "*bold* then `**code**` then *more bold*"

    def test_code_block_with_surrounding_bold(self):
        text = "**intro**\n```\ncode here\n```\n**outro**"
        assert markdown_to_slack_mrkdwn(text) == "*intro*\n```\ncode here\n```\n*outro*"

    # --- Edge cases ---
    def test_empty_string(self):
        assert markdown_to_slack_mrkdwn("") == ""

    def test_none(self):
        assert markdown_to_slack_mrkdwn(None) is None

    def test_plain_text_unchanged(self):
        text = "Just regular text with no formatting."
        assert markdown_to_slack_mrkdwn(text) == text

    def test_already_slack_mrkdwn_untouched(self):
        """Text already in Slack format should pass through unchanged."""
        text = "*bold* and ~strike~ and <https://example.com|link>"
        assert markdown_to_slack_mrkdwn(text) == text

    def test_multiple_transforms(self):
        text = "**bold** and ~~strike~~ and [link](https://example.com)"
        expected = "*bold* and ~strike~ and <https://example.com|link>"
        assert markdown_to_slack_mrkdwn(text) == expected

    def test_multiline_bold(self):
        """Bold should not span newlines (non-greedy .+? doesn't match \\n by default)."""
        text = "**start\nend**"
        assert markdown_to_slack_mrkdwn(text) == text

    def test_kwargs_style_double_star_in_inline_code(self):
        """Common Python pattern: `**kwargs` inside inline code must not be mangled."""
        text = "Pass `**kwargs` to the function"
        assert markdown_to_slack_mrkdwn(text) == text

    def test_bare_double_stars_no_content(self):
        """Consecutive stars without content in between should not break."""
        text = "empty **** stars"
        assert markdown_to_slack_mrkdwn(text) == "empty **** stars"

    def test_nested_formatting_bold_with_italic(self):
        """Bold wrapping italic: ***text*** — best-effort, not critical."""
        # Not a common LLM pattern; just ensure no crash
        result = markdown_to_slack_mrkdwn("***text***")
        assert isinstance(result, str)


class TestFormatResponseMrkdwn:
    """Verify that format_response_for_slack applies mrkdwn conversion."""

    def test_bold_converted(self):
        assert format_response_for_slack("**hello**") == "*hello*"

    def test_link_converted(self):
        result = format_response_for_slack("See [docs](https://example.com)")
        assert "<https://example.com|docs>" in result

    def test_code_protected(self):
        result = format_response_for_slack("use `**kwargs`")
        assert "**kwargs" in result


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
