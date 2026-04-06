"""Tests for strip_malformed_tool_calls — strips XML and JSON tool-call fragments from text."""
import pytest

from app.agent.llm import ToolCallXmlFilter, strip_malformed_tool_calls


@pytest.mark.parametrize("input_text,expected", [
    # Basic invoke tag
    (
        '<invoke name="get_attachment"><parameter name="attachment_id">abc-123</parameter></invoke>',
        "",
    ),
    # With trailing minimax close tag (the exact bug)
    (
        '<invoke name="get_attachment">\n<parameter name="attachment_id">e29a15a4</parameter>\n</invoke>\n</minimax:tool_call>',
        "",
    ),
    # Mixed text + invoke — only XML stripped
    (
        'Here is the image. <invoke name="get_attachment"><parameter name="id">123</parameter></invoke>',
        "Here is the image.",
    ),
    # tool_call tags
    (
        '<tool_call>{"name": "foo", "args": {}}</tool_call>',
        "",
    ),
    # Opening minimax:tool_call tag
    (
        '<minimax:tool_call>some content</minimax:tool_call>',
        "some content",
    ),
    # Clean text — no stripping
    (
        "This is a normal response with no XML tags.",
        "This is a normal response with no XML tags.",
    ),
    # Empty string
    ("", ""),
    # Multiline invoke
    (
        'Response text\n<invoke name="search">\n<parameter name="q">hello</parameter>\n</invoke>\nMore text',
        "Response text\n\nMore text",
    ),
    # --- JSON tool-call fragments ---
    # JSON tool call with name + arguments (the Qwen/local model pattern)
    (
        '{"name": "client_action", "arguments": {"action": "greet", "params": "Hello!"}}',
        "",
    ),
    # Mangled tool name still stripped (has name + arguments structure)
    (
        '{"name": "clientaction", "arguments": {"action": "greet", "params": "Hi there!"}}',
        "",
    ),
    # Multiple concatenated JSON tool calls (exact pattern from screenshot)
    (
        '{"name": "clientaction", "arguments": {"action": "greet", "params": "Hi"}}'
        '{"name": "shellexec", "arguments": {"command": "echo hello"}}',
        "",
    ),
    # JSON tool call mixed with real text
    (
        'Here is my response. {"name": "web_search", "arguments": {"query": "test"}} Done.',
        "Here is my response.  Done.",
    ),
    # JSON without "arguments" key — NOT stripped (not a tool call)
    (
        '{"name": "some_data", "value": 42}',
        '{"name": "some_data", "value": 42}',
    ),
    # JSON without "name" key — NOT stripped
    (
        '{"tool": "search", "arguments": {"q": "test"}}',
        '{"tool": "search", "arguments": {"q": "test"}}',
    ),
])
def test_strip_malformed_tool_calls(input_text: str, expected: str):
    assert strip_malformed_tool_calls(input_text) == expected


# ---------------------------------------------------------------------------
# ToolCallXmlFilter (streaming) tests
# ---------------------------------------------------------------------------


