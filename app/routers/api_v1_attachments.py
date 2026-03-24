"""API endpoints for /api/v1/attachments — Phase 3 scaffold."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Attachment
from app.dependencies import get_db, verify_auth

router = APIRouter(prefix="/attachments", tags=["Attachments"])


class AttachmentOut(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    channel_id: Optional[uuid.UUID]
    type: str
    url: str
    filename: str
    mime_type: str
    size_bytes: int
    posted_by: Optional[str]
    source_integration: str
    description: Optional[str]
    description_model: Optional[str]
    described_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/{attachment_id}", response_model=AttachmentOut)
async def get_attachment(
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return att


def _verify_token_or_header(
    token: Optional[str],
    authorization: Optional[str],
) -> None:
    from app.config import settings
    if token and token == settings.API_KEY:
        return
    if authorization and authorization.startswith("Bearer "):
        if authorization.removeprefix("Bearer ") == settings.API_KEY:
            return
    raise HTTPException(status_code=401, detail="Invalid or missing token")


@router.get("/{attachment_id}/file")
async def get_attachment_file(
    attachment_id: uuid.UUID,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Serve raw file data for an attachment. Accepts auth via query param for <img> tags."""
    _verify_token_or_header(token, authorization)

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
    _auth: str = Depends(verify_auth),
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
