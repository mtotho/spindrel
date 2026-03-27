"""Tool approval API — /api/v1/approvals"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolApproval
from app.dependencies import get_db, verify_admin_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approvals", tags=["Approvals"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ApprovalOut(BaseModel):
    id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    channel_id: Optional[uuid.UUID] = None
    bot_id: str
    client_id: Optional[str] = None
    correlation_id: Optional[uuid.UUID] = None
    tool_name: str
    tool_type: str
    arguments: dict
    policy_rule_id: Optional[uuid.UUID] = None
    reason: Optional[str] = None
    status: str
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    dispatch_type: Optional[str] = None
    dispatch_metadata: Optional[dict] = None
    timeout_seconds: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DecideRequest(BaseModel):
    approved: bool
    decided_by: str = "api:admin"


class DecideResponse(BaseModel):
    id: uuid.UUID
    status: str
    decided_by: str
    decided_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    bot_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ToolApproval).order_by(ToolApproval.created_at.desc())
    if bot_id:
        stmt = stmt.where(ToolApproval.bot_id == bot_id)
    if status:
        stmt = stmt.where(ToolApproval.status == status)
    stmt = stmt.offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [ApprovalOut.model_validate(r) for r in rows]


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: uuid.UUID,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ToolApproval, approval_id)
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    return ApprovalOut.model_validate(row)


@router.post("/{approval_id}/decide", response_model=DecideResponse)
async def decide_approval(
    approval_id: uuid.UUID,
    body: DecideRequest,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ToolApproval, approval_id)
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval already {row.status}")

    verdict = "approved" if body.approved else "denied"
    now = datetime.now(timezone.utc)
    row.status = verdict
    row.decided_by = body.decided_by
    row.decided_at = now
    await db.commit()
    await db.refresh(row)

    # Resolve the in-process Future (if the agent loop is still waiting)
    from app.agent.approval_pending import resolve_approval
    resolved = resolve_approval(str(approval_id), verdict)
    if not resolved:
        logger.info("Approval %s decided but no waiting future (may have expired)", approval_id)

    return DecideResponse(
        id=row.id,
        status=row.status,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
    )
