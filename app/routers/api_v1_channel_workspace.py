"""API v1 — Channel Workspace file browser endpoints."""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel
from app.dependencies import get_db, verify_auth_or_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/channels/{channel_id}/workspace", tags=["Channel Workspace"])


class FileWriteBody(BaseModel):
    content: str


def _get_bot(bot_id: str):
    from app.agent.bots import get_bot
    return get_bot(bot_id)


def _schedule_reindex(channel_id: str, bot):
    """Fire-and-forget background re-index for channel workspace."""
    from app.services.channel_workspace_indexing import index_channel_workspace
    asyncio.create_task(index_channel_workspace(channel_id, bot))


async def _require_channel_workspace(
    channel_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[Channel, object]:
    """Load channel, verify workspace is enabled, return (channel, bot)."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace is not enabled")
    bot = _get_bot(channel.bot_id)
    return channel, bot


@router.get("/files")
async def list_workspace_files(
    channel_id: uuid.UUID,
    include_archive: bool = Query(False, description="Include archived files"),
    include_data: bool = Query(False, description="Include data/ files"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """List files in the channel workspace."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import list_workspace_files as _list
    files = _list(str(channel_id), bot, include_archive=include_archive, include_data=include_data)
    return {"files": files}


@router.get("/files/content")
async def read_workspace_file(
    channel_id: uuid.UUID,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Read a file from the channel workspace."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import read_workspace_file as _read
    content = _read(str(channel_id), bot, path)
    if content is None:
        raise HTTPException(404, "File not found")
    return {"path": path, "content": content}


@router.put("/files/content")
async def write_workspace_file(
    channel_id: uuid.UUID,
    body: FileWriteBody,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Write a file to the channel workspace."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import (
        ensure_channel_workspace,
        write_workspace_file as _write,
    )
    ensure_channel_workspace(str(channel_id), bot)
    try:
        result = _write(str(channel_id), bot, path, body.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _schedule_reindex(str(channel_id), bot)
    return result


@router.delete("/files")
async def delete_workspace_file(
    channel_id: uuid.UUID,
    path: str = Query(..., description="File path to delete"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Delete a file from the channel workspace."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import delete_workspace_file as _delete
    try:
        result = _delete(str(channel_id), bot, path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    _schedule_reindex(str(channel_id), bot)
    return result


@router.post("/files/upload")
async def upload_workspace_file(
    channel_id: uuid.UUID,
    file: UploadFile = File(...),
    path: str = Query("", description="Optional subdirectory path"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Upload a file to the channel workspace."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import (
        ensure_channel_workspace,
        write_workspace_file as _write,
    )
    ensure_channel_workspace(str(channel_id), bot)

    filename = file.filename or "upload.md"
    file_path = f"{path}/{filename}" if path else filename
    content = (await file.read()).decode("utf-8", errors="replace")

    try:
        result = _write(str(channel_id), bot, file_path, content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _schedule_reindex(str(channel_id), bot)
    return result
