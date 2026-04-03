"""API endpoints for /api/v1/attachments — Phase 3 scaffold."""
import os
import re
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Attachment
from app.dependencies import get_db, require_scopes, verify_auth_or_user

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
_SAFE_FILENAME_RE = re.compile(r"[^\w.\- ]")

router = APIRouter(prefix="/attachments", tags=["Attachments"])


class AttachmentOut(BaseModel):
    id: uuid.UUID
    message_id: Optional[uuid.UUID] = None
    channel_id: Optional[uuid.UUID] = None
    type: str
    url: Optional[str] = None
    filename: str
    mime_type: str
    size_bytes: int
    posted_by: Optional[str] = None
    source_integration: str
    description: Optional[str] = None
    description_model: Optional[str] = None
    described_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/{attachment_id}", response_model=AttachmentOut)
async def get_attachment(
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("attachments:read")),
):
    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return att


async def _verify_token_or_header(
    token: Optional[str],
    authorization: Optional[str],
    db: AsyncSession,
) -> None:
    """Accept static API key, scoped API key, or JWT — via query param or header."""
    from app.config import settings

    # Collect the raw bearer value from whichever source is available
    raw = token
    if not raw and authorization and authorization.startswith("Bearer "):
        raw = authorization.removeprefix("Bearer ")
    if not raw:
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    # Static API key
    if raw == settings.API_KEY:
        return

    # Scoped API key
    if raw.startswith("ask_"):
        from app.services.api_keys import validate_api_key
        if await validate_api_key(db, raw) is not None:
            return
        raise HTTPException(status_code=401, detail="Invalid API key")

    # JWT access token
    from app.services.auth import decode_access_token, get_user_by_id
    import jwt as _jwt
    try:
        payload = decode_access_token(raw)
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    from uuid import UUID as _UUID
    user = await get_user_by_id(db, _UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")


@router.get("/{attachment_id}/file")
async def get_attachment_file(
    attachment_id: uuid.UUID,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Serve raw file data for an attachment. Accepts auth via query param for <img> tags."""
    await _verify_token_or_header(token, authorization, db)

    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if att.file_data is None:
        raise HTTPException(status_code=404, detail="No file data stored")
    return Response(
        content=att.file_data,
        media_type=att.mime_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("", response_model=list[AttachmentOut])
async def list_attachments(
    channel_id: Optional[uuid.UUID] = Query(None),
    message_id: Optional[uuid.UUID] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("attachments:read")),
):
    q = select(Attachment)
    if channel_id:
        q = q.where(Attachment.channel_id == channel_id)
    if message_id:
        q = q.where(Attachment.message_id == message_id)
    if type:
        q = q.where(Attachment.type == type)
    q = q.order_by(Attachment.created_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/upload", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    file: UploadFile = File(...),
    channel_id: uuid.UUID = Form(...),
    _auth=Depends(require_scopes("attachments:write")),
):
    """Upload a file as a standalone attachment (no message)."""
    from app.services.attachments import create_attachment

    # Read with size limit
    file_data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)")

    mime = file.content_type or "application/octet-stream"
    # Sanitize filename — strip path components, limit chars
    filename = os.path.basename(file.filename or "upload")
    filename = _SAFE_FILENAME_RE.sub("_", filename)[:255]

    attachment = await create_attachment(
        message_id=None,
        channel_id=channel_id,
        filename=filename,
        mime_type=mime,
        size_bytes=len(file_data),
        posted_by=None,
        source_integration="web",
        file_data=file_data,
    )
    return attachment
