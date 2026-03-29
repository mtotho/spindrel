"""Usage & Cost analytics API — /admin/usage/

Provides aggregated cost analysis by joining token_usage trace events
with ProviderModel pricing data at read time.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, ProviderConfig, ProviderModel, Session, TraceEvent
from app.dependencies import get_db

from ._helpers import _parse_time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["Usage"])


# ---------------------------------------------------------------------------
# Cost helpers
# ---------------------------------------------------------------------------

def _parse_cost_str(value: str | None) -> float | None:
    """Parse a cost string like '$3.00' or '3.00' into a float."""
    if not value:
        return None
    try:
        return float(value.strip().lstrip("$"))
    except (ValueError, TypeError):
        return None


def _compute_cost(
    prompt_tokens: int,
    completion_tokens: int,
    input_rate_str: str | None,
    output_rate_str: str | None,
) -> float | None:
    """Compute cost from token counts and per-1M-token rate strings."""
    input_rate = _parse_cost_str(input_rate_str)
    output_rate = _parse_cost_str(output_rate_str)
    if input_rate is None and output_rate is None:
        return None
    cost = 0.0
    if input_rate is not None:
        cost += prompt_tokens * input_rate / 1_000_000
    if output_rate is not None:
        cost += completion_tokens * output_rate / 1_000_000
    return cost


async def _load_pricing_map(
    db: AsyncSession,
) -> dict[tuple[str, str], tuple[str | None, str | None]]:
    """Bulk load pricing from DB ProviderModel rows + LiteLLM model info cache.

    LiteLLM cached entries are added first, then DB rows override so that
    user-configured pricing always wins.
    """
    result: dict[tuple[str, str], tuple[str | None, str | None]] = {}

    # Seed from LiteLLM model info cache (auto-fetched from /model/info at startup)
    from app.services.providers import _model_info_cache
    litellm_entries = 0
    for provider_id, models in _model_info_cache.items():
        pid = provider_id or "__env__"
        for model_id, info in models.items():
            inp = info.get("input_cost_per_1m")
            out = info.get("output_cost_per_1m")
            if inp or out:
                result[(pid, model_id)] = (inp, out)
                litellm_entries += 1

    # DB rows override LiteLLM cache
    rows = (await db.execute(
        select(
            ProviderModel.provider_id,
            ProviderModel.model_id,
            ProviderModel.input_cost_per_1m,
            ProviderModel.output_cost_per_1m,
        )
    )).all()
    db_entries = 0
    for r in rows:
        if r.input_cost_per_1m or r.output_cost_per_1m:
            result[(r.provider_id, r.model_id)] = (r.input_cost_per_1m, r.output_cost_per_1m)
            db_entries += 1

    logger.info(
        "Pricing map: %d LiteLLM cache providers, %d LiteLLM entries with cost, %d DB entries, %d total keys",
        len(_model_info_cache), litellm_entries, db_entries, len(result),
    )
    if result:
        sample = next(iter(result.items()))
        logger.info("Pricing map sample: %s → %s", sample[0], sample[1])
    return result


def _lookup_pricing(
    pricing_map: dict[tuple[str, str], tuple[str | None, str | None]],
    provider_id: str | None,
    model: str | None,
) -> tuple[str | None, str | None]:
    """Find pricing for a (provider_id, model) pair.

    Resolution order:
    1. Exact (provider_id, model) match in ProviderModel DB rows
    2. Model-only match in DB rows (for old events without provider_id)
    3. LiteLLM model info cache (auto-fetched from /model/info at startup)
    """
    if not model:
        return (None, None)
    if provider_id:
        key = (provider_id, model)
        if key in pricing_map:
            return pricing_map[key]
    else:
        # No provider_id — try the .env LiteLLM fallback key
        env_key = ("__env__", model)
        if env_key in pricing_map:
            return pricing_map[env_key]
    # Fallback: match on model_id alone across all providers
    for (pid, mid), costs in pricing_map.items():
        if mid == model:
            return costs
    # Fallback: LiteLLM cached model info (fetched from /model/info at startup)
    from app.services.providers import get_cached_model_info
    cached = get_cached_model_info(model, provider_id)
    if cached:
        inp = cached.get("input_cost_per_1m")
        out = cached.get("output_cost_per_1m")
        if inp or out:
            return (inp, out)
    return (None, None)


async def _fetch_token_usage_events(
    db: AsyncSession,
    *,
    after: datetime | None = None,
    before: datetime | None = None,
    bot_id: str | None = None,
    model: str | None = None,
    provider_id: str | None = None,
    channel_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    count_total: bool = False,
) -> tuple[list[TraceEvent], int]:
    """Query token_usage trace events with filters. Returns (events, total_count)."""
    base = select(TraceEvent).where(TraceEvent.event_type == "token_usage")
    count_q = select(func.count(TraceEvent.id)).where(TraceEvent.event_type == "token_usage")

    if after:
        base = base.where(TraceEvent.created_at >= after)
        count_q = count_q.where(TraceEvent.created_at >= after)
    if before:
        base = base.where(TraceEvent.created_at <= before)
        count_q = count_q.where(TraceEvent.created_at <= before)
    if bot_id:
        base = base.where(TraceEvent.bot_id == bot_id)
        count_q = count_q.where(TraceEvent.bot_id == bot_id)
    if model:
        base = base.where(TraceEvent.data["model"].astext == model)
        count_q = count_q.where(TraceEvent.data["model"].astext == model)
    if provider_id:
        base = base.where(TraceEvent.data["provider_id"].astext == provider_id)
        count_q = count_q.where(TraceEvent.data["provider_id"].astext == provider_id)
    if channel_id:
        base = base.where(TraceEvent.data["channel_id"].astext == channel_id)
        count_q = count_q.where(TraceEvent.data["channel_id"].astext == channel_id)

    total = 0
    if count_total:
        total = (await db.execute(count_q)).scalar() or 0

    base = base.order_by(TraceEvent.created_at.desc())
    if offset:
        base = base.offset(offset)
    if limit:
        base = base.limit(limit)

    events = (await db.execute(base)).scalars().all()
    return list(events), total


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CostByDimension(BaseModel):
    label: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float | None = None
    has_cost_data: bool = True


class UsageSummaryOut(BaseModel):
    total_calls: int = 0
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost: float | None = None
    cost_by_model: list[CostByDimension] = []
    cost_by_bot: list[CostByDimension] = []
    cost_by_provider: list[CostByDimension] = []
    models_without_cost_data: list[str] = []
    calls_without_cost_data: int = 0


class UsageLogEntry(BaseModel):
    id: str
    created_at: str
    correlation_id: str | None = None
    model: str | None = None
    provider_id: str | None = None
    provider_name: str | None = None
    bot_id: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None
    has_cost_data: bool = False
    duration_ms: int | None = None


class UsageLogsOut(BaseModel):
    entries: list[UsageLogEntry] = []
    total: int = 0
    page: int = 1
    page_size: int = 50
    bot_ids: list[str] = []
    model_names: list[str] = []
    provider_ids: list[str] = []


class BreakdownGroup(BaseModel):
    label: str
    calls: int = 0
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None


class UsageBreakdownOut(BaseModel):
    group_by: str
    groups: list[BreakdownGroup] = []


class TimeseriesPoint(BaseModel):
    bucket: str
    cost: float | None = None
    tokens: int = 0
    calls: int = 0


class UsageTimeseriesOut(BaseModel):
    bucket_size: str
    points: list[TimeseriesPoint] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=UsageSummaryOut)
async def usage_summary(
    after: Optional[str] = Query(None),
    before: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None

    events, _ = await _fetch_token_usage_events(
        db, after=after_dt, before=before_dt,
        bot_id=bot_id, model=model, provider_id=provider_id, channel_id=channel_id,
    )
    pricing = await _load_pricing_map(db)

    total_cost = 0.0
    total_tokens = 0
    total_prompt = 0
    total_completion = 0
    models_without_cost: set[str] = set()
    calls_without_cost = 0

    by_model: dict[str, CostByDimension] = {}
    by_bot: dict[str, CostByDimension] = {}
    by_provider: dict[str, CostByDimension] = {}

    for ev in events:
        d = ev.data or {}
        pt = d.get("prompt_tokens", 0)
        ct = d.get("completion_tokens", 0)
        tt = d.get("total_tokens", 0)
        ev_model = d.get("model", "unknown")
        ev_provider = d.get("provider_id")
        ev_bot = ev.bot_id or "unknown"

        total_tokens += tt
        total_prompt += pt
        total_completion += ct

        input_rate, output_rate = _lookup_pricing(pricing, ev_provider, ev_model)
        cost = _compute_cost(pt, ct, input_rate, output_rate)

        if cost is not None:
            total_cost += cost
        else:
            models_without_cost.add(ev_model)
            calls_without_cost += 1

        # By model
        if ev_model not in by_model:
            by_model[ev_model] = CostByDimension(label=ev_model)
        m = by_model[ev_model]
        m.calls += 1
        m.prompt_tokens += pt
        m.completion_tokens += ct
        m.total_tokens += tt
        if cost is not None:
            m.cost = (m.cost or 0) + cost
        else:
            m.has_cost_data = False

        # By bot
        if ev_bot not in by_bot:
            by_bot[ev_bot] = CostByDimension(label=ev_bot)
        b = by_bot[ev_bot]
        b.calls += 1
        b.prompt_tokens += pt
        b.completion_tokens += ct
        b.total_tokens += tt
        if cost is not None:
            b.cost = (b.cost or 0) + cost
        else:
            b.has_cost_data = False

        # By provider
        prov_label = ev_provider or "default"
        if prov_label not in by_provider:
            by_provider[prov_label] = CostByDimension(label=prov_label)
        p = by_provider[prov_label]
        p.calls += 1
        p.prompt_tokens += pt
        p.completion_tokens += ct
        p.total_tokens += tt
        if cost is not None:
            p.cost = (p.cost or 0) + cost
        else:
            p.has_cost_data = False

    return UsageSummaryOut(
        total_calls=len(events),
        total_tokens=total_tokens,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        total_cost=total_cost if total_cost > 0 else None,
        cost_by_model=sorted(by_model.values(), key=lambda x: x.cost or 0, reverse=True),
        cost_by_bot=sorted(by_bot.values(), key=lambda x: x.cost or 0, reverse=True),
        cost_by_provider=sorted(by_provider.values(), key=lambda x: x.cost or 0, reverse=True),
        models_without_cost_data=sorted(models_without_cost),
        calls_without_cost_data=calls_without_cost,
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
):
    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None

    events, total = await _fetch_token_usage_events(
        db, after=after_dt, before=before_dt,
        bot_id=bot_id, model=model, provider_id=provider_id, channel_id=channel_id,
        limit=page_size, offset=(page - 1) * page_size, count_total=True,
    )
    pricing = await _load_pricing_map(db)

    # Load provider display names
    provider_names: dict[str, str] = {}
    prov_rows = (await db.execute(
        select(ProviderConfig.id, ProviderConfig.display_name)
    )).all()
    for r in prov_rows:
        provider_names[r.id] = r.display_name

    # Load channel names for channel_ids in events
    channel_ids_in_events: set[str] = set()
    for ev in events:
        cid = (ev.data or {}).get("channel_id")
        if cid:
            channel_ids_in_events.add(cid)

    # Also look up via session if channel_id not in data
    session_ids_needing_channel: list = []
    for ev in events:
        if not (ev.data or {}).get("channel_id") and ev.session_id:
            session_ids_needing_channel.append(ev.session_id)

    session_channel_map: dict = {}
    if session_ids_needing_channel:
        sess_rows = (await db.execute(
            select(Session.id, Session.channel_id)
            .where(Session.id.in_(session_ids_needing_channel))
        )).all()
        for r in sess_rows:
            if r.channel_id:
                session_channel_map[r.id] = str(r.channel_id)
                channel_ids_in_events.add(str(r.channel_id))

    channel_name_map: dict[str, str] = {}
    if channel_ids_in_events:
        import uuid as _uuid
        valid_uuids = []
        for cid in channel_ids_in_events:
            try:
                valid_uuids.append(_uuid.UUID(cid))
            except ValueError:
                pass
        if valid_uuids:
            ch_rows = (await db.execute(
                select(Channel.id, Channel.name).where(Channel.id.in_(valid_uuids))
            )).all()
            for r in ch_rows:
                channel_name_map[str(r.id)] = r.name

    # Query distinct filter values across the FULL filtered dataset (not just this page)
    _base_filter = select(TraceEvent).where(TraceEvent.event_type == "token_usage")
    if after_dt:
        _base_filter = _base_filter.where(TraceEvent.created_at >= after_dt)
    if before_dt:
        _base_filter = _base_filter.where(TraceEvent.created_at <= before_dt)

    _distinct_bots_q = select(func.distinct(TraceEvent.bot_id)).where(
        TraceEvent.event_type == "token_usage", TraceEvent.bot_id.is_not(None),
    )
    _distinct_models_q = select(func.distinct(TraceEvent.data["model"].astext)).where(
        TraceEvent.event_type == "token_usage",
    )
    _distinct_providers_q = select(func.distinct(TraceEvent.data["provider_id"].astext)).where(
        TraceEvent.event_type == "token_usage",
    )
    if after_dt:
        _distinct_bots_q = _distinct_bots_q.where(TraceEvent.created_at >= after_dt)
        _distinct_models_q = _distinct_models_q.where(TraceEvent.created_at >= after_dt)
        _distinct_providers_q = _distinct_providers_q.where(TraceEvent.created_at >= after_dt)
    if before_dt:
        _distinct_bots_q = _distinct_bots_q.where(TraceEvent.created_at <= before_dt)
        _distinct_models_q = _distinct_models_q.where(TraceEvent.created_at <= before_dt)
        _distinct_providers_q = _distinct_providers_q.where(TraceEvent.created_at <= before_dt)

    all_bot_ids = sorted(
        r[0] for r in (await db.execute(_distinct_bots_q)).all() if r[0]
    )
    all_model_names = sorted(
        r[0] for r in (await db.execute(_distinct_models_q)).all() if r[0]
    )
    all_provider_ids = sorted(
        r[0] for r in (await db.execute(_distinct_providers_q)).all() if r[0]
    )

    entries: list[UsageLogEntry] = []
    for ev in events:
        d = ev.data or {}
        pt = d.get("prompt_tokens", 0)
        ct = d.get("completion_tokens", 0)
        ev_model = d.get("model")
        ev_provider = d.get("provider_id")
        ev_channel = d.get("channel_id") or session_channel_map.get(ev.session_id)

        input_rate, output_rate = _lookup_pricing(pricing, ev_provider, ev_model)
        cost = _compute_cost(pt, ct, input_rate, output_rate)

        entries.append(UsageLogEntry(
            id=str(ev.id),
            created_at=ev.created_at.isoformat() if ev.created_at else "",
            correlation_id=str(ev.correlation_id) if ev.correlation_id else None,
            model=ev_model,
            provider_id=ev_provider,
            provider_name=provider_names.get(ev_provider) if ev_provider else None,
            bot_id=ev.bot_id,
            channel_id=ev_channel,
            channel_name=channel_name_map.get(ev_channel) if ev_channel else None,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost=cost,
            has_cost_data=cost is not None,
            duration_ms=ev.duration_ms,
        ))

    return UsageLogsOut(
        entries=entries,
        total=total,
        page=page,
        page_size=page_size,
        bot_ids=all_bot_ids,
        model_names=all_model_names,
        provider_ids=all_provider_ids,
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
):
    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None

    events, _ = await _fetch_token_usage_events(
        db, after=after_dt, before=before_dt,
        bot_id=bot_id, model=model, provider_id=provider_id, channel_id=channel_id,
    )
    pricing = await _load_pricing_map(db)

    # Channel name lookup
    channel_name_map: dict[str, str] = {}
    if group_by == "channel":
        ch_ids: set[str] = set()
        for ev in events:
            cid = (ev.data or {}).get("channel_id")
            if cid:
                ch_ids.add(cid)
        if ch_ids:
            import uuid as _uuid
            valid_uuids = []
            for cid in ch_ids:
                try:
                    valid_uuids.append(_uuid.UUID(cid))
                except ValueError:
                    pass
            if valid_uuids:
                ch_rows = (await db.execute(
                    select(Channel.id, Channel.name).where(Channel.id.in_(valid_uuids))
                )).all()
                for r in ch_rows:
                    channel_name_map[str(r.id)] = r.name

    groups: dict[str, BreakdownGroup] = {}
    for ev in events:
        d = ev.data or {}
        pt = d.get("prompt_tokens", 0)
        ct = d.get("completion_tokens", 0)
        tt = d.get("total_tokens", 0)
        ev_model = d.get("model", "unknown")
        ev_provider = d.get("provider_id")

        if group_by == "model":
            key = ev_model
        elif group_by == "bot":
            key = ev.bot_id or "unknown"
        elif group_by == "channel":
            key = d.get("channel_id") or "unknown"
        elif group_by == "provider":
            key = ev_provider or "default"
        else:
            key = "unknown"

        if key not in groups:
            label = key
            if group_by == "channel" and key in channel_name_map:
                label = channel_name_map[key]
            groups[key] = BreakdownGroup(label=label)

        g = groups[key]
        g.calls += 1
        g.tokens += tt
        g.prompt_tokens += pt
        g.completion_tokens += ct

        input_rate, output_rate = _lookup_pricing(pricing, ev_provider, ev_model)
        cost = _compute_cost(pt, ct, input_rate, output_rate)
        if cost is not None:
            g.cost = (g.cost or 0) + cost

    return UsageBreakdownOut(
        group_by=group_by,
        groups=sorted(groups.values(), key=lambda x: x.cost or 0, reverse=True),
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
):
    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None

    events, _ = await _fetch_token_usage_events(
        db, after=after_dt, before=before_dt,
        bot_id=bot_id, model=model, provider_id=provider_id, channel_id=channel_id,
    )
    pricing = await _load_pricing_map(db)

    # Auto bucket selection
    if bucket == "auto":
        if after_dt and before_dt:
            span = (before_dt - after_dt).total_seconds()
        elif after_dt:
            span = (datetime.now(timezone.utc) - after_dt).total_seconds()
        elif events:
            first = min(ev.created_at for ev in events)
            span = (datetime.now(timezone.utc) - first).total_seconds()
        else:
            span = 86400
        if span <= 86400:
            bucket = "1h"
        elif span <= 86400 * 3:
            bucket = "6h"
        else:
            bucket = "1d"

    bucket_seconds = {"1h": 3600, "6h": 21600, "1d": 86400}[bucket]

    buckets: dict[str, TimeseriesPoint] = {}
    for ev in events:
        d = ev.data or {}
        pt = d.get("prompt_tokens", 0)
        ct = d.get("completion_tokens", 0)
        tt = d.get("total_tokens", 0)
        ev_model = d.get("model")
        ev_provider = d.get("provider_id")

        ts = ev.created_at
        bucket_ts = datetime.fromtimestamp(
            (int(ts.timestamp()) // bucket_seconds) * bucket_seconds,
            tz=timezone.utc,
        )
        bucket_key = bucket_ts.isoformat()

        if bucket_key not in buckets:
            buckets[bucket_key] = TimeseriesPoint(bucket=bucket_key)

        point = buckets[bucket_key]
        point.calls += 1
        point.tokens += tt

        input_rate, output_rate = _lookup_pricing(pricing, ev_provider, ev_model)
        cost = _compute_cost(pt, ct, input_rate, output_rate)
        if cost is not None:
            point.cost = (point.cost or 0) + cost

    return UsageTimeseriesOut(
        bucket_size=bucket,
        points=sorted(buckets.values(), key=lambda x: x.bucket),
    )


@router.get("/debug-pricing")
async def debug_pricing(
    db: AsyncSession = Depends(get_db),
):
    """Debug endpoint: show what pricing data is available."""
    from app.services.providers import _model_info_cache

    pricing_map = await _load_pricing_map(db)

    # Show cache structure
    cache_summary: dict[str, list[dict]] = {}
    for provider_id, models in _model_info_cache.items():
        pid = str(provider_id) if provider_id else "__env__"
        entries = []
        for model_id, info in models.items():
            entries.append({
                "model": model_id,
                "input_cost_per_1m": info.get("input_cost_per_1m"),
                "output_cost_per_1m": info.get("output_cost_per_1m"),
            })
        cache_summary[pid] = entries

    # Show pricing map
    pricing_list = [
        {"provider_id": pid, "model": mid, "input": inp, "output": out}
        for (pid, mid), (inp, out) in pricing_map.items()
    ]

    return {
        "litellm_cache_providers": list(cache_summary.keys()),
        "litellm_cache_entries": cache_summary,
        "pricing_map_size": len(pricing_map),
        "pricing_map": pricing_list,
    }
