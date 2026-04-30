from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Channel, ChannelHeartbeat, HeartbeatRun, Session, Task, ToolCall
from app.services.agent_status import build_agent_status_snapshot


pytestmark = pytest.mark.asyncio


async def _seed_context(db_session, *, bot_id: str = "agent"):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add_all([
        Channel(id=channel_id, name="Status", bot_id=bot_id, client_id=f"status-{uuid.uuid4().hex[:8]}"),
        Session(id=session_id, client_id=f"session-{uuid.uuid4().hex[:8]}", bot_id=bot_id, channel_id=channel_id),
    ])
    await db_session.flush()
    return channel_id, session_id


async def test_agent_status_without_context_is_unknown(db_session):
    snapshot = await build_agent_status_snapshot(db_session)

    assert snapshot["available"] is False
    assert snapshot["state"] == "unknown"
    assert snapshot["recommendation"] == "unknown"


async def test_agent_status_reports_scheduled_heartbeat(db_session):
    now = datetime.now(timezone.utc)
    channel_id, session_id = await _seed_context(db_session)
    db_session.add(ChannelHeartbeat(
        id=uuid.uuid4(),
        channel_id=channel_id,
        enabled=True,
        interval_minutes=30,
        next_run_at=now + timedelta(minutes=20),
        max_run_seconds=300,
    ))
    await db_session.commit()

    snapshot = await build_agent_status_snapshot(
        db_session,
        bot_id="agent",
        channel_id=channel_id,
        session_id=session_id,
        now=now,
    )

    assert snapshot["state"] == "scheduled"
    assert snapshot["recommendation"] == "wait_for_run"
    assert snapshot["heartbeat"]["configured"] is True
    assert snapshot["heartbeat"]["enabled"] is True
    assert snapshot["current"] is None


async def test_agent_status_flags_stale_running_task(db_session):
    now = datetime.now(timezone.utc)
    channel_id, session_id = await _seed_context(db_session)
    task_id = uuid.uuid4()
    db_session.add(Task(
        id=task_id,
        bot_id="agent",
        channel_id=channel_id,
        session_id=session_id,
        status="running",
        task_type="scheduled",
        title="Long running check",
        prompt="Check status",
        run_at=now - timedelta(minutes=10),
        max_run_seconds=60,
    ))
    await db_session.commit()

    snapshot = await build_agent_status_snapshot(
        db_session,
        bot_id="agent",
        channel_id=channel_id,
        session_id=session_id,
        now=now,
    )

    assert snapshot["state"] == "blocked"
    assert snapshot["recommendation"] == "review_stale_run"
    assert snapshot["current"]["type"] == "task"
    assert snapshot["current"]["stale"] is True
    assert snapshot["current"]["task_id"] == str(task_id)


async def test_agent_status_reports_failed_heartbeat_with_structured_error(db_session):
    now = datetime.now(timezone.utc)
    channel_id, session_id = await _seed_context(db_session)
    heartbeat_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    db_session.add(ChannelHeartbeat(
        id=heartbeat_id,
        channel_id=channel_id,
        enabled=True,
        interval_minutes=60,
        next_run_at=now + timedelta(hours=1),
        last_run_at=now - timedelta(minutes=2),
    ))
    db_session.add(HeartbeatRun(
        id=uuid.uuid4(),
        heartbeat_id=heartbeat_id,
        run_at=now - timedelta(minutes=3),
        completed_at=now - timedelta(minutes=2),
        status="failed",
        error="HTTP 429",
        correlation_id=correlation_id,
    ))
    db_session.add(ToolCall(
        session_id=session_id,
        bot_id="agent",
        tool_name="call_api",
        tool_type="local",
        status="error",
        error="HTTP 429",
        error_code="http_429",
        error_kind="rate_limited",
        retryable=True,
        correlation_id=correlation_id,
        created_at=now - timedelta(minutes=2),
    ))
    await db_session.commit()

    snapshot = await build_agent_status_snapshot(
        db_session,
        bot_id="agent",
        channel_id=channel_id,
        now=now,
    )

    assert snapshot["state"] == "error"
    assert snapshot["recommendation"] == "review_failure"
    assert snapshot["recent_runs"][0]["type"] == "heartbeat"
    assert snapshot["recent_runs"][0]["error"]["error_kind"] == "rate_limited"
    assert snapshot["recent_runs"][0]["error"]["retryable"] is True


async def test_get_agent_status_snapshot_tool_uses_current_context(
    db_session,
    patched_async_sessions,
    agent_context,
):
    now = datetime.now(timezone.utc)
    channel_id, session_id = await _seed_context(db_session)
    db_session.add(ChannelHeartbeat(
        id=uuid.uuid4(),
        channel_id=channel_id,
        enabled=True,
        interval_minutes=30,
        next_run_at=now + timedelta(minutes=30),
    ))
    await db_session.commit()
    agent_context(bot_id="agent", channel_id=channel_id, session_id=session_id)

    from app.tools.local.agent_capabilities import get_agent_status_snapshot

    payload = json.loads(await get_agent_status_snapshot(max_runs=5))

    assert payload["context"]["bot_id"] == "agent"
    assert payload["context"]["channel_id"] == str(channel_id)
    assert payload["agent_status"]["state"] == "scheduled"
