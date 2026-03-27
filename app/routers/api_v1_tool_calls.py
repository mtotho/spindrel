"""Tool audit API — /api/v1/tool-calls"""
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolCall
from app.dependencies import get_db, verify_admin_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tool-calls", tags=["Tool Audit"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ToolCallOut(BaseModel):
    id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    bot_id: Optional[str] = None
    client_id: Optional[str] = None
    tool_name: str
    tool_type: str
    server_name: Optional[str] = None
    iteration: Optional[int] = None
    arguments: dict
    result: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    correlation_id: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ToolCallDetail(ToolCallOut):
    """Full detail — includes untruncated result."""
    pass


class ToolCallStatGroup(BaseModel):
    key: str
    count: int
    total_duration_ms: int
    avg_duration_ms: int
    error_count: int


class ToolCallStatsResponse(BaseModel):
    group_by: str
    stats: list[ToolCallStatGroup]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ToolCallOut])
async def list_tool_calls(
    bot_id: Optional[str] = Query(None),
    tool_name: Optional[str] = Query(None),
    tool_type: Optional[str] = Query(None),
    session_id: Optional[uuid.UUID] = Query(None),
    error_only: bool = Query(False),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ToolCall).order_by(ToolCall.created_at.desc())
    if bot_id:
        stmt = stmt.where(ToolCall.bot_id == bot_id)
    if tool_name:
        stmt = stmt.where(ToolCall.tool_name == tool_name)
    if tool_type:
        stmt = stmt.where(ToolCall.tool_type == tool_type)
    if session_id:
        stmt = stmt.where(ToolCall.session_id == session_id)
    if error_only:
        stmt = stmt.where(ToolCall.error.isnot(None))
    if since:
        stmt = stmt.where(ToolCall.created_at >= since)
    if until:
        stmt = stmt.where(ToolCall.created_at <= until)
    stmt = stmt.offset(offset).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    # Truncate result for list view
    out = []
    for row in rows:
        d = ToolCallOut.model_validate(row)
        if d.result and len(d.result) > 500:
            d.result = d.result[:500] + "…"
        out.append(d)
    return out


@router.get("/stats", response_model=ToolCallStatsResponse)
async def tool_call_stats(
    group_by: str = Query("tool_name", pattern="^(tool_name|bot_id|tool_type)$"),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    bot_id: Optional[str] = Query(None),
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    col_map = {
        "tool_name": ToolCall.tool_name,
        "bot_id": ToolCall.bot_id,
        "tool_type": ToolCall.tool_type,
    }
    group_col = col_map[group_by]

    stmt = (
        select(
            group_col.label("key"),
            func.count().label("count"),
            func.coalesce(func.sum(ToolCall.duration_ms), 0).label("total_duration_ms"),
            func.coalesce(func.avg(ToolCall.duration_ms), 0).label("avg_duration_ms"),
            func.count(ToolCall.error).label("error_count"),
        )
        .group_by(group_col)
        .order_by(func.count().desc())
    )
    if since:
        stmt = stmt.where(ToolCall.created_at >= since)
    if until:
        stmt = stmt.where(ToolCall.created_at <= until)
    if bot_id:
        stmt = stmt.where(ToolCall.bot_id == bot_id)

    rows = (await db.execute(stmt)).all()
    stats = [
        ToolCallStatGroup(
            key=str(r.key or "(none)"),
            count=r.count,
            total_duration_ms=int(r.total_duration_ms),
            avg_duration_ms=int(r.avg_duration_ms),
            error_count=r.error_count,
        )
        for r in rows
    ]
    return ToolCallStatsResponse(group_by=group_by, stats=stats)


@router.get("/{tool_call_id}", response_model=ToolCallDetail)
async def get_tool_call(
    tool_call_id: uuid.UUID,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ToolCall, tool_call_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tool call not found")
    return ToolCallDetail.model_validate(row)
