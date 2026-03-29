"""Usage Limits admin API — /admin/limits/"""
from __future__ import annotations

import uuid as _uuid
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageLimit
from app.dependencies import get_db
from app.services.usage_limits import load_limits, get_limits_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/limits", tags=["Usage Limits"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class UsageLimitCreate(BaseModel):
    scope_type: str  # "model" or "bot"
    scope_value: str
    period: str  # "daily" or "monthly"
    limit_usd: float
    enabled: bool = True


class UsageLimitUpdate(BaseModel):
    limit_usd: Optional[float] = None
    enabled: Optional[bool] = None


class UsageLimitOut(BaseModel):
    id: str
    scope_type: str
    scope_value: str
    period: str
    limit_usd: float
    enabled: bool
    created_at: str
    updated_at: str


class UsageLimitStatusOut(BaseModel):
    id: str
    scope_type: str
    scope_value: str
    period: str
    limit_usd: float
    current_spend: float
    percentage: float
    enabled: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[UsageLimitOut])
async def list_limits(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(UsageLimit).order_by(UsageLimit.created_at.desc())
    )).scalars().all()
    return [
        UsageLimitOut(
            id=str(r.id),
            scope_type=r.scope_type,
            scope_value=r.scope_value,
            period=r.period,
            limit_usd=r.limit_usd,
            enabled=r.enabled,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )
        for r in rows
    ]


@router.post("/", response_model=UsageLimitOut, status_code=201)
async def create_limit(body: UsageLimitCreate, db: AsyncSession = Depends(get_db)):
    if body.scope_type not in ("model", "bot"):
        raise HTTPException(400, "scope_type must be 'model' or 'bot'")
    if body.period not in ("daily", "monthly"):
        raise HTTPException(400, "period must be 'daily' or 'monthly'")
    if body.limit_usd <= 0:
        raise HTTPException(400, "limit_usd must be positive")

    # Check uniqueness
    existing = (await db.execute(
        select(UsageLimit).where(
            UsageLimit.scope_type == body.scope_type,
            UsageLimit.scope_value == body.scope_value,
            UsageLimit.period == body.period,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "A limit for this scope_type/scope_value/period already exists")

    row = UsageLimit(
        id=_uuid.uuid4(),
        scope_type=body.scope_type,
        scope_value=body.scope_value,
        period=body.period,
        limit_usd=body.limit_usd,
        enabled=body.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await load_limits()

    return UsageLimitOut(
        id=str(row.id),
        scope_type=row.scope_type,
        scope_value=row.scope_value,
        period=row.period,
        limit_usd=row.limit_usd,
        enabled=row.enabled,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


@router.put("/{limit_id}", response_model=UsageLimitOut)
async def update_limit(limit_id: str, body: UsageLimitUpdate, db: AsyncSession = Depends(get_db)):
    try:
        uid = _uuid.UUID(limit_id)
    except ValueError:
        raise HTTPException(400, "Invalid limit_id")

    row = await db.get(UsageLimit, uid)
    if not row:
        raise HTTPException(404, "Limit not found")

    if body.limit_usd is not None:
        if body.limit_usd <= 0:
            raise HTTPException(400, "limit_usd must be positive")
        row.limit_usd = body.limit_usd
    if body.enabled is not None:
        row.enabled = body.enabled

    from datetime import datetime, timezone
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    await load_limits()

    return UsageLimitOut(
        id=str(row.id),
        scope_type=row.scope_type,
        scope_value=row.scope_value,
        period=row.period,
        limit_usd=row.limit_usd,
        enabled=row.enabled,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


@router.delete("/{limit_id}", status_code=204)
async def delete_limit(limit_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = _uuid.UUID(limit_id)
    except ValueError:
        raise HTTPException(400, "Invalid limit_id")

    row = await db.get(UsageLimit, uid)
    if not row:
        raise HTTPException(404, "Limit not found")

    await db.delete(row)
    await db.commit()
    await load_limits()


@router.get("/status", response_model=list[UsageLimitStatusOut])
async def limits_status():
    return await get_limits_status()
