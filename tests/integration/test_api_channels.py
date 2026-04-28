"""Integration tests for /api/v1/channels endpoints."""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Channel, Message, Session, Task
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
# GET /api/v1/admin/channels/{id}/context-preview
# ---------------------------------------------------------------------------

class TestAdminContextPreview:
    """Context preview should return separate prompt blocks instead of one concatenated blob."""

    async def test_returns_separate_blocks(self, client, db_session):
        ch = await _create_channel(client)
        ch_id = ch["id"]

        resp = await client.get(
            f"/api/v1/admin/channels/{ch_id}/context-preview",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        blocks = resp.json()["blocks"]
        labels = [b["label"] for b in blocks]

        # The test bot has system_prompt="You are a test bot." and no memory,
        # so we expect its bot prompt as a separate preview block.
        assert "Bot System Prompt" in labels
        # Should NOT have the old monolithic "System Prompt" label
        assert "System Prompt" not in labels

    async def test_bot_system_prompt_content(self, client, db_session):
        ch = await _create_channel(client)
        ch_id = ch["id"]

        resp = await client.get(
            f"/api/v1/admin/channels/{ch_id}/context-preview",
            headers=AUTH_HEADERS,
        )
        blocks = resp.json()["blocks"]
        bot_block = next(b for b in blocks if b["label"] == "Bot System Prompt")
        assert bot_block["content"] == "You are a test bot."
        assert bot_block["role"] == "system"

    async def test_global_base_prompt_shown_when_set(self, client, db_session, monkeypatch):
        monkeypatch.setattr("app.config.settings.GLOBAL_BASE_PROMPT", "Be helpful always.")
        ch = await _create_channel(client)
        ch_id = ch["id"]

        resp = await client.get(
            f"/api/v1/admin/channels/{ch_id}/context-preview",
            headers=AUTH_HEADERS,
        )
        blocks = resp.json()["blocks"]
        labels = [b["label"] for b in blocks]
        assert "Global Base Prompt" in labels
        global_block = next(b for b in blocks if b["label"] == "Global Base Prompt")
        assert global_block["content"] == "Be helpful always."

    async def test_no_global_base_prompt_when_empty(self, client, db_session, monkeypatch):
        monkeypatch.setattr("app.config.settings.GLOBAL_BASE_PROMPT", "")
        ch = await _create_channel(client)
        ch_id = ch["id"]

        resp = await client.get(
            f"/api/v1/admin/channels/{ch_id}/context-preview",
            headers=AUTH_HEADERS,
        )
        blocks = resp.json()["blocks"]
        labels = [b["label"] for b in blocks]
        assert "Global Base Prompt" not in labels

    async def test_includes_pinned_widget_context_snapshot(self, client, db_session):
        ch = await _create_channel(client)
        ch_id = ch["id"]

        resp = await client.get(
            f"/api/v1/admin/channels/{ch_id}/context-preview",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "pinned_widget_context" in body
        assert body["pinned_widget_context"] == {
            "enabled": True,
            "decision": "skipped_empty",
        }
        labels = [b["label"] for b in body["blocks"]]
        assert "Pinned Widget Context" not in labels

    async def test_uses_runtime_context_preview_assembly(self, client, monkeypatch):
        ch = await _create_channel(client)
        ch_id = ch["id"]
        called = {}

        async def fake_assemble_for_preview(channel_id, *, user_message=""):
            called["channel_id"] = str(channel_id)
            called["user_message"] = user_message

            class FakeBudget:
                total_tokens = 1000
                reserve_tokens = 100
                used_tokens = 250
                remaining_tokens = 650

            class FakeAssembly:
                inject_decisions = {"pinned_widgets": "skipped_empty"}
                context_profile = "chat"
                context_policy = {}

            return type("Preview", (), {
                "messages": [{"role": "system", "content": "Assembled preview only."}],
                "inject_chars": {},
                "assembly": FakeAssembly(),
                "budget": FakeBudget(),
                "bot_id": "test-bot",
                "model": "test/model",
            })()

        monkeypatch.setattr(
            "app.routers.api_v1_admin.channels.assemble_for_preview",
            fake_assemble_for_preview,
        )

        resp = await client.get(
            f"/api/v1/admin/channels/{ch_id}/context-preview",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert called == {"channel_id": ch_id, "user_message": ""}
        assert resp.json()["blocks"] == [
            {
                "label": "Bot System Prompt",
                "role": "system",
                "content": "Assembled preview only.",
            }
        ]
