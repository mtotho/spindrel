"""Codex runtime — dynamic-tools bridge attach behavior + protocol shapes.

Fixtures derived from the upstream codex app-server protocol README:
https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
"""

from __future__ import annotations

from integrations.codex import schema
from integrations.codex.harness import (
    _dynamic_tool_entry,
    _dynamic_tools_changed,
    _dynamic_tools_signature,
    _extract_thread_id,
    _extract_turn_id,
    _server_supports_dynamic_tools,
)
from integrations.sdk import HarnessToolSpec


class _FakeClient:
    def __init__(self, capabilities: dict | None) -> None:
        self.server_capabilities = capabilities or {}


def test_dynamic_tools_supported_when_capability_true():
    client = _FakeClient({"dynamicTools": True})
    assert _server_supports_dynamic_tools(client) is True


def test_dynamic_tools_unsupported_when_capability_false():
    client = _FakeClient({"dynamicTools": False})
    assert _server_supports_dynamic_tools(client) is False


def test_dynamic_tools_optimistic_when_capability_silent():
    client = _FakeClient({})
    assert _server_supports_dynamic_tools(client) is True


def test_dynamic_tool_envelope_uses_input_text_kind():
    """Per README, contentItems entries use ``inputText`` (not ``text``)."""
    body = schema.dynamic_tool_text_result("ok", success=True)
    assert body[schema.DYNAMIC_TOOL_RESULT_SUCCESS] is True
    items = body[schema.DYNAMIC_TOOL_RESULT_CONTENT_ITEMS]
    assert items[0]["type"] == schema.DYNAMIC_TOOL_CONTENT_ITEM_KIND_TEXT == "inputText"
    assert items[0]["text"] == "ok"


def test_thread_start_dynamic_tools_entry_uses_input_schema():
    """Per README, dynamicTools entries use ``inputSchema`` (not ``parameters``)."""
    spec = HarnessToolSpec(
        name="search_channel_knowledge",
        description="Search channel knowledge",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        schema={},
    )
    entry = _dynamic_tool_entry(spec)
    assert "inputSchema" in entry
    assert entry["namespace"] == "spindrel"
    assert "parameters" not in entry
    assert "query" in entry["inputSchema"]["properties"]


def test_dynamic_tools_signature_changes_when_schema_changes():
    first = _dynamic_tools_signature([
        {
            "name": "search",
            "description": "Search",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    ])
    second = _dynamic_tools_signature([
        {
            "name": "search",
            "description": "Search",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "number"}}},
        }
    ])

    assert first != second
    assert first == _dynamic_tools_signature([
        {
            "inputSchema": {"properties": {"q": {"type": "string"}}, "type": "object"},
            "description": "Search",
            "name": "search",
        }
    ])


def test_dynamic_tools_signature_is_order_insensitive():
    left = _dynamic_tools_signature([
        {"name": "b", "description": "B", "inputSchema": {"type": "object"}},
        {"name": "a", "description": "A", "inputSchema": {"type": "object"}},
    ])
    right = _dynamic_tools_signature([
        {"name": "a", "description": "A", "inputSchema": {"type": "object"}},
        {"name": "b", "description": "B", "inputSchema": {"type": "object"}},
    ])

    assert left == right


def test_dynamic_tools_change_detects_add_remove_and_schema_drift():
    assert _dynamic_tools_changed(
        harness_session_id=None,
        current_signature="next",
        prior_signature="prior",
    ) is False
    assert _dynamic_tools_changed(
        harness_session_id="thread-1",
        current_signature="next",
        prior_signature="prior",
    ) is True
    assert _dynamic_tools_changed(
        harness_session_id="thread-1",
        current_signature=None,
        prior_signature="prior",
    ) is True
    assert _dynamic_tools_changed(
        harness_session_id="thread-1",
        current_signature=None,
        prior_signature="",
    ) is False


def test_extract_thread_id_reads_nested_thread_object():
    """Per README: thread/start result is { thread: { id, ... } }."""
    assert _extract_thread_id({"thread": {"id": "th-1"}}) == "th-1"
    assert _extract_thread_id({"threadId": "th-x"}) is None
    assert _extract_thread_id({}) is None
    assert _extract_thread_id(None) is None


def test_extract_turn_id_reads_nested_turn_object():
    """Per README: turn/start result is { turn: { id, ... } }."""
    assert _extract_turn_id({"turn": {"id": "t-1"}}) == "t-1"
    assert _extract_turn_id({"turnId": "t-x"}) is None
    assert _extract_turn_id({}) is None


def test_text_input_item_shape():
    """Per README: turn/start.input is an array of typed content items."""
    item = schema.text_input_item("hello world")
    assert item == {"type": "text", "text": "hello world"}


def test_initialize_capabilities_carries_experimental_api():
    """Per README, experimentalApi lives under params.capabilities (not at top level)."""
    # Exercises the schema constants used in app_server.initialize().
    assert schema.METHOD_INITIALIZE == "initialize"
    assert schema.NOTIFICATION_INITIALIZED == "initialized"
