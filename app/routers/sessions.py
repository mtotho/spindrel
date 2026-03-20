import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.config import settings
from app.db.models import Memory, Message, Plan, PlanItem, Session, TraceEvent
from app.dependencies import get_db, verify_auth
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
    _auth: str = Depends(verify_auth),
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
    _auth: str = Depends(verify_auth),
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


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
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
    _auth: str = Depends(verify_auth),
):
    """Return the most recent context_breakdown trace event for the session."""
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


@router.get("/{session_id}/plans")
async def get_session_plans(
    session_id: uuid.UUID,
    status: Optional[str] = "active",
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
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
    _auth: str = Depends(verify_auth),
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
    _auth: str = Depends(verify_auth),
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
    _auth: str = Depends(verify_auth),
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
