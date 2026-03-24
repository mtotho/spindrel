"""Elevation observability endpoints — config + recent decisions."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db, verify_auth_or_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ElevationLogEntry(BaseModel):
    id: str
    turn_id: Optional[str] = None
    bot_id: str
    channel_id: Optional[str] = None
    iteration: int = 0
    base_model: str
    model_chosen: str
    was_elevated: bool
    classifier_score: float
    elevation_reason: Optional[str] = None
    rules_fired: list = []
    signal_scores: dict = {}
    tokens_used: Optional[int] = None
    latency_ms: Optional[int] = None
    created_at: str


class ElevationConfigOut(BaseModel):
    enabled: Optional[bool] = None
    threshold: Optional[float] = None
    elevated_model: Optional[str] = None
    # Resolved effective values (accounting for global defaults)
    effective_enabled: bool = False
    effective_threshold: float = 0.4
    effective_elevated_model: str = ""


class ElevationOverview(BaseModel):
    config: ElevationConfigOut
    recent: list[ElevationLogEntry]
    stats: dict


class ElevationConfigUpdate(BaseModel):
    elevation_enabled: Optional[bool] = None
    elevation_threshold: Optional[float] = None
    elevated_model: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_recent_logs(
    db: AsyncSession, *, bot_id: str | None = None, channel_id: uuid.UUID | None = None, limit: int = 20,
) -> list[ElevationLogEntry]:
    from app.db.models import ModelElevationLog

    q = select(ModelElevationLog).order_by(ModelElevationLog.created_at.desc()).limit(limit)
    if bot_id:
        q = q.where(ModelElevationLog.bot_id == bot_id)
    if channel_id:
        q = q.where(ModelElevationLog.channel_id == channel_id)

    rows = (await db.execute(q)).scalars().all()
    return [
        ElevationLogEntry(
            id=str(r.id),
            turn_id=str(r.turn_id) if r.turn_id else None,
            bot_id=r.bot_id,
            channel_id=str(r.channel_id) if r.channel_id else None,
            iteration=r.iteration,
            base_model=r.base_model,
            model_chosen=r.model_chosen,
            was_elevated=r.was_elevated,
            classifier_score=r.classifier_score,
            elevation_reason=r.elevation_reason,
            rules_fired=r.rules_fired or [],
            signal_scores=r.signal_scores or {},
            tokens_used=r.tokens_used,
            latency_ms=r.latency_ms,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


async def _get_stats(
    db: AsyncSession, *, bot_id: str | None = None, channel_id: uuid.UUID | None = None,
) -> dict:
    from app.db.models import ModelElevationLog

    base_q = select(func.count()).select_from(ModelElevationLog)
    elev_q = select(func.count()).select_from(ModelElevationLog).where(ModelElevationLog.was_elevated == True)
    avg_score_q = select(func.avg(ModelElevationLog.classifier_score)).select_from(ModelElevationLog)
    avg_latency_q = select(func.avg(ModelElevationLog.latency_ms)).select_from(ModelElevationLog).where(ModelElevationLog.latency_ms.isnot(None))

    if bot_id:
        base_q = base_q.where(ModelElevationLog.bot_id == bot_id)
        elev_q = elev_q.where(ModelElevationLog.bot_id == bot_id)
        avg_score_q = avg_score_q.where(ModelElevationLog.bot_id == bot_id)
        avg_latency_q = avg_latency_q.where(ModelElevationLog.bot_id == bot_id)
    if channel_id:
        base_q = base_q.where(ModelElevationLog.channel_id == channel_id)
        elev_q = elev_q.where(ModelElevationLog.channel_id == channel_id)
        avg_score_q = avg_score_q.where(ModelElevationLog.channel_id == channel_id)
        avg_latency_q = avg_latency_q.where(ModelElevationLog.channel_id == channel_id)

    total = (await db.execute(base_q)).scalar() or 0
    elevated = (await db.execute(elev_q)).scalar() or 0
    avg_score = (await db.execute(avg_score_q)).scalar()
    avg_latency = (await db.execute(avg_latency_q)).scalar()

    return {
        "total_decisions": total,
        "elevated_count": elevated,
        "elevation_rate": round(elevated / total, 4) if total > 0 else 0,
        "avg_score": round(avg_score, 4) if avg_score is not None else 0,
        "avg_latency_ms": round(avg_latency, 1) if avg_latency is not None else None,
    }


# ---------------------------------------------------------------------------
# Bot elevation endpoints
# ---------------------------------------------------------------------------

@router.get("/bots/{bot_id}/elevation", response_model=ElevationOverview)
async def get_bot_elevation(
    bot_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.db.models import Bot
    bot_row = await db.get(Bot, bot_id)
    if not bot_row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Bot not found")

    config = ElevationConfigOut(
        enabled=bot_row.elevation_enabled,
        threshold=bot_row.elevation_threshold,
        elevated_model=bot_row.elevated_model,
        effective_enabled=bot_row.elevation_enabled if bot_row.elevation_enabled is not None else settings.MODEL_ELEVATION_ENABLED,
        effective_threshold=bot_row.elevation_threshold if bot_row.elevation_threshold is not None else settings.MODEL_ELEVATION_THRESHOLD,
        effective_elevated_model=bot_row.elevated_model or settings.MODEL_ELEVATED_MODEL,
    )
    recent = await _get_recent_logs(db, bot_id=bot_id, limit=limit)
    stats = await _get_stats(db, bot_id=bot_id)
    return ElevationOverview(config=config, recent=recent, stats=stats)


@router.patch("/bots/{bot_id}/elevation", response_model=ElevationConfigOut)
async def update_bot_elevation(
    bot_id: str,
    data: ElevationConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.db.models import Bot
    bot_row = await db.get(Bot, bot_id)
    if not bot_row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Bot not found")

    updates = {}
    if data.elevation_enabled is not None:
        updates["elevation_enabled"] = data.elevation_enabled
    if data.elevation_threshold is not None:
        updates["elevation_threshold"] = data.elevation_threshold
    if data.elevated_model is not None:
        updates["elevated_model"] = data.elevated_model or None

    if updates:
        await db.execute(update(Bot).where(Bot.id == bot_id).values(**updates))
        await db.commit()
        await db.refresh(bot_row)

    from app.agent.bots import reload_bots
    await reload_bots()

    return ElevationConfigOut(
        enabled=bot_row.elevation_enabled,
        threshold=bot_row.elevation_threshold,
        elevated_model=bot_row.elevated_model,
        effective_enabled=bot_row.elevation_enabled if bot_row.elevation_enabled is not None else settings.MODEL_ELEVATION_ENABLED,
        effective_threshold=bot_row.elevation_threshold if bot_row.elevation_threshold is not None else settings.MODEL_ELEVATION_THRESHOLD,
        effective_elevated_model=bot_row.elevated_model or settings.MODEL_ELEVATED_MODEL,
    )


# ---------------------------------------------------------------------------
# Channel elevation endpoints
# ---------------------------------------------------------------------------

@router.get("/channels/{channel_id}/elevation", response_model=ElevationOverview)
async def get_channel_elevation(
    channel_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.db.models import Channel
    ch = await db.get(Channel, channel_id)
    if not ch:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Channel not found")

    config = ElevationConfigOut(
        enabled=ch.elevation_enabled,
        threshold=ch.elevation_threshold,
        elevated_model=ch.elevated_model,
        effective_enabled=ch.elevation_enabled if ch.elevation_enabled is not None else settings.MODEL_ELEVATION_ENABLED,
        effective_threshold=ch.elevation_threshold if ch.elevation_threshold is not None else settings.MODEL_ELEVATION_THRESHOLD,
        effective_elevated_model=ch.elevated_model or settings.MODEL_ELEVATED_MODEL,
    )
    recent = await _get_recent_logs(db, channel_id=channel_id, limit=limit)
    stats = await _get_stats(db, channel_id=channel_id)
    return ElevationOverview(config=config, recent=recent, stats=stats)


@router.patch("/channels/{channel_id}/elevation", response_model=ElevationConfigOut)
async def update_channel_elevation(
    channel_id: uuid.UUID,
    data: ElevationConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.db.models import Channel
    ch = await db.get(Channel, channel_id)
    if not ch:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Channel not found")

    updates = {}
    if data.elevation_enabled is not None:
        updates["elevation_enabled"] = data.elevation_enabled
    if data.elevation_threshold is not None:
        updates["elevation_threshold"] = data.elevation_threshold
    if data.elevated_model is not None:
        updates["elevated_model"] = data.elevated_model or None

    if updates:
        await db.execute(update(Channel).where(Channel.id == channel_id).values(**updates))
        await db.commit()
        await db.refresh(ch)

    return ElevationConfigOut(
        enabled=ch.elevation_enabled,
        threshold=ch.elevation_threshold,
        elevated_model=ch.elevated_model,
        effective_enabled=ch.elevation_enabled if ch.elevation_enabled is not None else settings.MODEL_ELEVATION_ENABLED,
        effective_threshold=ch.elevation_threshold if ch.elevation_threshold is not None else settings.MODEL_ELEVATION_THRESHOLD,
        effective_elevated_model=ch.elevated_model or settings.MODEL_ELEVATED_MODEL,
    )
