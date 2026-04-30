from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Channel, ChannelHeartbeat
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


async def test_agent_status_api_returns_scheduled_snapshot(client, db_session):
    now = datetime.now(timezone.utc)
    channel_id = uuid.uuid4()
    heartbeat_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name="Status API",
        bot_id="agent",
        client_id=f"status-api-{uuid.uuid4().hex[:8]}",
    ))
    db_session.add(ChannelHeartbeat(
        id=heartbeat_id,
        channel_id=channel_id,
        enabled=True,
        interval_minutes=30,
        next_run_at=now + timedelta(minutes=10),
    ))
    await db_session.commit()

    response = await client.get(
        "/api/v1/agent-status",
        params={
            "bot_id": "agent",
            "channel_id": str(channel_id),
            "limit": "5",
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "agent-status.v1"
    assert body["state"] == "scheduled"
    assert body["recommendation"] == "wait_for_run"
    assert body["heartbeat"]["heartbeat_id"] == str(heartbeat_id)
