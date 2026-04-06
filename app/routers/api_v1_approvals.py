"""Tool approval API — /api/v1/approvals"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
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
    safety_tier: Optional[str] = None

    model_config = {"from_attributes": True}


class DecideRequest(BaseModel):
    approved: bool
    decided_by: str = "api:admin"
    # Optional: create an allow rule along with the approval
    # {tool_name, conditions, scope ("bot"|"global"), priority}
    create_rule: Optional[dict] = None
    # Optional: pin a capability (carapace ID) to the bot's permanent list
    pin_capability: Optional[str] = None


class DecideResponse(BaseModel):
    id: uuid.UUID
    status: str
    decided_by: str
    decided_at: datetime
    rule_created: Optional[uuid.UUID] = None  # ID of the created rule, if any
    capability_pinned: Optional[str] = None  # set if capability was pinned


class SuggestionOut(BaseModel):
    label: str
    tool_name: str
    conditions: dict
    description: str
    scope: str = "bot"


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
    from app.tools.registry import get_tool_safety_tier

    stmt = select(ToolApproval).order_by(ToolApproval.created_at.desc())
    if bot_id:
        stmt = stmt.where(ToolApproval.bot_id == bot_id)
    if status:
        stmt = stmt.where(ToolApproval.status == status)
    stmt = stmt.offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    result = []
    for r in rows:
        out = ApprovalOut.model_validate(r)
        out.safety_tier = get_tool_safety_tier(r.tool_name)
        result.append(out)
    return result


@router.get("/{approval_id}/suggestions", response_model=list[SuggestionOut])
async def get_approval_suggestions(
    approval_id: uuid.UUID,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return smart allow-rule suggestions based on the approval's tool + arguments."""
    row = await db.get(ToolApproval, approval_id)
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")

    # Count recent approvals for this bot+tool to power escalation hints
    recent_count = await _count_recent_approvals(db, row.bot_id, row.tool_name)

    from app.services.approval_suggestions import build_suggestions
    from app.tools.registry import get_tool_safety_tier
    tier = get_tool_safety_tier(row.tool_name)
    suggestions = build_suggestions(
        row.tool_name, row.arguments or {},
        recent_approval_count=recent_count,
        safety_tier=tier,
    )
    return [SuggestionOut(
        label=s.label, tool_name=s.tool_name,
        conditions=s.conditions, description=s.description,
        scope=s.scope,
    ) for s in suggestions]


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: uuid.UUID,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    from app.tools.registry import get_tool_safety_tier

    row = await db.get(ToolApproval, approval_id)
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    out = ApprovalOut.model_validate(row)
    out.safety_tier = get_tool_safety_tier(row.tool_name)
    return out


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

    # Optionally create an allow rule
    rule_id = None
    if body.create_rule and body.approved:
        from app.db.models import ToolPolicyRule
        from app.services.tool_policies import invalidate_cache
        # scope: "global" sets bot_id=NULL so rule applies to all bots
        scope = body.create_rule.get("scope", "bot")
        rule = ToolPolicyRule(
            bot_id=None if scope == "global" else row.bot_id,
            tool_name=body.create_rule.get("tool_name", row.tool_name),
            action="allow",
            conditions=body.create_rule.get("conditions", {}),
            priority=body.create_rule.get("priority", 50),
            reason=f"Allowed by {body.decided_by}",
        )
        db.add(rule)
        await db.flush()
        rule_id = rule.id
        invalidate_cache()

    # Optionally pin a capability to the bot's carapace list
    pinned_cap = None
    if body.pin_capability and body.approved:
        from sqlalchemy.orm.attributes import flag_modified
        from app.db.models import Bot as BotRow
        bot_row = await db.get(BotRow, row.bot_id)
        if bot_row:
            current = list(bot_row.carapaces or [])
            if body.pin_capability not in current:
                current.append(body.pin_capability)
                bot_row.carapaces = current
                flag_modified(bot_row, "carapaces")
            pinned_cap = body.pin_capability

    # Session-scoped allow: when approving (even without a permanent rule),
    # allow this tool for the rest of this conversation so the user isn't
    # asked again for the same tool in the same agent run.
    if body.approved and row.correlation_id:
        from app.agent.session_allows import add_session_allow
        add_session_allow(str(row.correlation_id), row.tool_name)

    await db.commit()
    await db.refresh(row)

    # Reload bots if a capability was pinned (so it takes effect immediately)
    if pinned_cap:
        from app.agent.bots import reload_bots
        await reload_bots()

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
        rule_created=rule_id,
        capability_pinned=pinned_cap,
    )


async def _count_recent_approvals(
    db: AsyncSession, bot_id: str, tool_name: str,
) -> int:
    """Count approved approvals for this bot+tool (for escalation hints)."""
    stmt = (
        select(func.count())
        .select_from(ToolApproval)
        .where(
            ToolApproval.bot_id == bot_id,
            ToolApproval.tool_name == tool_name,
            ToolApproval.status == "approved",
        )
    )
    result = await db.execute(stmt)
    return result.scalar() or 0
