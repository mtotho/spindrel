"""Fallback events & circuit breaker cooldowns: /fallbacks, /fallbacks/cooldowns."""
from __future__ import annotations

import uuid
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelFallbackEvent
from app.dependencies import get_db, require_scopes

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FallbackEventOut(BaseModel):
    id: str
    model: str
    fallback_model: str
    reason: str
    error_message: Optional[str] = None
    session_id: Optional[str] = None
    channel_id: Optional[str] = None
    bot_id: Optional[str] = None
    cooldown_until: Optional[str] = None
    created_at: Optional[str] = None


class FallbackEventsListOut(BaseModel):
    events: list[FallbackEventOut]


class CooldownOut(BaseModel):
    model: str
    fallback_model: str
    expires_at: str
    remaining_seconds: int


class CooldownsListOut(BaseModel):
    cooldowns: list[CooldownOut]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/fallbacks", response_model=FallbackEventsListOut)
async def list_fallback_events(
    model: Optional[str] = None,
    bot_id: Optional[str] = None,
    count: int = Query(50, ge=1, le=500),
    after: Optional[str] = None,
    before: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("logs:read")),
):
    """List recent model fallback events."""
    stmt = select(ModelFallbackEvent).order_by(ModelFallbackEvent.created_at.desc())

    if model:
        stmt = stmt.where(ModelFallbackEvent.model == model)
    if bot_id:
        stmt = stmt.where(ModelFallbackEvent.bot_id == bot_id)
    if after:
        stmt = stmt.where(ModelFallbackEvent.created_at > after)
    if before:
        stmt = stmt.where(ModelFallbackEvent.created_at < before)

    stmt = stmt.limit(count)
    rows = (await db.execute(stmt)).scalars().all()

    events = [
        FallbackEventOut(
            id=str(r.id),
            model=r.model,
            fallback_model=r.fallback_model,
            reason=r.reason,
            error_message=r.error_message,
            session_id=str(r.session_id) if r.session_id else None,
            channel_id=str(r.channel_id) if r.channel_id else None,
            bot_id=r.bot_id,
            cooldown_until=r.cooldown_until.isoformat() if r.cooldown_until else None,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return FallbackEventsListOut(events=events)


@router.get("/fallbacks/cooldowns", response_model=CooldownsListOut)
async def list_active_cooldowns(
    _auth=Depends(require_scopes("logs:read")),
):
    """List active in-memory circuit breaker cooldowns."""
    from app.agent.llm import get_active_cooldowns

    entries = get_active_cooldowns()
    return CooldownsListOut(cooldowns=[CooldownOut(**e) for e in entries])


@router.delete("/fallbacks/cooldowns/{model:path}")
async def clear_cooldown(
    model: str,
    _auth=Depends(require_scopes("logs:write")),
):
    """Clear the circuit breaker cooldown for a specific model."""
    from app.agent.llm import clear_model_cooldown

    decoded = unquote(model)
    found = clear_model_cooldown(decoded)
    return {"ok": True, "cleared": found, "model": decoded}
