"""Tests for strip_malformed_tool_calls — strips XML tool-call fragments from text."""
import pytest

from app.agent.llm import strip_malformed_tool_calls


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
])
def test_strip_malformed_tool_calls(input_text: str, expected: str):
    assert strip_malformed_tool_calls(input_text) == expected
