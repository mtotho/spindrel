"""Integration tests for /api/v1/messages/{id}/thread and /messages/thread-summaries."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import Channel, Message, Session
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _make_channel_session(db_session, bot_id: str = "test-bot"):
    session = Session(
        id=uuid.uuid4(),
        client_id="web",
        bot_id=bot_id,
        channel_id=None,
        depth=0,
        session_type="channel",
    )
    db_session.add(session)
    await db_session.flush()
    channel = Channel(
        id=uuid.uuid4(),
        name="int-thread-test",
        bot_id=bot_id,
        active_session_id=session.id,
    )
    session.channel_id = channel.id
    db_session.add(channel)
    await db_session.flush()
    return channel, session


async def _add_message(
    db_session, *, session_id, role, content, metadata=None, created_at=None,
):
    msg = Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        metadata_=metadata or {},
        created_at=created_at or datetime.now(timezone.utc),
    )
    db_session.add(msg)
    await db_session.flush()
    return msg


# ---------------------------------------------------------------------------
# POST /messages/{id}/thread
# ---------------------------------------------------------------------------


class TestCreateThreadSession:
    async def test_spawns_thread_with_channel_bot_for_user_message(
        self, client, db_session
    ):
        channel, session = await _make_channel_session(db_session)
        msg = await _add_message(
            db_session, session_id=session.id, role="user", content="hey bot"
        )
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/messages/{msg.id}/thread",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["parent_message_id"] == str(msg.id)
        assert body["session_type"] == "thread"
        assert body["bot_id"] == "test-bot"

        thread = await db_session.get(Session, uuid.UUID(body["session_id"]))
        assert thread is not None
        assert thread.session_type == "thread"
        assert thread.parent_message_id == msg.id
        assert thread.channel_id is None

    async def test_infers_bot_from_assistant_message_metadata(
        self, client, db_session
    ):
        channel, session = await _make_channel_session(db_session)
        msg = await _add_message(
            db_session,
            session_id=session.id,
            role="assistant",
            content="bot reply",
            metadata={"bot_id": "default"},
        )
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/messages/{msg.id}/thread",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["bot_id"] == "default"

    async def test_body_bot_id_overrides_inference(self, client, db_session):
        channel, session = await _make_channel_session(db_session)
        msg = await _add_message(
            db_session, session_id=session.id, role="user", content="hi"
        )
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/messages/{msg.id}/thread",
            json={"bot_id": "default"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        assert resp.json()["bot_id"] == "default"

    async def test_unknown_message_404(self, client):
        bogus = uuid.uuid4()
        resp = await client.post(
            f"/api/v1/messages/{bogus}/thread",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_unknown_bot_400(self, client, db_session):
        channel, session = await _make_channel_session(db_session)
        msg = await _add_message(
            db_session, session_id=session.id, role="user", content="hi"
        )
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/messages/{msg.id}/thread",
            json={"bot_id": "no-such-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400

    async def test_seeds_context_message(self, client, db_session):
        channel, session = await _make_channel_session(db_session)
        base = datetime.now(timezone.utc) - timedelta(minutes=5)
        await _add_message(
            db_session,
            session_id=session.id,
            role="user",
            content="pre-1",
            created_at=base,
        )
        msg = await _add_message(
            db_session,
            session_id=session.id,
            role="user",
            content="anchor",
            created_at=base + timedelta(minutes=1),
        )
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/messages/{msg.id}/thread",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        session_id = uuid.UUID(resp.json()["session_id"])
        ctx_rows = (
            await db_session.execute(
                select(Message).where(Message.session_id == session_id)
            )
        ).scalars().all()
        assert len(ctx_rows) == 1
        assert ctx_rows[0].role == "system"
        assert ctx_rows[0].metadata_["kind"] == "thread_context"
        assert "anchor" in ctx_rows[0].content
        assert "pre-1" in ctx_rows[0].content


# ---------------------------------------------------------------------------
# GET /messages/thread-summaries
# ---------------------------------------------------------------------------


class TestBatchedThreadSummaries:
    async def test_returns_summary_for_messages_with_threads(
        self, client, db_session
    ):
        channel, session = await _make_channel_session(db_session)
        anchor = await _add_message(
            db_session, session_id=session.id, role="user", content="anchor-A"
        )
        no_thread = await _add_message(
            db_session, session_id=session.id, role="user", content="anchor-B"
        )
        await db_session.commit()

        # Spawn a thread on anchor only.
        resp = await client.post(
            f"/api/v1/messages/{anchor.id}/thread",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        thread_session_id = resp.json()["session_id"]

        # Add a user reply into the thread directly to get a nonzero reply count.
        reply = Message(
            id=uuid.uuid4(),
            session_id=uuid.UUID(thread_session_id),
            role="user",
            content="first reply in thread",
            metadata_={},
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(reply)
        await db_session.commit()

        ids = f"{anchor.id},{no_thread.id}"
        resp = await client.get(
            f"/api/v1/messages/thread-summaries?message_ids={ids}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert str(anchor.id) in body
        assert str(no_thread.id) not in body
        summary = body[str(anchor.id)]
        assert summary["session_id"] == thread_session_id
        assert summary["bot_id"] == "test-bot"
        assert summary["reply_count"] == 1
        assert "first reply" in summary["last_reply_preview"]

    async def test_empty_ids_returns_empty_dict(self, client):
        resp = await client.get(
            "/api/v1/messages/thread-summaries?message_ids=",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json() == {}

    async def test_invalid_uuid_400(self, client):
        resp = await client.get(
            "/api/v1/messages/thread-summaries?message_ids=not-a-uuid",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400
