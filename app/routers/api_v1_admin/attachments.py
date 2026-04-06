"""Admin attachment management — list, stats, delete, purge."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Attachment, Channel
from app.dependencies import get_db, require_scopes

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AttachmentAdminOut(BaseModel):
    id: uuid.UUID
    message_id: Optional[uuid.UUID] = None
    channel_id: Optional[uuid.UUID] = None
    channel_name: Optional[str] = None
    type: str
    url: Optional[str] = None
    filename: str
    mime_type: str
    size_bytes: int
    has_file_data: bool = False
    posted_by: Optional[str] = None
    source_integration: str
    description: Optional[str] = None
    created_at: datetime


class AttachmentListOut(BaseModel):
    attachments: list[AttachmentAdminOut]
    total: int


class AttachmentGlobalStats(BaseModel):
    total_count: int
    with_file_data_count: int
    total_size_bytes: int
    by_type: dict[str, int]
    by_channel: list[dict]


class PurgeRequest(BaseModel):
    before_date: datetime
    channel_id: Optional[uuid.UUID] = None
    type: Optional[str] = None
    purge_file_data_only: bool = False


class PurgeResult(BaseModel):
    purged_count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/attachments", response_model=AttachmentListOut)
async def list_attachments(
    channel_id: Optional[uuid.UUID] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("attachments:read")),
):
    """List attachments with pagination and filters."""
    base = select(Attachment)
    if channel_id:
        base = base.where(Attachment.channel_id == channel_id)
    if type:
        base = base.where(Attachment.type == type)

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    rows = (await db.execute(
        base.order_by(Attachment.created_at.desc())
        .limit(limit).offset(offset)
    )).scalars().all()

    # Batch-load channel names
    ch_ids = {r.channel_id for r in rows if r.channel_id}
    ch_names: dict[uuid.UUID, str] = {}
    if ch_ids:
        ch_rows = (await db.execute(
            select(Channel.id, Channel.name).where(Channel.id.in_(ch_ids))
        )).all()
        ch_names = {r.id: r.name for r in ch_rows}

    attachments = [
        AttachmentAdminOut(
            id=r.id,
            message_id=r.message_id,
            channel_id=r.channel_id,
            channel_name=ch_names.get(r.channel_id) if r.channel_id else None,
            type=r.type,
            url=r.url,
            filename=r.filename,
            mime_type=r.mime_type,
            size_bytes=r.size_bytes,
            has_file_data=r.file_data is not None,
            posted_by=r.posted_by,
            source_integration=r.source_integration,
            description=r.description,
            created_at=r.created_at,
        )
        for r in rows
    ]

    return AttachmentListOut(attachments=attachments, total=total)


@router.get("/attachments/stats", response_model=AttachmentGlobalStats)
async def attachment_global_stats(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("attachments:read")),
):
    """Global attachment storage stats."""
    row = (await db.execute(
        select(
            func.count().label("total_count"),
            func.count().filter(Attachment.file_data.is_not(None)).label("with_file_data_count"),
            func.coalesce(func.sum(Attachment.size_bytes).filter(Attachment.file_data.is_not(None)), 0).label("total_size_bytes"),
        )
    )).one()

    # By type breakdown
    type_rows = (await db.execute(
        select(Attachment.type, func.count().label("cnt"))
        .group_by(Attachment.type)
        .order_by(func.count().desc())
    )).all()
    by_type = {r.type: r.cnt for r in type_rows}

    # Top 10 channels by attachment count
    ch_rows = (await db.execute(
        select(
            Attachment.channel_id,
            Channel.name.label("channel_name"),
            func.count().label("cnt"),
            func.coalesce(func.sum(Attachment.size_bytes).filter(Attachment.file_data.is_not(None)), 0).label("size_bytes"),
        )
        .outerjoin(Channel, Attachment.channel_id == Channel.id)
        .where(Attachment.channel_id.is_not(None))
        .group_by(Attachment.channel_id, Channel.name)
        .order_by(func.count().desc())
        .limit(10)
    )).all()
    by_channel = [
        {
            "channel_id": str(r.channel_id),
            "channel_name": r.channel_name,
            "count": r.cnt,
            "size_bytes": r.size_bytes,
        }
        for r in ch_rows
    ]

    return AttachmentGlobalStats(
        total_count=row.total_count,
        with_file_data_count=row.with_file_data_count,
        total_size_bytes=row.total_size_bytes,
        by_type=by_type,
        by_channel=by_channel,
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("attachments:write")),
):
    """Hard delete an attachment."""
    att = await db.get(Attachment, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    await db.delete(att)
    await db.commit()


@router.post("/attachments/purge", response_model=PurgeResult)
async def purge_attachments(
    body: PurgeRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("attachments:write")),
):
    """Bulk purge attachments by date and optional filters."""
    if body.purge_file_data_only:
        # Just null out file_data column
        from sqlalchemy import update
        stmt = (
            update(Attachment)
            .where(Attachment.created_at < body.before_date)
            .where(Attachment.file_data.is_not(None))
        )
        if body.channel_id:
            stmt = stmt.where(Attachment.channel_id == body.channel_id)
        if body.type:
            stmt = stmt.where(Attachment.type == body.type)
        stmt = stmt.values(file_data=None)
        result = await db.execute(stmt)
        await db.commit()
        return PurgeResult(purged_count=result.rowcount)

    # Hard delete
    stmt = delete(Attachment).where(Attachment.created_at < body.before_date)
    if body.channel_id:
        stmt = stmt.where(Attachment.channel_id == body.channel_id)
    if body.type:
        stmt = stmt.where(Attachment.type == body.type)
    result = await db.execute(stmt)
    await db.commit()
    return PurgeResult(purged_count=result.rowcount)
