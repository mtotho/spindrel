"""Workspace Mission Control API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.workspace_mission_control import build_mission_control


router = APIRouter(prefix="/workspace/mission-control", tags=["workspace-mission-control"])


@router.get("")
async def get_mission_control(
    include_completed: bool = False,
    limit: int = Query(100, ge=1, le=250),
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return await build_mission_control(
        db,
        auth=auth,
        include_completed=include_completed,
        limit=limit,
    )
