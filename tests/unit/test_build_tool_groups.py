"""Unit tests for _build_tool_groups in app.routers.api_v1_admin.bots.

Regression: MCP-source tools (server_name is not None) were filtered out of the
bot Tool Pool, hiding external-integration tools like bennie_loggins from the
admin UI. They now group under source_integration (when set) or server_name.
"""
from types import SimpleNamespace

from app.routers.api_v1_admin.bots import _build_tool_groups


def _row(tool_name, *, server_name=None, source_integration=None, source_file=None, description=None):
    schema = {"function": {"name": tool_name, "description": description or f"{tool_name} desc"}}
    return SimpleNamespace(
        tool_name=tool_name,
        server_name=server_name,
        source_integration=source_integration,
        source_file=source_file,
        schema_=schema,
    )


class TestBuildToolGroups:
    def test_local_tools_grouped_by_source_integration(self):
        rows = [
            _row("exec_command", source_integration=None, source_file="exec_command.py"),
            _row("send_slack_message", source_integration="slack", source_file="slack.py"),
        ]
        groups = _build_tool_groups(rows)
        integrations = {g["integration"] for g in groups}
        assert "core" in integrations
        assert "slack" in integrations

    def test_mcp_tools_appear_under_server_name(self):
        """bennie_loggins regression: MCP tools must appear in Tool Pool."""
        rows = [
            _row("bennie_loggins_health_summary", server_name="bennie_loggins"),
            _row("bennie_loggins_log_poop", server_name="bennie_loggins"),
        ]
        groups = _build_tool_groups(rows)
        assert len(groups) == 1
        g = groups[0]
        assert g["integration"] == "bennie_loggins"
        assert g["is_core"] is False
        tool_names = [t["name"] for p in g["packs"] for t in p["tools"]]
        assert "bennie_loggins_health_summary" in tool_names
        assert "bennie_loggins_log_poop" in tool_names

    def test_mcp_tools_with_source_integration_prefer_that(self):
        """When source_integration is populated for MCP tools, use it as the group key."""
        rows = [
            _row("mcp_tool_a", server_name="some_server", source_integration="explicit_int"),
        ]
        groups = _build_tool_groups(rows)
        assert len(groups) == 1
        assert groups[0]["integration"] == "explicit_int"

    def test_local_and_mcp_tools_coexist(self):
        rows = [
            _row("exec_command", source_file="exec_command.py"),  # core local
            _row("bennie_loggins_summary", server_name="bennie_loggins"),  # MCP
            _row("firecrawl_scrape", server_name="firecrawl"),  # MCP
        ]
        groups = _build_tool_groups(rows)
        integrations = {g["integration"] for g in groups}
        assert integrations == {"core", "bennie_loggins", "firecrawl"}

    def test_core_ordered_first(self):
        rows = [
            _row("z_mcp_tool", server_name="aaa_server"),
            _row("core_tool", source_file="core.py"),
        ]
        groups = _build_tool_groups(rows)
        assert groups[0]["integration"] == "core"

    def test_empty_rows_yields_empty_groups(self):
        assert _build_tool_groups([]) == []
