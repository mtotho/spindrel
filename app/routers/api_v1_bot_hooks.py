"""Bot hooks CRUD API — /api/v1/bot-hooks"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BotHook
from app.dependencies import get_db, require_scopes
from app.services.bot_hooks import VALID_TRIGGERS, BLOCKING_TRIGGERS, load_bot_hooks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bot-hooks", tags=["Bot Hooks"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BotHookCreate(BaseModel):
    bot_id: str
    name: str
    trigger: str
    conditions: dict = {}
    command: str
    cooldown_seconds: int = 60
    on_failure: Optional[str] = None
    enabled: bool = True


class BotHookUpdate(BaseModel):
    name: Optional[str] = None
    trigger: Optional[str] = None
    conditions: Optional[dict] = None
    command: Optional[str] = None
    cooldown_seconds: Optional[int] = None
    on_failure: Optional[str] = None
    enabled: Optional[bool] = None


class BotHookOut(BaseModel):
    id: uuid.UUID
    bot_id: str
    name: str
    trigger: str
    conditions: dict
    command: str
    cooldown_seconds: int
    on_failure: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_trigger(trigger: str) -> None:
    if trigger not in VALID_TRIGGERS:
        raise HTTPException(
            status_code=422,
            detail=f"trigger must be one of: {', '.join(sorted(VALID_TRIGGERS))}",
        )


def _validate_on_failure(on_failure: str) -> None:
    if on_failure not in ("block", "warn"):
        raise HTTPException(status_code=422, detail="on_failure must be 'block' or 'warn'")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[BotHookOut])
async def list_bot_hooks(
    bot_id: Optional[str] = None,
    _auth=Depends(require_scopes("bot_hooks:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(BotHook).order_by(BotHook.created_at.asc())
    if bot_id is not None:
        stmt = stmt.where(BotHook.bot_id == bot_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [BotHookOut.model_validate(r) for r in rows]


@router.get("/{hook_id}", response_model=BotHookOut)
async def get_bot_hook(
    hook_id: uuid.UUID,
    _auth=Depends(require_scopes("bot_hooks:read")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(BotHook, hook_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bot hook not found")
    return BotHookOut.model_validate(row)


@router.post("", response_model=BotHookOut, status_code=201)
async def create_bot_hook(
    body: BotHookCreate,
    _auth=Depends(require_scopes("bot_hooks:write")),
    db: AsyncSession = Depends(get_db),
):
    _validate_trigger(body.trigger)
    on_failure = body.on_failure
    if on_failure:
        _validate_on_failure(on_failure)
    else:
        on_failure = "block" if body.trigger in BLOCKING_TRIGGERS else "warn"

    row = BotHook(
        bot_id=body.bot_id,
        name=body.name,
        trigger=body.trigger,
        conditions=body.conditions,
        command=body.command,
        cooldown_seconds=body.cooldown_seconds,
        on_failure=on_failure,
        enabled=body.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await load_bot_hooks()
    return BotHookOut.model_validate(row)


@router.put("/{hook_id}", response_model=BotHookOut)
async def update_bot_hook(
    hook_id: uuid.UUID,
    body: BotHookUpdate,
    _auth=Depends(require_scopes("bot_hooks:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(BotHook, hook_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bot hook not found")
    if body.trigger is not None:
        _validate_trigger(body.trigger)
    if body.on_failure is not None:
        _validate_on_failure(body.on_failure)
    updates = body.model_dump(exclude_unset=True)
    for key, val in updates.items():
        setattr(row, key, val)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    await load_bot_hooks()
    return BotHookOut.model_validate(row)


@router.delete("/{hook_id}", status_code=204)
async def delete_bot_hook(
    hook_id: uuid.UUID,
    _auth=Depends(require_scopes("bot_hooks:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(BotHook, hook_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bot hook not found")
    await db.delete(row)
    await db.commit()
    await load_bot_hooks()
