import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import (
    Channel,
    ChannelIntegration,
    Message,
    NotificationTarget,
    Session,
    SessionReadState,
    UnreadNotificationRule,
    User,
)
from app.services import unread


pytestmark = pytest.mark.asyncio


async def _seed_session(db_session):
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@example.com",
        display_name="Reid",
    )
    channel = Channel(
        id=uuid.uuid4(),
        name="ops",
        bot_id="codex",
        user_id=user.id,
    )
    session = Session(
        id=uuid.uuid4(),
        client_id=f"web:{uuid.uuid4()}",
        bot_id="codex",
        channel_id=channel.id,
    )
    db_session.add_all([user, channel, session])
    await db_session.flush()
    return user, channel, session


async def test_assistant_reply_creates_one_session_unread_state(db_session):
    user, channel, session = await _seed_session(db_session)
    msg = Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content="done",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(msg)
    await db_session.flush()

    await unread.process_persisted_messages(
        db_session,
        session_id=session.id,
        bus_channel_id=channel.id,
        records=[msg],
    )

    row = (await db_session.execute(select(SessionReadState))).scalar_one()
    assert row.user_id == user.id
    assert row.session_id == session.id
    assert row.channel_id == channel.id
    assert row.latest_unread_message_id == msg.id
    assert row.unread_agent_reply_count == 1


async def test_visible_session_agent_reply_marks_read_instead_of_unread(db_session):
    user, channel, session = await _seed_session(db_session)
    msg = Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content="visible",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(msg)
    await db_session.flush()
    unread.mark_session_visible(user.id, session.id)

    await unread.process_persisted_messages(
        db_session,
        session_id=session.id,
        bus_channel_id=channel.id,
        records=[msg],
    )

    row = (await db_session.execute(select(SessionReadState))).scalar_one()
    assert row.last_read_message_id == msg.id
    assert row.unread_agent_reply_count == 0
    assert row.latest_unread_message_id is None


async def test_mirrored_integration_target_is_suppressed(db_session, monkeypatch):
    user, channel, session = await _seed_session(db_session)
    target = NotificationTarget(
        id=uuid.uuid4(),
        slug="ops-slack",
        label="Ops Slack",
        kind="integration_binding",
        config={"integration_type": "slack", "client_id": "slack:C123"},
        enabled=True,
        allowed_bot_ids=[],
    )
    db_session.add(target)
    db_session.add(ChannelIntegration(
        id=uuid.uuid4(),
        channel_id=channel.id,
        integration_type="slack",
        client_id="slack:C123",
    ))
    db_session.add(UnreadNotificationRule(
        id=uuid.uuid4(),
        user_id=user.id,
        target_ids=[str(target.id)],
    ))
    msg = Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content="do not loop back to same slack mirror",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(msg)
    await db_session.flush()

    sent = []

    async def fake_send(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(unread, "_send_unread_notification", fake_send)
    await unread.process_persisted_messages(
        db_session,
        session_id=session.id,
        bus_channel_id=channel.id,
        records=[msg],
    )

    assert sent == []
    row = (await db_session.execute(select(SessionReadState))).scalar_one()
    assert row.unread_agent_reply_count == 1
    assert row.initial_notified_at is None
