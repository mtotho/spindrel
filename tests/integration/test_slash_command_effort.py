"""Integration tests for the `/effort` slash command.

Covers persistence (channel.config), enum validation, and the "off" clear
path. Uses the same real-DB harness as the other slash command tests — no
mocks.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Session
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _create_channel(db_session: AsyncSession) -> str:
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name="effort-test",
        bot_id="test-bot",
        active_session_id=session_id,
    ))
    db_session.add(Session(
        id=session_id,
        bot_id="test-bot",
        client_id=f"effort-{channel_id.hex[:8]}",
        channel_id=channel_id,
    ))
    await db_session.commit()
    return str(channel_id)


class TestEffortCommand:
    async def test_high_effort_persists_to_channel_config(self, client, db_session):
        channel_id = await _create_channel(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "effort", "channel_id": channel_id, "args": ["high"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "effort"
        assert body["result_type"] == "side_effect"
        assert body["payload"]["effect"] == "effort"
        assert "high" in body["fallback_text"]

        # Smoking gun: the setting must actually be persisted, not just echoed
        await db_session.commit()  # drop any cached state from our session
        refreshed = await db_session.get(Channel, uuid.UUID(channel_id))
        await db_session.refresh(refreshed)
        assert refreshed.config.get("effort_override") == "high"

    async def test_off_clears_the_override(self, client, db_session):
        channel_id = await _create_channel(db_session)
        # Set it first
        await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "effort", "channel_id": channel_id, "args": ["medium"]},
            headers=AUTH_HEADERS,
        )
        # Then clear it
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "effort", "channel_id": channel_id, "args": ["off"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["payload"]["effect"] == "effort"
        assert "cleared" in body["fallback_text"].lower() or "default" in body["fallback_text"].lower()

        # Smoking gun: the key must be absent from config, not just set to "off"
        await db_session.commit()
        refreshed = await db_session.get(Channel, uuid.UUID(channel_id))
        await db_session.refresh(refreshed)
        assert "effort_override" not in (refreshed.config or {})

    async def test_invalid_level_returns_400(self, client, db_session):
        channel_id = await _create_channel(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "effort", "channel_id": channel_id, "args": ["turbo"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400, resp.text
        assert "turbo" in resp.text or "effort" in resp.text.lower()

    async def test_missing_argument_returns_400(self, client, db_session):
        channel_id = await _create_channel(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "effort", "channel_id": channel_id, "args": []},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400, resp.text

    async def test_registry_exposes_effort_as_arg_taking(self, client):
        resp = await client.get("/api/v1/slash-commands", headers=AUTH_HEADERS)
        assert resp.status_code == 200, resp.text
        commands = resp.json()["commands"]
        effort = next((c for c in commands if c["id"] == "effort"), None)
        assert effort is not None, "effort missing from canonical registry"
        assert effort["accepts_args"] is True
        assert effort["arg_enum"] == ["off", "low", "medium", "high"]

    async def test_registry_flags_local_only_commands(self, client):
        resp = await client.get("/api/v1/slash-commands", headers=AUTH_HEADERS)
        assert resp.status_code == 200, resp.text
        commands = resp.json()["commands"]
        by_id = {c["id"]: c for c in commands}
        assert by_id["clear"]["local_only"] is True
        assert by_id["scratch"]["local_only"] is True
        assert by_id["effort"]["local_only"] is False
