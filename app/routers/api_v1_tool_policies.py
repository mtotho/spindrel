"""Tool policy rules CRUD API — /api/v1/tool-policies"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolPolicyRule
from app.dependencies import get_db, verify_admin_auth
from app.services.tool_policies import PolicyDecision, evaluate_tool_policy, invalidate_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tool-policies", tags=["Tool Policies"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PolicyRuleCreate(BaseModel):
    bot_id: Optional[str] = None
    tool_name: str
    action: str  # "allow" | "deny" | "require_approval"
    conditions: dict = {}
    priority: int = 100
    approval_timeout: int = 300
    reason: Optional[str] = None
    enabled: bool = True


class PolicyRuleUpdate(BaseModel):
    bot_id: Optional[str] = None
    tool_name: Optional[str] = None
    action: Optional[str] = None
    conditions: Optional[dict] = None
    priority: Optional[int] = None
    approval_timeout: Optional[int] = None
    reason: Optional[str] = None
    enabled: Optional[bool] = None


class PolicyRuleOut(BaseModel):
    id: uuid.UUID
    bot_id: Optional[str] = None
    tool_name: str
    action: str
    conditions: dict
    priority: int
    approval_timeout: int
    reason: Optional[str] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PolicyTestRequest(BaseModel):
    bot_id: str
    tool_name: str
    arguments: dict[str, Any] = {}


class PolicyTestResponse(BaseModel):
    action: str
    rule_id: Optional[str] = None
    reason: Optional[str] = None
    timeout: int = 300


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_ACTIONS = {"allow", "deny", "require_approval"}


def _validate_action(action: str) -> None:
    if action not in _VALID_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"action must be one of: {', '.join(sorted(_VALID_ACTIONS))}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PolicyRuleOut])
async def list_policy_rules(
    bot_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ToolPolicyRule).order_by(ToolPolicyRule.priority.asc(), ToolPolicyRule.created_at.asc())
    if bot_id is not None:
        stmt = stmt.where(ToolPolicyRule.bot_id == bot_id)
    if tool_name is not None:
        stmt = stmt.where(ToolPolicyRule.tool_name == tool_name)
    rows = (await db.execute(stmt)).scalars().all()
    return [PolicyRuleOut.model_validate(r) for r in rows]


@router.post("", response_model=PolicyRuleOut, status_code=201)
async def create_policy_rule(
    body: PolicyRuleCreate,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    _validate_action(body.action)
    rule = ToolPolicyRule(
        bot_id=body.bot_id,
        tool_name=body.tool_name,
        action=body.action,
        conditions=body.conditions,
        priority=body.priority,
        approval_timeout=body.approval_timeout,
        reason=body.reason,
        enabled=body.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    invalidate_cache()
    return PolicyRuleOut.model_validate(rule)


@router.put("/{rule_id}", response_model=PolicyRuleOut)
async def update_policy_rule(
    rule_id: uuid.UUID,
    body: PolicyRuleUpdate,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    rule = await db.get(ToolPolicyRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Policy rule not found")
    if body.action is not None:
        _validate_action(body.action)
    updates = body.model_dump(exclude_unset=True)
    for key, val in updates.items():
        setattr(rule, key, val)
    rule.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(rule)
    invalidate_cache()
    return PolicyRuleOut.model_validate(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_policy_rule(
    rule_id: uuid.UUID,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    rule = await db.get(ToolPolicyRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Policy rule not found")
    await db.delete(rule)
    await db.commit()
    invalidate_cache()


@router.post("/test", response_model=PolicyTestResponse)
async def test_policy(
    body: PolicyTestRequest,
    _auth=Depends(verify_admin_auth),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run: evaluate policies for given inputs and return the decision."""
    decision = await evaluate_tool_policy(db, body.bot_id, body.tool_name, body.arguments)
    return PolicyTestResponse(
        action=decision.action,
        rule_id=decision.rule_id,
        reason=decision.reason,
        timeout=decision.timeout,
    )
