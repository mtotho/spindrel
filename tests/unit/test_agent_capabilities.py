import inspect
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.models import Bot, Channel, Session
from app.services import agent_capabilities
from app.services.execution_receipts import create_execution_receipt, list_execution_receipts
from app.tools.registry import _tools as local_tools


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
    assert agent_capabilities._profile_for_tool("machine_run_probe") == "diagnostics"


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


def test_skill_opportunities_recommend_existing_widget_and_integration_skills():
    manifest = {
        "skills": {
            "bot_enrolled": [{"id": "widgets"}],
            "channel_enrolled": [],
        },
        "widgets": {
            "readiness": "needs_skills",
            "missing_skills": ["widgets/html"],
        },
        "integrations": {
            "summary": {
                "needs_setup_count": 1,
                "dependency_gap_count": 0,
                "process_gap_count": 0,
                "channel_stub_binding_count": 1,
            },
        },
        "coding_run": {"readiness": "needs_project"},
        "project": {"attached": False},
        "runtime_context": {"recommendation": "continue"},
        "doctor": {"findings": [], "pending_repair_requests": []},
    }

    payload = agent_capabilities._skill_opportunity_payload(manifest)
    by_feature = {entry["feature_id"]: entry for entry in payload["recommended_now"]}

    assert by_feature["widget_authoring"]["first_action"] == 'get_skill("widgets")'
    assert by_feature["widget_authoring"]["coverage_status"] == "covered"
    assert by_feature["widget_authoring"]["suggested_owner"] == "existing_runtime_skill"
    assert by_feature["widget_authoring"]["nearest_existing_skill_ids"] == [
        "widgets",
        "widgets/html",
        "widgets/channel_dashboards",
        "widgets/authoring_runs",
    ]
    assert by_feature["widget_authoring"]["missing_skill_ids"] == [
        "widgets/html",
        "widgets/channel_dashboards",
        "widgets/authoring_runs",
    ]
    assert by_feature["widget_authoring"]["model_support"] == "recommended_for_small_models"
    assert by_feature["integration_readiness"]["skill_ids"] == [
        "configurator/integration",
        "orchestrator/integration_builder",
        "diagnostics",
    ]
    assert by_feature["integration_readiness"]["coverage_status"] == "covered"
    assert payload["creation_candidates"] == []


def test_skill_opportunities_recommend_agent_readiness_runtime_skill():
    manifest = {
        "skills": {"bot_enrolled": [], "channel_enrolled": []},
        "widgets": {"readiness": "ready", "missing_skills": []},
        "integrations": {"summary": {}},
        "coding_run": {"readiness": "needs_project"},
        "project": {"attached": False},
        "runtime_context": {"recommendation": "handoff"},
        "doctor": {
            "findings": [{"code": "missing_api_scopes"}],
            "pending_repair_requests": [{"summary": "Requested readiness repair."}],
        },
    }

    payload = agent_capabilities._skill_opportunity_payload(manifest)

    assert payload["creation_candidates"] == []
    by_feature = {entry["feature_id"]: entry for entry in payload["recommended_now"]}
    readiness = by_feature["agent_readiness_operator"]
    assert readiness == {
        "feature_id": "agent_readiness_operator",
        "feature_label": "Agent Readiness operator",
        "skill_ids": ["agent_readiness/operator"],
        "missing_skill_ids": ["agent_readiness/operator"],
        "coverage_status": "covered",
        "nearest_existing_skill_ids": [
            "agent_readiness/operator",
            "configurator",
            "diagnostics",
            "orchestrator/audits",
        ],
        "why_skill_shaped": "Agent Readiness repair review is a repeated approval-gated workflow over manifest findings, preflight, requests, and receipts.",
        "small_model_reason": "Smaller models need a short procedure to avoid mutating stale repair requests or skipping preflight.",
        "suggested_owner": "existing_runtime_skill",
        "reason": "Readiness repair review is a repeated approval-gated workflow that should have a short runtime skill for non-frontier models.",
        "when_to_load": "Before handling Doctor findings, pending repair requests, missing scopes, empty tool sets, or widget skill enrollment gaps.",
        "first_action": 'get_skill("agent_readiness/operator")',
        "model_support": "recommended_for_small_models",
        "labels": {
            "agent_readiness/operator": "Agent Readiness operator",
        },
    }
    assert by_feature["context_pressure"]["first_action"] == 'get_skill("context_mastery")'


