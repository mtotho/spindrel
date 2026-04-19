"""Bot grants CRUD — admin-only per-user access to a bot.

Grants are what let a non-admin user mint a widget token for a bot they
don't own, and see that bot in channel-creation pickers. Role is stored
for forward-compat but today only ``'view'`` is accepted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow, BotGrant, User
from app.dependencies import get_db, require_scopes

router = APIRouter()


_ACCEPTED_ROLES = {"view"}


class GrantOut(BaseModel):
    bot_id: str
    user_id: str
    user_display_name: str
    user_email: str
    role: str
    granted_by: Optional[str] = None
    granted_by_display_name: Optional[str] = None
    created_at: datetime


class GrantCreateIn(BaseModel):
    user_id: str
    role: str = "view"


class BulkGrantIn(BaseModel):
    user_ids: list[str]
    role: str = "view"


async def _require_bot(db: AsyncSession, bot_id: str) -> BotRow:
    bot = await db.get(BotRow, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    return bot


def _parse_user_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid user_id")


def _validate_role(role: str) -> str:
    if role not in _ACCEPTED_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported role '{role}'. Accepted: {sorted(_ACCEPTED_ROLES)}",
        )
    return role


async def _serialize_grants(db: AsyncSession, grants: list[BotGrant]) -> list[GrantOut]:
    if not grants:
        return []
    user_ids: set[uuid.UUID] = set()
    for g in grants:
        user_ids.add(g.user_id)
        if g.granted_by is not None:
            user_ids.add(g.granted_by)
    users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    by_id = {u.id: u for u in users}
    out: list[GrantOut] = []
    for g in grants:
        grantee = by_id.get(g.user_id)
        granter = by_id.get(g.granted_by) if g.granted_by is not None else None
        out.append(GrantOut(
            bot_id=g.bot_id,
            user_id=str(g.user_id),
            user_display_name=grantee.display_name if grantee else "(deleted user)",
            user_email=grantee.email if grantee else "",
            role=g.role,
            granted_by=str(g.granted_by) if g.granted_by else None,
            granted_by_display_name=granter.display_name if granter else None,
            created_at=g.created_at,
        ))
    return out


@router.get("/bots/{bot_id}/grants", response_model=list[GrantOut])
async def list_bot_grants(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:read")),
):
    await _require_bot(db, bot_id)
    rows = (await db.execute(
        select(BotGrant).where(BotGrant.bot_id == bot_id).order_by(BotGrant.created_at)
    )).scalars().all()
    return await _serialize_grants(db, list(rows))


@router.post("/bots/{bot_id}/grants", response_model=GrantOut, status_code=201)
async def create_bot_grant(
    bot_id: str,
    body: GrantCreateIn,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("bots:write")),
):
    await _require_bot(db, bot_id)
    user_uuid = _parse_user_uuid(body.user_id)
    role = _validate_role(body.role)

    user = await db.get(User, user_uuid)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {body.user_id} not found")

    existing = await db.scalar(
        select(BotGrant).where(
            and_(BotGrant.bot_id == bot_id, BotGrant.user_id == user_uuid)
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"User already has a grant on bot {bot_id}",
        )

    granter_id = auth.id if isinstance(auth, User) else None
    grant = BotGrant(
        bot_id=bot_id,
        user_id=user_uuid,
        role=role,
        granted_by=granter_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    serialized = await _serialize_grants(db, [grant])
    return serialized[0]


@router.delete("/bots/{bot_id}/grants/{user_id}", status_code=204)
async def delete_bot_grant(
    bot_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("bots:write")),
):
    await _require_bot(db, bot_id)
    user_uuid = _parse_user_uuid(user_id)
    result = await db.execute(
        delete(BotGrant).where(
            and_(BotGrant.bot_id == bot_id, BotGrant.user_id == user_uuid)
        )
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Grant not found")
    return None


@router.post("/bots/{bot_id}/grants/bulk", response_model=list[GrantOut])
async def bulk_create_bot_grants(
    bot_id: str,
    body: BulkGrantIn,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_scopes("bots:write")),
):
    """Idempotent bulk grant — skip users who already have a grant."""
    await _require_bot(db, bot_id)
    role = _validate_role(body.role)

    wanted: list[uuid.UUID] = []
    for raw in body.user_ids:
        wanted.append(_parse_user_uuid(raw))

    if not wanted:
        return []

    # Filter to existing users
    users = (await db.execute(select(User).where(User.id.in_(wanted)))).scalars().all()
    valid_ids = {u.id for u in users}
    missing = [str(uid) for uid in wanted if uid not in valid_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Users not found: {missing}")

    existing = (await db.execute(
        select(BotGrant.user_id).where(
            and_(BotGrant.bot_id == bot_id, BotGrant.user_id.in_(list(valid_ids)))
        )
    )).scalars().all()
    skip = set(existing)

    granter_id = auth.id if isinstance(auth, User) else None
    new_grants: list[BotGrant] = []
    now = datetime.now(timezone.utc)
    for uid in wanted:
        if uid in skip:
            continue
        grant = BotGrant(
            bot_id=bot_id,
            user_id=uid,
            role=role,
            granted_by=granter_id,
            created_at=now,
        )
        db.add(grant)
        new_grants.append(grant)
    await db.commit()

    all_rows = (await db.execute(
        select(BotGrant).where(
            and_(BotGrant.bot_id == bot_id, BotGrant.user_id.in_(list(valid_ids)))
        )
    )).scalars().all()
    return await _serialize_grants(db, list(all_rows))
