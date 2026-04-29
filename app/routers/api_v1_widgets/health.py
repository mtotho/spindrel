"""Widget health-check endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.dashboard_pins import get_pin
from app.services.widget_health import (
    check_dashboard_widgets,
    check_envelope_health,
    check_pin_health,
    latest_health_for_pins,
)


router = APIRouter()


class WidgetHealthCheckRequest(BaseModel):
    pin_id: uuid.UUID | None = None
    envelope: dict | None = None
    include_browser: bool = True


@router.get(
    "/health",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_widget_health(
    pin_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    latest = await latest_health_for_pins(db, [pin_id])
    return {
        "pin_id": str(pin_id),
        "health": latest.get(str(pin_id)),
    }


@router.post(
    "/health/check",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def run_widget_health_check(
    body: WidgetHealthCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    if body.pin_id is None and body.envelope is None:
        raise HTTPException(400, "Provide pin_id or envelope.")
    if body.pin_id is not None and body.envelope is not None:
        raise HTTPException(400, "Provide only one of pin_id or envelope.")
    if body.pin_id is not None:
        return await check_pin_health(db, body.pin_id, include_browser=body.include_browser)
    return await check_envelope_health(
        body.envelope or {},
        target_ref="api:draft",
        include_browser=False,
    )


@router.get(
    "/dashboard/pins/{pin_id}/health",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_pin_health(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    # Match other pin endpoints: 404 if the pin itself is gone, even when no
    # health check has been recorded yet.
    await get_pin(db, pin_id)
    latest = await latest_health_for_pins(db, [pin_id])
    return {
        "pin_id": str(pin_id),
        "health": latest.get(str(pin_id)),
    }


@router.post(
    "/dashboard/pins/{pin_id}/health/check",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def run_dashboard_pin_health_check(
    pin_id: uuid.UUID,
    include_browser: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    return await check_pin_health(db, pin_id, include_browser=include_browser)


@router.post(
    "/dashboard/{dashboard_key:path}/health/check",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def run_dashboard_health_check(
    dashboard_key: str,
    limit: int = Query(20, ge=1, le=100),
    include_browser: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    return await check_dashboard_widgets(
        db,
        dashboard_key,
        limit=limit,
        include_browser=include_browser,
    )
