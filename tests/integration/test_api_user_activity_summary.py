import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, ConversationSection, Message, Session, User
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


def _is_sqlite(db_session: AsyncSession) -> bool:
    return "sqlite" in str(db_session.bind.url)


async def _seed_session(
    db_session: AsyncSession,
    *,
    user: User,
    sender_id: str,
    channel_name: str = "Activity Channel",
    created_at: datetime | None = None,
) -> tuple[Channel, Session]:
    now = created_at or datetime.now(timezone.utc)
    channel = Channel(
        id=uuid.uuid4(),
        client_id=f"user-activity-{uuid.uuid4().hex[:8]}",
        bot_id="test-bot",
        name=channel_name,
    )
    session = Session(
        id=uuid.uuid4(),
        client_id=f"user-activity-session-{uuid.uuid4().hex[:8]}",
        bot_id="test-bot",
        channel_id=channel.id,
        title="Decision follow-up",
        summary="Latest user activity summary.",
        last_active=now + timedelta(seconds=5),
    )
    channel.active_session_id = session.id
    db_session.add_all([channel, session])
    await db_session.flush()
    db_session.add_all([
        Message(
            id=uuid.uuid4(),
            session_id=session.id,
            role="user",
            content=f"{user.display_name} asked for a concise latest-session summary.",
            metadata_={
                "source": "web",
                "sender_type": "human",
                "sender_id": sender_id,
                "sender_display_name": user.display_name,
            },
            created_at=now,
        ),
        Message(
            id=uuid.uuid4(),
            session_id=session.id,
            role="assistant",
            content="Here is the latest session summary.",
            created_at=now + timedelta(seconds=2),
        ),
        ConversationSection(
            id=uuid.uuid4(),
            channel_id=channel.id,
            session_id=session.id,
            sequence=1,
            title="Summary",
            summary="Here is the latest session summary.",
            transcript="User asked for a concise summary.",
            message_count=2,
        ),
    ])
    await db_session.commit()
    return channel, session


async def test_user_activity_summary_counts_web_user_activity(client, db_session):
    if _is_sqlite(db_session):
        pytest.skip("JSONB sender extraction is Postgres-only in this endpoint")

    user = User(
        id=uuid.uuid4(),
        email=f"activity-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Activity User",
        auth_method="local",
        is_active=True,
    )
    inactive = User(
        id=uuid.uuid4(),
        email=f"inactive-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Inactive User",
        auth_method="local",
        is_active=False,
    )
    db_session.add_all([user, inactive])
    await db_session.commit()

    channel, session = await _seed_session(
        db_session,
        user=user,
        sender_id=f"user:{user.id}",
        channel_name="Decisions",
    )

    resp = await client.get("/api/v1/admin/users/activity-summary?limit=10", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    rows = {row["id"]: row for row in resp.json()["users"]}

    row = rows[str(user.id)]
    assert row["today_message_count"] == 1
    assert row["today_session_count"] == 1
    assert row["today_channel_count"] == 1
    assert row["latest_session"]["session_id"] == str(session.id)
    assert row["latest_session"]["channel_id"] == str(channel.id)
    assert row["latest_session"]["channel_name"] == "Decisions"
    assert row["latest_session"]["message_count"] == 2
    assert row["latest_session"]["section_count"] == 1
    assert "concise latest-session summary" in row["latest_session"]["preview"]

    inactive_row = rows[str(inactive.id)]
    assert inactive_row["is_active"] is False
    assert inactive_row["today_message_count"] == 0
    assert inactive_row["latest_session"] is None


async def test_user_activity_summary_counts_integration_identity(client, db_session):
    if _is_sqlite(db_session):
        pytest.skip("JSONB sender extraction is Postgres-only in this endpoint")

    user = User(
        id=uuid.uuid4(),
        email=f"slack-activity-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Slack Activity User",
        auth_method="local",
        integration_config={"slack": {"user_id": "U12345"}},
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    await _seed_session(
        db_session,
        user=user,
        sender_id="slack:U12345",
        channel_name="Slack Ops",
    )

    resp = await client.get("/api/v1/admin/users/activity-summary?limit=10", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    row = next(row for row in resp.json()["users"] if row["id"] == str(user.id))
    assert row["today_message_count"] == 1
    assert row["today_session_count"] == 1
    assert row["today_channel_count"] == 1
    assert row["latest_session"]["channel_name"] == "Slack Ops"
