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

    from app.db.models import Channel, ConversationSection, Session, Message

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

    old_sess_id = uuid.uuid4()
    old_session = Session(
        id=old_sess_id,
        client_id="test-client-old",
        bot_id="test-bot",
        channel_id=ch_id,
        title="Old database notes",
    )
    db_session.add(old_session)
    await db_session.flush()
    db_session.add(Message(
        id=uuid.uuid4(),
        session_id=old_sess_id,
        role="user",
        content="The rollback checklist mentions the blue-green verifier",
    ))
    db_session.add(ConversationSection(
        id=uuid.uuid4(),
        channel_id=ch_id,
        session_id=old_sess_id,
        sequence=1,
        title="Blue-green verifier notes",
        summary="Archived rollout notes for the verifier",
        transcript="Archived transcript about blue-green deployment verifier steps.",
        message_count=3,
    ))

    hidden_task_sess_id = uuid.uuid4()
    hidden_child_sess_id = uuid.uuid4()
    hidden_thread_sess_id = uuid.uuid4()
    for hidden_id, kwargs in [
        (hidden_task_sess_id, {"session_type": "pipeline_run", "source_task_id": uuid.uuid4()}),
        (hidden_child_sess_id, {"session_type": "channel", "parent_session_id": sess_id}),
        (hidden_thread_sess_id, {"session_type": "thread", "parent_message_id": messages[0].id}),
    ]:
        db_session.add(Session(
            id=hidden_id,
            client_id=f"hidden-{hidden_id}",
            bot_id="test-bot",
            channel_id=ch_id,
            title="Hidden task transcript",
            **kwargs,
        ))
        db_session.add(Message(
            id=uuid.uuid4(),
            session_id=hidden_id,
            role="user",
            content="rollback hidden sub-session transcript should not appear",
        ))
    await db_session.commit()

    return ch_id, sess_id, old_sess_id, messages


class TestSearchEndpoint:
    async def test_search_endpoint_basic(self, client, channel_with_messages):
        ch_id, _, _, _ = channel_with_messages
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
        ch_id, _, _, _ = channel_with_messages
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
        ch_id, _, _, _ = channel_with_messages
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
        ch_id, _, _, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/messages/search",
            params={"role": "user"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        for msg in resp.json():
            assert msg["role"] == "user"

    async def test_search_excludes_tool_system_by_default(self, client, channel_with_messages):
        ch_id, _, _, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/messages/search",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        for msg in resp.json():
            assert msg["role"] in ("user", "assistant")


class TestSessionSearchEndpoint:
    async def test_session_catalog_includes_active_and_previous(self, client, channel_with_messages):
        ch_id, active_sid, old_sid, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/sessions",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        ids = {row["session_id"] for row in sessions}
        assert str(active_sid) in ids
        assert str(old_sid) in ids
        active = next(row for row in sessions if row["session_id"] == str(active_sid))
        assert active["surface_kind"] == "channel"
        assert active["is_active"] is True

    async def test_session_catalog_excludes_sub_sessions(self, client, channel_with_messages):
        ch_id, _, _, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/sessions",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        labels = {row.get("label") for row in resp.json()["sessions"]}
        assert "Hidden task transcript" not in labels

    async def test_session_search_groups_live_message_matches_by_session(self, client, channel_with_messages):
        ch_id, _, old_sid, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/sessions/search",
            params={"q": "rollback"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert any(row["session_id"] == str(old_sid) for row in sessions)
        row = next(row for row in sessions if row["session_id"] == str(old_sid))
        assert any(match["kind"] == "message" for match in row["matches"])

    async def test_session_search_excludes_sub_session_matches(self, client, channel_with_messages):
        ch_id, _, _, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/sessions/search",
            params={"q": "hidden sub-session"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    async def test_session_search_uses_archived_section_matches(self, client, channel_with_messages):
        ch_id, _, old_sid, _ = channel_with_messages
        resp = await client.get(
            f"/api/v1/channels/{ch_id}/sessions/search",
            params={"q": "verifier"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        row = next(row for row in resp.json()["sessions"] if row["session_id"] == str(old_sid))
        assert any(match["kind"] == "section" for match in row["matches"])
