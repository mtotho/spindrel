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
from app.db.models import Channel, Memory, Message, Plan, PlanItem, Session, TraceEvent
from app.dependencies import get_db, verify_auth, verify_auth_or_user
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


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionDetail(BaseModel):
    session: SessionSummary
    messages: list[MessageOut]


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    client_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
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
    _auth=Depends(verify_auth_or_user),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return SessionDetail(session=session, messages=messages)


class MessagePage(BaseModel):
    messages: list[MessageOut]
    has_more: bool


@router.get("/{session_id}/messages", response_model=MessagePage)
async def get_session_messages(
    session_id: uuid.UUID,
    limit: int = 50,
    before: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Cursor-based paginated messages. Returns newest first. Use `before` with the oldest message id to load older messages."""
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    stmt = select(Message).where(Message.session_id == session_id)

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

    return MessagePage(messages=messages, has_more=has_more)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    # If bot (or global) is configured to wipe memory on session delete, delete memories first.
    # Otherwise the FK uses ON DELETE SET NULL and memories are kept with session_id=NULL.
    try:
        bot = get_bot(session.bot_id)
        wipe = bot.memory.wipe_on_session_delete
    except HTTPException:
        wipe = settings.WIPE_MEMORY_ON_SESSION_DELETE
    if wipe:
        await db.execute(delete(Memory).where(Memory.session_id == session_id))
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()


@router.get("/{session_id}/context")
async def get_session_context(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
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

    # Also fetch the last context_compressed event from the same correlation
    compression_info = None
    correlation_id = event.correlation_id
    if correlation_id:
        comp_result = await db.execute(
            select(TraceEvent)
            .where(
                TraceEvent.session_id == session_id,
                TraceEvent.correlation_id == correlation_id,
                TraceEvent.event_type == "context_compressed",
            )
            .order_by(TraceEvent.created_at.desc())
            .limit(1)
        )
        comp_event = comp_result.scalar_one_or_none()
        if comp_event and comp_event.data:
            compression_info = comp_event.data

    return {
        "breakdown": event.data.get("breakdown"),
        "total_chars": event.data.get("total_chars", 0),
        "total_messages": event.data.get("total_messages", 0),
        "iteration": event.data.get("iteration"),
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "compression": compression_info,
    }


@router.get("/{session_id}/context/compressed")
async def get_session_context_compressed(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Run compression on the current session messages and return both breakdowns.

    This actually calls the cheap model to produce a summary — it's not free.
    """
    from app.agent.tracing import _CLASSIFY_SYS_MSG
    from app.services.compression import compress_context
    from app.services.sessions import _load_messages

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    bot = get_bot(session.bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")

    messages = await _load_messages(db, session)

    def _build_breakdown(msgs: list[dict]) -> dict:
        breakdown: dict[str, dict] = {}
        for m in msgs:
            role = m.get("role", "?")
            content = m.get("content") or ""
            chars = sum(len(str(p)) for p in content) if isinstance(content, list) else len(content)
            if role == "assistant" and m.get("tool_calls"):
                chars += sum(len(str(tc)) for tc in m["tool_calls"])
            key = role
            if role == "system" and isinstance(content, str):
                key = _CLASSIFY_SYS_MSG(content)
            if key not in breakdown:
                breakdown[key] = {"count": 0, "chars": 0}
            breakdown[key]["count"] += 1
            breakdown[key]["chars"] += chars
        total_chars = sum(v["chars"] for v in breakdown.values())
        return {"breakdown": breakdown, "total_chars": total_chars, "total_messages": len(msgs)}

    original = _build_breakdown(messages)

    # Find the last user message for compression context
    user_message = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            user_message = c if isinstance(c, str) else str(c)
            break

    result = await compress_context(
        messages, bot, user_message,
        channel_id=session.channel_id,
        provider_id=bot.model_provider_id,
    )

    if result is None:
        return {**original, "compressed": None, "reason": "below_threshold_or_disabled"}

    compressed_msgs, _drilldown = result
    compressed = _build_breakdown(compressed_msgs)

    return {
        **original,
        "compressed": compressed,
        "chars_saved": original["total_chars"] - compressed["total_chars"],
        "reduction_pct": round(
            (1 - compressed["total_chars"] / original["total_chars"]) * 100, 1
        ) if original["total_chars"] > 0 else 0,
    }


@router.get("/{session_id}/context/contents")
async def get_session_context_contents(
    session_id: uuid.UUID,
    compress: bool = True,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Dump the actual messages that would go to the model.

    If compress=true (default) and compression is enabled, runs the cheap model
    first and returns the compressed view. Otherwise returns the raw messages.
    """
    from app.services.compression import compress_context
    from app.services.sessions import _load_messages

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    bot = get_bot(session.bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")

    messages = await _load_messages(db, session)

    compressed = False
    if compress:
        user_message = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content", "")
                user_message = c if isinstance(c, str) else str(c)
                break

        result = await compress_context(
            messages, bot, user_message,
            channel_id=session.channel_id,
            provider_id=bot.model_provider_id,
        )
        if result is not None:
            messages = result[0]
            compressed = True

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
        "compressed": compressed,
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
    _auth=Depends(verify_auth_or_user),
):
    """Return compaction + compression diagnostic info for a session."""
    from app.services.compaction import (
        _get_compaction_interval,
        _get_compaction_keep_turns,
        _is_compaction_enabled,
    )
    from app.services.compression import (
        _get_compression_keep_turns,
        _get_compression_threshold,
        _is_compression_enabled,
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

    compression_enabled = _is_compression_enabled(bot, channel)
    compression_keep_turns = _get_compression_keep_turns(bot, channel) if compression_enabled else None
    compression_threshold = _get_compression_threshold(bot, channel) if compression_enabled else None

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
        "compression": {
            "enabled": compression_enabled,
            "keep_turns": compression_keep_turns,
            "threshold_chars": compression_threshold,
        },
    }


@router.get("/{session_id}/plans")
async def get_session_plans(
    session_id: uuid.UUID,
    status: Optional[str] = "active",
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Return plans for a session with their items."""
    stmt = select(Plan).where(Plan.session_id == session_id)
    if status and status != "all":
        stmt = stmt.where(Plan.status == status)
    stmt = stmt.order_by(Plan.created_at)
    plans = (await db.execute(stmt)).scalars().all()

    result = []
    for plan in plans:
        items = (await db.execute(
            select(PlanItem).where(PlanItem.plan_id == plan.id).order_by(PlanItem.position)
        )).scalars().all()
        result.append({
            "id": str(plan.id),
            "title": plan.title,
            "description": plan.description,
            "status": plan.status,
            "created_at": plan.created_at.isoformat(),
            "items": [
                {
                    "id": str(i.id),
                    "position": i.position,
                    "content": i.content,
                    "status": i.status,
                    "notes": i.notes,
                }
                for i in items
            ],
        })
    return result


@router.post("/{session_id}/plans/{plan_id}/status")
async def update_plan_status(
    session_id: uuid.UUID,
    plan_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Update a plan's status. Body: {status: active|complete|abandoned}"""
    plan = await db.get(Plan, plan_id)
    if not plan or plan.session_id != session_id:
        raise HTTPException(status_code=404, detail="Plan not found")
    new_status = body.get("status")
    if new_status not in ("active", "complete", "abandoned"):
        raise HTTPException(status_code=400, detail="Invalid status")
    plan.status = new_status
    await db.commit()
    return {"ok": True}


@router.post("/{session_id}/plans/{plan_id}/items/{item_position}/status")
async def update_plan_item_status(
    session_id: uuid.UUID,
    plan_id: uuid.UUID,
    item_position: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Update a plan item's status by 1-based position. Body: {status: pending|in_progress|done|skipped}"""
    plan = await db.get(Plan, plan_id)
    if not plan or plan.session_id != session_id:
        raise HTTPException(status_code=404, detail="Plan not found")
    result = await db.execute(
        select(PlanItem)
        .where(PlanItem.plan_id == plan_id, PlanItem.position == item_position - 1)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item {item_position} not found")
    new_status = body.get("status")
    if new_status not in ("pending", "in_progress", "done", "skipped"):
        raise HTTPException(status_code=400, detail="Invalid status")
    item.status = new_status
    await db.commit()
    return {"ok": True}


class SummarizeResponse(BaseModel):
    title: str
    summary: str


@router.post("/{session_id}/summarize", response_model=SummarizeResponse)
async def summarize_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
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
