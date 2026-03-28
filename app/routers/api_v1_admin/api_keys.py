"""API Key CRUD: /api-keys."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey as ApiKeyRow
from app.dependencies import get_db, verify_auth_or_user
from app.services.api_keys import (
    ALL_SCOPES,
    SCOPE_DESCRIPTIONS,
    SCOPE_GROUPS,
    create_api_key,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreateIn(BaseModel):
    name: str
    scopes: list[str] = []
    expires_at: Optional[datetime] = None
    store_key_value: bool = False


class ApiKeyCreateOut(BaseModel):
    key: ApiKeyOut
    full_key: str


class ApiKeyUpdateIn(BaseModel):
    name: Optional[str] = None
    scopes: Optional[list[str]] = None
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None


class ScopeGroupOut(BaseModel):
    description: str
    scopes: list[str]


class ScopeGroupsOut(BaseModel):
    groups: dict[str, ScopeGroupOut]
    all_scopes: list[str]
    descriptions: dict[str, str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _key_to_out(row: ApiKeyRow) -> ApiKeyOut:
    return ApiKeyOut(
        id=str(row.id),
        name=row.name,
        key_prefix=row.key_prefix,
        scopes=row.scopes or [],
        is_active=row.is_active,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/api-keys/scopes", response_model=ScopeGroupsOut)
async def admin_api_key_scopes(
    _auth=Depends(verify_auth_or_user),
):
    """Return available scopes grouped for the UI."""
    return ScopeGroupsOut(
        groups={
            name: ScopeGroupOut(
                description=group["description"],
                scopes=group["scopes"],
            )
            for name, group in SCOPE_GROUPS.items()
        },
        all_scopes=ALL_SCOPES,
        descriptions=SCOPE_DESCRIPTIONS,
    )


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def admin_list_api_keys(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """List all API keys (never returns full key)."""
    rows = (await db.execute(
        select(ApiKeyRow).order_by(ApiKeyRow.created_at.desc())
    )).scalars().all()
    return [_key_to_out(r) for r in rows]


@router.post("/api-keys", response_model=ApiKeyCreateOut, status_code=201)
async def admin_create_api_key(
    body: ApiKeyCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Create a new API key. Returns the full key ONCE."""
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")

    # Validate scopes
    invalid = [s for s in body.scopes if s not in ALL_SCOPES]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid scopes: {invalid}")

    # Determine user_id from auth if JWT
    from app.db.models import User
    user_id = _auth.id if isinstance(_auth, User) else None

    row, full_key = await create_api_key(
        db,
        name=body.name.strip(),
        scopes=body.scopes,
        user_id=user_id,
        expires_at=body.expires_at,
        store_key_value=body.store_key_value,
    )
    return ApiKeyCreateOut(key=_key_to_out(row), full_key=full_key)


@router.get("/api-keys/{key_id}", response_model=ApiKeyOut)
async def admin_get_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Get API key details (no full key)."""
    import uuid
    try:
        pk = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="API key not found")
    row = await db.get(ApiKeyRow, pk)
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    return _key_to_out(row)


@router.put("/api-keys/{key_id}", response_model=ApiKeyOut)
async def admin_update_api_key(
    key_id: str,
    body: ApiKeyUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Update an API key's name, scopes, active status, or expiration."""
    import uuid
    try:
        pk = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="API key not found")
    row = await db.get(ApiKeyRow, pk)
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")

    if body.name is not None:
        row.name = body.name.strip()
    if body.scopes is not None:
        invalid = [s for s in body.scopes if s not in ALL_SCOPES]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid scopes: {invalid}")
        row.scopes = body.scopes
    if body.is_active is not None:
        row.is_active = body.is_active
    if body.expires_at is not None:
        row.expires_at = body.expires_at

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _key_to_out(row)


@router.delete("/api-keys/{key_id}")
async def admin_delete_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Hard delete an API key."""
    import uuid
    try:
        pk = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="API key not found")
    row = await db.get(ApiKeyRow, pk)
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
