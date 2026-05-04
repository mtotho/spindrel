"""Unit tests for app/services/turn_feedback.py."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import Channel, Message, Session, TraceEvent, TurnFeedback
from app.services.agent_quality_audit import AGENT_QUALITY_AUDIT_EVENT
from app.services.turn_feedback import (
    USER_EXPLICIT_FEEDBACK_EVENT_NAME,
    TurnFeedbackError,
    _has_tool_calls,
    anchor_message_id_for_correlation,
    anchor_message_ids_for_correlations,
    clear_vote,
    feedback_for_correlation_ids,
    record_vote,
    resolve_correlation_for_message,
)


def test_has_tool_calls_handles_list_dict_and_empty_shapes():
    """JSONB can hand back list, dict, or None — all must be classified."""
    assert _has_tool_calls(None) is False
    assert _has_tool_calls([]) is False
    assert _has_tool_calls({}) is False
    assert _has_tool_calls([{"id": "1", "function": {"name": "x"}}]) is True
    # Dict-shaped payload (legacy / non-OpenAI providers): non-empty dict
    # must NOT be treated as a votable anchor.
    assert _has_tool_calls({"tool_name": "x", "arguments": "{}"}) is True


async def _seed_channel(db) -> uuid.UUID:
    channel_id = uuid.uuid4()
    db.add(Channel(
        id=channel_id, name="c", bot_id="bot-a", client_id=f"web:{channel_id}",
    ))
    await db.flush()
    return channel_id


async def _seed_session(db, channel_id: uuid.UUID) -> uuid.UUID:
    session_id = uuid.uuid4()
    db.add(Session(
        id=session_id, client_id=f"web:{channel_id}", bot_id="bot-a",
        channel_id=channel_id,
    ))
    await db.flush()
    return session_id


async def _seed_turn(db, session_id: uuid.UUID, *, asst_text: str = "hello") -> tuple[uuid.UUID, uuid.UUID]:
    correlation_id = uuid.uuid4()
    user_msg = Message(
        session_id=session_id, role="user", content="ping",
        correlation_id=correlation_id,
    )
    asst_msg = Message(
        session_id=session_id, role="assistant", content=asst_text,
        correlation_id=correlation_id,
    )
    db.add_all([user_msg, asst_msg])
    await db.flush()
    return correlation_id, asst_msg.id


@pytest.mark.asyncio
async def test_record_vote_creates_row_and_trace(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    correlation_id, anchor_id = await _seed_turn(db_session, session_id)
    user_id = uuid.uuid4()

    row = await record_vote(
        db_session,
        message_id=anchor_id,
        user_id=user_id,
        source_integration="web",
        source_user_ref=None,
        vote="up",
        comment="nice",
    )

    assert row.vote == "up"
    assert row.correlation_id == correlation_id
    assert row.channel_id == channel_id
    assert row.session_id == session_id
    assert row.comment == "nice"
    assert row.user_id == user_id

    traces = (await db_session.execute(
        select(TraceEvent).where(TraceEvent.correlation_id == correlation_id)
    )).scalars().all()
    assert len(traces) == 1
    t = traces[0]
    assert t.event_type == AGENT_QUALITY_AUDIT_EVENT
    assert t.event_name == USER_EXPLICIT_FEEDBACK_EVENT_NAME
    assert t.data["vote"] == "up"
    assert t.data["has_comment"] is True
    assert t.data["anonymous"] is False
    assert "comment" not in t.data


@pytest.mark.asyncio
async def test_revote_collapses_to_single_row(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    _correlation_id, anchor_id = await _seed_turn(db_session, session_id)
    user_id = uuid.uuid4()

    await record_vote(
        db_session, message_id=anchor_id, user_id=user_id,
        source_integration="web", source_user_ref=None,
        vote="up", comment=None,
    )
    await record_vote(
        db_session, message_id=anchor_id, user_id=user_id,
        source_integration="web", source_user_ref=None,
        vote="down", comment="actually wrong",
    )

    rows = (await db_session.execute(select(TurnFeedback))).scalars().all()
    assert len(rows) == 1
    assert rows[0].vote == "down"
    assert rows[0].comment == "actually wrong"


@pytest.mark.asyncio
async def test_voting_on_different_message_in_same_turn_collapses(db_session):
    """Multiple assistant messages in one turn → one vote row."""
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    correlation_id = uuid.uuid4()

    msg1 = Message(
        session_id=session_id, role="assistant",
        content="first part", correlation_id=correlation_id,
    )
    msg2 = Message(
        session_id=session_id, role="assistant",
        content="second part", correlation_id=correlation_id,
    )
    db_session.add_all([msg1, msg2])
    await db_session.flush()

    user_id = uuid.uuid4()
    await record_vote(
        db_session, message_id=msg1.id, user_id=user_id,
        source_integration="web", source_user_ref=None,
        vote="up", comment=None,
    )
    await record_vote(
        db_session, message_id=msg2.id, user_id=user_id,
        source_integration="web", source_user_ref=None,
        vote="down", comment=None,
    )

    rows = (await db_session.execute(select(TurnFeedback))).scalars().all()
    assert len(rows) == 1
    assert rows[0].vote == "down"
    assert rows[0].correlation_id == correlation_id


@pytest.mark.asyncio
async def test_clear_vote_deletes_row_and_emits_cleared_trace(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    correlation_id, anchor_id = await _seed_turn(db_session, session_id)
    user_id = uuid.uuid4()

    await record_vote(
        db_session, message_id=anchor_id, user_id=user_id,
        source_integration="web", source_user_ref=None,
        vote="up", comment=None,
    )
    cleared = await clear_vote(
        db_session, message_id=anchor_id, user_id=user_id,
        source_integration="web", source_user_ref=None,
    )
    assert cleared is True

    rows = (await db_session.execute(select(TurnFeedback))).scalars().all()
    assert rows == []

    traces = (await db_session.execute(
        select(TraceEvent).where(
            TraceEvent.correlation_id == correlation_id,
            TraceEvent.event_name == USER_EXPLICIT_FEEDBACK_EVENT_NAME,
        )
    )).scalars().all()
    assert len(traces) == 2  # up + cleared
    cleared_trace = next(t for t in traces if t.data["vote"] == "cleared")
    assert cleared_trace.data["has_comment"] is False


@pytest.mark.asyncio
async def test_clear_vote_idempotent_when_missing(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    _correlation_id, anchor_id = await _seed_turn(db_session, session_id)

    cleared = await clear_vote(
        db_session, message_id=anchor_id, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
    )
    assert cleared is False


@pytest.mark.asyncio
async def test_anonymous_and_named_votes_coexist(db_session):
    """Anonymous (Slack-style) vote and a real-user vote on the same turn → two rows."""
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    _correlation_id, anchor_id = await _seed_turn(db_session, session_id)

    await record_vote(
        db_session, message_id=anchor_id, user_id=None,
        source_integration="slack", source_user_ref="U123",
        vote="down", comment=None,
    )
    await record_vote(
        db_session, message_id=anchor_id, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="up", comment=None,
    )

    rows = (await db_session.execute(select(TurnFeedback))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_record_vote_rejects_message_without_correlation(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    msg = Message(
        session_id=session_id, role="assistant", content="orphan",
        correlation_id=None,
    )
    db_session.add(msg)
    await db_session.flush()

    with pytest.raises(TurnFeedbackError):
        await record_vote(
            db_session, message_id=msg.id, user_id=uuid.uuid4(),
            source_integration="web", source_user_ref=None,
            vote="up", comment=None,
        )


@pytest.mark.asyncio
async def test_anchor_skips_dict_shaped_tool_calls(db_session):
    """tool_calls stored as a dict (legacy/Anthropic shape) must not anchor."""
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    correlation_id = uuid.uuid4()

    text_msg = Message(
        session_id=session_id, role="assistant",
        content="actual answer", correlation_id=correlation_id,
    )
    dict_tool_msg = Message(
        session_id=session_id, role="assistant",
        content="ignored", correlation_id=correlation_id,
        tool_calls={"tool_name": "x", "arguments": "{}"},
    )
    db_session.add_all([text_msg, dict_tool_msg])
    await db_session.flush()

    anchor = await anchor_message_id_for_correlation(db_session, correlation_id)
    assert anchor == text_msg.id


@pytest.mark.asyncio
async def test_anchor_message_ids_for_correlations_is_batched(db_session):
    """One query returns the canonical anchor for every requested turn."""
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    cid_a, anchor_a = await _seed_turn(db_session, session_id, asst_text="a")
    cid_b, anchor_b = await _seed_turn(db_session, session_id, asst_text="b")
    cid_unrelated = uuid.uuid4()  # nothing seeded

    out = await anchor_message_ids_for_correlations(
        db_session, [cid_a, cid_b, cid_unrelated],
    )
    assert out == {cid_a: anchor_a, cid_b: anchor_b}


@pytest.mark.asyncio
async def test_anchor_skips_tool_only_and_tool_result_messages(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    correlation_id = uuid.uuid4()

    text_msg = Message(
        session_id=session_id, role="assistant",
        content="here is the answer", correlation_id=correlation_id,
    )
    tool_dispatch = Message(
        session_id=session_id, role="assistant",
        content=None, correlation_id=correlation_id,
        tool_calls=[{"id": "1", "type": "function", "function": {"name": "x"}}],
    )
    tool_result = Message(
        session_id=session_id, role="assistant",
        content="tool output", correlation_id=correlation_id,
        tool_call_id="1",
    )
    db_session.add_all([text_msg, tool_dispatch, tool_result])
    await db_session.flush()

    anchor = await anchor_message_id_for_correlation(db_session, correlation_id)
    assert anchor == text_msg.id


@pytest.mark.asyncio
async def test_resolve_correlation_for_message_returns_triple(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    correlation_id, anchor_id = await _seed_turn(db_session, session_id)

    resolved = await resolve_correlation_for_message(db_session, anchor_id)
    assert resolved == (correlation_id, session_id, channel_id)


@pytest.mark.asyncio
async def test_feedback_for_correlation_ids_summary(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    correlation_id, anchor_id = await _seed_turn(db_session, session_id)

    me = uuid.uuid4()
    other = uuid.uuid4()

    await record_vote(
        db_session, message_id=anchor_id, user_id=me,
        source_integration="web", source_user_ref=None,
        vote="up", comment="great",
    )
    await record_vote(
        db_session, message_id=anchor_id, user_id=other,
        source_integration="web", source_user_ref=None,
        vote="down", comment="meh",
    )

    out = await feedback_for_correlation_ids(
        db_session, correlation_ids=[correlation_id], user_id=me,
    )
    block = out[correlation_id].to_block()
    assert block["mine"] == "up"
    assert block["totals"] == {"up": 1, "down": 1}
    assert block["comment_mine"] == "great"


@pytest.mark.asyncio
async def test_comment_is_truncated_and_stripped(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    _correlation_id, anchor_id = await _seed_turn(db_session, session_id)

    long_comment = "  " + ("x" * 600) + "  "
    row = await record_vote(
        db_session, message_id=anchor_id, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="up", comment=long_comment,
    )
    assert row.comment is not None
    assert len(row.comment) == 500
    assert row.comment.startswith("x")


@pytest.mark.asyncio
async def test_empty_comment_becomes_null(db_session):
    channel_id = await _seed_channel(db_session)
    session_id = await _seed_session(db_session, channel_id)
    _correlation_id, anchor_id = await _seed_turn(db_session, session_id)

    row = await record_vote(
        db_session, message_id=anchor_id, user_id=uuid.uuid4(),
        source_integration="web", source_user_ref=None,
        vote="down", comment="   ",
    )
    assert row.comment is None
