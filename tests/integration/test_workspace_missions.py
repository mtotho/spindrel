from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import ChannelHeartbeat, Task, WorkspaceMission, WorkspaceMissionAssignment, WorkspaceMissionUpdate
from app.domain.errors import ValidationError
from app.services.workspace_missions import report_mission_progress
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _create_channel(client, **overrides) -> dict:
    payload = {
        "bot_id": "test-bot",
        "client_id": f"mission-{uuid.uuid4().hex[:8]}",
        **overrides,
    }
    resp = await client.post("/api/v1/channels", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_workspace_mission_uses_task_backbone(client, db_session):
    resp = await client.post(
        "/api/v1/workspace/missions",
        headers=AUTH_HEADERS,
        json={
            "title": "Triage GitHub issues",
            "directive": "Review open issues and propose a first useful pass.",
            "scope": "workspace",
            "bot_id": "test-bot",
            "recurrence": "+2h",
            "model_override": "openai/gpt-test",
            "model_provider_id_override": "provider-test",
            "harness_effort": "high",
        },
    )
    assert resp.status_code == 201, resp.text
    mission_payload = resp.json()["mission"]

    mission = await db_session.get(WorkspaceMission, uuid.UUID(mission_payload["id"]))
    assert mission is not None
    assert mission.scope == "workspace"
    assert mission.recurrence == "+2h"
    assert mission.kickoff_task_id is not None
    assert mission.schedule_task_id is not None

    kickoff = await db_session.get(Task, mission.kickoff_task_id)
    schedule = await db_session.get(Task, mission.schedule_task_id)
    assert kickoff is not None
    assert schedule is not None
    assert kickoff.task_type == "mission_kickoff"
    assert kickoff.callback_config["mission_id"] == str(mission.id)
    assert kickoff.execution_config["model_override"] == "openai/gpt-test"
    assert kickoff.execution_config["model_provider_id_override"] == "provider-test"
    assert kickoff.execution_config["harness_effort"] == "high"
    assert schedule.status == "active"
    assert schedule.recurrence == "+2h"
    assert schedule.task_type == "mission_tick"

    assignments = list((await db_session.execute(
        select(WorkspaceMissionAssignment).where(WorkspaceMissionAssignment.mission_id == mission.id)
    )).scalars().all())
    assert [(row.bot_id, row.status) for row in assignments] == [("test-bot", "active")]


async def test_channel_mission_does_not_mutate_channel_heartbeat(client, db_session):
    channel = await _create_channel(client)
    channel_id = uuid.UUID(channel["id"])
    heartbeat = ChannelHeartbeat(
        channel_id=channel_id,
        enabled=True,
        interval_minutes=15,
        prompt="Existing heartbeat prompt",
        next_run_at=datetime.now(timezone.utc),
    )
    db_session.add(heartbeat)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/workspace/missions",
        headers=AUTH_HEADERS,
        json={
            "title": "Watch Jellyfin",
            "directive": "Keep an eye on media-service health and report meaningful changes.",
            "scope": "channel",
            "channel_id": str(channel_id),
            "recurrence": "+4h",
        },
    )
    assert resp.status_code == 201, resp.text

    await db_session.refresh(heartbeat)
    assert heartbeat.enabled is True
    assert heartbeat.interval_minutes == 15
    assert heartbeat.prompt == "Existing heartbeat prompt"

    mission = await db_session.get(WorkspaceMission, uuid.UUID(resp.json()["mission"]["id"]))
    assert mission is not None
    schedule = await db_session.get(Task, mission.schedule_task_id)
    assert schedule is not None
    assert schedule.channel_id == channel_id
    assert schedule.recurrence == "+4h"


async def test_report_mission_progress_requires_assigned_bot(client, db_session):
    resp = await client.post(
        "/api/v1/workspace/missions",
        headers=AUTH_HEADERS,
        json={
            "title": "Organize workspace",
            "directive": "Find stale project notes and suggest cleanup.",
            "scope": "workspace",
            "bot_id": "test-bot",
            "interval_kind": "manual",
            "recurrence": None,
        },
    )
    assert resp.status_code == 201, resp.text
    mission_id = uuid.UUID(resp.json()["mission"]["id"])

    update = await report_mission_progress(
        db_session,
        mission_id,
        bot_id="test-bot",
        summary="Found one stale track and one missing follow-up.",
        next_actions=["Open the stale track", "Ask whether to archive"],
    )
    assert update.summary.startswith("Found one stale")
    rows = list((await db_session.execute(
        select(WorkspaceMissionUpdate).where(WorkspaceMissionUpdate.mission_id == mission_id)
    )).scalars().all())
    assert any(row.kind == "progress" and row.bot_id == "test-bot" for row in rows)

    with pytest.raises(ValidationError):
        await report_mission_progress(
            db_session,
            mission_id,
            bot_id="other-bot",
            summary="Nope",
        )
