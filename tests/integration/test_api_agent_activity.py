from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Channel, Session, ToolCall
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


async def test_agent_activity_api_filters_replay_items(client, db_session):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    db_session.add_all([
        Channel(id=channel_id, name="Activity API", bot_id="agent", client_id=f"activity-{uuid.uuid4().hex[:8]}"),
        Session(id=session_id, client_id=f"session-{uuid.uuid4().hex[:8]}", bot_id="agent", channel_id=channel_id),
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
            fallback="Retry with backoff.",
            correlation_id=correlation_id,
            created_at=datetime.now(timezone.utc),
        ),
    ])
    await db_session.commit()

    response = await client.get(
        "/api/v1/agent-activity",
        params={
            "bot_id": "agent",
            "channel_id": str(channel_id),
            "kind": "tool_call",
            "limit": "5",
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["kind"] == "tool_call"
    assert body[0]["status"] == "failed"
    assert body[0]["target"]["channel_id"] == str(channel_id)
    assert body[0]["trace"]["correlation_id"] == str(correlation_id)
    assert body[0]["error"]["error_kind"] == "rate_limited"
