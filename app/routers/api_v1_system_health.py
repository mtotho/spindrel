"""System Health Summary API.

Read-only surface for the daily-summary landmark on the spatial canvas.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SystemHealthSummary
from app.dependencies import get_db, require_scopes


router = APIRouter(prefix="/system-health", tags=["system-health"])


def _serialize(row: SystemHealthSummary, *, include_findings: bool = True) -> dict:
    return {
        "id": str(row.id),
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "error_count": int(row.error_count or 0),
        "critical_count": int(row.critical_count or 0),
        "trace_event_count": int(row.trace_event_count or 0),
        "tool_error_count": int(row.tool_error_count or 0),
        "source_counts": row.source_counts or {},
        "findings": list(row.findings or []) if include_findings else [],
        "attention_item_id": str(row.attention_item_id) if row.attention_item_id else None,
        "attention_item_refs": list(row.attention_item_refs or []),
    }


@router.get("/summaries/latest")
async def get_latest_summary(
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(SystemHealthSummary).order_by(desc(SystemHealthSummary.generated_at)).limit(1)
    )).scalar_one_or_none()
    if row is None:
        return {"summary": None, "message": "No daily summary has been generated yet."}
    return {"summary": _serialize(row)}


@router.get("/summaries")
async def list_summaries(
    limit: int = 14,
    include_findings: bool = False,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    capped = max(1, min(int(limit or 14), 60))
    rows = (await db.execute(
        select(SystemHealthSummary)
        .order_by(desc(SystemHealthSummary.generated_at))
        .limit(capped)
    )).scalars().all()
    return {"summaries": [_serialize(r, include_findings=include_findings) for r in rows]}


@router.get("/summaries/{summary_id}")
async def get_summary(
    summary_id: uuid.UUID,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SystemHealthSummary, summary_id)
    if row is None:
        raise HTTPException(404, "summary not found")
    return {"summary": _serialize(row)}
