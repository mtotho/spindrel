"""Usage & Cost analytics API — /admin/usage/."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.schemas.usage import (
    AgentSmellOut,
    ProviderHealthOut,
    UsageAnomaliesOut,
    UsageBreakdownOut,
    UsageForecastOut,
    UsageLogsOut,
    UsageSummaryOut,
    UsageTimeseriesOut,
)
from app.services.usage_anomalies import build_agent_smell, build_usage_anomalies
from app.services.usage_forecast import build_usage_forecast
from app.services.usage_reports import (
    build_debug_pricing,
    build_provider_health,
    build_usage_breakdown,
    build_usage_logs,
    build_usage_summary,
    build_usage_timeseries,
)

router = APIRouter(prefix="/usage", tags=["Usage"])


@router.get("/anomalies", response_model=UsageAnomaliesOut)
async def usage_anomalies(
    after: Optional[str] = Query("24h"),
    before: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None, pattern="^(agent|task|heartbeat|maintenance)$"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("usage:read")),
):
    return await build_usage_anomalies(
        after=after,
        before=before,
        bot_id=bot_id,
        model=model,
        provider_id=provider_id,
        channel_id=channel_id,
        source_type=source_type,
        db=db,
    )


@router.get("/agent-smell", response_model=AgentSmellOut)
async def agent_smell(
    hours: int = Query(24, ge=1, le=168),
    baseline_days: int = Query(7, ge=1, le=30),
    bot_id: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None, pattern="^(agent|task|heartbeat|maintenance)$"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("usage:read")),
):
    return await build_agent_smell(
        hours=hours,
        baseline_days=baseline_days,
        bot_id=bot_id,
        source_type=source_type,
        limit=limit,
        db=db,
    )


@router.get("/summary", response_model=UsageSummaryOut)
async def usage_summary(
    after: Optional[str] = Query(None),
    before: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    _auth=Depends(require_scopes("usage:read")),
    db: AsyncSession = Depends(get_db),
):
    return await build_usage_summary(
        after=after,
        before=before,
        bot_id=bot_id,
        model=model,
        provider_id=provider_id,
        channel_id=channel_id,
        db=db,
    )


@router.get("/logs", response_model=UsageLogsOut)
async def usage_logs(
    after: Optional[str] = Query(None),
    before: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("usage:read")),
):
    return await build_usage_logs(
        after=after,
        before=before,
        bot_id=bot_id,
        model=model,
        provider_id=provider_id,
        channel_id=channel_id,
        page=page,
        page_size=page_size,
        db=db,
    )


@router.get("/breakdown", response_model=UsageBreakdownOut)
async def usage_breakdown(
    group_by: str = Query("model", pattern="^(model|bot|channel|provider)$"),
    after: Optional[str] = Query(None),
    before: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("usage:read")),
):
    return await build_usage_breakdown(
        group_by=group_by,
        after=after,
        before=before,
        bot_id=bot_id,
        model=model,
        provider_id=provider_id,
        channel_id=channel_id,
        db=db,
    )


@router.get("/timeseries", response_model=UsageTimeseriesOut)
async def usage_timeseries(
    after: Optional[str] = Query(None),
    before: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    bucket: str = Query("auto", pattern="^(1h|6h|1d|auto)$"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("usage:read")),
):
    return await build_usage_timeseries(
        after=after,
        before=before,
        bot_id=bot_id,
        model=model,
        provider_id=provider_id,
        channel_id=channel_id,
        bucket=bucket,
        db=db,
    )


@router.get("/debug-pricing")
async def debug_pricing(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("usage:read")),
):
    return await build_debug_pricing(db=db)


@router.get(
    "/forecast",
    response_model=UsageForecastOut,
    dependencies=[Depends(require_scopes("usage:read"))],
)
async def usage_forecast(db: AsyncSession = Depends(get_db)):
    return await build_usage_forecast(db=db)


@router.get("/usage/provider-health", response_model=ProviderHealthOut)
async def admin_provider_health(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("usage:read")),
):
    return await build_provider_health(hours=hours, db=db)
