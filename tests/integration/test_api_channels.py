"""Integration tests for /api/v1/channels endpoints."""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import BotKnowledge, Channel, KnowledgeAccess, Message, Session, Task
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_channel(client, **overrides) -> dict:
    payload = {
        "bot_id": "test-bot",
        "client_id": f"ch-client-{uuid.uuid4().hex[:8]}",
        **overrides,
    }
    resp = await client.post("/api/v1/channels", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/v1/channels
# ---------------------------------------------------------------------------

class TestCreateChannel:
    async def test_create_channel(self, client, db_session):
        resp = await client.post(
            "/api/v1/channels",
            json={"bot_id": "test-bot", "client_id": "new-channel-client"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["bot_id"] == "test-bot"
        assert body["client_id"] == "new-channel-client"
        assert body["active_session_id"] is not None
        assert body["require_mention"] is True
        assert body["passive_memory"] is True
        uuid.UUID(body["id"])

    async def test_create_channel_with_name(self, client):
        body = await _create_channel(client, name="My Channel")
        assert body["name"] == "My Channel"

    async def test_create_channel_with_integration(self, client):
        body = await _create_channel(client, integration="slack")
        assert body["integration"] == "slack"

    async def test_create_channel_unknown_bot(self, client):
        resp = await client.post(
            "/api/v1/channels",
            json={"bot_id": "nonexistent", "client_id": "bad-bot-client"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400
        assert "Unknown bot" in resp.json()["detail"]

    async def test_create_channel_idempotent(self, client):
        """Same client_id returns the same channel."""
        cid = f"idem-{uuid.uuid4().hex[:8]}"
        r1 = await _create_channel(client, client_id=cid)
        r2 = await _create_channel(client, client_id=cid)
        assert r1["id"] == r2["id"]


# ---------------------------------------------------------------------------
# GET /api/v1/channels
# ---------------------------------------------------------------------------

class TestListChannels:
    async def test_list_channels_empty(self, client):
        resp = await client.get("/api/v1/channels", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_channels_with_data(self, client):
        await _create_channel(client)
        await _create_channel(client)
        resp = await client.get("/api/v1/channels", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    async def test_filter_by_bot_id(self, client):
        await _create_channel(client, bot_id="test-bot")
        resp = await client.get(
            "/api/v1/channels",
            params={"bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        for ch in resp.json():
            assert ch["bot_id"] == "test-bot"

    async def test_filter_by_integration(self, client):
        await _create_channel(client, integration="discord")
        resp = await client.get(
            "/api/v1/channels",
            params={"integration": "discord"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        for ch in resp.json():
            assert ch["integration"] == "discord"


# ---------------------------------------------------------------------------
# GET /api/v1/channels/{id}
# ---------------------------------------------------------------------------

class TestGetChannel:
    async def test_get_channel(self, client):
        created = await _create_channel(client)
        ch_id = created["id"]

        resp = await client.get(f"/api/v1/channels/{ch_id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["id"] == ch_id

    async def test_get_channel_not_found(self, client):
        resp = await client.get(
            f"/api/v1/channels/{uuid.uuid4()}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/v1/channels/{id}
# ---------------------------------------------------------------------------

class TestUpdateChannel:
    async def test_update_name(self, client):
        created = await _create_channel(client)
        ch_id = created["id"]

        resp = await client.put(
            f"/api/v1/channels/{ch_id}",
            json={"name": "Updated Name"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    async def test_update_bot_id(self, client):
        created = await _create_channel(client, bot_id="default")
        ch_id = created["id"]

        resp = await client.put(
            f"/api/v1/channels/{ch_id}",
            json={"bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["bot_id"] == "test-bot"

    async def test_update_require_mention(self, client):
        created = await _create_channel(client)
        ch_id = created["id"]

        resp = await client.put(
            f"/api/v1/channels/{ch_id}",
            json={"require_mention": False},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["require_mention"] is False

    async def test_update_passive_memory(self, client):
        created = await _create_channel(client)
        ch_id = created["id"]

        resp = await client.put(
            f"/api/v1/channels/{ch_id}",
            json={"passive_memory": False},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["passive_memory"] is False

    async def test_update_unknown_bot(self, client):
        created = await _create_channel(client)
        ch_id = created["id"]

        resp = await client.put(
            f"/api/v1/channels/{ch_id}",
            json={"bot_id": "nonexistent"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400

    async def test_update_not_found(self, client):
        resp = await client.put(
            f"/api/v1/channels/{uuid.uuid4()}",
            json={"name": "Nope"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/channels/{id}/messages
# ---------------------------------------------------------------------------

class TestInjectChannelMessage:
    async def test_inject_message(self, client, db_session):
        created = await _create_channel(client)
        ch_id = created["id"]

        resp = await client.post(
            f"/api/v1/channels/{ch_id}/messages",
            json={"content": "Hello channel"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["session_id"] is not None
        uuid.UUID(body["message_id"])
        assert body["task_id"] is None

    async def test_inject_message_with_run_agent(self, client, db_session):
        created = await _create_channel(client)
        ch_id = created["id"]

        resp = await client.post(
            f"/api/v1/channels/{ch_id}/messages",
            json={"content": "Process this", "run_agent": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["task_id"] is not None

        task = await db_session.get(Task, uuid.UUID(body["task_id"]))
        assert task is not None
        assert task.status == "pending"

    async def test_inject_message_channel_not_found(self, client):
        resp = await client.post(
            f"/api/v1/channels/{uuid.uuid4()}/messages",
            json={"content": "Oops"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/channels/{id}/reset
# ---------------------------------------------------------------------------

class TestResetChannel:
    async def test_reset_channel(self, client):
        created = await _create_channel(client)
        ch_id = created["id"]
        old_session_id = created["active_session_id"]

        resp = await client.post(
            f"/api/v1/channels/{ch_id}/reset",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["channel_id"] == ch_id
        assert body["new_session_id"] != old_session_id
        assert body["previous_session_id"] == old_session_id

    async def test_reset_channel_not_found(self, client):
        resp = await client.post(
            f"/api/v1/channels/{uuid.uuid4()}/reset",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/channels/{id}/knowledge
# ---------------------------------------------------------------------------

class TestListChannelKnowledge:
    async def test_empty_knowledge(self, client):
        created = await _create_channel(client)
        ch_id = created["id"]

        resp = await client.get(
            f"/api/v1/channels/{ch_id}/knowledge",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_channel_not_found(self, client):
        resp = await client.get(
            f"/api/v1/channels/{uuid.uuid4()}/knowledge",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_knowledge_with_entries(self, client, db_session):
        created = await _create_channel(client)
        ch_id = created["id"]

        # Create a knowledge entry (no embedding needed for access listing)
        bk = BotKnowledge(
            id=uuid.uuid4(),
            name="test-knowledge",
            content="Some knowledge content",
            bot_id="test-bot",
            created_by_bot="test-bot",
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(bk)
        await db_session.flush()

        # Create access entry scoped to this channel
        ka = KnowledgeAccess(
            id=uuid.uuid4(),
            knowledge_id=bk.id,
            scope_type="channel",
            scope_key=str(ch_id),
            mode="rag",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(ka)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/channels/{ch_id}/knowledge",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["knowledge_name"] == "test-knowledge"
        assert entries[0]["scope_type"] == "channel"
        assert entries[0]["mode"] == "rag"


# ---------------------------------------------------------------------------
# GET /api/v1/admin/channels/{id}/knowledge
# ---------------------------------------------------------------------------

class TestAdminListChannelKnowledge:
    async def test_empty_knowledge(self, client):
        created = await _create_channel(client)
        ch_id = created["id"]

        resp = await client.get(
            f"/api/v1/admin/channels/{ch_id}/knowledge",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_channel_not_found(self, client):
        resp = await client.get(
            f"/api/v1/admin/channels/{uuid.uuid4()}/knowledge",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_knowledge_with_entries(self, client, db_session):
        created = await _create_channel(client)
        ch_id = created["id"]

        bk = BotKnowledge(
            id=uuid.uuid4(),
            name="admin-test-knowledge",
            content="Some detailed knowledge content here",
            bot_id="test-bot",
            created_by_bot="test-bot",
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(bk)
        await db_session.flush()

        ka = KnowledgeAccess(
            id=uuid.uuid4(),
            knowledge_id=bk.id,
            scope_type="channel",
            scope_key=str(ch_id),
            mode="pinned",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(ka)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/admin/channels/{ch_id}/knowledge",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["title"] == "admin-test-knowledge"
        assert entries[0]["mode"] == "pinned"
        assert entries[0]["bot_id"] == "test-bot"
        assert entries[0]["content_length"] == len("Some detailed knowledge content here")
        assert entries[0]["content"] == "Some detailed knowledge content here"
        assert "updated_at" in entries[0]
