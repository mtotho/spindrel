"""Tests for attachment-to-message linking via pre-allocated user message ID."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Message as MessageModel, Session as SessionModel


async def _seed_session(db_session: AsyncSession, session_id: uuid.UUID) -> None:
    db_session.add(SessionModel(id=session_id, client_id="web", bot_id="default"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_persist_user_message_uses_pre_allocated_id(engine, db_session):
    """When pre_allocated_id is set, the message row should use that UUID.

    The POST handler pre-persists a stub Message row so attachment FKs resolve.
    The turn worker must detect that row via ``db.get()`` and update it in place
    rather than inserting a new row.
    """
    from app.services.turn_worker import _persist_and_publish_user_message

    pre_id = uuid.uuid4()
    session_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    await _seed_session(db_session, session_id)
    db_session.add(MessageModel(id=pre_id, session_id=session_id, role="user", content=""))
    await db_session.commit()

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with (
        patch("app.services.turn_worker.async_session", factory),
        patch("app.services.turn_worker.publish_typed"),
        patch("app.services.outbox_publish.enqueue_new_message_for_channel", new_callable=AsyncMock),
    ):
        result = await _persist_and_publish_user_message(
            session_id=session_id,
            channel_id=channel_id,
            text="hello",
            correlation_id=correlation_id,
            metadata={"sender_id": "user"},
            pre_allocated_id=pre_id,
        )

    assert result == pre_id

    await db_session.commit()  # pick up cross-session writes
    rows = (await db_session.execute(select(MessageModel).where(MessageModel.session_id == session_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == pre_id
    assert rows[0].content == "hello"
    assert rows[0].correlation_id == correlation_id


@pytest.mark.asyncio
async def test_persist_user_message_auto_generates_id_without_pre_allocation(engine, db_session):
    """Without pre_allocated_id, the message should auto-generate a UUID."""
    from app.services.turn_worker import _persist_and_publish_user_message

    session_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    await _seed_session(db_session, session_id)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with (
        patch("app.services.turn_worker.async_session", factory),
        patch("app.services.turn_worker.publish_typed"),
        patch("app.services.outbox_publish.enqueue_new_message_for_channel", new_callable=AsyncMock),
    ):
        result = await _persist_and_publish_user_message(
            session_id=session_id,
            channel_id=channel_id,
            text="hello",
            correlation_id=correlation_id,
            metadata={"sender_id": "user"},
        )

    assert result is not None
    assert isinstance(result, uuid.UUID)

    await db_session.commit()
    rows = (await db_session.execute(select(MessageModel).where(MessageModel.session_id == session_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == result
    assert rows[0].content == "hello"
