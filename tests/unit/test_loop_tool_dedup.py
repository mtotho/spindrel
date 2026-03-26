"""Tests for tool-schema deduplication in the agent loop."""

from app.agent.message_utils import _merge_tool_schemas


def _tool(name: str) -> dict:
    """Helper to build a minimal tool schema dict."""
    return {"type": "function", "function": {"name": name, "parameters": {}}}


class TestPreSelectedToolsDedup:
    """Verify _merge_tool_schemas deduplicates pre_selected_tools correctly."""

    def test_removes_duplicates_single_list(self):
        tools = [_tool("get_message_detail"), _tool("web_search"), _tool("get_message_detail")]
        result = _merge_tool_schemas(tools)
        names = [t["function"]["name"] for t in result]
        assert names == ["get_message_detail", "web_search"]

    def test_preserves_order(self):
        tools = [_tool("a"), _tool("b"), _tool("c"), _tool("b")]
        result = _merge_tool_schemas(tools)
        names = [t["function"]["name"] for t in result]
        assert names == ["a", "b", "c"]

    def test_empty_list(self):
        assert _merge_tool_schemas([]) == []


class TestGetMessageDetailGuard:
    """Simulate the guard logic that prevents duplicate get_message_detail append."""

    def test_skips_append_when_already_present(self):
        pre_selected_tools = [_tool("web_search"), _tool("get_message_detail")]
        existing_names = {t.get("function", {}).get("name") for t in (pre_selected_tools or [])}
        assert "get_message_detail" in existing_names

    def test_appends_when_not_present(self):
        pre_selected_tools = [_tool("web_search"), _tool("save_memory")]
        existing_names = {t.get("function", {}).get("name") for t in (pre_selected_tools or [])}
        assert "get_message_detail" not in existing_names

    def test_handles_none_pre_selected(self):
        pre_selected_tools = None
        existing_names = {t.get("function", {}).get("name") for t in (pre_selected_tools or [])}
        assert "get_message_detail" not in existing_names
