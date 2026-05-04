"""Public API v1 — Message-scoped endpoints (threads).

A *thread* is a sub-session anchored at a specific Message. Users click
"Reply in thread" on a message; the UI hits ``POST /messages/{id}/thread``
to spawn a new Session with ``session_type="thread"`` and
``parent_message_id`` pointing at the anchor. Replies live on the thread
session only — the parent feed renders a compact anchor card beneath
the original message via ``GET /messages/thread-summaries``.

Nesting is UI-gated, not backend-gated — the data model supports thread
sessions anchored at messages inside other thread sessions, but the
frontend hides the "Reply in thread" button within thread/ephemeral
views. Nothing here enforces depth.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message, Session, TurnFeedback, User as UserRow
from app.domain.errors import DomainError
from app.dependencies import (
    assert_admin_or_channel_owner,
    get_db,
    require_scopes,
    verify_auth_or_user,
    verify_user,
)
from app.services.sub_sessions import SESSION_TYPE_THREAD, spawn_thread_session
from app.services.turn_feedback import (
    COMMENT_MAX_LEN,
    TurnFeedbackError,
    anchor_message_id_for_correlation,
    clear_vote,
    record_vote,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["Messages"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ThreadSessionCreate(BaseModel):
    bot_id: Optional[str] = None


class ThreadSessionOut(BaseModel):
    session_id: uuid.UUID
    parent_message_id: uuid.UUID
    bot_id: str
    session_type: str = SESSION_TYPE_THREAD


class ThreadSummary(BaseModel):
    session_id: uuid.UUID
    bot_id: str
    bot_name: Optional[str] = None
    reply_count: int
    last_reply_preview: Optional[str] = None
    last_reply_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_message_channel(
    db: AsyncSession, message_id: uuid.UUID
) -> tuple[Message, Channel | None]:
    """Load a message + its channel (via its session). 404 if missing."""
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    session = await db.get(Session, msg.session_id)
    channel: Channel | None = None
    if session is not None and session.channel_id is not None:
        channel = await db.get(Channel, session.channel_id)
    return msg, channel


def _infer_bot_id(msg: Message, channel: Channel | None) -> str:
    """Pick a default bot for a thread rooted at this message.

    Assistant messages with a ``bot_id`` in metadata inherit that bot
    (reply-in-thread on @rolland's message → thread runs as @rolland).
    Otherwise fall back to the parent channel's primary bot.
    """
    meta = msg.metadata_ or {}
    if msg.role == "assistant":
        bot_id = meta.get("bot_id") or meta.get("source_bot_id")
        if isinstance(bot_id, str) and bot_id:
            return bot_id
    if channel is not None and channel.bot_id:
        return channel.bot_id
    # Last resort — use the session's bot.
    raise HTTPException(
        status_code=400,
        detail="Unable to infer bot for thread; pass bot_id explicitly",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{message_id}/thread",
    response_model=ThreadSessionOut,
    status_code=201,
)
async def create_thread_session(
    message_id: uuid.UUID,
    body: ThreadSessionCreate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Spawn a thread sub-session anchored at ``message_id``.

    Auth: same rule as the parent channel's owner/admin guard. Messages in
    channel-less sessions (e.g. already inside an ephemeral dock) require
    admin-equivalent auth since there's no channel to check ownership
    against.
    """
    _ = auth  # scope gate below if caller is a scoped API key
    msg, channel = await _resolve_message_channel(db, message_id)

    if channel is not None:
        assert_admin_or_channel_owner(channel, auth)
    else:
        # No parent channel — require scope-holding auth. Scoped API keys
        # (widget auth, integrations) have their own write scopes; JWT
        # users must be admin.
        from app.dependencies import ApiKeyAuth
        if not isinstance(auth, ApiKeyAuth) and not getattr(auth, "is_admin", False):
            raise HTTPException(
                status_code=403,
                detail="Thread on channel-less message requires admin",
            )

    bot_id = body.bot_id or _infer_bot_id(msg, channel)

    # Validate the bot actually exists — avoid a confusing downstream failure
    # when the configured channel bot was renamed / removed.
    from app.agent.bots import get_bot
    try:
        get_bot(bot_id)
    except (HTTPException, DomainError):
        raise HTTPException(status_code=400, detail=f"Unknown bot: {bot_id}")

    sub = await spawn_thread_session(
        db,
        parent_message_id=message_id,
        bot_id=bot_id,
    )

    # Pre-mint ``integration_thread_refs`` from the parent Message's
    # persisted external identifiers (Slack ``slack_ts``, Discord message
    # id, etc.) so the first outbound reply lands in the correct native
    # thread. Integration-generic via ``IntegrationMeta.build_thread_ref_from_message``
    # — each integration opts in by returning a ref dict from its own
    # hooks.py. No-ops when the parent has no recorded external id.
    from app.agent.hooks import iter_integration_meta
    parent_meta = dict(msg.metadata_ or {})
    thread_refs: dict = {}
    for meta in iter_integration_meta():
        if meta.build_thread_ref_from_message is None:
            continue
        try:
            ref = meta.build_thread_ref_from_message(parent_meta)
        except Exception:
            logger.warning(
                "build_thread_ref_from_message failed for %s",
                meta.integration_type, exc_info=True,
            )
            continue
        if ref:
            thread_refs[meta.integration_type] = ref
    if thread_refs:
        sub.integration_thread_refs = thread_refs

    await db.commit()

    return ThreadSessionOut(
        session_id=sub.id,
        parent_message_id=message_id,
        bot_id=bot_id,
    )


class ThreadParentMessageOut(BaseModel):
    """Full parent-message shape — mirrors `MessageOut` from `api_v1_sessions`
    so the UI can paint the parent as a regular `MessageBubble` without a
    second network round-trip. Kept intentionally minimal: the anchor bubble
    renders `content`, `role`, `created_at`, and `metadata`; attachments
    aren't surfaced inline on the anchor (click-through still works).
    """

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: Optional[str]
    created_at: datetime
    metadata: dict = {}


class ThreadInfoOut(BaseModel):
    session_id: uuid.UUID
    bot_id: str
    bot_name: Optional[str] = None
    parent_message_id: Optional[uuid.UUID] = None
    parent_channel_id: Optional[uuid.UUID] = None
    parent_message_preview: Optional[str] = None
    parent_message_role: Optional[str] = None
    parent_message: Optional[ThreadParentMessageOut] = None


@router.get("/thread/{session_id}", response_model=ThreadInfoOut)
async def get_thread_info(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Lookup thread metadata for a thread session.

    Used by the full-screen thread route to render the 'Replying to …'
    header without first spawning the thread from a message click. Returns
    the linked parent message (if still present) as a preview + role.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Thread session not found")
    if session.session_type != SESSION_TYPE_THREAD:
        raise HTTPException(status_code=400, detail="Not a thread session")

    parent_channel_id: uuid.UUID | None = None
    parent_msg_row: Message | None = None
    if session.parent_message_id:
        parent_msg_row = await db.get(Message, session.parent_message_id)
    if parent_msg_row is not None:
        parent_session = await db.get(Session, parent_msg_row.session_id)
        if parent_session is not None:
            parent_channel_id = parent_session.channel_id

    preview = None
    role = None
    if parent_msg_row is not None:
        preview_src = (parent_msg_row.content or "").strip().replace("\n", " ")
        preview = preview_src[:200] if preview_src else None
        role = parent_msg_row.role

    bot_name: str | None = None
    try:
        from app.agent.bots import get_bot as _get_bot
        bot_name = _get_bot(session.bot_id).name
    except Exception:
        pass

    parent_message_out: ThreadParentMessageOut | None = None
    if parent_msg_row is not None:
        parent_message_out = ThreadParentMessageOut(
            id=parent_msg_row.id,
            session_id=parent_msg_row.session_id,
            role=parent_msg_row.role,
            content=parent_msg_row.content,
            created_at=parent_msg_row.created_at,
            metadata=parent_msg_row.metadata_ or {},
        )

    return ThreadInfoOut(
        session_id=session.id,
        bot_id=session.bot_id,
        bot_name=bot_name,
        parent_message_id=session.parent_message_id,
        parent_channel_id=parent_channel_id,
        parent_message_preview=preview,
        parent_message_role=role,
        parent_message=parent_message_out,
    )


@router.get("/thread-summaries", response_model=dict[str, ThreadSummary])
async def batched_thread_summaries(
    message_ids: str = Query(
        ...,
        description="Comma-separated list of message UUIDs",
    ),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Return thread summaries keyed by message_id.

    Only messages that have at least one thread session appear in the
    response. The UI calls this once per visible-message batch to decide
    which messages should render a ThreadAnchor card.

    Summary includes the first thread per message (v1 supports one thread
    per message; nesting is UI-gated but the data model allows more). If
    multiple exist, the most-recently-updated wins.
    """
    ids: list[uuid.UUID] = []
    for raw in message_ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid message id: {raw}",
            )
    if not ids:
        return {}

    # Find thread sessions that anchor onto the requested messages.
    sess_stmt = (
        select(Session)
        .where(
            Session.parent_message_id.in_(ids),
            Session.session_type == SESSION_TYPE_THREAD,
        )
        .order_by(Session.last_active.desc())
    )
    sessions = list((await db.execute(sess_stmt)).scalars().all())
    if not sessions:
        return {}

    # Keep one thread per message — the most-recently-active.
    by_msg: dict[uuid.UUID, Session] = {}
    for s in sessions:
        if s.parent_message_id is None:
            continue
        by_msg.setdefault(s.parent_message_id, s)

    session_ids = [s.id for s in by_msg.values()]

    # Reply counts — non-system messages in each thread session.
    counts_stmt = (
        select(Message.session_id, func.count(Message.id))
        .where(
            Message.session_id.in_(session_ids),
            Message.role.in_(("user", "assistant")),
        )
        .group_by(Message.session_id)
    )
    count_rows = await db.execute(counts_stmt)
    counts = {sid: int(c) for sid, c in count_rows.all()}

    # Latest non-system message per thread — for the preview excerpt.
    latest_stmt = (
        select(Message)
        .where(
            Message.session_id.in_(session_ids),
            Message.role.in_(("user", "assistant")),
        )
        .order_by(Message.created_at.desc())
    )
    latest_rows = list((await db.execute(latest_stmt)).scalars().all())
    latest_by_session: dict[uuid.UUID, Message] = {}
    for m in latest_rows:
        latest_by_session.setdefault(m.session_id, m)

    # Resolve bot names (best-effort — bot registry lookup).
    from app.agent.bots import get_bot

    out: dict[str, ThreadSummary] = {}
    for msg_id, s in by_msg.items():
        bot_name: str | None = None
        try:
            bot_name = get_bot(s.bot_id).name
        except Exception:
            bot_name = None

        latest = latest_by_session.get(s.id)
        preview = None
        if latest is not None:
            preview_src = (latest.content or "").strip().replace("\n", " ")
            preview = preview_src[:140] if preview_src else None

        out[str(msg_id)] = ThreadSummary(
            session_id=s.id,
            bot_id=s.bot_id,
            bot_name=bot_name,
            reply_count=counts.get(s.id, 0),
            last_reply_preview=preview,
            last_reply_at=latest.created_at if latest is not None else None,
        )

    return out


# ---------------------------------------------------------------------------
# Turn feedback (thumbs up/down)
# ---------------------------------------------------------------------------


class FeedbackIn(BaseModel):
    vote: str = Field(..., description="'up' or 'down'")
    comment: Optional[str] = Field(None, max_length=COMMENT_MAX_LEN)


class FeedbackOut(BaseModel):
    vote: str
    comment: Optional[str] = None
    updated_at: datetime


class FeedbackReviewRow(BaseModel):
    correlation_id: uuid.UUID
    channel_id: uuid.UUID
    channel_name: Optional[str] = None
    session_id: uuid.UUID
    bot_id: Optional[str] = None
    vote: str
    comment: Optional[str] = None
    source_integration: str
    source_user_ref: Optional[str] = None
    anonymous: bool
    user_id: Optional[uuid.UUID] = None
    anchor_excerpt: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FeedbackReviewOut(BaseModel):
    row_count: int
    rows: list[FeedbackReviewRow]


_FEEDBACK_REVIEW_EXCERPT_LEN = 240


@router.get("/feedback", response_model=FeedbackReviewOut)
async def list_message_feedback(
    vote: Optional[str] = Query(None, pattern="^(up|down)$"),
    since_hours: int = Query(168, ge=1, le=720),
    bot_id: Optional[str] = None,
    channel_id: Optional[uuid.UUID] = None,
    correlation_id: Optional[uuid.UUID] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    """Admin review surface for explicit user feedback."""
    stmt = select(TurnFeedback).order_by(desc(TurnFeedback.created_at)).limit(limit)
    if correlation_id is not None:
        stmt = stmt.where(TurnFeedback.correlation_id == correlation_id)
    else:
        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        stmt = stmt.where(TurnFeedback.created_at >= since)
    if vote is not None:
        stmt = stmt.where(TurnFeedback.vote == vote)
    if channel_id is not None:
        stmt = stmt.where(TurnFeedback.channel_id == channel_id)

    rows = (await db.execute(stmt)).scalars().all()

    session_ids = {r.session_id for r in rows}
    sessions: dict[uuid.UUID, Session] = {}
    if session_ids:
        session_rows = (await db.execute(
            select(Session).where(Session.id.in_(session_ids))
        )).scalars().all()
        sessions = {s.id: s for s in session_rows}

    if bot_id:
        rows = [
            r for r in rows
            if sessions.get(r.session_id) and sessions[r.session_id].bot_id == bot_id
        ]

    channel_ids = {r.channel_id for r in rows}
    channels: dict[uuid.UUID, Channel] = {}
    if channel_ids:
        channel_rows = (await db.execute(
            select(Channel).where(Channel.id.in_(channel_ids))
        )).scalars().all()
        channels = {c.id: c for c in channel_rows}

    correlation_ids = list({r.correlation_id for r in rows})
    excerpts: dict[uuid.UUID, str] = {}
    if correlation_ids:
        anchor_rows = (await db.execute(
            select(Message)
            .where(
                Message.correlation_id.in_(correlation_ids),
                Message.role == "assistant",
                Message.content.isnot(None),
                Message.tool_call_id.is_(None),
            )
            .order_by(desc(Message.created_at))
        )).scalars().all()
        for message in anchor_rows:
            if message.correlation_id in excerpts:
                continue
            if isinstance(message.tool_calls, list) and message.tool_calls:
                continue
            content = (message.content or "").strip().replace("\n", " ")
            excerpts[message.correlation_id] = content[:_FEEDBACK_REVIEW_EXCERPT_LEN]

    out_rows = []
    for row in rows:
        session = sessions.get(row.session_id)
        channel = channels.get(row.channel_id)
        out_rows.append(FeedbackReviewRow(
            correlation_id=row.correlation_id,
            channel_id=row.channel_id,
            channel_name=channel.name if channel else None,
            session_id=row.session_id,
            bot_id=session.bot_id if session else None,
            vote=row.vote,
            comment=row.comment,
            source_integration=row.source_integration,
            source_user_ref=row.source_user_ref,
            anonymous=row.user_id is None,
            user_id=row.user_id,
            anchor_excerpt=excerpts.get(row.correlation_id),
            created_at=row.created_at,
            updated_at=row.updated_at,
        ))

    return FeedbackReviewOut(row_count=len(out_rows), rows=out_rows)



async def _resolve_message_for_feedback(
    db: AsyncSession, message_id: uuid.UUID, user,
) -> tuple[Message, Channel]:
    """Load message → session → channel and enforce the access boundary.

    Mirrors the channel-ownership check used elsewhere in this router
    (thread creation, ``assert_admin_or_channel_owner``). A user who can
    guess a message id must still own the channel — or be an admin —
    to vote.

    Raises 404 when the message has no correlation_id or no resolvable
    channel (turn-less / channel-less rows are not votable in v1).
    """
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.correlation_id is None:
        raise HTTPException(status_code=404, detail="Message has no turn correlation")
    session = await db.get(Session, msg.session_id)
    if session is None or session.channel_id is None:
        raise HTTPException(
            status_code=404, detail="Message is not bound to a channel",
        )
    channel = await db.get(Channel, session.channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    assert_admin_or_channel_owner(channel, user)
    return msg, channel


@router.post(
    "/{message_id}/feedback",
    response_model=FeedbackOut,
)
async def record_message_feedback(
    message_id: uuid.UUID,
    body: FeedbackIn,
    db: AsyncSession = Depends(get_db),
    user: UserRow = Depends(verify_user),
):
    """Record a thumbs-up / thumbs-down vote on the turn anchored at this message.

    The vote is keyed at the *turn* level (Message.correlation_id), not at
    the message level — re-voting via any message of the same turn updates
    the same row. Comments are optional and capped at 500 chars.
    """
    if body.vote not in ("up", "down"):
        raise HTTPException(status_code=422, detail="vote must be 'up' or 'down'")

    msg, _channel = await _resolve_message_for_feedback(db, message_id, user)

    # Require an anchor — turn-less or tool-only turns aren't votable.
    anchor_id = await anchor_message_id_for_correlation(db, msg.correlation_id)
    if anchor_id is None:
        raise HTTPException(
            status_code=404, detail="Turn has no votable anchor message",
        )

    try:
        row = await record_vote(
            db,
            message_id=message_id,
            user_id=user.id,
            source_integration="web",
            source_user_ref=None,
            vote=body.vote,
            comment=body.comment,
        )
    except TurnFeedbackError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    await db.commit()
    return FeedbackOut(
        vote=row.vote,
        comment=row.comment,
        updated_at=row.updated_at,
    )


@router.delete(
    "/{message_id}/feedback",
    status_code=204,
)
async def delete_message_feedback(
    message_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: UserRow = Depends(verify_user),
):
    """Clear the requesting user's vote on this turn. Idempotent."""
    await _resolve_message_for_feedback(db, message_id, user)

    await clear_vote(
        db,
        message_id=message_id,
        user_id=user.id,
        source_integration="web",
        source_user_ref=None,
    )
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Slack-reaction → turn-feedback bridge
#
# Slack runs in a separate process and reaches back via HTTP. Reactions on
# bot messages are mapped here. Only an admin-scoped credential (the
# integration's API key) may call these endpoints — Slack ``user_id`` is
# stored as ``source_user_ref`` with ``user_id=NULL`` because there is no
# Slack→User mapping in the codebase yet.
# ---------------------------------------------------------------------------


class SlackReactionFeedbackIn(BaseModel):
    slack_ts: str
    slack_channel: str
    slack_user_id: str
    vote: str  # "up" | "down"


class SlackReactionClearIn(BaseModel):
    slack_ts: str
    slack_channel: str
    slack_user_id: str


async def _resolve_message_for_slack_ref(
    db: AsyncSession, *, slack_ts: str, slack_channel: str,
) -> Message | None:
    """Find the Spindrel ``Message`` matching a Slack ``(channel, ts)`` ref.

    ``slack_ts`` and ``slack_channel`` are stamped on Message metadata at
    delivery time by ``integrations/slack/hooks.py``. The query is JSONB
    on Postgres; SQLAlchemy emits the ``->>`` operator for both dialects
    via ``func.jsonb_extract_path_text`` fall-throughs, but here a simple
    string compare against the typed string accessor is enough.
    """
    rows = (await db.execute(
        select(Message).where(
            Message.metadata_["slack_ts"].astext == slack_ts,
            Message.metadata_["slack_channel"].astext == slack_channel,
        ).limit(1)
    )).scalars().all()
    return rows[0] if rows else None


@router.post(
    "/feedback/by-slack-reaction",
    response_model=FeedbackOut,
)
async def record_slack_reaction_feedback(
    body: SlackReactionFeedbackIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    """Persist a Slack `:+1:` / `:-1:` reaction as anonymous turn feedback."""
    if body.vote not in ("up", "down"):
        raise HTTPException(status_code=422, detail="vote must be 'up' or 'down'")

    msg = await _resolve_message_for_slack_ref(
        db, slack_ts=body.slack_ts, slack_channel=body.slack_channel,
    )
    if msg is None or msg.correlation_id is None:
        raise HTTPException(status_code=404, detail="No turn for slack ref")

    anchor_id = await anchor_message_id_for_correlation(db, msg.correlation_id)
    if anchor_id is None:
        raise HTTPException(
            status_code=404, detail="Turn has no votable anchor message",
        )

    try:
        row = await record_vote(
            db,
            message_id=msg.id,
            user_id=None,
            source_integration="slack",
            source_user_ref=body.slack_user_id,
            vote=body.vote,
            comment=None,
        )
    except TurnFeedbackError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    await db.commit()
    return FeedbackOut(vote=row.vote, comment=row.comment, updated_at=row.updated_at)


@router.post(
    "/feedback/by-slack-reaction/clear",
    status_code=204,
)
async def clear_slack_reaction_feedback(
    body: SlackReactionClearIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    """Clear a Slack-anonymous vote (matches ``reaction_removed``)."""
    msg = await _resolve_message_for_slack_ref(
        db, slack_ts=body.slack_ts, slack_channel=body.slack_channel,
    )
    if msg is None:
        return Response(status_code=204)

    await clear_vote(
        db,
        message_id=msg.id,
        user_id=None,
        source_integration="slack",
        source_user_ref=body.slack_user_id,
    )
    await db.commit()
    return Response(status_code=204)