def test_agent_readiness_operator_skill_documents_runtime_boundaries():
    text = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "agent_readiness"
        / "operator.md"
    ).read_text()

    for required in (
        "list_agent_capabilities",
        "run_agent_doctor",
        "preflight_agent_repair",
        "request_agent_repair",
        "Do not import repo-local `.agents` skills into runtime skills",
    ):
        assert required in text


def test_skill_opportunities_recommend_native_planning_runtime_skill():
    manifest = {
        "skills": {"bot_enrolled": [], "channel_enrolled": []},
        "widgets": {"readiness": "ready", "missing_skills": []},
        "integrations": {"summary": {}},
        "coding_run": {"readiness": "needs_project"},
        "project": {"attached": False},
        "runtime_context": {"recommendation": "continue"},
        "doctor": {"findings": [], "pending_repair_requests": []},
        "planning": {"active": True, "mode": "executing"},
    }

    payload = agent_capabilities._skill_opportunity_payload(manifest)

    assert payload["creation_candidates"] == []
    by_feature = {entry["feature_id"]: entry for entry in payload["recommended_now"]}
    planning = by_feature["native_session_planning"]
    assert planning["first_action"] == 'get_skill("planning/native_session")'
    assert planning["coverage_status"] == "covered"
    assert planning["suggested_owner"] == "existing_runtime_skill"
    assert planning["missing_skill_ids"] == ["planning/native_session"]


def test_planning_payload_exposes_active_plan_mode_without_new_api_state():
    session = Session(
        id=uuid.uuid4(),
        client_id="planning-skill-test",
        bot_id="agent",
        channel_id=uuid.uuid4(),
        metadata_={
            "plan_mode": "executing",
            "plan_runtime": {
                "current_focus": {"label": "Create marker"},
                "latest_outcome": {"outcome": "progress"},
                "latest_semantic_review": {"verdict": "supported"},
                "latest_tool_feedback": {"tool_name": "publish_plan"},
            },
        },
    )

    payload = agent_capabilities._planning_payload(session)

    assert payload["active"] is True
    assert payload["mode"] == "executing"
    assert payload["recommended_skills"] == ["planning/native_session"]
    assert payload["current_focus"] == {"label": "Create marker"}
    assert "publish_plan" in payload["required_tools"]


def test_native_planning_skill_documents_runtime_boundaries():
    text = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "planning"
        / "native_session.md"
    ).read_text()

    for required in (
        "ask_plan_questions",
        "publish_plan",
        "record_plan_progress",
        "request_plan_replan",
        "Do not use repo-local `.agents` skill text as runtime guidance",
        "update this skill first",
    ):
        assert required in text


def test_skill_opportunities_recommend_project_coding_run_runtime_skill():
    manifest = {
        "skills": {"bot_enrolled": [], "channel_enrolled": []},
        "widgets": {"readiness": "ready", "missing_skills": []},
        "integrations": {"summary": {}},
        "coding_run": {"readiness": "ready"},
        "project": {"attached": True},
        "runtime_context": {"recommendation": "continue"},
        "doctor": {"findings": []},
    }

    payload = agent_capabilities._skill_opportunity_payload(manifest)

    by_feature = {entry["feature_id"]: entry for entry in payload["recommended_now"]}
    project = by_feature["project_coding_run"]
    assert project["skill_ids"] == [
        "workspace/project_coding_runs",
        "workspace/files",
        "workspace/member",
        "e2e_testing",
    ]
    assert project["first_action"] == 'get_skill("workspace/project_coding_runs")'
    assert project["labels"]["workspace/project_coding_runs"] == "Project coding runs"
    assert project["coverage_status"] == "covered"


