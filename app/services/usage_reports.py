"""Usage summary, log, breakdown, timeseries, and provider-health read models."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, Channel, ProviderConfig, TraceEvent, Session
from app.services.usage_costs import (
    _fetch_token_usage_events,
    _get_provider_type_map,
    _load_pricing_map,
    _lookup_pricing,
    _parse_time,
    _resolve_event_cost,
)
from app.schemas.usage import (
    BreakdownGroup,
    CostByDimension,
    ProviderHealthOut,
    ProviderHealthRow,
    TimeseriesPoint,
    UsageBreakdownOut,
    UsageLogEntry,
    UsageLogsOut,
    UsageSummaryOut,
    UsageTimeseriesOut,
)


async def build_usage_summary(
    after: Optional[str] = None,
    before: Optional[str] = None,
    bot_id: Optional[str] = None,
    model: Optional[str] = None,
    provider_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    db: AsyncSession = None,
):
    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None

    events, _ = await _fetch_token_usage_events(
        db, after=after_dt, before=before_dt,
        bot_id=bot_id, model=model, provider_id=provider_id, channel_id=channel_id,
    )
    pricing = await _load_pricing_map(db)
    ptype_map = _get_provider_type_map()

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

        cost = _resolve_event_cost(d, pricing, ptype_map)

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


async def build_usage_logs(
    after: Optional[str] = None,
    before: Optional[str] = None,
    bot_id: Optional[str] = None,
    model: Optional[str] = None,
    provider_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = None,
):
    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None

    events, total = await _fetch_token_usage_events(
        db, after=after_dt, before=before_dt,
        bot_id=bot_id, model=model, provider_id=provider_id, channel_id=channel_id,
        limit=page_size, offset=(page - 1) * page_size, count_total=True,
    )
    pricing = await _load_pricing_map(db)
    ptype_map = _get_provider_type_map()

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

        cost = _resolve_event_cost(d, pricing, ptype_map)

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


async def build_usage_breakdown(
    group_by: str = "model",
    after: Optional[str] = None,
    before: Optional[str] = None,
    bot_id: Optional[str] = None,
    model: Optional[str] = None,
    provider_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    db: AsyncSession = None,
):
    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None

    events, _ = await _fetch_token_usage_events(
        db, after=after_dt, before=before_dt,
        bot_id=bot_id, model=model, provider_id=provider_id, channel_id=channel_id,
    )
    pricing = await _load_pricing_map(db)
    ptype_map = _get_provider_type_map()

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
            groups[key] = BreakdownGroup(label=label, key=key)

        g = groups[key]
        g.calls += 1
        g.tokens += tt
        g.prompt_tokens += pt
        g.completion_tokens += ct

        cost = _resolve_event_cost(d, pricing, ptype_map)
        if cost is not None:
            g.cost = (g.cost or 0) + cost

    return UsageBreakdownOut(
        group_by=group_by,
        groups=sorted(groups.values(), key=lambda x: x.cost or 0, reverse=True),
    )


async def build_usage_timeseries(
    after: Optional[str] = None,
    before: Optional[str] = None,
    bot_id: Optional[str] = None,
    model: Optional[str] = None,
    provider_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    bucket: str = "auto",
    db: AsyncSession = None,
):
    after_dt = _parse_time(after) if after else None
    before_dt = _parse_time(before) if before else None

    events, _ = await _fetch_token_usage_events(
        db, after=after_dt, before=before_dt,
        bot_id=bot_id, model=model, provider_id=provider_id, channel_id=channel_id,
    )
    pricing = await _load_pricing_map(db)
    ptype_map = _get_provider_type_map()

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

        cost = _resolve_event_cost(d, pricing, ptype_map)
        if cost is not None:
            point.cost = (point.cost or 0) + cost

    return UsageTimeseriesOut(
        bucket_size=bucket,
        points=sorted(buckets.values(), key=lambda x: x.bucket),
    )


async def build_debug_pricing(
    db: AsyncSession = None,
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
        {
            "provider_id": pid,
            "model": mid,
            "input": inp,
            "output": out,
            "cached_input": cached_inp,
        }
        for (pid, mid), (inp, out, cached_inp) in pricing_map.items()
    ]

    return {
        "litellm_cache_providers": list(cache_summary.keys()),
        "litellm_cache_entries": cache_summary,
        "pricing_map_size": len(pricing_map),
        "pricing_map": pricing_list,
    }


def _percentile(values: list[float], pct: float) -> float | None:
    """Linear-interp percentile (0.0 < pct < 1.0). Returns None on empty list."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    if lo == hi:
        return float(s[lo])
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


