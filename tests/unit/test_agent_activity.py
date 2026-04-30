from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import (
    Channel,
    ExecutionReceipt,
    Project,
    ProjectRunReceipt,
    Session,
    SharedWorkspace,
    ToolCall,
    WidgetAgencyReceipt,
    WorkspaceAttentionItem,
    WorkspaceMission,
    WorkspaceMissionUpdate,
)
from app.services.agent_activity import agent_activity_summary, list_agent_activity


pytestmark = pytest.mark.asyncio


async def _seed_activity(db_session):
    now = datetime.now(timezone.utc)
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    task_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    workspace = SharedWorkspace(name=f"activity-{uuid.uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Activity Project",
        slug=f"activity-{uuid.uuid4().hex[:8]}",
        root_path="common/projects/activity",
    )
    mission = WorkspaceMission(
        title="Keep project moving",
        directive="Review recent activity.",
        channel_id=channel_id,
    )
    db_session.add_all([
        Channel(id=channel_id, name="Ops", bot_id="agent", client_id=f"ops-{uuid.uuid4().hex[:8]}"),
        Session(id=session_id, client_id=f"client-{uuid.uuid4().hex[:8]}", bot_id="agent", channel_id=channel_id),
        project,
        mission,
    ])
    await db_session.flush()

    db_session.add_all([
        ToolCall(
            session_id=session_id,
            bot_id="agent",
            tool_name="call_api",
            tool_type="local",
            status="error",
            error="HTTP 429",
            error_code="http_429",
            error_kind="rate_limited",
            retryable=True,
            retry_after_seconds=30,
            fallback="Retry with backoff.",
            correlation_id=correlation_id,
            created_at=now,
        ),
        WorkspaceAttentionItem(
            source_type="bot",
            source_id="agent",
            channel_id=channel_id,
            target_kind="channel",
            target_id=str(channel_id),
            dedupe_key=f"activity:{uuid.uuid4()}",
            severity="warning",
            title="API retries needed",
            message="Retryable upstream failure",
            next_steps=["Wait for retry_after_seconds before retrying."],
            latest_correlation_id=correlation_id,
            last_seen_at=now,
        ),
        WorkspaceMissionUpdate(
            mission_id=mission.id,
            bot_id="agent",
            kind="progress",
            summary="Checked current blockers.",
            next_actions=["Review the retryable tool failure."],
            task_id=task_id,
            session_id=session_id,
            correlation_id=correlation_id,
            created_at=now,
        ),
        ProjectRunReceipt(
            project_id=project.id,
            task_id=task_id,
            session_id=session_id,
            bot_id="agent",
            status="needs_review",
            summary="Opened a review handoff.",
            handoff_type="branch",
            handoff_url="https://example.invalid/review",
            created_at=now,
        ),
        WidgetAgencyReceipt(
            channel_id=channel_id,
            dashboard_key=f"channel:{channel_id}",
            action="authoring_checked",
            summary="Checked dashboard widget health.",
            bot_id="agent",
            session_id=session_id,
            correlation_id=correlation_id,
            task_id=task_id,
            affected_pin_ids=[str(uuid.uuid4())],
            metadata_={"kind": "authoring", "next_actions": [{"label": "Fix stale data"}]},
            created_at=now,
        ),
        ExecutionReceipt(
            scope="agent_readiness",
            action_type="bot_patch",
            status="succeeded",
            summary="Applied readiness repair.",
            actor={"kind": "human_ui"},
            target={"bot_id": "agent", "finding_code": "missing_api_permissions"},
            before_summary="Bot could not call APIs.",
            after_summary="Bot has API grants.",
            approval_required=True,
            approval_ref="agent_readiness_panel",
            result={"applied": True},
            bot_id="agent",
            channel_id=channel_id,
            session_id=session_id,
            task_id=task_id,
            correlation_id=correlation_id,
            created_at=now,
        ),
    ])
    await db_session.commit()
    return {
        "channel_id": channel_id,
        "session_id": session_id,
        "task_id": task_id,
        "correlation_id": correlation_id,
    }


async def test_agent_activity_normalizes_existing_evidence(db_session):
    ids = await _seed_activity(db_session)

    items = await list_agent_activity(db_session, bot_id="agent", channel_id=ids["channel_id"], limit=20)
    by_kind = {item["kind"]: item for item in items}

    assert set(by_kind) == {
        "tool_call",
        "attention",
        "mission_update",
        "project_receipt",
        "widget_receipt",
        "execution_receipt",
    }
    assert by_kind["tool_call"]["status"] == "failed"
    assert by_kind["tool_call"]["error"] == {
        "error_code": "http_429",
        "error_kind": "rate_limited",
        "retryable": True,
    }
    assert by_kind["tool_call"]["next_action"] == "Retry with backoff."
    assert by_kind["attention"]["status"] == "needs_review"
    assert by_kind["mission_update"]["next_action"] == "Review the retryable tool failure."
    assert by_kind["project_receipt"]["target"]["project_id"]
    assert by_kind["widget_receipt"]["target"]["widget_pin_ids"]
    assert by_kind["execution_receipt"]["source"]["scope"] == "agent_readiness"
    assert by_kind["execution_receipt"]["target"]["bot_id"] == "agent"


async def test_agent_activity_filters_by_kind_task_and_correlation(db_session):
    ids = await _seed_activity(db_session)

    tool_items = await list_agent_activity(
        db_session,
        bot_id="agent",
        channel_id=ids["channel_id"],
        correlation_id=ids["correlation_id"],
        kind="tool_call",
    )
    task_items = await list_agent_activity(
        db_session,
        bot_id="agent",
        channel_id=ids["channel_id"],
        task_id=ids["task_id"],
    )

    assert [item["kind"] for item in tool_items] == ["tool_call"]
    assert {item["kind"] for item in task_items} == {
        "mission_update",
        "project_receipt",
        "widget_receipt",
        "execution_receipt",
    }


async def test_agent_activity_summary_advertises_replay_contract(db_session):
    ids = await _seed_activity(db_session)

    summary = await agent_activity_summary(
        db_session,
        bot_id="agent",
        channel_id=ids["channel_id"],
    )

    assert summary["available"] is True
    assert "correlation_id" in summary["supported_filters"]
    assert "tool_call" in summary["supported_kinds"]
    assert summary["recent_count"] == 6
    assert summary["recent_counts"]["tool_call"] == 1
    assert summary["recent_counts"]["execution_receipt"] == 1
    assert len(summary["recent"]) == 5


async def test_get_agent_activity_log_tool_uses_current_bot_context(
    db_session,
    patched_async_sessions,
    agent_context,
):
    ids = await _seed_activity(db_session)
    agent_context(bot_id="agent", channel_id=ids["channel_id"], session_id=ids["session_id"])

    from app.tools.local.agent_capabilities import get_agent_activity_log

    payload = json.loads(await get_agent_activity_log(kind="tool_call", max_items=5))

    assert payload["context"]["bot_id"] == "agent"
    assert payload["context"]["channel_id"] == str(ids["channel_id"])
    assert payload["supported_kinds"][0] == "tool_call"
    assert [item["kind"] for item in payload["items"]] == ["tool_call"]
