"""Upcoming activity endpoint: /upcoming-activity."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.upcoming_activity import list_upcoming_activity

router = APIRouter()


@router.get("/upcoming-activity")
async def upcoming_activity(
    limit: int = Query(50, ge=1, le=1000),
    type: str | None = Query(None, description="Filter by type: heartbeat, task, memory_hygiene"),
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("admin")),
):
    """Return a merged, chronologically sorted list of upcoming heartbeats, tasks, and memory hygiene runs."""
    items = await list_upcoming_activity(
        db,
        limit=limit,
        type_filter=type,
        auth=auth,
        include_memory_hygiene=True,
        include_channelless_tasks=True,
    )
    return {"items": items}