async def build_provider_health(
    hours: int = 24,
    db: AsyncSession = None,
):
    """Per-(provider, model) latency + cache-hit surface over a recent window.

    Aggregates the existing ``token_usage`` trace events — no new event type
    required. Returns p50/p95 latency, cache-hit rate, sample count, and last
    call timestamp. If the circuit-breaker has a cooldown for a specific
    model, surfaces ``cooldown_until_ts`` so the UI can flag it red.

    Known limit: only successful calls emit ``token_usage`` today, so the
    "error rate" metric isn't populated yet — we surface a derived sample
    count instead. When we add an explicit ``llm_call`` event later, this
    endpoint becomes the obvious home for error rate too.
    """
    from app.services.providers import _registry

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = (
        await db.execute(
            select(TraceEvent)
            .where(
                TraceEvent.event_type == "token_usage",
                TraceEvent.created_at >= since,
            )
            .order_by(TraceEvent.created_at.desc())
        )
    ).scalars().all()

    # Group (provider_id, model) → [events]
    buckets: dict[tuple[str | None, str], list[TraceEvent]] = {}
    for ev in events:
        data = ev.data or {}
        model = data.get("model")
        if not model:
            continue
        pid = data.get("provider_id")
        buckets.setdefault((pid, model), []).append(ev)

    # Pull circuit-breaker cooldowns so rows can flag active blocks.
    cooldowns: dict[str, str] = {}
    try:
        from app.agent.llm import get_active_cooldowns
        for entry in get_active_cooldowns():
            model = entry.get("model")
            until = entry.get("cooldown_until") or entry.get("expires")
            if model and until:
                cooldowns[model] = until if isinstance(until, str) else until.isoformat()
    except Exception:
        cooldowns = {}

    rows: list[ProviderHealthRow] = []
    for (pid, model), evs in buckets.items():
        latencies: list[float] = []
        cache_ratios: list[float] = []
        last_ts: datetime | None = None
        for ev in evs:
            if ev.duration_ms is not None:
                latencies.append(float(ev.duration_ms))
            d = ev.data or {}
            pt = d.get("prompt_tokens") or 0
            cached = d.get("cached_tokens")
            if pt and cached is not None:
                cache_ratios.append(min(float(cached) / float(pt), 1.0))
            if ev.created_at and (last_ts is None or ev.created_at > last_ts):
                last_ts = ev.created_at

        provider_name = None
        if pid and pid in _registry:
            provider_name = _registry[pid].display_name

        rows.append(ProviderHealthRow(
            provider_id=pid,
            provider_name=provider_name,
            model=model,
            sample_count=len(evs),
            latency_ms_p50=_percentile(latencies, 0.50),
            latency_ms_p95=_percentile(latencies, 0.95),
            cache_hit_rate=(
                sum(cache_ratios) / len(cache_ratios) if cache_ratios else None
            ),
            last_call_ts=last_ts.isoformat() if last_ts else None,
            cooldown_until_ts=cooldowns.get(model),
        ))

    rows.sort(key=lambda r: (r.provider_name or r.provider_id or "", r.model))

    return ProviderHealthOut(window_hours=hours, rows=rows)
