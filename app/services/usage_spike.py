"""Usage spike detection and alerting.

Background worker that monitors spend rate and dispatches alerts when
the current rate exceeds the baseline by a configured threshold.

Follows the same cache + refresh pattern as usage_limits.py.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, update

from app.config import settings
from app.db.engine import async_session
from app.db.models import TraceEvent, UsageSpikeConfig, UsageSpikeAlert, Channel

logger = logging.getLogger(__name__)

# In-memory cache of the singleton config
_config: UsageSpikeConfig | None = None
_refresh_task: asyncio.Task | None = None

# Cached status result (refreshed by worker, avoids DB hit on every HUD poll)
_cached_status: dict | None = None
_cached_status_at: datetime | None = None
_STATUS_CACHE_TTL = timedelta(seconds=15)


# ---------------------------------------------------------------------------
# Config cache
# ---------------------------------------------------------------------------

async def load_spike_config() -> None:
    """Load the singleton spike config into in-memory cache."""
    global _config
    async with async_session() as db:
        row = (await db.execute(select(UsageSpikeConfig).limit(1))).scalars().first()
        if row:
            db.expunge(row)
        _config = row
    logger.info("Loaded usage spike config: %s", "enabled" if (_config and _config.enabled) else "disabled")


async def _refresh_loop() -> None:
    """Background loop that refreshes the config cache every 60s."""
    while True:
        await asyncio.sleep(60)
        try:
            await load_spike_config()
        except Exception:
            logger.exception("Failed to refresh usage spike config")


def start_spike_refresh_task() -> None:
    global _refresh_task
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_refresh_loop())


def get_cached_config() -> UsageSpikeConfig | None:
    """Return the in-memory cached config (for status endpoint)."""
    return _config


# ---------------------------------------------------------------------------
# Cost computation helpers (reuse from usage.py like usage_limits does)
# ---------------------------------------------------------------------------

async def _compute_cost_in_range(
    after: datetime,
    before: datetime | None = None,
) -> tuple[float, list[TraceEvent]]:
    """Compute total cost for token_usage events in a time range.
    Returns (total_cost, events_list).
    """
    async with async_session() as db:
        q = select(TraceEvent).where(
            TraceEvent.event_type == "token_usage",
            TraceEvent.created_at >= after,
        )
        if before is not None:
            q = q.where(TraceEvent.created_at < before)

        events = list((await db.execute(q)).scalars().all())
        if not events:
            return 0.0, []

        from app.routers.api_v1_admin.usage import (
            _load_pricing_map, _compute_cost_for_events, _get_provider_type_map,
        )
        pricing = await _load_pricing_map(db)
        ptype_map = _get_provider_type_map()
        total = _compute_cost_for_events(events, pricing, ptype_map)
        return total, events


# ---------------------------------------------------------------------------
# Context gathering (top models, bots, traces)
# ---------------------------------------------------------------------------

def _gather_context(events: list[TraceEvent], pricing: dict, ptype_map: dict) -> dict:
    """Compute top models, bots, and traces from a list of events."""
    from app.routers.api_v1_admin.usage import _resolve_event_cost

    model_costs: dict[str, dict] = {}  # model -> {cost, calls}
    bot_costs: dict[str, float] = {}
    trace_costs: dict[str, dict] = {}  # correlation_id -> {model, bot_id, cost}

    for ev in events:
        d = ev.data or {}
        cost = _resolve_event_cost(d, pricing, ptype_map) or 0.0
        model = d.get("model", "unknown")
        bot_id = ev.bot_id or "unknown"
        cid = str(ev.correlation_id) if ev.correlation_id else str(ev.id)

        entry = model_costs.setdefault(model, {"cost": 0.0, "calls": 0})
        entry["cost"] += cost
        entry["calls"] += 1

        bot_costs[bot_id] = bot_costs.get(bot_id, 0.0) + cost

        if cid not in trace_costs:
            trace_costs[cid] = {"model": model, "bot_id": bot_id, "cost": 0.0}
        trace_costs[cid]["cost"] += cost

    top_models = sorted(model_costs.items(), key=lambda x: x[1]["cost"], reverse=True)[:5]
    top_bots = sorted(bot_costs.items(), key=lambda x: x[1], reverse=True)[:5]
    top_traces = sorted(trace_costs.items(), key=lambda x: x[1]["cost"], reverse=True)[:5]

    return {
        "top_models": [{"model": m, "cost": round(d["cost"], 4), "calls": d["calls"]} for m, d in top_models],
        "top_bots": [{"bot_id": b, "cost": round(c, 4)} for b, c in top_bots],
        "recent_traces": [
            {"correlation_id": cid, "model": d["model"], "bot_id": d["bot_id"], "cost": round(d["cost"], 4)}
            for cid, d in top_traces
        ],
    }


# ---------------------------------------------------------------------------
# Alert message formatting
# ---------------------------------------------------------------------------

def format_alert_message(
    window_rate: float,
    baseline_rate: float,
    spike_ratio: float | None,
    window_minutes: int,
    baseline_hours: int,
    context: dict,
) -> str:
    """Format a human-readable spike alert message."""
    lines = ["\u26a0\ufe0f USAGE SPIKE ALERT", ""]

    lines.append(f"Current rate: ${window_rate:.2f}/hr (last {window_minutes} min)")
    lines.append(f"Baseline rate: ${baseline_rate:.2f}/hr ({baseline_hours}hr avg)")
    if spike_ratio is not None:
        lines.append(f"Spike: {spike_ratio:.1f}x baseline")
    lines.append("")

    if context.get("top_models"):
        models_str = ", ".join(
            f"{m['model']} (${m['cost']:.2f}, {m['calls']} calls)"
            for m in context["top_models"][:3]
        )
        lines.append(f"Top models: {models_str}")

    if context.get("top_bots"):
        bots_str = ", ".join(
            f"{b['bot_id']} (${b['cost']:.2f})" for b in context["top_bots"][:3]
        )
        lines.append(f"Top bots: {bots_str}")

    if context.get("recent_traces"):
        lines.append("")
        lines.append("Recent traces:")
        for t in context["recent_traces"][:5]:
            cid_short = t["correlation_id"][:8] if len(t["correlation_id"]) > 8 else t["correlation_id"]
            lines.append(f"  {cid_short} \u2014 {t['model']} via {t['bot_id']}: ${t['cost']:.2f}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Notification dispatch
# ---------------------------------------------------------------------------

async def _dispatch_alert(
    config: UsageSpikeConfig,
    message: str,
) -> tuple[int, int, list[dict]]:
    """Dispatch alert to all configured targets.
    Returns (attempted, succeeded, delivery_details).
    """
    from app.agent import dispatchers
    from app.agent.hooks import get_integration_meta

    targets = config.targets or []
    attempted = 0
    succeeded = 0
    details: list[dict] = []

    for target in targets:
        attempted += 1
        target_type = target.get("type")
        detail: dict = {"target": target, "success": False}

        try:
            if target_type == "channel":
                channel_id = target.get("channel_id")
                if not channel_id:
                    detail["error"] = "missing channel_id"
                    details.append(detail)
                    continue

                async with async_session() as db:
                    channel = await db.get(Channel, uuid.UUID(channel_id))
                if not channel or not channel.integration:
                    detail["error"] = "channel not found or has no integration"
                    details.append(detail)
                    continue

                dispatcher = dispatchers.get(channel.integration)
                ok = await dispatcher.post_message(
                    channel.dispatch_config or {},
                    message,
                    username="Spike Alert",
                    reply_in_thread=False,
                )
                detail["success"] = ok
                if ok:
                    succeeded += 1

            elif target_type == "integration":
                integration_type = target.get("integration_type")
                client_id = target.get("client_id")
                if not integration_type or not client_id:
                    detail["error"] = "missing integration_type or client_id"
                    details.append(detail)
                    continue

                meta = get_integration_meta(integration_type)
                if not meta or not meta.resolve_dispatch_config:
                    detail["error"] = f"integration {integration_type} not found or has no dispatch config resolver"
                    details.append(detail)
                    continue

                dispatch_config = meta.resolve_dispatch_config(client_id)
                if not dispatch_config:
                    detail["error"] = f"could not resolve dispatch config for {client_id}"
                    details.append(detail)
                    continue

                dispatcher = dispatchers.get(integration_type)
                ok = await dispatcher.post_message(
                    dispatch_config,
                    message,
                    username="Spike Alert",
                    reply_in_thread=False,
                )
                detail["success"] = ok
                if ok:
                    succeeded += 1

            else:
                detail["error"] = f"unknown target type: {target_type}"

        except Exception as exc:
            detail["error"] = str(exc)
            logger.warning("Spike alert dispatch failed for target %s: %s", target, exc)

        details.append(detail)

    return attempted, succeeded, details


# ---------------------------------------------------------------------------
# Core spike check
# ---------------------------------------------------------------------------

async def check_for_spike(
    config: UsageSpikeConfig,
    *,
    force: bool = False,
) -> UsageSpikeAlert | None:
    """Run spike detection. Returns the alert if one was fired, else None.

    If force=True, bypass cooldown and threshold checks (for test alerts).
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=config.window_minutes)
    baseline_end = window_start
    baseline_start = now - timedelta(hours=config.baseline_hours)

    # Compute window cost
    window_cost, window_events = await _compute_cost_in_range(window_start, None)
    window_hours = config.window_minutes / 60.0
    window_rate = window_cost / window_hours if window_hours > 0 else 0.0

    # Compute baseline cost (excluding the window period)
    baseline_cost, baseline_events = await _compute_cost_in_range(baseline_start, baseline_end)
    baseline_duration_hours = (baseline_end - baseline_start).total_seconds() / 3600.0
    baseline_rate = baseline_cost / baseline_duration_hours if baseline_duration_hours > 0 else 0.0

    # Determine spike
    spike_ratio: float | None = None
    is_spike = False
    trigger_reason = ""

    if not force:
        # Relative check (skip if no baseline data)
        if baseline_rate > 0 and config.relative_threshold > 0:
            spike_ratio = window_rate / baseline_rate
            if spike_ratio >= config.relative_threshold:
                is_spike = True
                trigger_reason = "relative"

        # Absolute check
        if config.absolute_threshold_usd > 0 and window_rate >= config.absolute_threshold_usd:
            is_spike = True
            if not trigger_reason:
                trigger_reason = "absolute"
            else:
                trigger_reason = "relative+absolute"

        if not is_spike:
            return None

        # Cooldown check
        if config.last_alert_at:
            cooldown_until = config.last_alert_at + timedelta(minutes=config.cooldown_minutes)
            if now < cooldown_until:
                logger.debug("Spike detected but cooldown active until %s", cooldown_until)
                return None
    else:
        trigger_reason = "test"
        if baseline_rate > 0:
            spike_ratio = window_rate / baseline_rate

    # Gather context
    from app.routers.api_v1_admin.usage import (
        _load_pricing_map, _get_provider_type_map,
    )
    async with async_session() as db:
        pricing = await _load_pricing_map(db)
    ptype_map = _get_provider_type_map()
    context = _gather_context(window_events, pricing, ptype_map)

    # Format and dispatch
    message = format_alert_message(
        window_rate, baseline_rate, spike_ratio,
        config.window_minutes, config.baseline_hours, context,
    )
    attempted, succeeded, delivery_details = await _dispatch_alert(config, message)

    # Record alert
    alert = UsageSpikeAlert(
        window_rate_usd_per_hour=round(window_rate, 6),
        baseline_rate_usd_per_hour=round(baseline_rate, 6),
        spike_ratio=round(spike_ratio, 2) if spike_ratio is not None else None,
        trigger_reason=trigger_reason,
        top_models=context["top_models"],
        top_bots=context["top_bots"],
        recent_traces=context["recent_traces"],
        targets_attempted=attempted,
        targets_succeeded=succeeded,
        delivery_details=delivery_details,
    )
    async with async_session() as db:
        db.add(alert)
        # Update config timestamps
        await db.execute(
            update(UsageSpikeConfig)
            .where(UsageSpikeConfig.id == config.id)
            .values(last_alert_at=now, last_check_at=now)
        )
        await db.commit()
        db.expunge(alert)

    # Refresh cached config to pick up new timestamps
    await load_spike_config()

    logger.info(
        "Spike alert fired: window_rate=$%.4f/hr, baseline=$%.4f/hr, ratio=%s, "
        "dispatched=%d/%d",
        window_rate, baseline_rate, spike_ratio, succeeded, attempted,
    )
    return alert


