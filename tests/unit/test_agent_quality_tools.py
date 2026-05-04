"""Unit tests for the audit-agent tools that surface user feedback.

Covers ``audit_trace_quality`` (per-correlation feedback hydration)
and the new ``list_user_feedback`` discovery tool.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Channel, Message, Session, TurnFeedback
from app.services.turn_feedback import record_vote


async def _seed_channel_session(db, *, bot_id: str = "bot-a") -> tuple[uuid.UUID, uuid.UUID]:
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db.add(Channel(
        id=channel_id, name=f"c-{channel_id}", bot_id=bot_id,
        client_id=f"web:{channel_id}",
    ))
    db.add(Session(
        id=session_id, client_id=f"web:{channel_id}", bot_id=bot_id,
        channel_id=channel_id,
    ))
    await db.flush()
    return channel_id, session_id


async def _seed_turn(db, session_id: uuid.UUID, *, content="answer text", created_at=None) -> tuple[uuid.UUID, uuid.UUID]:
    cid = uuid.uuid4()
    msg = Message(
        session_id=session_id,
        role="assistant",
        content=content,
        correlation_id=cid,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(msg)
    await db.flush()
    return cid, msg.id


@pytest.mark.asyncio
async def test_audit_trace_quality_includes_user_feedback(db_session, engine):
    from app.tools.local import agent_quality

    channel_id, session_id = await _seed_channel_session(db_session)
    cid, anchor_id = await _seed_turn(db_session, session_id)
    user_id = uuid.uuid4()
    await record_vote(
        db_session, message_id=anchor_id, user_id=user_id,
        source_integration="web", source_user_ref=None,
        vote="down", comment="answered the wrong thing",
    )
    await db_session.commit()

    test_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(agent_quality, "async_session", test_factory):
        out = json.loads(await agent_quality.audit_trace_quality(
            correlation_id=str(cid), persist=False,
        ))

    assert out["audited_count"] == 1
    assert out["user_feedback_count"] == 1
    result = out["results"][0]
    assert result["correlation_id"] == str(cid)
    assert len(result["user_feedback"]) == 1
    fb = result["user_feedback"][0]
    assert fb["vote"] == "down"
    assert fb["comment"] == "answered the wrong thing"
    assert fb["source_integration"] == "web"
    assert fb["anonymous"] is False
    assert fb["user_id"] == str(user_id)


@pytest.mark.asyncio
async def test_audit_trace_quality_user_feedback_empty_when_no_votes(db_session, engine):
    from app.tools.local import agent_quality

    _channel_id, session_id = await _seed_channel_session(db_session)
    cid, _anchor = await _seed_turn(db_session, session_id)
    await db_session.commit()

    test_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(agent_quality, "async_session", test_factory):
        out = json.loads(await agent_quality.audit_trace_quality(
            correlation_id=str(cid), persist=False,
        ))

    assert out["user_feedback_count"] == 0
    assert out["results"][0]["user_feedback"] == []


@pytest.mark.asyncio
async def test_list_user_feedback_filters_by_vote_and_returns_excerpt(db_session, engine):
    from app.tools.local import agent_quality

    _channel_id, session_id = await _seed_channel_session(db_session)
    long_content = "This is a very long answer text that should be excerpted by the tool when returned to the audit agent and that's that."
    cid_down, anchor_down = await _seed_turn(db_session, session_id, content=long_content)
    cid_up, anchor_up = await _seed_turn(db_session, session_id, content="quick reply")

    await record_vote(
        db_session, message_id=anchor_down, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="down", comment="missed it",
    )
    await record_vote(
        db_session, message_id=anchor_up, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="up", comment=None,
    )
    await db_session.commit()

    test_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(agent_quality, "async_session", test_factory):
        out_down = json.loads(await agent_quality.list_user_feedback(
            vote="down", since_hours=24, limit=50,
        ))
        out_all = json.loads(await agent_quality.list_user_feedback(
            since_hours=24, limit=50,
        ))

    assert out_down["row_count"] == 1
    row = out_down["rows"][0]
    assert row["vote"] == "down"
    assert row["comment"] == "missed it"
    assert row["correlation_id"] == str(cid_down)
    assert row["bot_id"] == "bot-a"
    assert row["anchor_excerpt"].startswith("This is a very long answer text")
    assert row["channel_name"] is not None

    assert out_all["row_count"] == 2
    votes = sorted(r["vote"] for r in out_all["rows"])
    assert votes == ["down", "up"]


@pytest.mark.asyncio
async def test_list_user_feedback_filters_by_correlation_id(db_session, engine):
    from app.tools.local import agent_quality

    _channel_id, session_id = await _seed_channel_session(db_session)
    cid_a, anchor_a = await _seed_turn(db_session, session_id)
    _cid_b, anchor_b = await _seed_turn(db_session, session_id)
    await record_vote(
        db_session, message_id=anchor_a, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="down", comment="a",
    )
    await record_vote(
        db_session, message_id=anchor_b, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="up", comment="b",
    )
    await db_session.commit()

    test_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(agent_quality, "async_session", test_factory):
        out = json.loads(await agent_quality.list_user_feedback(
            correlation_id=str(cid_a),
        ))

    assert out["row_count"] == 1
    assert out["rows"][0]["correlation_id"] == str(cid_a)
    assert out["rows"][0]["comment"] == "a"


@pytest.mark.asyncio
async def test_list_user_feedback_respects_since_hours(db_session, engine):
    """Old feedback outside the window must not appear."""
    from app.tools.local import agent_quality

    _channel_id, session_id = await _seed_channel_session(db_session)
    old_when = datetime.now(timezone.utc) - timedelta(hours=72)
    cid_old, anchor_old = await _seed_turn(db_session, session_id, created_at=old_when)
    cid_new, anchor_new = await _seed_turn(db_session, session_id)

    await record_vote(
        db_session, message_id=anchor_old, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="down", comment="ancient",
    )
    await record_vote(
        db_session, message_id=anchor_new, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="down", comment="recent",
    )
    # Backdate the old feedback row directly to simulate prior history; the
    # service stamps server defaults at flush time.
    old_fb = (await db_session.execute(
        TurnFeedback.__table__.select().where(
            TurnFeedback.correlation_id == cid_old,
        )
    )).first()
    assert old_fb is not None
    await db_session.execute(
        TurnFeedback.__table__.update()
        .where(TurnFeedback.correlation_id == cid_old)
        .values(created_at=old_when)
    )
    await db_session.commit()

    test_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(agent_quality, "async_session", test_factory):
        out = json.loads(await agent_quality.list_user_feedback(
            since_hours=24, vote="down",
        ))

    cids = [r["correlation_id"] for r in out["rows"]]
    assert str(cid_new) in cids
    assert str(cid_old) not in cids


@pytest.mark.asyncio
async def test_list_user_feedback_filters_by_bot_id(db_session, engine):
    from app.tools.local import agent_quality

    _ca, sa = await _seed_channel_session(db_session, bot_id="bot-a")
    _cb, sb = await _seed_channel_session(db_session, bot_id="bot-b")
    cid_a, anchor_a = await _seed_turn(db_session, sa)
    cid_b, anchor_b = await _seed_turn(db_session, sb)

    await record_vote(
        db_session, message_id=anchor_a, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="down", comment="a",
    )
    await record_vote(
        db_session, message_id=anchor_b, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="down", comment="b",
    )
    await db_session.commit()

    test_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(agent_quality, "async_session", test_factory):
        out = json.loads(await agent_quality.list_user_feedback(
            bot_id="bot-b", since_hours=24,
        ))

    assert out["row_count"] == 1
    assert out["rows"][0]["bot_id"] == "bot-b"
    assert out["rows"][0]["correlation_id"] == str(cid_b)


@pytest.mark.asyncio
async def test_list_user_feedback_rejects_invalid_vote():
    from app.tools.local import agent_quality

    out = json.loads(await agent_quality.list_user_feedback(vote="sideways"))
    assert "error" in out
