"""Admin user management API — /api/v1/admin/users."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, User
from app.dependencies import get_db, require_scopes
from app.services.auth import create_local_user, get_user_by_id, hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None
    integration_config: dict
    is_admin: bool
    is_active: bool
    auth_method: str
    created_at: str


class CreateUserRequest(BaseModel):
    email: str
    display_name: str
    password: str


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None
    integration_config: dict | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    password: str | None = None  # reset password (local only)


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        display_name=u.display_name,
        avatar_url=u.avatar_url,
        integration_config=u.integration_config or {},
        is_admin=u.is_admin,
        is_active=u.is_active,
        auth_method=u.auth_method,
        created_at=u.created_at.isoformat() if u.created_at else "",
    )


@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:read")),
):
    result = await db.execute(select(User).order_by(User.created_at))
    return [_user_out(u) for u in result.scalars().all()]


@router.post("", response_model=UserOut)
async def create_user(
    req: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:write")),
):
    user = await create_local_user(db, req.email, req.display_name, req.password)
    return _user_out(user)


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:write")),
):
    from uuid import UUID
    user = await get_user_by_id(db, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.avatar_url is not None:
        user.avatar_url = req.avatar_url
    if req.integration_config is not None:
        user.integration_config = req.integration_config
    if req.is_admin is not None:
        user.is_admin = req.is_admin
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.password is not None and user.auth_method == "local":
        user.password_hash = hash_password(req.password)
    await db.commit()
    await db.refresh(user)
    return _user_out(user)


@router.delete("/{user_id}")
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:write")),
):
    from uuid import UUID
    user = await get_user_by_id(db, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    await db.commit()
    return {"status": "deactivated"}


@router.get("/identity-suggestions/{integration}")
async def identity_suggestions(
    integration: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:read")),
):
    """Return distinct sender IDs for an integration, excluding already-claimed ones."""
    prefix = f"{integration}:"
    stmt = select(distinct(Message.metadata_["sender_id"].astext)).where(
        Message.metadata_["sender_id"].astext.like(f"{prefix}%"),
        Message.metadata_["sender_type"].astext == "human",
    )
    result = await db.execute(stmt)
    all_ids = [row[0].removeprefix(prefix) for row in result.all()]

    # Filter out claimed
    users_result = await db.execute(select(User))
    users = users_result.scalars().all()
    claimed = {
        u.integration_config.get(integration, {}).get("user_id")
        for u in users if u.integration_config
    }
    return [uid for uid in all_ids if uid not in claimed]
