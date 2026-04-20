import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from app.agent.bots import get_bot
from app.config import settings
from sqlalchemy.orm import selectinload

from app.db.models import Attachment, Channel, Message, Session, TraceEvent
from app.dependencies import get_db, require_scopes
from app.schemas.messages import AttachmentBrief, MessageOut
from app.services.compaction import run_compaction_forced

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionSummary(BaseModel):
    id: uuid.UUID
    client_id: str
    bot_id: str
    title: Optional[str] = None
    created_at: datetime
    last_active: datetime

    model_config = {"from_attributes": True}


class SessionDetail(BaseModel):
    session: SessionSummary
    messages: list[MessageOut]


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    client_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    stmt = select(Session).order_by(Session.last_active.desc())
    if client_id:
        stmt = stmt.where(Session.client_id == client_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    result = await db.execute(
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    messages = list(result.scalars().all())
    if session.channel_id:
        await _recover_orphan_attachments(db, session.channel_id, messages)
    return SessionDetail(session=session, messages=[MessageOut.from_orm(m) for m in messages])


class MessagePage(BaseModel):
    messages: list[MessageOut]
    has_more: bool


import logging
_logger = logging.getLogger(__name__)


async def _recover_orphan_attachments(
    db: AsyncSession,
    channel_id: uuid.UUID,
    messages: list["Message"],
) -> None:
    """Find attachments with message_id=NULL in this channel and link them to
    the nearest assistant message.  This is a fallback for when persist_turn's
    orphan-linking step fails silently (try/except swallows errors)."""
    orphan_result = await db.execute(
        select(Attachment)
        .where(
            Attachment.channel_id == channel_id,
            Attachment.message_id.is_(None),
        )
    )
    orphans = list(orphan_result.scalars().all())
    if not orphans:
        return

    _logger.warning(
        "Found %d orphaned attachment(s) in channel %s — recovering",
        len(orphans), channel_id,
    )

    # Build time-sorted list of assistant messages from the loaded set
    assistant_msgs = [
        m for m in messages if m.role == "assistant"
    ]
    if not assistant_msgs:
        return

    linked = 0
    for att in orphans:
        # Find the closest assistant message by time (prefer one created AFTER the attachment)
        best = None
        for m in assistant_msgs:
            if m.created_at >= att.created_at:
                best = m
                break
        if best is None:
            # Fallback: use the last assistant message
            best = assistant_msgs[-1]
        att.message_id = best.id
        # Also populate the in-memory relationship so the current response includes it
        if not hasattr(best, "attachments") or best.attachments is None:
            best.attachments = []
        best.attachments.append(att)
        linked += 1

    if linked:
        await db.commit()
        _logger.info("Recovered %d orphan attachment(s) in channel %s", linked, channel_id)


@router.get("/{session_id}/messages", response_model=MessagePage)
async def get_session_messages(
    session_id: uuid.UUID,
    limit: int = 50,
    before: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Cursor-based paginated messages. Returns newest first. Use `before` with the oldest message id to load older messages."""
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    stmt = (
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.session_id == session_id)
    )

    if before:
        # Get the created_at of the cursor message
        cursor_msg = await db.get(Message, before)
        if cursor_msg:
            stmt = stmt.where(Message.created_at < cursor_msg.created_at)

    # Fetch limit+1 to determine has_more
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    messages = rows[:limit]
    # Reverse to chronological order
    messages.reverse()

    # Recover orphaned attachments: if persist_turn's orphan linking failed,
    # attachments created by send_file have message_id=NULL.  Link them now.
    if session.channel_id:
        await _recover_orphan_attachments(db, session.channel_id, messages)

    return MessagePage(messages=[MessageOut.from_orm(m) for m in messages], has_more=has_more)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()


@router.get("/{session_id}/context")
async def get_session_context(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Return the most recent context_breakdown trace event for the session,
    plus last compression info if available."""
    result = await db.execute(
        select(TraceEvent)
        .where(TraceEvent.session_id == session_id, TraceEvent.event_type == "context_breakdown")
        .order_by(TraceEvent.created_at.desc())
        .limit(1)
    )
    event = result.scalar_one_or_none()
    if event is None or not event.data:
        return {"breakdown": None, "total_chars": 0, "total_messages": 0, "iteration": None, "created_at": None}

    return {
        "breakdown": event.data.get("breakdown"),
        "total_chars": event.data.get("total_chars", 0),
        "total_messages": event.data.get("total_messages", 0),
        "iteration": event.data.get("iteration"),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.get("/{session_id}/context/contents")
async def get_session_context_contents(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Dump the actual messages that would go to the model."""
    from app.services.sessions import _load_messages

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    bot = get_bot(session.bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")

    messages = await _load_messages(db, session)

    # Sanitize messages for display — strip huge binary content
    display_messages = []
    for m in messages:
        dm = {"role": m.get("role", "?"), "content": m.get("content")}
        if m.get("tool_calls"):
            dm["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            dm["tool_call_id"] = m["tool_call_id"]
        display_messages.append(dm)

    return {
        "session_id": str(session_id),
        "total_messages": len(display_messages),
        "total_chars": sum(
            len(str(m.get("content", ""))) for m in display_messages
        ),
        "messages": display_messages,
    }


@router.get("/{session_id}/context/diagnostics")
async def get_session_context_diagnostics(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:read")),
):
    """Return compaction diagnostic info for a session."""
    from app.services.compaction import (
        _get_compaction_interval,
        _get_compaction_keep_turns,
        _is_compaction_enabled,
    )

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    bot = get_bot(session.bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")

    channel: Channel | None = None
    if session.channel_id:
        channel = await db.get(Channel, session.channel_id)

    # Count total messages and user messages in session
    total_msg_count = (await db.execute(
        select(func.count()).where(Message.session_id == session_id)
    )).scalar() or 0

    total_user_count = (await db.execute(
        select(func.count())
        .where(Message.session_id == session_id)
        .where(Message.role == "user")
    )).scalar() or 0

    # Count user messages since watermark (what compaction checks)
    if session.summary_message_id:
        watermark_msg = await db.get(Message, session.summary_message_id)
        watermark_created = watermark_msg.created_at if watermark_msg else None
        if watermark_msg:
            user_since_watermark = (await db.execute(
                select(func.count())
                .where(Message.session_id == session_id)
                .where(Message.role == "user")
                .where(Message.created_at > watermark_msg.created_at)
            )).scalar() or 0
            msgs_since_watermark = (await db.execute(
                select(func.count())
                .where(Message.session_id == session_id)
                .where(Message.created_at > watermark_msg.created_at)
            )).scalar() or 0
        else:
            user_since_watermark = total_user_count
            msgs_since_watermark = total_msg_count
            watermark_created = None
    else:
        user_since_watermark = total_user_count
        msgs_since_watermark = total_msg_count
        watermark_created = None

    # Last compaction trace event
    last_compaction = (await db.execute(
        select(TraceEvent)
        .where(TraceEvent.session_id == session_id)
        .where(TraceEvent.event_type == "compaction_done")
        .order_by(TraceEvent.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    compaction_enabled = _is_compaction_enabled(bot, channel)
    compaction_interval = _get_compaction_interval(bot, channel) if compaction_enabled else None
    compaction_keep_turns = _get_compaction_keep_turns(bot, channel) if compaction_enabled else None

    return {
        "session_id": str(session_id),
        "total_messages": total_msg_count,
        "total_user_turns": total_user_count,
        "compaction": {
            "enabled": compaction_enabled,
            "interval": compaction_interval,
            "keep_turns": compaction_keep_turns,
            "has_summary": bool(session.summary),
            "has_watermark": bool(session.summary_message_id),
            "watermark_created_at": watermark_created.isoformat() if watermark_created else None,
            "user_turns_since_watermark": user_since_watermark,
            "msgs_since_watermark": msgs_since_watermark,
            "turns_until_next": (
                max(0, compaction_interval - user_since_watermark)
                if compaction_enabled and compaction_interval else None
            ),
            "last_compaction_at": (
                last_compaction.created_at.isoformat() if last_compaction else None
            ),
        },
    }


class SummarizeResponse(BaseModel):
    title: str
    summary: str


@router.post("/{session_id}/summarize", response_model=SummarizeResponse)
async def summarize_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("sessions:write")),
):
    """Force full compaction: memory phase (if bot has memory/persona/knowledge) then summary. Sets watermark so the summary is used on next load."""
    try:
        session = await db.get(Session, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        bot = get_bot(session.bot_id)
        title, summary = await run_compaction_forced(session_id, bot, db)
        await db.commit()
        return SummarizeResponse(title=title, summary=summary)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="Session not found")
        if "no conversation" in str(e).lower():
            raise HTTPException(status_code=400, detail="No conversation content to summarize")
        if "no messages" in str(e).lower():
            raise HTTPException(status_code=400, detail="No messages in session")
        raise HTTPException(status_code=400, detail=str(e))
