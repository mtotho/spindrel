"""Unit tests for app.tools.client_tools."""
import pytest

from app.tools import client_tools


@pytest.fixture(autouse=True)
def _clean_client_tools():
    """Save and restore client tool registry state."""
    backup = client_tools._client_tools.copy()
    yield
    client_tools._client_tools.clear()
    client_tools._client_tools.update(backup)


SAMPLE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "test_tool",
        "description": "A test tool.",
        "parameters": {"type": "object", "properties": {}},
    },
}


# ---------------------------------------------------------------------------
# register_client_tool()
# ---------------------------------------------------------------------------

class TestRegisterClientTool:
    def test_registers(self):
        client_tools.register_client_tool(SAMPLE_SCHEMA)
        assert "test_tool" in client_tools._client_tools


# ---------------------------------------------------------------------------
# get_client_tool_schemas()
# ---------------------------------------------------------------------------

class TestGetClientToolSchemas:
    def test_filters_allowed(self):
        client_tools.register_client_tool(SAMPLE_SCHEMA)
        result = client_tools.get_client_tool_schemas(["test_tool"])
        assert len(result) == 1
        assert result[0]["function"]["name"] == "test_tool"

    def test_returns_empty_for_none(self):
        assert client_tools.get_client_tool_schemas(None) == []

    def test_returns_empty_for_empty(self):
        assert client_tools.get_client_tool_schemas([]) == []

    def test_skips_unknown(self):
        result = client_tools.get_client_tool_schemas(["nonexistent"])
        assert result == []


# ---------------------------------------------------------------------------
# is_client_tool()
# ---------------------------------------------------------------------------

class TestIsClientTool:
    def test_shell_exec_builtin(self):
        assert client_tools.is_client_tool("shell_exec") is True

    def test_unknown(self):
        assert client_tools.is_client_tool("no_such_tool") is False

    def test_registered_tool(self):
        client_tools.register_client_tool(SAMPLE_SCHEMA)
        assert client_tools.is_client_tool("test_tool") is True