def test_project_coding_run_payload_includes_review_tools(monkeypatch):
    monkeypatch.setattr(agent_capabilities, "_local_tools", {
        "file": {},
        "exec_command": {},
        "run_e2e_tests": {},
        "prepare_project_run_handoff": {},
        "schedule_project_coding_run": {},
        "get_project_coding_run_review_context": {},
        "finalize_project_coding_run_review": {},
        "publish_project_run_receipt": {},
    })
    manifest = {
        "project": {"attached": True, "runtime_env": {"ready": True}},
    }

    payload = agent_capabilities._coding_run_payload(manifest)

    assert payload["readiness"] == "ready"
    assert payload["review_context"] == "available"
    assert payload["review_finalizer"] == "available"
    assert payload["missing_tools"] == []
    assert "get_project_coding_run_review_context" in payload["required_tools"]
    assert "finalize_project_coding_run_review" in payload["required_tools"]


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

    async def fake_activity_log_payload(*args, **kwargs):
        return {
            "available": True,
            "supported_kinds": ["tool_call"],
            "supported_filters": ["bot_id", "kind"],
            "recent_count": 1,
            "recent_counts": {"tool_call": 1},
            "recent": [{"kind": "tool_call", "summary": "get_tool_info done"}],
        }

    async def fake_agent_status_payload(*args, **kwargs):
        return {
            "available": True,
            "state": "idle",
            "recommendation": "continue",
            "current": None,
            "heartbeat": {"configured": True, "enabled": True},
            "recent_runs": [],
        }

    async def fake_doctor_recent_receipts_payload(*args, **kwargs):
        return [{"scope": "agent_readiness", "summary": "Verified resolved."}]

    async def fake_doctor_pending_repair_requests_payload(*args, **kwargs):
        return [{"scope": "agent_readiness", "status": "needs_review", "summary": "Requested repair."}]

    monkeypatch.setattr(agent_capabilities, "_resolve_context", fake_resolve_context)
    monkeypatch.setattr(agent_capabilities, "_scopes_for_bot", fake_scopes_for_bot)
    monkeypatch.setattr(agent_capabilities, "_tool_payload", fake_tool_payload)
    monkeypatch.setattr(agent_capabilities, "_skill_payload", fake_skill_payload)
    monkeypatch.setattr(agent_capabilities, "_project_payload", fake_project_payload)
    monkeypatch.setattr(agent_capabilities, "_integration_payload", fake_integration_payload)
    monkeypatch.setattr(agent_capabilities, "runtime_context_payload", fake_runtime_context_payload)
    monkeypatch.setattr(agent_capabilities, "work_state_payload", fake_work_state_payload)
    monkeypatch.setattr(agent_capabilities, "activity_log_payload", fake_activity_log_payload)
    monkeypatch.setattr(agent_capabilities, "agent_status_payload", fake_agent_status_payload)
    monkeypatch.setattr(agent_capabilities, "doctor_recent_receipts_payload", fake_doctor_recent_receipts_payload)
    monkeypatch.setattr(agent_capabilities, "doctor_pending_repair_requests_payload", fake_doctor_pending_repair_requests_payload)

    manifest = await agent_capabilities.build_agent_capability_manifest(SimpleNamespace(), bot_id="agent")

    assert manifest["runtime_context"]["recommendation"] == "continue"
    assert manifest["work_state"]["summary"]["recommended_next_action"] == "idle"
    assert manifest["agent_status"]["state"] == "idle"
    assert manifest["activity_log"]["recent_counts"]["tool_call"] == 1
    assert manifest["tool_error_contract"]["version"] == "tool-error.v1"
    assert "validation" in manifest["tool_error_contract"]["benign_review_kinds"]
    assert manifest["doctor"]["recent_receipts"][0]["summary"] == "Verified resolved."
    assert manifest["doctor"]["pending_repair_requests"][0]["summary"] == "Requested repair."
    assert "context_should_summarize" not in {
        finding["code"] for finding in manifest["doctor"]["findings"]
    }


