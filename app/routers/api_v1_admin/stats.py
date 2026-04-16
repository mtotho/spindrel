"""GET /stats endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import list_bots
from app.db.models import (
    SandboxInstance,
    Session,
    ToolCall,
    ToolEmbedding,
)
from app.dependencies import get_db, require_scopes

router = APIRouter()


class DashboardStats(BaseModel):
    bot_count: int
    session_count: int
    tool_count: int
    tool_call_count: int
    sandbox_running_count: int


@router.get("/stats", response_model=DashboardStats)
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    """Dashboard overview stats — mirrors the /admin index page."""
    session_count = (await db.execute(
        select(func.count()).select_from(Session)
    )).scalar_one()
    tool_count = (await db.execute(
        select(func.count()).select_from(ToolEmbedding)
    )).scalar_one()
    tool_call_count = (await db.execute(
        select(func.count()).select_from(ToolCall)
    )).scalar_one()
    sandbox_running = (await db.execute(
        select(func.count()).select_from(SandboxInstance)
        .where(SandboxInstance.status == "running")
    )).scalar_one()

    bots = list_bots()

    return DashboardStats(
        bot_count=len(bots),
        session_count=session_count,
        tool_count=tool_count,
        tool_call_count=tool_call_count,
        sandbox_running_count=sandbox_running,
    )
