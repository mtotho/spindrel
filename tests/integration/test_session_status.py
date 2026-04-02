"""Integration tests for GET /channels/{id}/session-status and
user message persistence when a session is busy (queued path)."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.db.models import Channel, Message, Session, Task
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _create_channel_with_session(db_session, bot_id="test-bot"):
    """Helper — create a channel with an active session directly in the DB."""
    client_id = f"test:{uuid.uuid4().hex[:8]}"
    session_id = uuid.uuid4()
    session = Session(id=session_id, bot_id=bot_id, client_id=client_id)
    db_session.add(session)
    await db_session.flush()

    channel_id = uuid.uuid4()
    channel = Channel(
        id=channel_id,
        name=f"test-channel-{channel_id.hex[:8]}",
        bot_id=bot_id,
        client_id=client_id,
        active_session_id=session.id,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return channel, session


# ---------------------------------------------------------------------------
# GET /channels/{id}/session-status
# ---------------------------------------------------------------------------


class TestSessionStatus:
    """Tests for the session-status polling endpoint."""

    async def test_session_status_idle(self, client, db_session):
        """Idle session returns processing=false, pending_tasks=0."""
        channel, _ = await _create_channel_with_session(db_session)
        resp = await client.get(
            f"/api/v1/channels/{channel.id}/session-status",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["processing"] is False
        assert body["pending_tasks"] == 0

    async def test_session_status_active_lock(self, client, db_session):
        """When the session lock is held, processing=true."""
        channel, session = await _create_channel_with_session(db_session)

        from app.services import session_locks
        session_locks.acquire(session.id)
        try:
            resp = await client.get(
                f"/api/v1/channels/{channel.id}/session-status",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["processing"] is True
        finally:
            session_locks.release(session.id)

    async def test_session_status_with_pending_tasks(self, client, db_session):
        """Pending tasks for the session are counted."""
        channel, session = await _create_channel_with_session(db_session)

        task = Task(
            bot_id="test-bot",
            client_id="web",
            session_id=session.id,
            channel_id=channel.id,
            prompt="test",
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/channels/{channel.id}/session-status",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pending_tasks"] == 1

    async def test_session_status_running_task_counted(self, client, db_session):
        """Running tasks are also counted."""
        channel, session = await _create_channel_with_session(db_session)

        task = Task(
            bot_id="test-bot",
            client_id="web",
            session_id=session.id,
            channel_id=channel.id,
            prompt="test",
            status="running",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/channels/{channel.id}/session-status",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pending_tasks"] == 1

    async def test_session_status_completed_task_not_counted(self, client, db_session):
        """Completed tasks are not counted."""
        channel, session = await _create_channel_with_session(db_session)

        task = Task(
            bot_id="test-bot",
            client_id="web",
            session_id=session.id,
            channel_id=channel.id,
            prompt="test",
            status="complete",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/channels/{channel.id}/session-status",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pending_tasks"] == 0

    async def test_session_status_no_session(self, client, db_session):
        """Channel with no active session returns idle."""
        cid = uuid.uuid4()
        channel = Channel(id=cid, name=f"test-{cid.hex[:8]}", bot_id="test-bot", client_id=f"test:{uuid.uuid4().hex[:8]}")
        db_session.add(channel)
        await db_session.commit()
        await db_session.refresh(channel)

        resp = await client.get(
            f"/api/v1/channels/{channel.id}/session-status",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["processing"] is False
        assert body["pending_tasks"] == 0

    async def test_session_status_not_found(self, client):
        """Non-existent channel returns 404."""
        fake_id = uuid.uuid4()
        resp = await client.get(
            f"/api/v1/channels/{fake_id}/session-status",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# User message persistence when session is busy
# ---------------------------------------------------------------------------


class TestQueuedMessagePersistence:
    """Tests that user messages are persisted to the session when queued."""

    @pytest.fixture(autouse=True)
    def _mock_session_locks(self):
        """Mock session locks so acquire returns False (session busy)."""
        with patch("app.routers.chat.session_locks") as mock:
            mock.acquire.return_value = False
            mock.is_active.return_value = True
            yield mock

    async def test_queued_message_persists_user_message(self, client, db_session):
        """When a message is queued, the user message is also persisted to the session."""
        channel, session = await _create_channel_with_session(db_session)

        resp = await client.post(
            "/chat/stream",
            json={
                "message": "Hello from queued path",
                "bot_id": "test-bot",
                "client_id": channel.client_id,
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert "queued" in resp.text

        # Check that the user message was persisted
        from sqlalchemy import select
        messages = (await db_session.execute(
            select(Message).where(
                Message.session_id == session.id,
                Message.role == "user",
            )
        )).scalars().all()

        user_messages = [m for m in messages if "Hello from queued path" in (m.content or "")]
        assert len(user_messages) == 1

    async def test_queued_response_contains_task_id(self, client, db_session):
        """The queued SSE event includes a task_id."""
        channel, _ = await _create_channel_with_session(db_session)

        resp = await client.post(
            "/chat/stream",
            json={
                "message": "Test queued",
                "bot_id": "test-bot",
                "client_id": channel.client_id,
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200

        for line in resp.text.strip().split("\n"):
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if data.get("type") == "queued":
                    assert "task_id" in data
                    assert "session_id" in data
                    break
        else:
            pytest.fail("No 'queued' event found in SSE response")
