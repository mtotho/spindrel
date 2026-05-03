from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Attachment, Message, Session
from app.services.recent_attachments import (
    recent_inline_image_context,
    recent_inline_image_payloads,
)


pytestmark = pytest.mark.asyncio


async def _image_message(
    db_session,
    *,
    session_id: uuid.UUID,
    created_at: datetime,
    filename: str = "plant.jpg",
    hidden: bool = False,
) -> tuple[Message, Attachment]:
    msg = Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role="user",
        content="image",
        metadata_={"hidden": True} if hidden else {},
        created_at=created_at,
    )
    att = Attachment(
        id=uuid.uuid4(),
        message_id=msg.id,
        type="image",
        file_data=b"image-bytes",
        filename=filename,
        mime_type="image/jpeg",
        size_bytes=11,
        source_integration="web",
    )
    db_session.add_all([msg, att])
    return msg, att


async def test_recent_inline_image_context_uses_latest_visible_image_without_time_cap(db_session):
    session_id = uuid.uuid4()
    db_session.add(Session(id=session_id, client_id="web", bot_id="sprout"))
    old_msg, old_att = await _image_message(
        db_session,
        session_id=session_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=6),
        filename="old-pot.jpg",
    )
    hidden_msg, _hidden_att = await _image_message(
        db_session,
        session_id=session_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        filename="hidden.jpg",
        hidden=True,
    )
    current_msg = Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role="user",
        content='4" pot for reference',
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(current_msg)
    await db_session.commit()

    context = await recent_inline_image_context(
        db_session,
        session_id=session_id,
        before_message_id=current_msg.id,
    )

    assert context is not None
    assert context.source_message_id == old_msg.id
    assert context.attachment_ids == [str(old_att.id)]
    assert context.filenames == ["old-pot.jpg"]
    assert context.max_age_seconds is None
    assert context.payloads[0]["source"] == "recent_chat_image"
    assert context.payloads[0]["attachment_id"] == str(old_att.id)

    trace = context.trace_data(current_message_id=current_msg.id)
    assert trace["current_message_id"] == str(current_msg.id)
    assert trace["source_message_id"] == str(old_msg.id)
    assert trace["admitted_count"] == 1
    assert trace["content_included"] is False
    assert "content" not in trace
    assert hidden_msg.id != context.source_message_id


async def test_recent_inline_image_payloads_wrapper_preserves_payload_shape(db_session):
    session_id = uuid.uuid4()
    db_session.add(Session(id=session_id, client_id="web", bot_id="sprout"))
    _msg, att = await _image_message(
        db_session,
        session_id=session_id,
        created_at=datetime.now(timezone.utc),
        filename="seedling.jpg",
    )
    await db_session.commit()

    payloads = await recent_inline_image_payloads(db_session, session_id=session_id)

    assert len(payloads) == 1
    assert payloads[0]["attachment_id"] == str(att.id)
    assert payloads[0]["name"] == "seedling.jpg"
    assert payloads[0]["content"]
