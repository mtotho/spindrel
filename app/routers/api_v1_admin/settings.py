"""Server settings CRUD: /settings."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_auth_or_user

router = APIRouter()


class SettingsUpdateIn(BaseModel):
    settings: dict[str, Any]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/settings")
async def admin_get_settings(
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_settings import get_all_settings
    groups = await get_all_settings()
    return {"groups": groups}


@router.put("/settings")
async def admin_update_settings(
    body: SettingsUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_settings import update_settings
    try:
        applied = await update_settings(body.settings, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "applied": applied}


@router.delete("/settings/{key}")
async def admin_reset_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    from app.services.server_settings import reset_setting
    try:
        default_value = await reset_setting(key, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "default": default_value}
