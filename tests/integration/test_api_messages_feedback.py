"""Integration tests for /api/v1/messages/{id}/feedback and the slack bridge."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import Channel, Message, Session, TraceEvent, TurnFeedback, User
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


async def _make_user_and_channel(db_session, *, bot_id: str = "test-bot"):
    user = User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4()}@example.com",
        display_name="tester",
    )
    db_session.add(user)
    await db_session.flush()

    session = Session(
        id=uuid.uuid4(),
        client_id=f"web:{uuid.uuid4()}",
        bot_id=bot_id,
        depth=0,
        session_type="channel",
    )
    db_session.add(session)
    await db_session.flush()

    channel = Channel(
        id=uuid.uuid4(),
        name="feedback-int",
        bot_id=bot_id,
        active_session_id=session.id,
    )
    session.channel_id = channel.id
    db_session.add(channel)
    await db_session.flush()
    return user, channel, session


async def _add_assistant_turn(db_session, session, *, content="hi"):
    cid = uuid.uuid4()
    msg = Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content=content,
        correlation_id=cid,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(msg)
    await db_session.flush()
    return msg


@pytest.fixture
def override_user(client, db_session):
    """Helper that swaps verify_user for a test user. Returns the patched user."""
    from app.dependencies import verify_user
    user_holder: dict = {}

    async def _override():
        return user_holder["user"]

    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[verify_user] = _override

    def _set(user):
        user_holder["user"] = user

    yield _set
    app.dependency_overrides.pop(verify_user, None)


async def test_post_feedback_persists_row_and_block_serializes(
    client, db_session, override_user,
):
    user, channel, session = await _make_user_and_channel(db_session)
    channel.user_id = user.id  # owner — required for the access guard
    msg = await _add_assistant_turn(db_session, session, content="answer")
    await db_session.commit()
    override_user(user)

    r = await client.post(
        f"/api/v1/messages/{msg.id}/feedback",
        json={"vote": "down", "comment": "missed the question"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["vote"] == "down"
    assert body["comment"] == "missed the question"

    rows = (await db_session.execute(select(TurnFeedback))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == user.id

    traces = (await db_session.execute(
        select(TraceEvent).where(TraceEvent.event_name == "user_explicit_feedback")
    )).scalars().all()
    assert len(traces) == 1
    assert traces[0].data["vote"] == "down"
    assert "comment" not in traces[0].data

    # Round-trip: GET /sessions/{id}/messages must hydrate feedback onto the
    # anchor row for this user. Proves the canonical anchor selector +
    # FeedbackBlock serializer are wired correctly together.
    r2 = await client.get(
        f"/api/v1/sessions/{session.id}/messages",
        headers=AUTH_HEADERS,
    )
    assert r2.status_code == 200, r2.text
    msgs_out = r2.json()
    anchor_serialized = next(m for m in msgs_out if m["id"] == str(msg.id))
    assert anchor_serialized["feedback"] is not None
    assert anchor_serialized["feedback"]["mine"] == "down"
    assert anchor_serialized["feedback"]["totals"] == {"up": 0, "down": 1}
    assert anchor_serialized["feedback"]["comment_mine"] == "missed the question"


async def test_post_feedback_403_when_user_does_not_own_channel(
    client, db_session, override_user,
):
    """A user with a valid JWT but no claim on the channel must be rejected."""
    owner, channel, session = await _make_user_and_channel(db_session)
    channel.user_id = owner.id
    intruder = User(
        id=uuid.uuid4(),
        email=f"intruder-{uuid.uuid4()}@example.com",
        display_name="intruder",
    )
    db_session.add(intruder)
    msg = await _add_assistant_turn(db_session, session, content="answer")
    await db_session.commit()
    override_user(intruder)

    r = await client.post(
        f"/api/v1/messages/{msg.id}/feedback",
        json={"vote": "up"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 403, r.text

    # And no row should exist.
    rows = (await db_session.execute(select(TurnFeedback))).scalars().all()
    assert rows == []


async def test_get_messages_hydrates_feedback_when_anchor_outside_visible_page(
    client, db_session, override_user,
):
    """The hydration path resolves the anchor against the FULL turn,
    not just the visible page slice. Voting on a single-message turn whose
    anchor lives on an earlier page must still attach feedback when we
    request a page that includes that anchor.

    The earlier implementation picked the anchor from the page slice,
    which would silently skip feedback when the anchor was filtered out.
    """
    user, channel, session = await _make_user_and_channel(db_session)
    channel.user_id = user.id
    # Make a turn with two assistant rows: a tool-dispatch then the text.
    cid = uuid.uuid4()
    tool_dispatch = Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content=None,
        correlation_id=cid,
        tool_calls=[{"id": "1", "function": {"name": "x"}}],
        created_at=datetime.now(timezone.utc),
    )
    text = Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content="the answer",
        correlation_id=cid,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([tool_dispatch, text])
    await db_session.commit()
    override_user(user)

    await client.post(
        f"/api/v1/messages/{text.id}/feedback",
        json={"vote": "up"},
        headers=AUTH_HEADERS,
    )

    r = await client.get(
        f"/api/v1/sessions/{session.id}/messages?limit=10",
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200
    msgs_out = r.json()
    text_out = next(m for m in msgs_out if m["id"] == str(text.id))
    tool_out = next(m for m in msgs_out if m["id"] == str(tool_dispatch.id))
    assert text_out["feedback"] is not None
    assert text_out["feedback"]["mine"] == "up"
    # The tool-dispatch row must NOT carry the feedback block.
    assert tool_out["feedback"] is None


async def test_channel_out_exposes_show_message_feedback(
    client, db_session, override_user,
):
    """ChannelOut (chat-page payload) must surface the toggle so the UI gates."""
    user, channel, _session = await _make_user_and_channel(db_session)
    channel.user_id = user.id
    channel.show_message_feedback = False
    await db_session.commit()

    r = await client.get(
        f"/api/v1/channels/{channel.id}",
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["show_message_feedback"] is False


async def test_delete_feedback_is_idempotent(client, db_session, override_user):
    user, _channel, session = await _make_user_and_channel(db_session)
    msg = await _add_assistant_turn(db_session, session, content="answer")
    await db_session.commit()
    override_user(user)

    # No vote yet — DELETE still returns 204.
    r = await client.delete(
        f"/api/v1/messages/{msg.id}/feedback", headers=AUTH_HEADERS,
    )
    assert r.status_code == 204

    # Record then clear.
    await client.post(
        f"/api/v1/messages/{msg.id}/feedback",
        json={"vote": "up", "comment": None},
        headers=AUTH_HEADERS,
    )
    r = await client.delete(
        f"/api/v1/messages/{msg.id}/feedback", headers=AUTH_HEADERS,
    )
    assert r.status_code == 204

    rows = (await db_session.execute(select(TurnFeedback))).scalars().all()
    assert rows == []


async def test_post_feedback_404_when_message_has_no_correlation(
    client, db_session, override_user,
):
    user, _channel, session = await _make_user_and_channel(db_session)
    msg = Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content="orphan",
        correlation_id=None,
    )
    db_session.add(msg)
    await db_session.commit()
    override_user(user)

    r = await client.post(
        f"/api/v1/messages/{msg.id}/feedback",
        json={"vote": "up"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 404


async def test_slack_reaction_bridge_records_anonymous_vote(client, db_session):
    """The Slack-anonymous bridge resolves slack_ts → message → turn."""
    _user, _channel, session = await _make_user_and_channel(db_session)

    cid = uuid.uuid4()
    msg = Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content="answer",
        correlation_id=cid,
        metadata_={"slack_ts": "1700000000.99", "slack_channel": "C_S"},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(msg)
    await db_session.commit()

    r = await client.post(
        "/api/v1/messages/feedback/by-slack-reaction",
        json={
            "slack_ts": "1700000000.99",
            "slack_channel": "C_S",
            "slack_user_id": "U_X",
            "vote": "down",
        },
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text

    rows = (await db_session.execute(select(TurnFeedback))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert rows[0].source_integration == "slack"
    assert rows[0].source_user_ref == "U_X"
    assert rows[0].vote == "down"
