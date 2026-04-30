from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import (
    Channel,
    WorkspaceAttentionItem,
    WorkspaceMission,
    WorkspaceMissionAssignment,
    WorkspaceMissionUpdate,
)
from app.services.agent_work_snapshot import build_agent_work_snapshot


pytestmark = pytest.mark.asyncio


async def _channel(db_session, name: str = "ops") -> Channel:
    channel = Channel(
        id=uuid.uuid4(),
        name=name,
        bot_id="agent",
        client_id=f"test-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(channel)
    await db_session.flush()
    return channel


async def _mission(
    db_session,
    *,
    title: str,
    bot_id: str = "agent",
    status: str = "active",
    assignment_status: str = "active",
    channel: Channel | None = None,
    next_run_at: datetime | None = None,
    last_update_at: datetime | None = None,
) -> WorkspaceMission:
    mission = WorkspaceMission(
        title=title,
        directive=f"Directive for {title}",
        status=status,
        scope="channel" if channel else "workspace",
        channel_id=channel.id if channel else None,
        next_run_at=next_run_at,
        last_update_at=last_update_at,
    )
    db_session.add(mission)
    await db_session.flush()
    db_session.add(WorkspaceMissionAssignment(
        mission_id=mission.id,
        bot_id=bot_id,
        role="owner",
        status=assignment_status,
        target_channel_id=channel.id if channel else None,
    ))
    update_kwargs = {}
    if last_update_at is not None:
        update_kwargs["created_at"] = last_update_at
    db_session.add(WorkspaceMissionUpdate(
        mission_id=mission.id,
        bot_id=bot_id,
        kind="progress",
        summary=f"Latest update for {title}",
        next_actions=[f"Continue {title}"],
        **update_kwargs,
    ))
    await db_session.commit()
    return mission


async def _attention(
    db_session,
    *,
    title: str,
    severity: str,
    channel: Channel,
    bot_id: str = "agent",
    status: str = "open",
    assignment_status: str | None = "assigned",
    assigned_at: datetime | None = None,
) -> WorkspaceAttentionItem:
    item = WorkspaceAttentionItem(
        source_type="system",
        source_id="test",
        channel_id=channel.id,
        target_kind="channel",
        target_id=str(channel.id),
        dedupe_key=f"test:{title}",
        severity=severity,
        title=title,
        message=f"Investigate {title}",
        next_steps=[f"Check {title}"],
        requires_response=True,
        status=status,
        assigned_bot_id=bot_id if assignment_status else None,
        assignment_status=assignment_status,
        assignment_mode="run_now" if assignment_status else None,
        assignment_instructions=f"Instructions for {title}" if assignment_status else None,
        assigned_at=assigned_at,
        last_seen_at=assigned_at,
    )
    db_session.add(item)
    await db_session.commit()
    return item


async def test_work_snapshot_without_assigned_work_is_idle(db_session):
    snapshot = await build_agent_work_snapshot(db_session, bot_id="agent")

    assert snapshot["available"] is True
    assert snapshot["summary"] == {
        "assigned_mission_count": 0,
        "assigned_attention_count": 0,
        "has_current_work": False,
        "recommended_next_action": "idle",
    }
    assert snapshot["missions"] == []
    assert snapshot["attention"] == []


async def test_work_snapshot_lists_assigned_missions_with_latest_update(db_session):
    now = datetime.now(timezone.utc)
    channel = await _channel(db_session, "triage")
    late = await _mission(
        db_session,
        title="Later mission",
        channel=channel,
        next_run_at=now + timedelta(hours=4),
        last_update_at=now - timedelta(minutes=5),
    )
    early = await _mission(
        db_session,
        title="Earlier mission",
        channel=channel,
        next_run_at=now + timedelta(hours=1),
        last_update_at=now - timedelta(minutes=1),
    )
    await _mission(db_session, title="Other bot mission", bot_id="other", next_run_at=now)
    await _mission(db_session, title="Completed mission", status="completed", next_run_at=now)
    await _mission(db_session, title="Paused assignment", assignment_status="paused", next_run_at=now)

    snapshot = await build_agent_work_snapshot(db_session, bot_id="agent", max_items=10)

    assert snapshot["summary"]["assigned_mission_count"] == 2
    assert snapshot["summary"]["recommended_next_action"] == "advance_mission"
    assert [mission["id"] for mission in snapshot["missions"]] == [str(early.id), str(late.id)]
    assert snapshot["missions"][0]["channel_name"] == "triage"
    assert snapshot["missions"][0]["latest_update"]["summary"] == "Latest update for Earlier mission"
    assert snapshot["missions"][0]["latest_update"]["next_actions"] == ["Continue Earlier mission"]


async def test_work_snapshot_lists_attention_by_severity_then_age(db_session):
    now = datetime.now(timezone.utc)
    channel = await _channel(db_session)
    warning = await _attention(
        db_session,
        title="Warning item",
        severity="warning",
        channel=channel,
        assigned_at=now - timedelta(hours=2),
    )
    critical = await _attention(
        db_session,
        title="Critical item",
        severity="critical",
        channel=channel,
        assigned_at=now - timedelta(minutes=5),
    )
    await _attention(
        db_session,
        title="Reported item",
        severity="critical",
        channel=channel,
        assignment_status="reported",
        assigned_at=now - timedelta(hours=3),
    )
    await _attention(
        db_session,
        title="Resolved item",
        severity="critical",
        channel=channel,
        status="resolved",
        assigned_at=now - timedelta(hours=4),
    )
    await _attention(
        db_session,
        title="Unassigned item",
        severity="critical",
        channel=channel,
        assignment_status=None,
        assigned_at=now - timedelta(hours=5),
    )

    snapshot = await build_agent_work_snapshot(db_session, bot_id="agent", max_items=10)

    assert snapshot["summary"]["assigned_attention_count"] == 2
    assert snapshot["summary"]["recommended_next_action"] == "review_attention"
    assert [item["id"] for item in snapshot["attention"]] == [str(critical.id), str(warning.id)]
    assert snapshot["attention"][0]["assignment_instructions"] == "Instructions for Critical item"
    assert snapshot["attention"][0]["next_steps"] == ["Check Critical item"]
