"""Integration tests for GET /api/v1/channels/{channel_id}/messages/search.

Requires PostgreSQL (ILIKE not supported on SQLite) — tests are skipped on SQLite.
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


def _is_sqlite(db_session) -> bool:
    return "sqlite" in str(db_session.bind.url)


@pytest_asyncio.fixture
async def channel_with_messages(db_session):
    """Create a channel, session, and some messages for search tests.

    Skips if backend is SQLite (ILIKE unsupported).
    """
    if _is_sqlite(db_session):
        pytest.skip("ILIKE not supported on SQLite")

    from app.db.models import Channel, Session, Message

    ch_id = uuid.uuid4()
    sess_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    channel = Channel(
        id=ch_id,
        name="search-test",
        bot_id="test-bot",
        active_session_id=sess_id,
    )
    session = Session(
        id=sess_id,
        client_id="test-client",
        bot_id="test-bot",
        channel_id=ch_id,
    )
    db_session.add(channel)
    db_session.add(session)
    await db_session.flush()

    messages = [
        Message(id=uuid.uuid4(), session_id=sess_id, role="user", content="Deploy to production today"),
        Message(id=uuid.uuid4(), session_id=sess_id, role="assistant", content="Deployment initiated successfully"),
        Message(id=uuid.uuid4(), session_id=sess_id, role="user", content="Check the logs for errors"),
        Message(id=uuid.uuid4(), session_id=sess_id, role="tool", content="tool result data"),
        Message(id=uuid.uuid4(), session_id=sess_id, role="system", content="system prompt"),
    ]
    for m in messages:
        db_session.add(m)
    await db_session.commit()

    return ch_id, sess_id, messages


class TestSearchEndpoint:
    async def test_search_endpoint_basic(self, client, channel_with_messages):
        ch_id, _, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/messages/search",
            params={"q": "deploy"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        for msg in data:
            assert "deploy" in msg["content_preview"].lower()

    async def test_search_endpoint_empty(self, client, channel_with_messages):
        ch_id, _, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/messages/search",
            params={"q": "zzz_nonexistent_zzz"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_search_endpoint_bad_channel(self, client):
        fake_id = uuid.uuid4()
        resp = await client.get(
            f"/api/v1/channels/{fake_id}/messages/search",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_search_endpoint_pagination(self, client, channel_with_messages):
        ch_id, _, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/messages/search",
            params={"limit": 1, "offset": 0},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        page1 = resp.json()
        assert len(page1) <= 1

        resp2 = await client.get(
            f"/api/v1/channels/{ch_id}/messages/search",
            params={"limit": 1, "offset": 1},
            headers=AUTH_HEADERS,
        )
        assert resp2.status_code == 200
        page2 = resp2.json()
        if page1 and page2:
            assert page1[0]["id"] != page2[0]["id"]

    async def test_search_role_filter(self, client, channel_with_messages):
        ch_id, _, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/messages/search",
            params={"role": "user"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        for msg in resp.json():
            assert msg["role"] == "user"

    async def test_search_excludes_tool_system_by_default(self, client, channel_with_messages):
        ch_id, _, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/messages/search",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        for msg in resp.json():
            assert msg["role"] in ("user", "assistant")