# ---------------------------------------------------------------------------
# Status computation (for HUD/API)
# ---------------------------------------------------------------------------

async def get_spike_status() -> dict:
    """Compute current spike status without triggering an alert.

    Results are cached for 15s to avoid hammering the DB on every HUD poll.
    """
    global _cached_status, _cached_status_at

    now = datetime.now(timezone.utc)
    if _cached_status is not None and _cached_status_at is not None:
        if now - _cached_status_at < _STATUS_CACHE_TTL:
            return _cached_status

    config = _config
    if not config:
        result = {"enabled": False, "spiking": False, "window_rate": 0, "baseline_rate": 0, "spike_ratio": None, "cooldown_active": False, "cooldown_remaining_seconds": 0}
        _cached_status = result
        _cached_status_at = now
        return result

    window_start = now - timedelta(minutes=config.window_minutes)
    baseline_end = window_start
    baseline_start = now - timedelta(hours=config.baseline_hours)

    window_cost, _ = await _compute_cost_in_range(window_start, None)
    window_hours = config.window_minutes / 60.0
    window_rate = window_cost / window_hours if window_hours > 0 else 0.0

    baseline_cost, _ = await _compute_cost_in_range(baseline_start, baseline_end)
    baseline_duration_hours = (baseline_end - baseline_start).total_seconds() / 3600.0
    baseline_rate = baseline_cost / baseline_duration_hours if baseline_duration_hours > 0 else 0.0

    spike_ratio: float | None = None
    spiking = False
    if baseline_rate > 0 and config.relative_threshold > 0:
        spike_ratio = window_rate / baseline_rate
        if spike_ratio >= config.relative_threshold:
            spiking = True
    if config.absolute_threshold_usd > 0 and window_rate >= config.absolute_threshold_usd:
        spiking = True

    cooldown_active = False
    cooldown_remaining = 0
    if config.last_alert_at:
        cooldown_until = config.last_alert_at + timedelta(minutes=config.cooldown_minutes)
        if now < cooldown_until:
            cooldown_active = True
            cooldown_remaining = int((cooldown_until - now).total_seconds())

    result = {
        "enabled": config.enabled,
        "spiking": spiking,
        "window_rate": round(window_rate, 4),
        "baseline_rate": round(baseline_rate, 4),
        "spike_ratio": round(spike_ratio, 2) if spike_ratio is not None else None,
        "cooldown_active": cooldown_active,
        "cooldown_remaining_seconds": cooldown_remaining,
    }
    _cached_status = result
    _cached_status_at = now
    return result


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

async def usage_spike_worker() -> None:
    """Background worker: check for spikes every 60s."""
    logger.info("Usage spike worker started")
    while True:
        try:
            if settings.SYSTEM_PAUSED:
                await asyncio.sleep(60)
                continue

            config = _config
            if not config or not config.enabled:
                await asyncio.sleep(60)
                continue

            now = datetime.now(timezone.utc)

            # Update last_check_at
            async with async_session() as db:
                await db.execute(
                    update(UsageSpikeConfig)
                    .where(UsageSpikeConfig.id == config.id)
                    .values(last_check_at=now)
                )
                await db.commit()

            await check_for_spike(config)

        except Exception:
            logger.exception("usage_spike_worker error")

        await asyncio.sleep(60)
