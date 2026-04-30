from app.services import agent_capabilities


def test_filter_endpoints_for_scopes_uses_existing_scope_rules(monkeypatch):
    monkeypatch.setattr(agent_capabilities._api_keys_mod, "ENDPOINT_CATALOG", [
        {"method": "GET", "path": "/api/v1/channels", "scope": "channels:read"},
        {"method": "POST", "path": "/api/v1/channels/1/messages", "scope": "channels.messages:write"},
        {"method": "GET", "path": "/api/v1/tools", "scope": "tools:read"},
        {"method": "GET", "path": "/api/v1/discover", "scope": None},
    ])

    visible = agent_capabilities.filter_endpoints_for_scopes(["channels:write"])
    paths = {entry["path"] for entry in visible}

    assert "/api/v1/channels" in paths
    assert "/api/v1/channels/1/messages" in paths
    assert "/api/v1/discover" in paths
    assert "/api/v1/tools" not in paths


def test_tool_profiles_group_agent_first_surfaces():
    assert agent_capabilities._profile_for_tool("call_api") == "api"
    assert agent_capabilities._profile_for_tool("emit_html_widget") == "widgets"
    assert agent_capabilities._profile_for_tool("record_plan_progress") == "planning"
    assert agent_capabilities._profile_for_tool("get_recent_server_errors") == "diagnostics"


def test_doctor_flags_missing_api_scopes_and_harness_workdir():
    manifest = {
        "context": {"bot_id": "agent"},
        "api": {"scopes": []},
        "tools": {"catalog_count": 4, "working_set_count": 0},
        "project": {"attached": False},
        "harness": {"runtime": "codex", "workdir": None},
    }

    findings = agent_capabilities._doctor_findings(manifest)
    codes = {finding["code"] for finding in findings}

    assert "missing_api_scopes" in codes
    assert "empty_tool_working_set" in codes
    assert "harness_without_workdir" in codes
