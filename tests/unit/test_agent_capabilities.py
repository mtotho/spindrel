import inspect
import uuid
from types import SimpleNamespace

import pytest

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


def test_runtime_context_budget_normalization_and_thresholds():
    base = {
        "consumed_tokens": 74_000,
        "total_tokens": 100_000,
        "source": "api",
        "context_profile": "chat",
    }

    snapshot = agent_capabilities._runtime_context_from_budget(
        base,
        channel_id="channel-1",
        session_id="session-1",
    )
    assert snapshot["available"] is True
    assert snapshot["recommendation"] == "continue"
    assert snapshot["budget"] == {
        "tokens_used": 74_000,
        "tokens_remaining": 26_000,
        "total_tokens": 100_000,
        "percent_full": 74.0,
        "source": "api",
        "context_profile": "chat",
    }

    summarize = agent_capabilities._runtime_context_from_budget(
        {**base, "consumed_tokens": 75_000},
        channel_id="channel-1",
        session_id="session-1",
    )
    handoff = agent_capabilities._runtime_context_from_budget(
        {**base, "consumed_tokens": 90_000},
        channel_id="channel-1",
        session_id="session-1",
    )

    assert summarize["recommendation"] == "summarize"
    assert handoff["recommendation"] == "handoff"


def test_runtime_context_without_budget_data_is_unknown():
    snapshot = agent_capabilities._runtime_context_from_budget(
        {"source": "none"},
        channel_id="channel-1",
        session_id=None,
    )

    assert snapshot["available"] is False
    assert snapshot["recommendation"] == "unknown"
    assert snapshot["budget"]["tokens_used"] is None
    assert snapshot["reason"] == "No context budget has been recorded yet."


@pytest.mark.asyncio
async def test_manifest_includes_runtime_context(monkeypatch):
    bot = SimpleNamespace(
        id="agent",
        name="Agent",
        harness_runtime=None,
        harness_workdir=None,
    )

    async def fake_resolve_context(*args, **kwargs):
        return bot, None, None

    async def fake_scopes_for_bot(*args, **kwargs):
        return ["tools:read"]

    async def fake_tool_payload(*args, **kwargs):
        return {"catalog_count": 1, "working_set_count": 1, "recommended_core": []}

    async def fake_skill_payload(*args, **kwargs):
        return {"bot_enrolled": [], "channel_enrolled": [], "working_set_count": 0}

    async def fake_project_payload(*args, **kwargs):
        return {"attached": False}

    async def fake_integration_payload(*args, **kwargs):
        return {"summary": {}, "global": [], "channel": None}

    async def fake_runtime_context_payload(*args, **kwargs):
        return {
            "available": True,
            "recommendation": "continue",
            "budget": {"percent_full": 12.5},
        }

    async def fake_work_state_payload(*args, **kwargs):
        return {
            "available": True,
            "summary": {
                "assigned_mission_count": 0,
                "assigned_attention_count": 0,
                "has_current_work": False,
                "recommended_next_action": "idle",
            },
            "missions": [],
            "attention": [],
        }

    monkeypatch.setattr(agent_capabilities, "_resolve_context", fake_resolve_context)
    monkeypatch.setattr(agent_capabilities, "_scopes_for_bot", fake_scopes_for_bot)
    monkeypatch.setattr(agent_capabilities, "_tool_payload", fake_tool_payload)
    monkeypatch.setattr(agent_capabilities, "_skill_payload", fake_skill_payload)
    monkeypatch.setattr(agent_capabilities, "_project_payload", fake_project_payload)
    monkeypatch.setattr(agent_capabilities, "_integration_payload", fake_integration_payload)
    monkeypatch.setattr(agent_capabilities, "runtime_context_payload", fake_runtime_context_payload)
    monkeypatch.setattr(agent_capabilities, "work_state_payload", fake_work_state_payload)

    manifest = await agent_capabilities.build_agent_capability_manifest(SimpleNamespace(), bot_id="agent")

    assert manifest["runtime_context"]["recommendation"] == "continue"
    assert manifest["work_state"]["summary"]["recommended_next_action"] == "idle"
    assert manifest["tool_error_contract"]["version"] == "tool-error.v1"
    assert "validation" in manifest["tool_error_contract"]["benign_review_kinds"]
    assert "context_should_summarize" not in {
        finding["code"] for finding in manifest["doctor"]["findings"]
    }


def test_doctor_flags_runtime_context_pressure():
    manifest = {
        "context": {"bot_id": "agent"},
        "api": {"scopes": ["tools:read"]},
        "tools": {"catalog_count": 4, "working_set_count": 1},
        "project": {"attached": False},
        "harness": {"runtime": None, "workdir": None},
        "runtime_context": {
            "recommendation": "handoff",
            "budget": {"percent_full": 91.2},
        },
    }

    findings = agent_capabilities._doctor_findings(manifest)
    handoff = next(item for item in findings if item["code"] == "context_should_handoff")

    assert handoff["severity"] == "error"
    assert "91.2% full" in handoff["message"]


def test_agent_context_snapshot_tool_registered_with_return_schema():
    from app.tools.local import agent_capabilities as _tool_module  # noqa: F401
    from app.tools.registry import _tools

    entry = _tools["get_agent_context_snapshot"]

    assert entry["safety_tier"] == "readonly"
    assert entry["requires_bot_context"] is True
    assert entry["returns"]["properties"]["runtime_context"]["type"] == "object"


def test_agent_work_snapshot_tool_registered_with_return_schema():
    from app.tools.local import agent_capabilities as _tool_module  # noqa: F401
    from app.tools.registry import _tools

    entry = _tools["get_agent_work_snapshot"]

    assert entry["safety_tier"] == "readonly"
    assert entry["requires_bot_context"] is True
    assert entry["returns"]["properties"]["work_state"]["type"] == "object"


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