@pytest.mark.asyncio
async def test_doctor_recent_receipts_payload_filters_agent_readiness_receipts(db_session):
    channel_id = uuid.uuid4()
    other_channel_id = uuid.uuid4()
    db_session.add_all([
        Channel(id=channel_id, name="Readiness", bot_id="agent", client_id=f"receipt-{uuid.uuid4().hex[:8]}"),
        Channel(id=other_channel_id, name="Other", bot_id="agent", client_id=f"receipt-{uuid.uuid4().hex[:8]}"),
    ])
    await db_session.commit()
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="tool_setup",
        status="succeeded",
        summary="Verified resolved.",
        bot_id="agent",
        channel_id=channel_id,
    )
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="tool_setup",
        status="succeeded",
        summary="Other channel.",
        bot_id="agent",
        channel_id=other_channel_id,
    )
    await create_execution_receipt(
        db_session,
        scope="general",
        action_type="tool_setup",
        status="succeeded",
        summary="Wrong scope.",
        bot_id="agent",
        channel_id=channel_id,
    )

    receipts = await agent_capabilities.doctor_recent_receipts_payload(
        db_session,
        bot_id="agent",
        channel_id=channel_id,
    )

    assert [receipt["summary"] for receipt in receipts] == ["Verified resolved."]
    assert receipts[0]["schema_version"] == "execution-receipt.v1"


@pytest.mark.asyncio
async def test_doctor_pending_repair_requests_payload_filters_requested_needs_review(db_session):
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="tool_setup",
        status="needs_review",
        summary="Requested repair.",
        bot_id="agent",
        result={"requested_repair": True},
    )
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="tool_setup",
        status="succeeded",
        summary="Already applied.",
        bot_id="agent",
        result={"requested_repair": True},
    )
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="tool_setup",
        status="needs_review",
        summary="Manual review.",
        bot_id="agent",
        result={"requested_repair": False},
    )

    receipts = await agent_capabilities.doctor_pending_repair_requests_payload(db_session, bot_id="agent")

    assert [receipt["summary"] for receipt in receipts] == ["Requested repair."]
    assert receipts[0]["status"] == "needs_review"


@pytest.mark.asyncio
async def test_agent_readiness_autofix_queue_serializes_pending_requests(db_session):
    channel_id = uuid.uuid4()
    other_channel_id = uuid.uuid4()
    db_session.add_all([
        Channel(id=channel_id, name="Readiness", bot_id="agent", client_id=f"autofix-{uuid.uuid4().hex[:8]}"),
        Channel(id=other_channel_id, name="Other", bot_id="agent", client_id=f"autofix-{uuid.uuid4().hex[:8]}"),
    ])
    await db_session.commit()
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="bot_patch",
        status="needs_review",
        summary="Requested readiness repair: enable tools",
        actor={"kind": "bot_tool", "name": "Sprout"},
        target={
            "bot_id": "agent",
            "channel_id": str(channel_id),
            "action_id": "enable_core_agent_tools",
            "finding_code": "missing_core_agent_tools",
        },
        result={
            "requested_repair": True,
            "rationale": "Tool calls are blocked.",
            "requester_missing_actor_scopes": ["bots:write"],
        },
        bot_id="agent",
        channel_id=channel_id,
    )
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="bot_patch",
        status="needs_review",
        summary="Other channel request.",
        result={"requested_repair": True},
        bot_id="agent",
        channel_id=other_channel_id,
    )
    await create_execution_receipt(
        db_session,
        scope="agent_readiness",
        action_type="bot_patch",
        status="succeeded",
        summary="Already applied.",
        result={"requested_repair": True},
        bot_id="agent",
        channel_id=channel_id,
    )

    queue = await agent_capabilities.agent_readiness_autofix_queue_payload(
        db_session,
        channel_id=channel_id,
    )

    assert len(queue) == 1
    item = queue[0]
    assert item["summary"] == "Requested readiness repair: enable tools"
    assert item["bot_id"] == "agent"
    assert item["channel_id"] == str(channel_id)
    assert item["action_id"] == "enable_core_agent_tools"
    assert item["finding_code"] == "missing_core_agent_tools"
    assert item["requested_by"] == "Sprout"
    assert item["rationale"] == "Tool calls are blocked."
    assert item["requester_missing_actor_scopes"] == ["bots:write"]
    assert item["receipt"]["status"] == "needs_review"


def _preflight_manifest(action: dict, *, bot_id: str = "agent", findings: list[str] | None = None) -> dict:
    findings = findings or [action["finding_code"]]
    return {
        "context": {"bot_id": bot_id},
        "doctor": {
            "findings": [{"code": code, "severity": "warning", "message": code} for code in findings],
            "proposed_actions": [action],
        },
    }


