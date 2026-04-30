import inspect
import uuid
from types import SimpleNamespace

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


def test_integration_global_entry_reports_setup_dependency_and_process_gaps():
    entry = agent_capabilities._global_integration_entry(
        {
            "id": "discord",
            "name": "Discord",
            "lifecycle_status": "enabled",
            "status": "partial",
            "env_vars": [
                {"key": "DISCORD_TOKEN", "required": True, "is_set": False},
                {"key": "AGENT_BASE_URL", "required": False, "is_set": False},
            ],
            "python_dependencies": [{"package": "discord.py", "installed": False}],
            "npm_dependencies": [{"package": "vite", "installed": True}],
            "system_dependencies": [{"binary": "ffmpeg", "apt_package": "ffmpeg", "installed": False}],
            "has_process": True,
            "process_status": {"status": "stopped", "exit_code": 1, "restart_count": 2},
            "webhook": {"path": "/integrations/discord/webhook"},
            "api_permissions": ["chat"],
        },
        {"capabilities": ["text", "rich_tool_results"], "tool_result_rendering": {"modes": ["compact"]}},
    )

    assert entry["missing_required_settings"] == ["DISCORD_TOKEN"]
    assert entry["dependency_gaps"] == {
        "python": ["discord.py"],
        "npm": [],
        "system": ["ffmpeg"],
    }
    assert entry["process"] == {
        "declared": True,
        "running": False,
        "exit_code": 1,
        "restart_count": 2,
    }
    assert entry["webhook_declared"] is True
    assert entry["api_permissions_declared"] is True
    assert entry["rich_tool_results"] is True
    assert entry["href"] == "/admin/integrations/discord"


def test_channel_integration_payload_flags_stub_bindings_and_missing_activation_config():
    channel_id = str(uuid.uuid4())
    binding = SimpleNamespace(
        id=uuid.uuid4(),
        integration_type="github",
        client_id=f"mc-activated:github:{channel_id}",
        display_name=None,
        activated=True,
        dispatch_config={"event_filter": ["issues"]},
    )

    payload = agent_capabilities._channel_integration_payload(
        channel_id=channel_id,
        bindings=[binding],
        activation_options=[
            {
                "integration_type": "github",
                "activated": True,
                "tools": ["github_repo_dashboard"],
                "includes": [],
                "requires_workspace": False,
                "activation_config": {},
                "config_fields": [{"key": "repository", "required": True}],
            }
        ],
        binding_href=f"/channels/{channel_id}/settings#channel",
        activation_href=f"/channels/{channel_id}/settings#agent",
    )

    assert payload["bindings"][0]["stub_binding"] is True
    assert payload["bindings"][0]["dispatch_config_keys"] == ["event_filter"]
    assert payload["activation_options"][0]["missing_config_fields"] == ["repository"]
    assert payload["activation_options"][0]["href"] == f"/channels/{channel_id}/settings#agent"


def test_integration_doctor_findings_and_actions_are_navigation_only():
    channel_id = str(uuid.uuid4())
    manifest = {
        "context": {"bot_id": "agent", "channel_id": channel_id},
        "api": {"scopes": ["tools:read"]},
        "tools": {"catalog_count": 4, "working_set_count": 1},
        "project": {"attached": False},
        "harness": {"runtime": None, "workdir": None},
        "integrations": {
            "global": [
                {
                    "id": "slack",
                    "name": "Slack",
                    "lifecycle_status": "enabled",
                    "status": "partial",
                    "missing_required_settings": ["SLACK_BOT_TOKEN"],
                    "dependency_gaps": {"python": [], "npm": [], "system": []},
                    "process": {"declared": True, "running": False},
                    "href": "/admin/integrations/slack",
                },
                {
                    "id": "github",
                    "name": "GitHub",
                    "lifecycle_status": "enabled",
                    "status": "partial",
                    "missing_required_settings": [],
                    "dependency_gaps": {"python": [], "npm": [], "system": ["gh"]},
                    "process": {"declared": False, "running": False},
                    "href": "/admin/integrations/github",
                },
            ],
            "channel": {
                "bindings": [
                    {
                        "integration_type": "github",
                        "stub_binding": True,
                    }
                ],
                "activation_options": [
                    {
                        "integration_type": "github",
                        "activated": True,
                        "missing_config_fields": ["repository"],
                    }
                ],
            },
        },
    }
    manifest["widgets"] = {}
    manifest["doctor"] = {"findings": agent_capabilities._doctor_findings(manifest)}

    codes = {finding["code"] for finding in manifest["doctor"]["findings"]}
    assert "integration_settings_missing:slack" in codes
    assert "integration_dependencies_missing:github" in codes
    assert "channel_integration_stub_binding:github" in codes
    assert "channel_integration_activation_config_missing:github" in codes

    actions = agent_capabilities._doctor_proposed_actions(manifest)
    assert actions
    assert {action["apply"]["type"] for action in actions} == {"navigate"}
    assert {action["kind"] for action in actions} >= {
        "integration_setup",
        "integration_binding",
        "integration_activation",
    }
    assert any(action["apply"]["href"] == "/admin/integrations/slack" for action in actions)
    assert any(action["apply"]["href"] == f"/channels/{channel_id}/settings#channel" for action in actions)
    assert any(action["apply"]["href"] == f"/channels/{channel_id}/settings#agent" for action in actions)


def test_integration_doctor_has_no_platform_specific_branches():
    source = inspect.getsource(agent_capabilities)

    assert 'integration_id == "slack"' not in source
    assert 'integration_id == "discord"' not in source
    assert 'integration_id == "bluebubbles"' not in source
    assert "integrations/slack" not in source


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
                {"id": "widgets/authoring_runs"},
            ],
            "channel_enrolled": [],
        }
    }

    widgets = agent_capabilities._widget_payload(manifest)

    assert widgets["readiness"] == "ready"
    assert widgets["missing_authoring_tools"] == []
    assert "prepare_widget_authoring" in widgets["authoring_tools"]
    assert "check_html_widget_authoring" in widgets["authoring_tools"]
    assert "publish_widget_authoring_receipt" in widgets["authoring_tools"]
    assert widgets["authoring_flow"][-2:] == [
        "publish_widget_authoring_receipt",
        "inspect_widget_pin_if_health_fails",
    ]
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
