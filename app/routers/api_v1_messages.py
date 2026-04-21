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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message, Session
from app.dependencies import (
    assert_admin_or_channel_owner,
    get_db,
    require_scopes,
    verify_auth_or_user,
)
from app.services.sub_sessions import SESSION_TYPE_THREAD, spawn_thread_session

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
    except HTTPException:
        raise HTTPException(status_code=400, detail=f"Unknown bot: {bot_id}")

    sub = await spawn_thread_session(
        db,
        parent_message_id=message_id,
        bot_id=bot_id,
    )
    await db.commit()

    return ThreadSessionOut(
        session_id=sub.id,
        parent_message_id=message_id,
        bot_id=bot_id,
    )


class ThreadInfoOut(BaseModel):
    session_id: uuid.UUID
    bot_id: str
    bot_name: Optional[str] = None
    parent_message_id: Optional[uuid.UUID] = None
    parent_channel_id: Optional[uuid.UUID] = None
    parent_message_preview: Optional[str] = None
    parent_message_role: Optional[str] = None


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

    return ThreadInfoOut(
        session_id=session.id,
        bot_id=session.bot_id,
        bot_name=bot_name,
        parent_message_id=session.parent_message_id,
        parent_channel_id=parent_channel_id,
        parent_message_preview=preview,
        parent_message_role=role,
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