def _bot_patch_action(
    *,
    action_id: str = "agent:empty_tool_working_set:core_tools",
    finding_code: str = "empty_tool_working_set",
    patch: dict | None = None,
    required_actor_scopes: list[str] | None = None,
) -> dict:
    return {
        "id": action_id,
        "finding_code": finding_code,
        "kind": "tool_setup",
        "title": "Add core tools",
        "description": "Add tools.",
        "impact": "Adds tools.",
        "required_actor_scopes": required_actor_scopes or ["bots:write"],
        "grants_scopes": [],
        "apply": {
            "type": "bot_patch",
            "patch": patch or {"local_tools": ["list_agent_capabilities"]},
        },
    }


async def _fake_request_manifest(db, *, action: dict, bot_id: str = "agent") -> dict:
    return _preflight_manifest(action, bot_id=bot_id)


@pytest.mark.asyncio
async def test_preflight_agent_repair_ready_for_bot_patch(db_session):
    db_session.add(Bot(
        id="agent",
        name="Agent",
        model="test/model",
        system_prompt="",
        local_tools=[],
        pinned_tools=[],
    ))
    await db_session.commit()

    action = _bot_patch_action()
    preflight = await agent_capabilities._preflight_action_from_manifest(
        db_session,
        _preflight_manifest(action),
        action_id=action["id"],
        actor_scopes=["bots:write"],
    )

    assert preflight["schema_version"] == "agent-action-preflight.v1"
    assert preflight["status"] == "ready"
    assert preflight["can_apply"] is True
    assert preflight["missing_actor_scopes"] == []
    assert preflight["action"]["apply_type"] == "bot_patch"
    assert preflight["would_change"] == [{
        "field": "local_tools",
        "current": [],
        "next": ["list_agent_capabilities"],
        "changes": True,
    }]


@pytest.mark.asyncio
async def test_preflight_agent_repair_diffs_api_permission_patch(db_session):
    db_session.add(Bot(
        id="agent",
        name="Agent",
        model="test/model",
        system_prompt="",
        local_tools=[],
        pinned_tools=[],
    ))
    await db_session.commit()

    action = _bot_patch_action(
        action_id="agent:missing_api_scopes:workspace_bot",
        finding_code="missing_api_scopes",
        patch={"api_permissions": ["channels:read", "tools:read"]},
    )
    preflight = await agent_capabilities._preflight_action_from_manifest(
        db_session,
        _preflight_manifest(action),
        action_id=action["id"],
        actor_scopes=["admin"],
    )

    assert preflight["status"] == "ready"
    assert preflight["would_change"] == [{
        "field": "api_permissions",
        "current": [],
        "next": ["channels:read", "tools:read"],
        "changes": True,
    }]


@pytest.mark.asyncio
async def test_preflight_agent_repair_blocks_missing_actor_scope(db_session):
    db_session.add(Bot(
        id="agent",
        name="Agent",
        model="test/model",
        system_prompt="",
        local_tools=[],
        pinned_tools=[],
    ))
    await db_session.commit()

    action = _bot_patch_action(required_actor_scopes=["bots:write"])
    preflight = await agent_capabilities._preflight_action_from_manifest(
        db_session,
        _preflight_manifest(action),
        action_id=action["id"],
        actor_scopes=["tools:read"],
    )

    assert preflight["status"] == "blocked"
    assert preflight["can_apply"] is False
    assert preflight["missing_actor_scopes"] == ["bots:write"]
    assert preflight["would_change"] == []


@pytest.mark.asyncio
async def test_preflight_agent_repair_reports_stale_action(db_session):
    action = _bot_patch_action()

    preflight = await agent_capabilities._preflight_action_from_manifest(
        db_session,
        _preflight_manifest(action, findings=["empty_tool_working_set"]),
        action_id="agent:missing_api_scopes:workspace_bot",
        actor_scopes=["bots:write"],
    )

    assert preflight["status"] == "stale"
    assert preflight["can_apply"] is False
    assert preflight["action"] is None
    assert preflight["current_findings"] == ["empty_tool_working_set"]