class TestToolCallXmlFilter:
    """Tests for the streaming XML tool-call filter."""

    def test_plain_text_passes_through(self):
        f = ToolCallXmlFilter()
        assert f.feed("Hello world") == "Hello world"
        assert f.flush() == ""

    def test_invoke_tag_suppressed(self):
        f = ToolCallXmlFilter()
        result = f.feed('<invoke name="get_last_heartbeat"><parameter name="limit">2</parameter></invoke>')
        result += f.flush()
        assert result == ""

    def test_minimax_close_tag_suppressed(self):
        f = ToolCallXmlFilter()
        result = f.feed("</minimax:tool_call>")
        result += f.flush()
        assert result == ""

    def test_text_before_invoke_preserved(self):
        f = ToolCallXmlFilter()
        result = f.feed('Good response. <invoke name="search"><parameter name="q">test</parameter></invoke>')
        result += f.flush()
        assert result == "Good response. "

    def test_text_after_invoke_preserved(self):
        f = ToolCallXmlFilter()
        result = f.feed('<invoke name="search"><parameter name="q">test</parameter></invoke> More text.')
        result += f.flush()
        assert result == " More text."

    def test_chunked_invoke_tag(self):
        """Simulate streaming where the tag arrives in multiple chunks."""
        f = ToolCallXmlFilter()
        parts = []
        parts.append(f.feed("Good. "))
        parts.append(f.feed("<inv"))
        parts.append(f.feed('oke name="search">'))
        parts.append(f.feed('<parameter name="q">test</parameter>'))
        parts.append(f.feed("</invoke>"))
        parts.append(f.feed(" Done."))
        parts.append(f.flush())
        assert "".join(parts) == "Good.  Done."

    def test_chunked_minimax_close(self):
        """Namespace-prefixed close tag arrives in chunks."""
        f = ToolCallXmlFilter()
        parts = []
        parts.append(f.feed("</mini"))
        parts.append(f.feed("max:tool_call>"))
        parts.append(f.flush())
        assert "".join(parts) == ""

    def test_normal_html_not_suppressed(self):
        """Regular HTML tags should pass through."""
        f = ToolCallXmlFilter()
        result = f.feed("<b>bold</b> text")
        result += f.flush()
        assert result == "<b>bold</b> text"

    def test_tool_call_tag_suppressed(self):
        f = ToolCallXmlFilter()
        result = f.feed('<tool_call>{"name": "foo"}</tool_call>')
        result += f.flush()
        assert result == ""

    def test_multiple_invoke_blocks(self):
        """Multiple invoke blocks with text between them."""
        f = ToolCallXmlFilter()
        result = f.feed(
            '<invoke name="a"><parameter name="x">1</parameter></invoke>'
            '\n'
            '<invoke name="b"><parameter name="y">2</parameter></invoke>'
        )
        result += f.flush()
        assert result.strip() == ""

    def test_full_minimax_scenario(self):
        """Reproduce the exact MiniMax output from the bug report."""
        xml = (
            '<invoke name="get_last_heartbeat">\n'
            '<parameter name="limit">2</parameter>\n'
            '</invoke>\n'
            '<invoke name="search_channel_workspace">\n'
            '<parameter name="query">checklist bugs</parameter>\n'
            '</invoke>\n'
            '</minimax:tool_call>'
        )
        f = ToolCallXmlFilter()
        result = f.feed(xml)
        result += f.flush()
        assert result.strip() == ""

    def test_full_minimax_scenario_chunked(self):
        """Same MiniMax scenario but fed character by character."""
        xml = (
            '<invoke name="get_last_heartbeat">\n'
            '<parameter name="limit">2</parameter>\n'
            '</invoke>\n'
            '</minimax:tool_call>'
        )
        f = ToolCallXmlFilter()
        parts = []
        for char in xml:
            parts.append(f.feed(char))
        parts.append(f.flush())
        assert "".join(parts).strip() == ""


# ---------------------------------------------------------------------------
# StreamAccumulator.build() strips malformed tool calls
# ---------------------------------------------------------------------------


def test_stream_accumulator_build_strips_xml():
    """StreamAccumulator.build() should strip XML tool-call fragments from content."""
    from app.agent.llm import StreamAccumulator

    acc = StreamAccumulator()
    # Simulate content parts that include XML tool-call fragments
    acc._content_parts = [
        "Good response. ",
        '<invoke name="search"><parameter name="q">test</parameter></invoke>',
        "\n</minimax:tool_call>",
    ]
    msg = acc.build()
    assert msg.content == "Good response."


def test_stream_accumulator_build_preserves_clean_content():
    """StreamAccumulator.build() should not alter clean text content."""
    from app.agent.llm import StreamAccumulator

    acc = StreamAccumulator()
    acc._content_parts = ["Hello ", "world!"]
    msg = acc.build()
    assert msg.content == "Hello world!"
