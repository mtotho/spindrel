"""Integration tests for backend-owned slash commands."""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Session
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _create_channel_with_session(db_session: AsyncSession) -> tuple[str, str]:
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name="slash-test",
        bot_id="test-bot",
        active_session_id=session_id,
    ))
    db_session.add(Session(
        id=session_id,
        bot_id="test-bot",
        client_id=f"slash-{channel_id.hex[:8]}",
        channel_id=channel_id,
    ))
    await db_session.commit()
    return str(channel_id), str(session_id)


class TestSlashCommandExecute:
    async def test_context_command_for_channel_returns_normalized_summary(self, client, db_session):
        channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "context", "channel_id": channel_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "context"
        assert body["result_type"] == "context_summary"
        assert body["payload"]["scope_kind"] == "channel"
        assert body["payload"]["scope_id"] == channel_id
        assert body["payload"]["session_id"] == session_id
        assert isinstance(body["payload"]["top_categories"], list)
        assert isinstance(body["fallback_text"], str) and body["fallback_text"]

    async def test_context_command_for_session_returns_normalized_summary(self, client, db_session):
        _channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "context", "session_id": session_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "context"
        assert body["result_type"] == "context_summary"
        assert body["payload"]["scope_kind"] == "session"
        assert body["payload"]["scope_id"] == session_id
        assert body["payload"]["session_id"] == session_id
        assert body["payload"]["bot_id"] == "test-bot"
        assert isinstance(body["fallback_text"], str) and body["fallback_text"]

    async def test_stop_command_for_session_returns_side_effect(self, client, db_session):
        _channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "stop", "session_id": session_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "stop"
        assert body["result_type"] == "side_effect"
        assert body["payload"]["effect"] == "stop"
        assert body["payload"]["scope_kind"] == "session"
        assert body["payload"]["scope_id"] == session_id
        assert isinstance(body["fallback_text"], str) and body["fallback_text"]

    async def test_requires_exactly_one_scope(self, client):
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "context"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422