@pytest.mark.asyncio
async def test_preflight_agent_repair_noops_when_patch_matches_current_bot(db_session):
    db_session.add(Bot(
        id="agent",
        name="Agent",
        model="test/model",
        system_prompt="",
        local_tools=["list_agent_capabilities"],
        pinned_tools=[],
    ))
    await db_session.commit()

    action = _bot_patch_action()
    preflight = await agent_capabilities._preflight_action_from_manifest(
        db_session,
        _preflight_manifest(action),
        action_id=action["id"],
        actor_scopes=["admin"],
    )

    assert preflight["status"] == "noop"
    assert preflight["can_apply"] is False
    assert preflight["reason"] == "Patch would not change current bot configuration."
    assert preflight["would_change"][0]["changes"] is False


@pytest.mark.asyncio
async def test_request_agent_repair_queues_review_without_mutating_bot(monkeypatch, db_session):
    bot = Bot(
        id="agent",
        name="Agent",
        model="test/model",
        system_prompt="",
        local_tools=[],
        pinned_tools=[],
    )
    db_session.add(bot)
    await db_session.commit()
    action = _bot_patch_action()

    async def fake_manifest(*args, **kwargs):
        return await _fake_request_manifest(db_session, action=action)

    monkeypatch.setattr(agent_capabilities, "build_agent_capability_manifest", fake_manifest)

    request = await agent_capabilities.request_agent_repair_action(
        db_session,
        action_id=action["id"],
        bot_id="agent",
        requester_scopes=["tools:execute"],
        actor={"kind": "bot", "bot_id": "agent"},
        rationale="I need the core tools.",
    )
    await db_session.refresh(bot)

    assert request["schema_version"] == "agent-repair-request.v1"
    assert request["ok"] is True
    assert request["status"] == "queued"
    assert request["created"] is True
    assert request["updated"] is False
    assert request["requester_missing_actor_scopes"] == ["bots:write"]
    assert request["receipt"]["status"] == "needs_review"
    assert request["receipt"]["result"]["requested_repair"] is True
    assert request["receipt"]["result"]["rationale"] == "I need the core tools."
    assert bot.local_tools == []


@pytest.mark.asyncio
async def test_request_agent_repair_idempotently_updates_same_receipt(monkeypatch, db_session):
    db_session.add(Bot(
        id="agent",
        name="Agent",
        model="test/model",
        system_prompt="",
        local_tools=[],
        pinned_tools=[],
    ))
    await db_session.commit()
    action = _bot_patch_action()

    async def fake_manifest(*args, **kwargs):
        return await _fake_request_manifest(db_session, action=action)

    monkeypatch.setattr(agent_capabilities, "build_agent_capability_manifest", fake_manifest)

    first = await agent_capabilities.request_agent_repair_action(
        db_session,
        action_id=action["id"],
        bot_id="agent",
        requester_scopes=["tools:execute"],
        actor={"kind": "bot", "bot_id": "agent"},
        rationale="first",
    )
    second = await agent_capabilities.request_agent_repair_action(
        db_session,
        action_id=action["id"],
        bot_id="agent",
        requester_scopes=["tools:execute"],
        actor={"kind": "bot", "bot_id": "agent"},
        rationale="second",
    )

    rows = await list_execution_receipts(db_session, scope="agent_readiness", bot_id="agent")

    assert first["receipt_id"] == second["receipt_id"]
    assert second["created"] is False
    assert second["updated"] is True
    assert second["receipt"]["result"]["rationale"] == "second"
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_request_agent_repair_does_not_queue_noop(monkeypatch, db_session):
    db_session.add(Bot(
        id="agent",
        name="Agent",
        model="test/model",
        system_prompt="",
        local_tools=["list_agent_capabilities"],
        pinned_tools=[],
    ))
    await db_session.commit()
    action = _bot_patch_action()

    async def fake_manifest(*args, **kwargs):
        return await _fake_request_manifest(db_session, action=action)

    monkeypatch.setattr(agent_capabilities, "build_agent_capability_manifest", fake_manifest)

    request = await agent_capabilities.request_agent_repair_action(
        db_session,
        action_id=action["id"],
        bot_id="agent",
        requester_scopes=["bots:write", "tools:execute"],
        actor={"kind": "bot", "bot_id": "agent"},
    )
    rows = await list_execution_receipts(db_session, scope="agent_readiness", bot_id="agent")

    assert request["ok"] is False
    assert request["status"] == "noop"
    assert rows == []


