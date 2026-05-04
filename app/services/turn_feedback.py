"""Turn-keyed user feedback (thumbs up/down).

Votes are scored at the turn level (`Message.correlation_id`) rather than
per individual `Message` row. Reacting to any sub-message of a turn
collapses to a single row keyed on `(correlation_id, user_id)` (or
`(correlation_id, source_integration, source_user_ref)` for anonymous
integration votes).

Each write/clear emits an `agent_quality_audit` `TraceEvent` with
`event_name='user_explicit_feedback'`, so existing quality consumers see
explicit user signal without bespoke wiring. Comment text is never put on
the trace event — PII stays in `turn_feedback`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal, Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Session as SessionRow, TraceEvent, TurnFeedback
from app.services.agent_quality_audit import (
    AGENT_QUALITY_AUDIT_EVENT,
    AGENT_QUALITY_AUDIT_VERSION,
)

logger = logging.getLogger(__name__)

USER_EXPLICIT_FEEDBACK_EVENT_NAME = "user_explicit_feedback"
COMMENT_MAX_LEN = 500
Vote = Literal["up", "down"]


class TurnFeedbackError(ValueError):
    """Raised when the request cannot be satisfied (e.g., turn-less message)."""


# ---------------------------------------------------------------------------
# Anchor / correlation resolution
# ---------------------------------------------------------------------------


def _has_tool_calls(value: object) -> bool:
    """True when an assistant ``tool_calls`` payload represents tool dispatch.

    Postgres JSONB can hand back either a list (the OpenAI canonical
    shape) or a dict (legacy/Anthropic-style payloads or wrapper rows).
    Treat any non-empty container as "this row dispatched tools" so the
    anchor selector excludes pure tool-dispatch messages regardless of
    storage shape.
    """
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return len(value) > 0
    return bool(value)


async def anchor_message_id_for_correlation(
    db: AsyncSession, correlation_id: uuid.UUID,
) -> uuid.UUID | None:
    """Return the *anchor message* id for a turn.

    Anchor = the last user-visible assistant text message in the turn.
    Tool-call-only and tool-result rows are excluded — see plan
    ``docs/plans/user-message-feedback.md``.
    """
    rows = (await db.execute(
        select(Message)
        .where(
            Message.correlation_id == correlation_id,
            Message.role == "assistant",
            Message.content.isnot(None),
            Message.tool_call_id.is_(None),
        )
        .order_by(Message.created_at.desc())
    )).scalars().all()
    for msg in rows:
        if _has_tool_calls(msg.tool_calls):
            continue
        return msg.id
    return None


async def anchor_message_ids_for_correlations(
    db: AsyncSession, correlation_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, uuid.UUID]:
    """Batched form of :func:`anchor_message_id_for_correlation`.

    One query for all turns. Used by the messages-list hydration so we
    don't reduce the anchor down to the visible page slice.
    """
    if not correlation_ids:
        return {}
    ids = list({c for c in correlation_ids if c is not None})
    if not ids:
        return {}
    rows = (await db.execute(
        select(Message)
        .where(
            Message.correlation_id.in_(ids),
            Message.role == "assistant",
            Message.content.isnot(None),
            Message.tool_call_id.is_(None),
        )
        .order_by(Message.correlation_id, Message.created_at.desc())
    )).scalars().all()

    out: dict[uuid.UUID, uuid.UUID] = {}
    for row in rows:
        if row.correlation_id in out:
            continue
        if _has_tool_calls(row.tool_calls):
            continue
        out[row.correlation_id] = row.id
    return out


async def resolve_correlation_for_message(
    db: AsyncSession, message_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID] | None:
    """Resolve a message id to ``(correlation_id, session_id, channel_id)``.

    Returns ``None`` if the message is missing, has no correlation_id, or
    its session has no channel.
    """
    msg = await db.get(Message, message_id)
    if msg is None or msg.correlation_id is None:
        return None
    session = await db.get(SessionRow, msg.session_id)
    if session is None or session.channel_id is None:
        return None
    return msg.correlation_id, session.id, session.channel_id


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def _normalize_comment(comment: str | None) -> str | None:
    if comment is None:
        return None
    text = comment.strip()
    if not text:
        return None
    return text[:COMMENT_MAX_LEN]


def _emit_trace(
    db: AsyncSession,
    *,
    correlation_id: uuid.UUID,
    session_id: uuid.UUID,
    vote: str,  # "up", "down", or "cleared"
    has_comment: bool,
    source_integration: str,
    anonymous: bool,
) -> None:
    db.add(TraceEvent(
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=None,
        client_id=None,
        event_type=AGENT_QUALITY_AUDIT_EVENT,
        event_name=USER_EXPLICIT_FEEDBACK_EVENT_NAME,
        count=1,
        data={
            "audit_version": AGENT_QUALITY_AUDIT_VERSION,
            "kind": USER_EXPLICIT_FEEDBACK_EVENT_NAME,
            "vote": vote,
            "has_comment": has_comment,
            "source_integration": source_integration,
            "anonymous": anonymous,
        },
        created_at=datetime.now(timezone.utc),
    ))


def _identity_predicate(
    *,
    correlation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    source_integration: str,
    source_user_ref: str | None,
):
    if user_id is not None:
        return and_(
            TurnFeedback.correlation_id == correlation_id,
            TurnFeedback.user_id == user_id,
        )
    return and_(
        TurnFeedback.correlation_id == correlation_id,
        TurnFeedback.user_id.is_(None),
        TurnFeedback.source_integration == source_integration,
        TurnFeedback.source_user_ref == source_user_ref,
    )


async def record_vote(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    user_id: uuid.UUID | None,
    source_integration: str,
    source_user_ref: str | None,
    vote: Vote,
    comment: str | None,
) -> TurnFeedback:
    """Upsert a vote for the turn anchored at ``message_id``.

    Returns the persisted ``TurnFeedback`` row. Caller commits the session.
    """
    if vote not in ("up", "down"):
        raise TurnFeedbackError(f"invalid vote: {vote!r}")
    if user_id is None and not source_user_ref:
        raise TurnFeedbackError(
            "anonymous feedback requires source_user_ref",
        )

    resolved = await resolve_correlation_for_message(db, message_id)
    if resolved is None:
        raise TurnFeedbackError("message has no correlation/channel")
    correlation_id, session_id, channel_id = resolved

    normalized_comment = _normalize_comment(comment)

    existing = (await db.execute(
        select(TurnFeedback).where(_identity_predicate(
            correlation_id=correlation_id,
            user_id=user_id,
            source_integration=source_integration,
            source_user_ref=source_user_ref,
        ))
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is None:
        row = TurnFeedback(
            correlation_id=correlation_id,
            channel_id=channel_id,
            session_id=session_id,
            user_id=user_id,
            source_integration=source_integration,
            source_user_ref=source_user_ref,
            vote=vote,
            comment=normalized_comment,
        )
        db.add(row)
    else:
        existing.vote = vote
        existing.comment = normalized_comment
        existing.updated_at = now
        # Channel/session can drift if the message was moved, but in
        # practice they are stable. Keep them aligned defensively.
        existing.channel_id = channel_id
        existing.session_id = session_id
        row = existing

    _emit_trace(
        db,
        correlation_id=correlation_id,
        session_id=session_id,
        vote=vote,
        has_comment=normalized_comment is not None,
        source_integration=source_integration,
        anonymous=user_id is None,
    )
    await db.flush()
    return row


async def clear_vote(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    user_id: uuid.UUID | None,
    source_integration: str,
    source_user_ref: str | None,
) -> bool:
    """Delete the vote for ``(correlation_id, identity)``. Idempotent.

    Returns True if a row was deleted, False if there was nothing to clear.
    """
    resolved = await resolve_correlation_for_message(db, message_id)
    if resolved is None:
        return False
    correlation_id, session_id, _channel_id = resolved

    existing = (await db.execute(
        select(TurnFeedback).where(_identity_predicate(
            correlation_id=correlation_id,
            user_id=user_id,
            source_integration=source_integration,
            source_user_ref=source_user_ref,
        ))
    )).scalar_one_or_none()
    if existing is None:
        return False

    await db.delete(existing)
    _emit_trace(
        db,
        correlation_id=correlation_id,
        session_id=session_id,
        vote="cleared",
        has_comment=False,
        source_integration=source_integration,
        anonymous=user_id is None,
    )
    await db.flush()
    return True


# ---------------------------------------------------------------------------
# Read-side hydration
# ---------------------------------------------------------------------------


class FeedbackSummary:
    """Per-correlation feedback summary returned by the hydration helper."""

    __slots__ = ("mine", "totals", "comment_mine")

    def __init__(
        self,
        *,
        mine: Vote | None,
        totals: dict[str, int],
        comment_mine: str | None,
    ) -> None:
        self.mine: Vote | None = mine
        self.totals: dict[str, int] = totals
        self.comment_mine: str | None = comment_mine

    def to_block(self) -> dict:
        return {
            "mine": self.mine,
            "totals": dict(self.totals),
            "comment_mine": self.comment_mine,
        }


async def feedback_for_correlation_ids(
    db: AsyncSession,
    *,
    correlation_ids: Sequence[uuid.UUID],
    user_id: uuid.UUID | None,
) -> dict[uuid.UUID, FeedbackSummary]:
    """Return a per-correlation summary for the given user."""
    if not correlation_ids:
        return {}

    ids = list({cid for cid in correlation_ids if cid is not None})
    if not ids:
        return {}

    rows = (await db.execute(
        select(TurnFeedback).where(TurnFeedback.correlation_id.in_(ids))
    )).scalars().all()

    out: dict[uuid.UUID, FeedbackSummary] = {
        cid: FeedbackSummary(mine=None, totals={"up": 0, "down": 0}, comment_mine=None)
        for cid in ids
    }
    for row in rows:
        summary = out[row.correlation_id]
        if row.vote == "up":
            summary.totals["up"] += 1
        elif row.vote == "down":
            summary.totals["down"] += 1
        if user_id is not None and row.user_id == user_id:
            summary.mine = row.vote  # type: ignore[assignment]
            summary.comment_mine = row.comment
    return out


__all__ = [
    "USER_EXPLICIT_FEEDBACK_EVENT_NAME",
    "COMMENT_MAX_LEN",
    "FeedbackSummary",
    "TurnFeedbackError",
    "anchor_message_id_for_correlation",
    "anchor_message_ids_for_correlations",
    "resolve_correlation_for_message",
    "record_vote",
    "clear_vote",
    "feedback_for_correlation_ids",
]
