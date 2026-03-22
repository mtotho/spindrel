"""Integration tests for /api/v1/sessions endpoints."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import Message, Session, Task
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# POST /api/v1/sessions
# ---------------------------------------------------------------------------

class TestCreateSession:
    async def test_create_session(self, client, db_session):
        resp = await client.post(
            "/api/v1/sessions",
            json={"bot_id": "test-bot", "client_id": "integration-client-1"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "session_id" in body
        # Verify it's a valid UUID
        uuid.UUID(body["session_id"])
        assert isinstance(body["created"], bool)

    async def test_create_session_with_dispatch_config(self, client, db_session):
        cfg = {"type": "webhook", "url": "https://example.com/hook"}
        resp = await client.post(
            "/api/v1/sessions",
            json={
                "bot_id": "test-bot",
                "client_id": "dispatch-client",
                "dispatch_config": cfg,
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        sid = uuid.UUID(body["session_id"])

        # Verify dispatch_config was stored
        session = await db_session.get(Session, sid)
        assert session is not None
        assert session.dispatch_config == cfg

    async def test_create_session_unknown_bot(self, client):
        resp = await client.post(
            "/api/v1/sessions",
            json={"bot_id": "nonexistent-bot", "client_id": "c1"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400
        assert "Unknown bot" in resp.json()["detail"]

    async def test_create_session_defaults_to_default_bot(self, client):
        resp = await client.post(
            "/api/v1/sessions",
            json={"client_id": "default-bot-client"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201

    async def test_create_session_different_clients_get_different_sessions(self, client):
        """Different client_ids produce different sessions."""
        r1 = await client.post(
            "/api/v1/sessions",
            json={"bot_id": "test-bot", "client_id": "client-a"},
            headers=AUTH_HEADERS,
        )
        r2 = await client.post(
            "/api/v1/sessions",
            json={"bot_id": "test-bot", "client_id": "client-b"},
            headers=AUTH_HEADERS,
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["session_id"] != r2.json()["session_id"]


# ---------------------------------------------------------------------------
# POST /api/v1/sessions/{id}/messages
# ---------------------------------------------------------------------------

class TestInjectMessage:
    async def _create_session(self, client) -> uuid.UUID:
        resp = await client.post(
            "/api/v1/sessions",
            json={"bot_id": "test-bot", "client_id": f"msg-client-{uuid.uuid4().hex[:8]}"},
            headers=AUTH_HEADERS,
        )
        return uuid.UUID(resp.json()["session_id"])

    async def test_inject_message(self, client, db_session):
        sid = await self._create_session(client)
        resp = await client.post(
            f"/api/v1/sessions/{sid}/messages",
            json={"content": "Hello from integration"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["session_id"] == str(sid)
        uuid.UUID(body["message_id"])
        assert body["task_id"] is None

    async def test_inject_message_with_run_agent(self, client, db_session):
        sid = await self._create_session(client)
        resp = await client.post(
            f"/api/v1/sessions/{sid}/messages",
            json={"content": "Run me", "run_agent": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["task_id"] is not None
        task_id = uuid.UUID(body["task_id"])

        # Verify task was created in DB
        task = await db_session.get(Task, task_id)
        assert task is not None
        assert task.status == "pending"
        assert task.prompt == "Run me"

    async def test_inject_message_with_source_metadata(self, client, db_session):
        sid = await self._create_session(client)
        resp = await client.post(
            f"/api/v1/sessions/{sid}/messages",
            json={"content": "From Gmail", "source": "gmail"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201

        # Verify metadata stored
        msg_id = uuid.UUID(resp.json()["message_id"])
        msg = await db_session.get(Message, msg_id)
        assert msg is not None
        assert msg.metadata_.get("source") == "gmail"

    async def test_inject_message_session_not_found(self, client):
        fake_id = uuid.uuid4()
        resp = await client.post(
            f"/api/v1/sessions/{fake_id}/messages",
            json={"content": "Oops"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404
        assert "Session not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/sessions/{id}/messages
# ---------------------------------------------------------------------------

class TestListMessages:
    async def _create_session_and_inject(self, client, n_messages=3) -> uuid.UUID:
        resp = await client.post(
            "/api/v1/sessions",
            json={"bot_id": "test-bot", "client_id": f"list-client-{uuid.uuid4().hex[:8]}"},
            headers=AUTH_HEADERS,
        )
        sid = uuid.UUID(resp.json()["session_id"])
        for i in range(n_messages):
            await client.post(
                f"/api/v1/sessions/{sid}/messages",
                json={"content": f"Message {i}"},
                headers=AUTH_HEADERS,
            )
        return sid

    async def test_list_messages(self, client):
        sid = await self._create_session_and_inject(client, 3)
        resp = await client.get(
            f"/api/v1/sessions/{sid}/messages",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) >= 3  # at least our 3 injected messages (+ system)
        # Messages should be in chronological order (oldest first)
        for m in messages:
            assert "id" in m
            assert "role" in m
            assert "created_at" in m

    async def test_list_messages_with_limit(self, client):
        sid = await self._create_session_and_inject(client, 5)
        resp = await client.get(
            f"/api/v1/sessions/{sid}/messages",
            params={"limit": 2},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) == 2

    async def test_list_messages_session_not_found(self, client):
        resp = await client.get(
            f"/api/v1/sessions/{uuid.uuid4()}/messages",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404
