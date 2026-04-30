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


def test_missing_api_scopes_proposes_workspace_bot_patch():
    manifest = {
        "context": {"bot_id": "agent"},
        "api": {"scopes": []},
        "tools": {"catalog_count": 4, "working_set_count": 1},
        "project": {"attached": False},
        "harness": {"runtime": None, "workdir": None},
    }
    manifest["doctor"] = {"findings": agent_capabilities._doctor_findings(manifest)}

    actions = agent_capabilities._doctor_proposed_actions(manifest)
    action = next(item for item in actions if item["finding_code"] == "missing_api_scopes")

    assert action["apply"]["type"] == "bot_patch"
    assert action["required_actor_scopes"] == ["bots:write"]
    assert action["grants_scopes"] == agent_capabilities.SCOPE_PRESETS["workspace_bot"]["scopes"]
    assert action["apply"]["patch"] == {
        "api_permissions": agent_capabilities.SCOPE_PRESETS["workspace_bot"]["scopes"]
    }


def test_empty_working_set_proposes_deduped_core_tool_patch(monkeypatch):
    monkeypatch.setattr(agent_capabilities, "_local_tools", {
        "list_agent_capabilities": {},
        "run_agent_doctor": {},
        "get_tool_info": {},
        "get_skill": {},
        "list_api_endpoints": {},
        "call_api": {},
    })
    manifest = {
        "context": {"bot_id": "agent"},
        "api": {"scopes": ["tools:read"]},
        "tools": {
            "catalog_count": 6,
            "working_set_count": 0,
            "configured": ["get_tool_info"],
            "pinned": ["get_tool_info"],
            "recommended_core": ["get_tool_info", "run_agent_doctor", "call_api"],
        },
        "project": {"attached": False},
        "harness": {"runtime": None, "workdir": None},
    }
    manifest["doctor"] = {"findings": agent_capabilities._doctor_findings(manifest)}

    actions = agent_capabilities._doctor_proposed_actions(manifest)
    action = next(item for item in actions if item["finding_code"] == "empty_tool_working_set")

    assert action["apply"]["type"] == "bot_patch"
    assert action["apply"]["patch"]["local_tools"] == [
        "get_tool_info",
        "run_agent_doctor",
        "call_api",
    ]
    assert action["apply"]["patch"]["pinned_tools"] == [
        "get_tool_info",
        "run_agent_doctor",
        "call_api",
    ]


def test_manual_findings_propose_navigation_not_patches():
    manifest = {
        "context": {"bot_id": "agent", "channel_id": "channel-1"},
        "api": {"scopes": ["tools:read"]},
        "tools": {"catalog_count": 4, "working_set_count": 1},
        "project": {
            "attached": True,
            "id": "project-1",
            "runtime_env": {"ready": False, "missing_secrets": ["TOKEN"]},
        },
        "harness": {"runtime": "codex", "workdir": None},
    }
    manifest["doctor"] = {"findings": agent_capabilities._doctor_findings(manifest)}

    actions = agent_capabilities._doctor_proposed_actions(manifest)

    assert actions
    assert {action["apply"]["type"] for action in actions} == {"navigate"}
    assert any(action["apply"]["href"] == "/admin/projects/project-1#Settings" for action in actions)


def test_resolved_manifest_proposes_no_actions():
    manifest = {
        "context": {"bot_id": "agent"},
        "api": {"scopes": ["tools:read"]},
        "tools": {"catalog_count": 4, "working_set_count": 1},
        "project": {"attached": False},
        "harness": {"runtime": None, "workdir": None},
        "doctor": {"findings": []},
    }

    assert agent_capabilities._doctor_proposed_actions(manifest) == []


def test_widget_payload_lists_full_authoring_loop(monkeypatch):
    fake_tools = {name: {} for name in agent_capabilities.WIDGET_AUTHORING_TOOLS}
    monkeypatch.setattr(agent_capabilities, "_local_tools", fake_tools)
    manifest = {
        "skills": {
            "bot_enrolled": [
                {"id": "widgets"},
                {"id": "widgets/html"},
                {"id": "widgets/sdk"},
                {"id": "widgets/styling"},
                {"id": "widgets/errors"},
                {"id": "widgets/channel_dashboards"},
            ],
            "channel_enrolled": [],
        }
    }

    widgets = agent_capabilities._widget_payload(manifest)

    assert widgets["readiness"] == "ready"
    assert widgets["missing_authoring_tools"] == []
    assert "prepare_widget_authoring" in widgets["authoring_tools"]
    assert "check_html_widget_authoring" in widgets["authoring_tools"]
    assert widgets["missing_skills"] == []


def test_widget_payload_reports_skill_gap_without_doctor_warning(monkeypatch):
    fake_tools = {name: {} for name in agent_capabilities.WIDGET_AUTHORING_TOOLS}
    monkeypatch.setattr(agent_capabilities, "_local_tools", fake_tools)
    manifest = {
        "context": {"bot_id": "agent"},
        "api": {"scopes": ["tools:execute"]},
        "tools": {"catalog_count": 4, "working_set_count": 1},
        "project": {"attached": False},
        "harness": {"runtime": None, "workdir": None},
        "skills": {"bot_enrolled": [], "channel_enrolled": []},
    }
    manifest["widgets"] = agent_capabilities._widget_payload(manifest)

    assert manifest["widgets"]["readiness"] == "needs_skills"
    assert manifest["widgets"]["missing_skills"]
    assert "widget_authoring_tools_missing" not in {
        finding["code"] for finding in agent_capabilities._doctor_findings(manifest)
    }
