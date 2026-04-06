"""API v1 — Channel Workspace file browser endpoints."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel
from app.dependencies import get_db, require_scopes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/channels/{channel_id}/workspace", tags=["Channel Workspace"])


class FileWriteBody(BaseModel):
    content: str


class FileMoveBody(BaseModel):
    old_path: str
    new_path: str


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
    data_prefix: str | None = Query(None, description="Subfolder within data/ to list (e.g. 'spindrel')"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """List files in the channel workspace."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import list_workspace_files as _list
    files = _list(str(channel_id), bot, include_archive=include_archive, include_data=include_data, data_prefix=data_prefix)
    return {"files": files}


@router.get("/files/content")
async def read_workspace_file(
    channel_id: uuid.UUID,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """Read a file from the channel workspace."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import read_workspace_file as _read
    content = _read(str(channel_id), bot, path)
    if content is None:
        raise HTTPException(404, "File not found")
    return {"path": path, "content": content}


MIME_MAP = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".ico": "image/x-icon", ".bmp": "image/bmp", ".pdf": "application/pdf",
}


@router.get("/files/raw")
async def read_workspace_file_raw(
    channel_id: uuid.UUID,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """Serve a workspace file as raw bytes (for images, PDFs, etc.)."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import get_channel_workspace_root
    ws_path = get_channel_workspace_root(str(channel_id), bot)
    ws_real = os.path.realpath(ws_path)
    target = os.path.realpath(os.path.join(ws_path, path))
    if not (target == ws_real or target.startswith(ws_real + os.sep)):
        raise HTTPException(404, "File not found")
    if not os.path.isfile(target):
        raise HTTPException(404, "File not found")
    ext = os.path.splitext(target)[1].lower()
    mime = MIME_MAP.get(ext, "application/octet-stream")
    with open(target, "rb") as f:
        data = f.read()
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=300"})


@router.put("/files/content")
async def write_workspace_file(
    channel_id: uuid.UUID,
    body: FileWriteBody,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
):
    """Write a file to the channel workspace."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import (
        ensure_channel_workspace,
        write_workspace_file as _write,
    )
    ensure_channel_workspace(str(channel_id), bot, display_name=channel.name)
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
    _auth=Depends(require_scopes("channels:write")),
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


@router.post("/files/move")
async def move_workspace_file(
    channel_id: uuid.UUID,
    body: FileMoveBody,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
):
    """Move/rename a file within the channel workspace."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import move_workspace_file as _move
    try:
        result = _move(str(channel_id), bot, body.old_path, body.new_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    _schedule_reindex(str(channel_id), bot)
    return result


# File extensions treated as text (written via UTF-8 text writer)
_TEXT_EXTENSIONS = frozenset({
    ".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".xml", ".html",
    ".css", ".js", ".ts", ".tsx", ".jsx", ".py", ".sh", ".toml", ".ini",
    ".cfg", ".conf", ".log", ".env", ".sql", ".graphql", ".rst", ".tex",
    ".r", ".rb", ".go", ".java", ".kt", ".swift", ".c", ".cpp", ".h",
    ".hpp", ".rs", ".lua", ".pl", ".pm",
})


def _is_text_file(filename: str) -> bool:
    """Check if a filename should be treated as text based on extension."""
    _, ext = os.path.splitext(filename.lower())
    return ext in _TEXT_EXTENSIONS


@router.post("/files/upload")
async def upload_workspace_file(
    channel_id: uuid.UUID,
    file: UploadFile = File(...),
    path: str = Query("", description="Optional subdirectory path"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
):
    """Upload a file to the channel workspace. Text files are stored as UTF-8; binary files are stored as-is."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import (
        ensure_channel_workspace,
        write_workspace_file as _write_text,
        write_workspace_file_binary as _write_binary,
    )
    ensure_channel_workspace(str(channel_id), bot, display_name=channel.name)

    filename = file.filename or "upload.md"
    file_path = f"{path}/{filename}" if path else filename
    raw_bytes = await file.read()

    try:
        if _is_text_file(filename):
            result = _write_text(str(channel_id), bot, file_path, raw_bytes.decode("utf-8", errors="replace"))
        else:
            result = _write_binary(str(channel_id), bot, file_path, raw_bytes)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _schedule_reindex(str(channel_id), bot)
    return result
