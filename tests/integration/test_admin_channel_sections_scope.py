import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Channel, ConversationSection, Message, Session
from tests.integration.conftest import AUTH_HEADERS


def _ts(offset: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=offset)


async def _seed_channel_sections(db: AsyncSession):
    channel_id = uuid.uuid4()
    active_id = uuid.uuid4()
    previous_id = uuid.uuid4()

    db.add(Channel(
        id=channel_id,
        name="memory-scope",
        client_id=f"memory-scope-{channel_id}",
        bot_id="test-bot",
        active_session_id=active_id,
    ))
    db.add(Session(
        id=active_id,
        client_id="web",
        bot_id="test-bot",
        channel_id=channel_id,
        title="Active chat",
        created_at=_ts(0),
        last_active=_ts(10),
    ))
    db.add(Session(
        id=previous_id,
        client_id="web",
        bot_id="test-bot",
        channel_id=channel_id,
        title="Previous chat",
        created_at=_ts(-100),
        last_active=_ts(-50),
    ))
    db.add_all([
        Message(id=uuid.uuid4(), session_id=active_id, role="user", content="active question", created_at=_ts(1)),
        Message(id=uuid.uuid4(), session_id=active_id, role="assistant", content="active answer", created_at=_ts(2)),
        Message(id=uuid.uuid4(), session_id=previous_id, role="user", content="previous question", created_at=_ts(-40)),
    ])
    db.add_all([
        ConversationSection(
            id=uuid.uuid4(),
            channel_id=channel_id,
            session_id=active_id,
            sequence=1,
            title="Active Section",
            summary="Only the active session should expose this by default.",
            transcript="active transcript alpha",
            message_count=2,
            chunk_size=50,
            period_start=_ts(1),
            period_end=_ts(2),
            tags=["active"],
        ),
        ConversationSection(
            id=uuid.uuid4(),
            channel_id=channel_id,
            session_id=previous_id,
            sequence=2,
            title="Previous Section",
            summary="Older session section with beta content.",
            transcript="previous transcript beta",
            message_count=1,
            chunk_size=50,
            period_start=_ts(-40),
            period_end=_ts(-39),
            tags=["previous"],
        ),
    ])
    await db.commit()
    return channel_id, active_id, previous_id


@pytest.mark.asyncio
async def test_admin_sections_default_scope_is_active_session(client, db_session):
    channel_id, active_id, _previous_id = await _seed_channel_sections(db_session)

    resp = await client.get(f"/api/v1/admin/channels/{channel_id}/sections", headers=AUTH_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"] == "current"
    assert [s["title"] for s in data["sections"]] == ["Active Section"]
    assert data["sections"][0]["session"]["id"] == str(active_id)
    assert data["sections"][0]["session"]["kind"] == "primary"
    assert data["sections"][0]["transcript_path"] is None
    assert data["sections"][0]["has_transcript"] is True
    assert data["stats"]["coverage_mode"] == "current"
    assert data["stats"]["covered_messages"] == 2
    assert data["stats"]["total_messages"] == 2
    assert data["stats"]["all_section_count"] == 2
    assert data["stats"]["other_session_section_count"] == 1


@pytest.mark.asyncio
async def test_admin_sections_all_scope_returns_session_labeled_inventory(client, db_session):
    channel_id, _active_id, previous_id = await _seed_channel_sections(db_session)

    resp = await client.get(f"/api/v1/admin/channels/{channel_id}/sections?scope=all", headers=AUTH_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"] == "all"
    assert {s["title"] for s in data["sections"]} == {"Active Section", "Previous Section"}
    previous = next(s["session"] for s in data["sections"] if s["title"] == "Previous Section")
    assert previous["id"] == str(previous_id)
    assert previous["title"] == "Previous chat"
    assert previous["kind"] == "previous"
    assert data["stats"]["coverage_mode"] == "inventory"


@pytest.mark.asyncio
async def test_admin_section_search_current_scope_does_not_leak_previous_sessions(client, db_session, engine):
    channel_id, _active_id, _previous_id = await _seed_channel_sections(db_session)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with patch("app.tools.local.conversation_history.async_session", return_value=factory()):
        current_resp = await client.get(
            f"/api/v1/admin/channels/{channel_id}/sections/search?q=beta",
            headers=AUTH_HEADERS,
        )
        all_resp = await client.get(
            f"/api/v1/admin/channels/{channel_id}/sections/search?q=beta&scope=all",
            headers=AUTH_HEADERS,
        )

    assert current_resp.status_code == 200
    assert current_resp.json()["results"] == []
    assert all_resp.status_code == 200
    results = all_resp.json()["results"]
    assert [r["section"]["title"] for r in results] == ["Previous Section"]
    assert results[0]["session"]["title"] == "Previous chat"
