"""Spike Alerts admin API — /admin/spike-alerts/"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageSpikeConfig, UsageSpikeAlert, Channel, ChannelIntegration
from app.dependencies import get_db
from app.services.usage_spike import (
    load_spike_config, get_cached_config, check_for_spike, get_spike_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spike-alerts", tags=["Spike Alerts"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SpikeTarget(BaseModel):
    type: str  # "channel" | "integration"
    channel_id: Optional[str] = None
    integration_type: Optional[str] = None
    client_id: Optional[str] = None
    label: Optional[str] = None


class SpikeConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    window_minutes: Optional[int] = None
    baseline_hours: Optional[int] = None
    relative_threshold: Optional[float] = None
    absolute_threshold_usd: Optional[float] = None
    cooldown_minutes: Optional[int] = None
    targets: Optional[list[dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    """Get spike alert config (auto-creates default if missing)."""
    row = (await db.execute(select(UsageSpikeConfig).limit(1))).scalars().first()
    if not row:
        row = UsageSpikeConfig()
        db.add(row)
        await db.commit()
        await db.refresh(row)
        await load_spike_config()

    return {
        "id": str(row.id),
        "enabled": row.enabled,
        "window_minutes": row.window_minutes,
        "baseline_hours": row.baseline_hours,
        "relative_threshold": row.relative_threshold,
        "absolute_threshold_usd": row.absolute_threshold_usd,
        "cooldown_minutes": row.cooldown_minutes,
        "targets": row.targets or [],
        "last_alert_at": row.last_alert_at.isoformat() if row.last_alert_at else None,
        "last_check_at": row.last_check_at.isoformat() if row.last_check_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.put("/config")
async def update_config(body: SpikeConfigUpdate, db: AsyncSession = Depends(get_db)):
    """Update spike alert config."""
    row = (await db.execute(select(UsageSpikeConfig).limit(1))).scalars().first()
    if not row:
        row = UsageSpikeConfig()
        db.add(row)
        await db.flush()

    if body.enabled is not None:
        row.enabled = body.enabled
    if body.window_minutes is not None:
        if body.window_minutes < 1:
            raise HTTPException(400, "window_minutes must be >= 1")
        row.window_minutes = body.window_minutes
    if body.baseline_hours is not None:
        if body.baseline_hours < 1:
            raise HTTPException(400, "baseline_hours must be >= 1")
        row.baseline_hours = body.baseline_hours
    if body.relative_threshold is not None:
        if body.relative_threshold < 0:
            raise HTTPException(400, "relative_threshold must be >= 0")
        row.relative_threshold = body.relative_threshold
    if body.absolute_threshold_usd is not None:
        if body.absolute_threshold_usd < 0:
            raise HTTPException(400, "absolute_threshold_usd must be >= 0")
        row.absolute_threshold_usd = body.absolute_threshold_usd
    if body.cooldown_minutes is not None:
        if body.cooldown_minutes < 0:
            raise HTTPException(400, "cooldown_minutes must be >= 0")
        row.cooldown_minutes = body.cooldown_minutes
    if body.targets is not None:
        row.targets = body.targets

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    await load_spike_config()

    return {
        "id": str(row.id),
        "enabled": row.enabled,
        "window_minutes": row.window_minutes,
        "baseline_hours": row.baseline_hours,
        "relative_threshold": row.relative_threshold,
        "absolute_threshold_usd": row.absolute_threshold_usd,
        "cooldown_minutes": row.cooldown_minutes,
        "targets": row.targets or [],
        "last_alert_at": row.last_alert_at.isoformat() if row.last_alert_at else None,
        "last_check_at": row.last_check_at.isoformat() if row.last_check_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/test")
async def test_alert(db: AsyncSession = Depends(get_db)):
    """Fire a test alert (bypasses cooldown + threshold checks)."""
    row = (await db.execute(select(UsageSpikeConfig).limit(1))).scalars().first()
    if not row:
        raise HTTPException(404, "No spike config found. Create one first via GET /config.")

    # Detach for use outside session
    db.expunge(row)

    alert = await check_for_spike(row, force=True)
    if not alert:
        return {"ok": False, "message": "Test alert could not be created"}

    return {
        "ok": True,
        "alert_id": str(alert.id),
        "targets_attempted": alert.targets_attempted,
        "targets_succeeded": alert.targets_succeeded,
    }


@router.get("/history")
async def alert_history(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Paginated alert history (newest first)."""
    total = (await db.execute(
        select(func.count()).select_from(UsageSpikeAlert)
    )).scalar() or 0

    offset = (page - 1) * page_size
    rows = (await db.execute(
        select(UsageSpikeAlert)
        .order_by(UsageSpikeAlert.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "alerts": [
            {
                "id": str(r.id),
                "window_rate_usd_per_hour": r.window_rate_usd_per_hour,
                "baseline_rate_usd_per_hour": r.baseline_rate_usd_per_hour,
                "spike_ratio": r.spike_ratio,
                "trigger_reason": r.trigger_reason,
                "top_models": r.top_models,
                "top_bots": r.top_bots,
                "recent_traces": r.recent_traces,
                "targets_attempted": r.targets_attempted,
                "targets_succeeded": r.targets_succeeded,
                "delivery_details": r.delivery_details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/status")
async def spike_status():
    """Current spike status (for HUD badge)."""
    return await get_spike_status()


@router.get("/targets/available")
async def available_targets(db: AsyncSession = Depends(get_db)):
    """List channels with dispatchers + integration bindings as target options."""
    options: list[dict] = []

    # Channels with integration dispatchers
    channels = (await db.execute(
        select(Channel)
        .where(Channel.integration.isnot(None))
        .order_by(Channel.name)
    )).scalars().all()

    for ch in channels:
        options.append({
            "type": "channel",
            "channel_id": str(ch.id),
            "label": f"#{ch.name} ({ch.integration})",
            "integration_type": ch.integration,
        })

    # Integration bindings (from channel_integrations)
    bindings = (await db.execute(
        select(ChannelIntegration)
        .where(ChannelIntegration.dispatch_config.isnot(None))
        .order_by(ChannelIntegration.integration_type)
    )).scalars().all()

    seen_clients: set[str] = set()
    for b in bindings:
        if b.client_id in seen_clients:
            continue
        seen_clients.add(b.client_id)
        options.append({
            "type": "integration",
            "integration_type": b.integration_type,
            "client_id": b.client_id,
            "label": b.display_name or b.client_id,
        })

    return options
