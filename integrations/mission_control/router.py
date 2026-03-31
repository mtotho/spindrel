"""FastAPI router for Mission Control — overview aggregation and workspace file proxy."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, Channel, Session, Task
from app.dependencies import get_db, verify_auth

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/ping")
async def ping():
    return {"status": "ok", "service": "mission-control"}


# ---------------------------------------------------------------------------
# Overview — aggregated data for the global dashboard
# ---------------------------------------------------------------------------

class OverviewChannel(BaseModel):
    id: str
    name: str | None
    bot_id: str | None
    workspace_enabled: bool
    created_at: str | None
    updated_at: str | None

    class Config:
        from_attributes = True


@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth),
):
    """Aggregated global data for the dashboard overview page.

    Returns channel list, bot list, task counts, and stats in a single call.
    """
    # Channels
    channels_result = await db.execute(
        select(Channel).order_by(Channel.updated_at.desc()).limit(100)
    )
    channels = channels_result.scalars().all()

    # Bots
    bots_result = await db.execute(select(Bot).order_by(Bot.name))
    bots = bots_result.scalars().all()

    # Task counts by status
    task_counts_result = await db.execute(
        select(Task.status, func.count(Task.id)).group_by(Task.status)
    )
    task_counts = {row[0]: row[1] for row in task_counts_result.all()}

    # Active sessions count
    session_count_result = await db.execute(
        select(func.count(Session.id))
    )
    session_count = session_count_result.scalar() or 0

    return {
        "channels": [
            {
                "id": str(ch.id),
                "name": ch.name,
                "bot_id": ch.bot_id,
                "workspace_enabled": ch.channel_workspace_enabled,
                "created_at": ch.created_at.isoformat() if ch.created_at else None,
                "updated_at": ch.updated_at.isoformat() if ch.updated_at else None,
            }
            for ch in channels
        ],
        "bots": [
            {
                "id": bot.id,
                "name": bot.name,
                "model": bot.model,
            }
            for bot in bots
        ],
        "task_counts": task_counts,
        "session_count": session_count,
        "channel_count": len(channels),
        "bot_count": len(bots),
    }


# ---------------------------------------------------------------------------
# Workspace file proxy — reads/writes channel workspace files
# ---------------------------------------------------------------------------

class FileWriteBody(BaseModel):
    content: str


def _get_bot(bot_id: str):
    from app.agent.bots import get_bot
    return get_bot(bot_id)


async def _require_channel(
    channel_id: uuid.UUID,
    db: AsyncSession,
) -> Channel:
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    return channel


@router.get("/channels/{channel_id}/workspace/files")
async def list_workspace_files(
    channel_id: uuid.UUID,
    include_archive: bool = Query(False),
    include_data: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth),
):
    """List files in a channel's workspace."""
    channel = await _require_channel(channel_id, db)
    if not channel.channel_workspace_enabled:
        return {"files": []}
    bot = _get_bot(channel.bot_id)
    from app.services.channel_workspace import list_workspace_files as _list
    try:
        files = _list(str(channel_id), bot, include_archive=include_archive, include_data=include_data)
    except Exception:
        logger.exception("Failed to list workspace files for channel %s", channel_id)
        return {"files": []}
    return {"files": files}


@router.get("/channels/{channel_id}/workspace/files/content")
async def read_workspace_file(
    channel_id: uuid.UUID,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth),
):
    """Read a file from a channel's workspace."""
    channel = await _require_channel(channel_id, db)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")
    bot = _get_bot(channel.bot_id)
    from app.services.channel_workspace import read_workspace_file as _read
    content = _read(str(channel_id), bot, path)
    if content is None:
        raise HTTPException(404, "File not found")
    return {"path": path, "content": content}


@router.put("/channels/{channel_id}/workspace/files/content")
async def write_workspace_file(
    channel_id: uuid.UUID,
    body: FileWriteBody,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth),
):
    """Write a file to a channel's workspace (write-back from dashboard)."""
    channel = await _require_channel(channel_id, db)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")
    bot = _get_bot(channel.bot_id)
    from app.services.channel_workspace import (
        ensure_channel_workspace,
        write_workspace_file as _write,
    )
    ensure_channel_workspace(str(channel_id), bot, display_name=channel.name)
    try:
        result = _write(str(channel_id), bot, path, body.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return result