@pytest.mark.asyncio
async def test_request_agent_repair_does_not_queue_stale_action(monkeypatch, db_session):
    action = _bot_patch_action()

    async def fake_manifest(*args, **kwargs):
        return _preflight_manifest(action, findings=["empty_tool_working_set"])

    monkeypatch.setattr(agent_capabilities, "build_agent_capability_manifest", fake_manifest)

    request = await agent_capabilities.request_agent_repair_action(
        db_session,
        action_id="agent:missing_api_scopes:workspace_bot",
        bot_id="agent",
        requester_scopes=["bots:write", "tools:execute"],
        actor={"kind": "bot", "bot_id": "agent"},
    )
    rows = await list_execution_receipts(db_session, scope="agent_readiness", bot_id="agent")

    assert request["ok"] is False
    assert request["status"] == "stale"
    assert rows == []


def test_preflight_and_request_agent_repair_tools_are_registered():
    from app.tools.local import agent_capabilities as _agent_capabilities_tools  # noqa: F401

    assert "preflight_agent_repair" in agent_capabilities.CORE_AGENT_TOOLS
    assert "request_agent_repair" in agent_capabilities.CORE_AGENT_TOOLS
    assert "preflight_agent_repair" in local_tools
    assert "request_agent_repair" in local_tools
    assert local_tools["request_agent_repair"]["safety_tier"] == "mutating"


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


def test_doctor_flags_agent_status_findings_and_heartbeat_navigation():
    manifest = {
        "context": {"bot_id": "agent", "channel_id": "channel-1"},
        "api": {"scopes": ["tools:read"]},
        "tools": {"catalog_count": 4, "working_set_count": 1},
        "project": {"attached": False},
        "harness": {"runtime": None, "workdir": None},
        "agent_status": {
            "available": True,
            "state": "idle",
            "current": {"stale": True},
            "heartbeat": {"configured": False, "repetition_detected": True},
            "recent_runs": [
                {"status": "failed", "repetition_detected": True},
            ],
        },
    }
    manifest["doctor"] = {"findings": agent_capabilities._doctor_findings(manifest)}

    codes = {finding["code"] for finding in manifest["doctor"]["findings"]}
    assert "agent_status_stale_run" in codes
    assert "agent_last_run_failed" in codes
    assert "heartbeat_repetition_detected" in codes

    manifest["agent_status"]["current"] = None
    manifest["doctor"] = {"findings": agent_capabilities._doctor_findings(manifest)}
    actions = agent_capabilities._doctor_proposed_actions(manifest)

    assert "heartbeat_not_configured" in {
        finding["code"] for finding in manifest["doctor"]["findings"]
    }
    assert any(action["apply"]["href"] == "/channels/channel-1/settings#automation" for action in actions)


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


def test_agent_activity_log_tool_registered_with_return_schema():
    from app.tools.local import agent_capabilities as _tool_module  # noqa: F401
    from app.tools.registry import _tools

    entry = _tools["get_agent_activity_log"]

    assert entry["safety_tier"] == "readonly"
    assert entry["requires_bot_context"] is True
    assert entry["returns"]["properties"]["items"]["type"] == "array"


def test_agent_status_snapshot_tool_registered_with_return_schema():
    from app.tools.local import agent_capabilities as _tool_module  # noqa: F401
    from app.tools.registry import _tools

    entry = _tools["get_agent_status_snapshot"]

    assert entry["safety_tier"] == "readonly"
    assert entry["requires_bot_context"] is True
    assert entry["returns"]["properties"]["agent_status"]["type"] == "object"


def test_publish_execution_receipt_tool_registered_with_return_schema():
    from app.tools.local import execution_receipts as _tool_module  # noqa: F401
    from app.tools.registry import _tools

    entry = _tools["publish_execution_receipt"]

    assert entry["safety_tier"] == "mutating"
    assert entry["requires_bot_context"] is True
    assert entry["returns"]["properties"]["receipt"]["type"] == "object"


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
