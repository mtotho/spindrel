from __future__ import annotations

from types import SimpleNamespace

from app.agent.channel_overrides import resolve_effective_tools
from app.agent.bots import SkillConfig


def _bot(**overrides):
    defaults = {
        "local_tools": [],
        "mcp_servers": [],
        "client_tools": [],
        "pinned_tools": [],
        "skills": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _channel(**overrides):
    defaults = {
        "project_id": "project-1",
        "integrations": [],
        "local_tools_disabled": [],
        "mcp_servers_disabled": [],
        "client_tools_disabled": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_project_bound_channel_gets_project_skill_entrypoint_and_tools():
    effective = resolve_effective_tools(_bot(), _channel())

    assert [skill.id for skill in effective.skills] == ["project"]
    assert "get_project_factory_state" in effective.local_tools
    assert "get_project_orchestration_policy" in effective.local_tools
    assert "capture_project_intake" in effective.local_tools
    assert "propose_run_packs" in effective.local_tools
    assert "validate_project_run_environment_profile" in effective.local_tools
    assert "publish_project_run_receipt" in effective.local_tools


def test_project_bound_channel_respects_disabled_project_tools():
    effective = resolve_effective_tools(
        _bot(local_tools=["get_project_factory_state"]),
        _channel(local_tools_disabled=["get_project_factory_state"]),
    )

    assert "get_project_factory_state" not in effective.local_tools
    assert "project" in {skill.id for skill in effective.skills}


def test_project_skill_is_not_duplicated_when_bot_already_has_it():
    effective = resolve_effective_tools(
        _bot(skills=[SkillConfig(id="project", mode="on_demand")]),
        _channel(),
    )

    assert [skill.id for skill in effective.skills].count("project") == 1
