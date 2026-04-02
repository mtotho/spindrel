"""Integration tests for GET /channels/{id}/session-status and
user message persistence when a session is busy (queued path)."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# GET /channels/{id}/session-status
# ---------------------------------------------------------------------------


class TestSessionStatus:
    """Tests for the session-status polling endpoint."""

    async def _create_channel(self, client, bot_id="test-bot"):
        """Helper — create a channel and return its id + session_id."""
        resp = await client.post(
            "/api/v1/channels",
            json={"bot_id": bot_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        data = resp.json()
        return data["id"], data.get("active_session_id")

    async def test_session_status_idle(self, client):
        """Idle session returns processing=false, pending_tasks=0."""
        ch_id, _ = await self._create_channel(client)
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/session-status",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["processing"] is False
        assert body["pending_tasks"] == 0

    async def test_session_status_active_lock(self, client):
        """When the session lock is held, processing=true."""
        ch_id, _ = await self._create_channel(client)

        # Ensure channel has an active session
        resp = await client.post(
            f"/api/v1/channels/{ch_id}/ensure-session",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        # Simulate session lock being held
        from app.services import session_locks
        session_locks.acquire(session_id)
        try:
            resp = await client.get(
                f"/api/v1/channels/{ch_id}/session-status",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["processing"] is True
        finally:
            session_locks.release(session_id)

    async def test_session_status_with_pending_tasks(self, client, db_session):
        """Pending tasks for the session are counted."""
        ch_id, _ = await self._create_channel(client)
        resp = await client.post(
            f"/api/v1/channels/{ch_id}/ensure-session",
            headers=AUTH_HEADERS,
        )
        session_id = resp.json()["session_id"]

        # Create a pending task for this session
        from app.db.models import Task
        task = Task(
            bot_id="test-bot",
            client_id="web",
            session_id=uuid.UUID(session_id),
            channel_id=uuid.UUID(ch_id),
            prompt="test",
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(task)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/channels/{ch_id}/session-status",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pending_tasks"] == 1

    async def test_session_status_no_session(self, client):
        """Channel with no active session returns idle."""
        ch_id, _ = await self._create_channel(client)
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/session-status",
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
        # First, ensure we have a channel + session via a normal (unlocked) flow
        # We need to set up the channel first
        ch_resp = await client.post(
            "/api/v1/channels",
            json={"bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert ch_resp.status_code == 201
        ch_id = ch_resp.json()["id"]

        # Ensure session exists
        session_resp = await client.post(
            f"/api/v1/channels/{ch_id}/ensure-session",
            headers=AUTH_HEADERS,
        )
        session_id = session_resp.json()["session_id"]

        # Now send a message that will be queued (session lock returns False)
        resp = await client.post(
            "/chat/stream",
            json={"message": "Hello from queued path", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200

        # Parse the SSE response
        body = resp.text
        # Should contain a 'queued' event
        assert "queued" in body

        # Check that the user message was persisted in the database
        from app.db.models import Message
        from sqlalchemy import select

        messages = (await db_session.execute(
            select(Message)
            .where(
                Message.session_id == uuid.UUID(session_id),
                Message.role == "user",
            )
        )).scalars().all()

        user_messages = [m for m in messages if "Hello from queued path" in (m.content or "")]
        assert len(user_messages) == 1, f"Expected 1 persisted user message, got {len(user_messages)}"

    async def test_queued_response_contains_task_id(self, client):
        """The queued SSE event includes a task_id."""
        ch_resp = await client.post(
            "/api/v1/channels",
            json={"bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        ch_id = ch_resp.json()["id"]
        await client.post(
            f"/api/v1/channels/{ch_id}/ensure-session",
            headers=AUTH_HEADERS,
        )

        resp = await client.post(
            "/chat/stream",
            json={"message": "Test queued", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200

        # Parse SSE lines
        for line in resp.text.strip().split("\n"):
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if data.get("type") == "queued":
                    assert "task_id" in data
                    assert "session_id" in data
                    break
        else:
            pytest.fail("No 'queued' event found in SSE response")
