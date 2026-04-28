"""API v1 — Channel Workspace file browser endpoints."""
from __future__ import annotations

import asyncio
import glob as glob_mod
import logging
import os
import re
import shutil
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel
from app.config import settings
from app.dependencies import get_db, require_scopes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/channels/{channel_id}/workspace", tags=["Channel Workspace"])
_SAFE_UPLOAD_FILENAME_RE = re.compile(r"[^\w.\- ]")
_UPLOAD_CHUNK_BYTES = 1024 * 1024


class FileWriteBody(BaseModel):
    content: str


class FileMoveBody(BaseModel):
    old_path: str
    new_path: str


class FileRestoreBody(BaseModel):
    version: str  # .bak filename from the versions listing


def _get_bot(bot_id: str):
    from app.agent.bots import get_bot
    return get_bot(bot_id)


def _schedule_reindex(channel_id: str, bot):
    """Fire-and-forget background re-index for channel workspace."""
    from app.services.bot_indexing import reindex_channel
    asyncio.create_task(reindex_channel(channel_id, bot))


async def _require_channel_workspace(
    channel_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[Channel, object]:
    """Load channel, return (channel, bot). Workspace is always provisioned."""
    channel = await db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
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


@router.get("/html-widgets")
async def list_html_widgets(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """List standalone HTML widgets found in the channel workspace.

    Walks any ``.html`` under a ``widgets/`` directory plus any ``.html``
    referencing ``window.spindrel.*``. Frontmatter (YAML inside a leading
    HTML comment) drives the display name / description / tags.
    """
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.html_widget_scanner import scan_channel
    widgets = scan_channel(str(channel_id), bot)
    return {"widgets": widgets}


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


def _resolve_channel_path(channel_id: uuid.UUID, bot, path: str) -> str:
    """Resolve a channel-relative path to its absolute, sandbox-safe form."""
    from app.services.channel_workspace import get_channel_workspace_root
    ws_path = get_channel_workspace_root(str(channel_id), bot)
    ws_real = os.path.realpath(ws_path)
    target = os.path.realpath(os.path.join(ws_path, path))
    if not (target == ws_real or target.startswith(ws_real + os.sep)):
        raise HTTPException(404, "File not found")
    return target


def _safe_upload_filename(filename: str | None) -> str:
    base = os.path.basename(filename or "upload")
    cleaned = _SAFE_UPLOAD_FILENAME_RE.sub("_", base).strip(" .")
    return cleaned[:255] or "upload"


def _dedupe_upload_path(directory: str, filename: str) -> tuple[str, str]:
    stem, ext = os.path.splitext(filename)
    candidate = filename
    idx = 1
    while os.path.exists(os.path.join(directory, candidate)):
        suffix = f"-{idx}"
        candidate = f"{stem[:255 - len(ext) - len(suffix)]}{suffix}{ext}"
        idx += 1
    return candidate, os.path.join(directory, candidate)


async def _write_upload_stream(file: UploadFile, target: str, max_bytes: int) -> int:
    written = 0
    try:
        with open(target, "wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (max {max_bytes // (1024 * 1024)} MB)",
                    )
                out.write(chunk)
    except Exception:
        try:
            if os.path.exists(target):
                os.remove(target)
        finally:
            raise
    return written


@router.get("/files/versions")
async def list_workspace_file_versions(
    channel_id: uuid.UUID,
    path: str = Query(..., description="File path within workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:read")),
):
    """List `.versions/` backups for a workspace file.

    The `.versions/` directory is hidden from the bot's `file(list)` tool on
    purpose — we don't want agents churning backup listings into LLM context.
    But users need a way to recover from a bad overwrite, so we surface the
    listing via API for the File History UI.
    """
    channel, bot = await _require_channel_workspace(channel_id, db)
    target = _resolve_channel_path(channel_id, bot, path)
    parent = os.path.dirname(target)
    basename = os.path.basename(target)
    versions_dir = os.path.join(parent, ".versions")
    if not os.path.isdir(versions_dir):
        return {"path": path, "versions": []}

    pattern = os.path.join(versions_dir, f"{basename}.*.bak")
    backups = sorted(glob_mod.glob(pattern), key=os.path.getmtime, reverse=True)
    versions = []
    for bp in backups:
        try:
            st = os.stat(bp)
        except OSError:
            continue
        versions.append({
            "version": os.path.basename(bp),
            "bytes": st.st_size,
            "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        })
    return {"path": path, "versions": versions}


@router.post("/files/restore")
async def restore_workspace_file(
    channel_id: uuid.UUID,
    body: FileRestoreBody,
    path: str = Query(..., description="File path to restore"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
):
    """Restore a workspace file from a `.versions/` backup.

    The current live file is itself backed up before being overwritten, so
    restore is undoable via another restore.
    """
    channel, bot = await _require_channel_workspace(channel_id, db)
    if "/" in body.version or ".." in body.version:
        raise HTTPException(400, "version must be a plain filename")
    target = _resolve_channel_path(channel_id, bot, path)
    basename = os.path.basename(target)
    if not body.version.startswith(basename + "."):
        raise HTTPException(400, f"Backup does not belong to {basename}")

    parent = os.path.dirname(target)
    versions_dir = os.path.join(parent, ".versions")
    backup_path = os.path.join(versions_dir, body.version)
    if not os.path.isfile(backup_path):
        raise HTTPException(404, "Backup not found")

    # Back up current state first so the restore itself is undoable.
    prior_backup = None
    if os.path.isfile(target):
        ts = f"{time.time():.4f}".replace(".", "-")
        prior_backup = os.path.join(versions_dir, f"{basename}.{ts}.bak")
        try:
            shutil.copy2(target, prior_backup)
        except OSError as e:
            raise HTTPException(500, f"Failed to back up current file: {e}") from e

    try:
        shutil.copy2(backup_path, target)
    except OSError as e:
        raise HTTPException(500, f"Restore failed: {e}") from e

    _schedule_reindex(str(channel_id), bot)
    return {
        "path": path,
        "restored_from": body.version,
        "prior_backup": os.path.basename(prior_backup) if prior_backup else None,
        "bytes": os.path.getsize(target),
    }


@router.post("/files/upload")
async def upload_workspace_file(
    channel_id: uuid.UUID,
    file: UploadFile = File(...),
    path: str = Query("", description="Optional subdirectory path"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("channels:write")),
):
    """Upload a file to the channel workspace with streamed size enforcement."""
    channel, bot = await _require_channel_workspace(channel_id, db)
    from app.services.channel_workspace import ensure_channel_workspace, get_channel_workspace_root
    ensure_channel_workspace(str(channel_id), bot, display_name=channel.name)

    filename = _safe_upload_filename(file.filename)
    ws_path = get_channel_workspace_root(str(channel_id), bot)
    ws_real = os.path.realpath(ws_path)
    target_dir = os.path.realpath(os.path.join(ws_real, path)) if path else ws_real
    if not (target_dir == ws_real or target_dir.startswith(ws_real + os.sep)):
        raise HTTPException(400, "Path escapes workspace root")
    os.makedirs(target_dir, exist_ok=True)
    final_filename, target = _dedupe_upload_path(target_dir, filename)
    try:
        size = await _write_upload_stream(file, target, settings.CHANNEL_DATA_UPLOAD_MAX_BYTES)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    rel_path = os.path.relpath(target, ws_real)
    result = {
        "path": rel_path,
        "size": size,
        "filename": final_filename,
        "mime_type": file.content_type or "application/octet-stream",
    }
    _schedule_reindex(str(channel_id), bot)
    return result
