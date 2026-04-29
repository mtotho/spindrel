"""Usage limit enforcement — checks cost caps before each run_stream call."""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, func

from app.db.engine import async_session
from app.db.models import TraceEvent, UsageLimit

logger = logging.getLogger(__name__)

# In-memory cache of enabled limits
_limits: list[UsageLimit] = []
_refresh_task: asyncio.Task | None = None


class UsageLimitExceeded(Exception):
    pass


async def load_limits() -> None:
    """Load all enabled usage limits into the in-memory cache."""
    global _limits
    async with async_session() as db:
        rows = (await db.execute(
            select(UsageLimit).where(UsageLimit.enabled == True)  # noqa: E712
        )).scalars().all()
        # Detach from session so they're safe to use outside
        _limits = list(rows)
        for r in _limits:
            db.expunge(r)
    logger.info("Loaded %d enabled usage limits", len(_limits))


async def _refresh_loop() -> None:
    """Background loop that refreshes the limit cache every 60s."""
    while True:
        await asyncio.sleep(60)
        try:
            await load_limits()
        except Exception:
            logger.exception("Failed to refresh usage limits")


def start_refresh_task() -> None:
    global _refresh_task
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_refresh_loop())


def _period_start(period: str) -> datetime:
    """Return start of the current period in the user's configured timezone (as UTC)."""
    from app.config import settings
    local_tz = ZoneInfo(settings.TIMEZONE)
    now_local = datetime.now(timezone.utc).astimezone(local_tz)
    if period == "daily":
        return now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    elif period == "monthly":
        return now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    raise ValueError(f"Unknown period: {period}")


async def _compute_spend(scope_type: str, scope_value: str, since: datetime) -> float:
    """Compute total spend for a scope since a given time.

    Uses response_cost from trace event data (populated by LiteLLM) as primary,
    falling back to pricing map computation.
    """
    async with async_session() as db:
        # Build base query for token_usage events in the period
        base = select(TraceEvent).where(
            TraceEvent.event_type == "token_usage",
            TraceEvent.created_at >= since,
        )

        if scope_type == "bot":
            base = base.where(TraceEvent.bot_id == scope_value)
        elif scope_type == "model":
            base = base.where(TraceEvent.data["model"].astext == scope_value)

        events = (await db.execute(base)).scalars().all()

        if not events:
            return 0.0

        from app.services.usage_costs import (
            _load_pricing_map, _compute_cost_for_events, _get_provider_type_map,
        )

        pricing = await _load_pricing_map(db)
        ptype_map = _get_provider_type_map()
        return _compute_cost_for_events(events, pricing, ptype_map)


async def check_usage_limits(model: str, bot_id: str) -> None:
    """Check all applicable usage limits. Raises UsageLimitExceeded if any are exceeded."""
    if not _limits:
        return

    for limit in _limits:
        applies = False
        if limit.scope_type == "model" and limit.scope_value == model:
            applies = True
        elif limit.scope_type == "bot" and limit.scope_value == bot_id:
            applies = True

        if not applies:
            continue

        since = _period_start(limit.period)
        spend = await _compute_spend(limit.scope_type, limit.scope_value, since)

        if spend >= limit.limit_usd:
            raise UsageLimitExceeded(
                f"Usage limit exceeded: {limit.scope_type}={limit.scope_value} "
                f"{limit.period} limit ${limit.limit_usd:.2f}, "
                f"current spend ${spend:.2f}"
            )


async def get_limits_status() -> list[dict]:
    """Return all enabled limits with current spend info for the admin UI."""
    result = []
    for limit in _limits:
        since = _period_start(limit.period)
        spend = await _compute_spend(limit.scope_type, limit.scope_value, since)
        pct = (spend / limit.limit_usd * 100) if limit.limit_usd > 0 else 0
        result.append({
            "id": str(limit.id),
            "scope_type": limit.scope_type,
            "scope_value": limit.scope_value,
            "period": limit.period,
            "limit_usd": limit.limit_usd,
            "current_spend": round(spend, 4),
            "percentage": round(pct, 1),
            "enabled": limit.enabled,
        })
    return result
