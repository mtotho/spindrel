from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import Attachment, Message, Session, TraceEvent
from app.services.agent_quality_audit import (
    AGENT_QUALITY_AUDIT_EVENT,
    QualityEvidence,
    audit_turn_quality,
    detect_quality_findings,
)


async def _seed_turn(db_session, *, user: str, assistant: str, image: bool = False) -> uuid.UUID:
    session_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    db_session.add(Session(id=session_id, client_id="test", bot_id="bot-a"))
    user_msg = Message(
        session_id=session_id,
        role="user",
        content=user,
        correlation_id=correlation_id,
    )
    asst_msg = Message(
        session_id=session_id,
        role="assistant",
        content=assistant,
        correlation_id=correlation_id,
    )
    db_session.add_all([user_msg, asst_msg])
    await db_session.flush()
    if image:
        db_session.add(Attachment(
            message_id=user_msg.id,
            type="image",
            filename="photo.jpg",
            mime_type="image/jpeg",
            size_bytes=123,
        ))
    await db_session.commit()
    return correlation_id


def _evidence(**overrides) -> QualityEvidence:
    base = dict(
        correlation_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        bot_id="bot-a",
        client_id="web",
        turn_kind="chat",
        user_text="hello",
        assistant_text="hi",
        had_inline_image=False,
        tool_calls=[],
        trace_events=[],
        exposed_tools=set(),
    )
    base.update(overrides)
    return QualityEvidence(**base)


def test_detector_flags_image_refusal_without_db():
    findings = detect_quality_findings(_evidence(
        had_inline_image=True,
        assistant_text="I can't see the image attached here.",
    ))

    assert [f["code"] for f in findings] == ["current_inline_image_missed"]


def test_detector_treats_discovery_tools_as_not_live_lookup():
    findings = detect_quality_findings(_evidence(
        user_text="what is the current kitchen temperature?",
        assistant_text="It is 72 degrees.",
        tool_calls=[{"tool_name": "get_tool_info", "status": "done"}],
    ))

    assert [f["code"] for f in findings] == ["current_fact_without_lookup"]


def test_detector_flags_get_tool_info_not_found_surface_mismatch():
    findings = detect_quality_findings(_evidence(
        assistant_text="The ha_get_state tool is not available.",
        tool_calls=[{
            "tool_name": "get_tool_info",
            "status": "done",
            "result": "{\"error\": \"Tool 'ha_get_state' not found.\"}",
        }],
        exposed_tools={"homeassistant-ha_get_state", "get_tool_info"},
    ))

    assert any(f["code"] == "tool_surface_mismatch" for f in findings)
    mismatch = next(f for f in findings if f["subkind"] == "referenced_unexposed")
    assert mismatch["evidence"]["tool_name"] == "ha_get_state"


@pytest.mark.asyncio
async def test_audit_flags_inline_image_refusal_and_is_idempotent(db_session):
    correlation_id = await _seed_turn(
        db_session,
        user="what is wrong with this plant?",
        assistant="I can't see the image attached here.",
        image=True,
    )

    first = await audit_turn_quality(db_session, correlation_id, turn_kind="chat")
    second = await audit_turn_quality(db_session, correlation_id, turn_kind="chat")

    assert first == second
    assert [f["code"] for f in first["findings"]] == ["current_inline_image_missed"]

    rows = (await db_session.execute(
        select(TraceEvent).where(
            TraceEvent.correlation_id == correlation_id,
            TraceEvent.event_type == AGENT_QUALITY_AUDIT_EVENT,
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].data["audit_version"] == 1


@pytest.mark.asyncio
async def test_audit_treats_recent_attachment_context_as_inline_image(db_session):
    correlation_id = await _seed_turn(
        db_session,
        user='4" pot for reference',
        assistant="I can't see the image attached here.",
    )
    db_session.add(TraceEvent(
        correlation_id=correlation_id,
        event_type="recent_attachment_context",
        event_name="recent_chat_image",
        count=1,
        data={
            "source": "recent_chat_image",
            "admitted_count": 1,
            "content_included": False,
        },
    ))
    await db_session.commit()

    payload = await audit_turn_quality(db_session, correlation_id, turn_kind="chat")

    assert [f["code"] for f in payload["findings"]] == ["current_inline_image_missed"]


@pytest.mark.asyncio
async def test_audit_flags_current_fact_without_lookup(db_session):
    correlation_id = await _seed_turn(
        db_session,
        user="what is the current temperature in the kitchen?",
        assistant="It is 72 degrees.",
    )

    payload = await audit_turn_quality(db_session, correlation_id, turn_kind="chat")

    assert [f["code"] for f in payload["findings"]] == ["current_fact_without_lookup"]


@pytest.mark.asyncio
async def test_audit_does_not_flag_explicit_missing_capability(db_session):
    correlation_id = await _seed_turn(
        db_session,
        user="what is the current temperature in the kitchen?",
        assistant="I can't access the live Home Assistant state in this session.",
    )

    payload = await audit_turn_quality(db_session, correlation_id, turn_kind="chat")

    assert payload["findings"] == []
