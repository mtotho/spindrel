"""Usage & Cost analytics API — /admin/usage/

Provides aggregated cost analysis by joining token_usage trace events
with ProviderModel pricing data at read time.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Channel, ChannelHeartbeat, HeartbeatRun,
    ProviderConfig, ProviderModel, Session, Task, TraceEvent,
)
from app.config import settings
from app.dependencies import get_db, require_scopes

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
    cached_tokens: int = 0,
    cache_discount: float = 0.0,
) -> float | None:
    """Compute cost from token counts and per-1M-token rate strings.

    cached_tokens: number of prompt tokens served from cache.
    cache_discount: fraction to discount cached tokens (0.9 = 90% off, 0.5 = 50% off).
    """
    input_rate = _parse_cost_str(input_rate_str)
    output_rate = _parse_cost_str(output_rate_str)
    if input_rate is None and output_rate is None:
        return None
    cost = 0.0
    if input_rate is not None:
        if cached_tokens > 0 and cache_discount > 0:
            uncached = prompt_tokens - cached_tokens
            cost += uncached * input_rate / 1_000_000
            cost += cached_tokens * input_rate * (1 - cache_discount) / 1_000_000
        else:
            cost += prompt_tokens * input_rate / 1_000_000
    if output_rate is not None:
        cost += completion_tokens * output_rate / 1_000_000
    return cost


# Cache discount by provider type — fraction off the input rate for cached tokens.
# Anthropic: cache reads are 10% of input price (90% discount)
# OpenAI: cached tokens are 50% off
# Google/Gemini via LiteLLM: typically 75% off, but varies — use 50% as safe default
_CACHE_DISCOUNT_BY_PROVIDER_TYPE: dict[str, float] = {
    "anthropic": 0.9,
    "anthropic-compatible": 0.9,
    "openai": 0.5,
    "openai-compatible": 0.5,
    "litellm": 0.5,
}
_DEFAULT_CACHE_DISCOUNT = 0.5


def _get_provider_type_map() -> dict[str | None, str]:
    """Map provider_id → provider_type from the in-memory registry."""
    from app.services.providers import _registry
    result: dict[str | None, str] = {None: "litellm"}  # .env fallback
    for pid, row in _registry.items():
        result[pid] = row.provider_type
    return result


def _cache_discount_for_provider(
    provider_id: str | None,
    provider_type_map: dict[str | None, str],
) -> float:
    """Return cache discount fraction for a provider."""
    ptype = provider_type_map.get(provider_id, "litellm")
    return _CACHE_DISCOUNT_BY_PROVIDER_TYPE.get(ptype, _DEFAULT_CACHE_DISCOUNT)


def _is_plan_billed(provider_id: str | None, model: str | None) -> bool:
    """Check if a call is plan-billed, by provider ID or model name.

    Checks two paths:
    1. The event's provider_id directly references a plan-billed provider
    2. The event's model name matches a ProviderModel row under a plan-billed provider
       (handles cases where calls are routed through a different provider like .env fallback)
    """
    from app.services.providers import _registry, _plan_billed_models
    if provider_id and provider_id in _registry:
        if _registry[provider_id].billing_type == "plan":
            return True
    if model and model in _plan_billed_models:
        return True
    return False


def _resolve_event_cost(
    d: dict,
    pricing: dict[tuple[str, str], tuple[str | None, str | None]],
    provider_type_map: dict[str | None, str],
) -> float | None:
    """Resolve cost for a single trace event data dict.

    Prefers response_cost (actual from provider) → computed with cache awareness.
    For plan-billed calls (fixed monthly/weekly cost), marginal cost per call is 0.
    """
    cost = d.get("response_cost")
    if cost is not None:
        return float(cost)
    pt = d.get("prompt_tokens", 0)
    ct = d.get("completion_tokens", 0)
    ev_provider = d.get("provider_id")
    ev_model = d.get("model")
    input_rate, output_rate = _lookup_pricing(pricing, ev_provider, ev_model)
    cached = d.get("cached_tokens", 0)
    discount = _cache_discount_for_provider(ev_provider, provider_type_map) if cached else 0.0
    computed = _compute_cost(pt, ct, input_rate, output_rate, cached, discount)
    # Plan-billed calls: marginal cost is 0 (flat rate), suppress "no pricing" warnings
    if computed is None and _is_plan_billed(ev_provider, ev_model):
        return 0.0
    return computed


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
            groups[key] = BreakdownGroup(label=label)

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


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------

class ForecastComponent(BaseModel):
    source: str          # "heartbeats" | "recurring_tasks" | "trajectory"
    label: str
    daily_cost: float
    monthly_cost: float
    count: int | None = None
    avg_cost_per_run: float | None = None


class LimitForecast(BaseModel):
    scope_type: str
    scope_value: str
    period: str
    limit_usd: float
    current_spend: float
    percentage: float
    projected_spend: float
    projected_percentage: float


class UsageForecastOut(BaseModel):
    daily_spend: float
    monthly_spend: float
    projected_daily: float
    projected_monthly: float
    components: list[ForecastComponent] = []
    limits: list[LimitForecast] = []
    computed_at: str
    hours_elapsed_today: float


_RECURRENCE_RE = re.compile(r"^\+(\d+)([smhdw])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _recurrence_runs_per_day(recurrence: str) -> float:
    """Parse a recurrence string like '+30m' and return runs per day."""
    m = _RECURRENCE_RE.match(recurrence.strip())
    if not m:
        return 0.0
    n, unit = int(m.group(1)), m.group(2)
    interval_secs = n * _UNIT_SECONDS[unit]
    if interval_secs <= 0:
        return 0.0
    return 86400 / interval_secs


def _group_costs_by_template(
    corr_parent: dict[str, str],
    corr_costs: dict[str, float],
) -> dict[str, list[float]]:
    """Group per-correlation-id costs by their parent template task id.

    Args:
        corr_parent: mapping from correlation_id → parent_task_id (template)
        corr_costs: mapping from correlation_id → total cost for that run

    Returns:
        dict mapping template_id → list of per-run costs
    """
    from collections import defaultdict
    result: dict[str, list[float]] = defaultdict(list)
    for cid, run_cost in corr_costs.items():
        parent_id = corr_parent.get(cid)
        if parent_id:
            result[parent_id].append(run_cost)
    return dict(result)


def _compute_recurring_task_daily(
    tasks: list,
    template_run_costs: dict[str, list[float]],
) -> float:
    """Compute total daily cost from recurring tasks and their per-template costs.

    Args:
        tasks: list of recurring Task objects (with .id, .recurrence)
        template_run_costs: mapping from template_id → list of per-run costs

    Returns:
        total daily cost
    """
    total = 0.0
    for task in tasks:
        runs_per_day = _recurrence_runs_per_day(task.recurrence or "")
        costs = template_run_costs.get(str(task.id), [])
        avg_cost = sum(costs) / len(costs) if costs else 0.0
        total += runs_per_day * avg_cost
    return total


def _compute_cost_for_events(
    events: list[TraceEvent],
    pricing: dict,
    ptype_map: dict[str | None, str] | None = None,
) -> float:
    """Sum cost across a list of TraceEvent rows."""
    if ptype_map is None:
        ptype_map = _get_provider_type_map()
    total = 0.0
    for ev in events:
        d = ev.data or {}
        cost = _resolve_event_cost(d, pricing, ptype_map)
        if cost is not None:
            total += cost
    return total


@router.get(
    "/forecast",
    response_model=UsageForecastOut,
    dependencies=[Depends(require_scopes("usage:read"))],
)
async def usage_forecast(db: AsyncSession = Depends(get_db)):
    """Cost forecast: projected daily/monthly spend from heartbeats, recurring tasks, and current trajectory."""
    now_utc = datetime.now(timezone.utc)
    # Compute "today" and "this month" boundaries in the user's configured timezone
    local_tz = ZoneInfo(settings.TIMEZONE)
    now_local = now_utc.astimezone(local_tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    seven_days_ago = now_utc - timedelta(days=7)
    hours_elapsed = (now_utc - today_start).total_seconds() / 3600
    days_elapsed = (now_utc - month_start).total_seconds() / 86400

    pricing = await _load_pricing_map(db)
    ptype_map = _get_provider_type_map()

    # --- Actual spend today & this month ---
    today_events, _ = await _fetch_token_usage_events(db, after=today_start)
    daily_spend = _compute_cost_for_events(today_events, pricing, ptype_map)

    month_events, _ = await _fetch_token_usage_events(db, after=month_start)
    monthly_spend = _compute_cost_for_events(month_events, pricing, ptype_map)

    components: list[ForecastComponent] = []

    # --- Heartbeat forecast ---
    heartbeats = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.enabled == True)  # noqa: E712
    )).scalars().all()

    if heartbeats:
        hb_ids = [hb.id for hb in heartbeats]
        # Fetch recent runs with correlation_ids for cost lookup
        recent_runs = (await db.execute(
            select(HeartbeatRun).where(
                HeartbeatRun.heartbeat_id.in_(hb_ids),
                HeartbeatRun.run_at >= seven_days_ago,
                HeartbeatRun.correlation_id.isnot(None),
            )
        )).scalars().all()

        correlation_ids = [r.correlation_id for r in recent_runs if r.correlation_id]

        hb_cost_total = 0.0
        hb_run_count = 0
        if correlation_ids:
            # Batch fetch trace events for heartbeat runs
            hb_events = (await db.execute(
                select(TraceEvent).where(
                    TraceEvent.event_type == "token_usage",
                    TraceEvent.correlation_id.in_(correlation_ids),
                )
            )).scalars().all()
            hb_cost_total = _compute_cost_for_events(hb_events, pricing)
            hb_run_count = len(correlation_ids)

        avg_cost_per_hb = hb_cost_total / hb_run_count if hb_run_count > 0 else 0.0

        # Compute total runs per day across all enabled heartbeats
        from app.services.heartbeat import _resolve_quiet_range
        total_runs_per_day = 0.0
        for hb in heartbeats:
            interval = hb.interval_minutes or 60
            quiet = _resolve_quiet_range(hb)
            if quiet:
                qs, qe = quiet
                quiet_mins = (qe.hour * 60 + qe.minute) - (qs.hour * 60 + qs.minute)
                if quiet_mins < 0:
                    quiet_mins += 24 * 60  # wraps midnight
            else:
                quiet_mins = 0
            active_mins = max(24 * 60 - quiet_mins, 0)
            total_runs_per_day += active_mins / interval if interval > 0 else 0

        hb_daily = total_runs_per_day * avg_cost_per_hb
        components.append(ForecastComponent(
            source="heartbeats",
            label="Scheduled heartbeats",
            daily_cost=round(hb_daily, 4),
            monthly_cost=round(hb_daily * 30, 4),
            count=len(heartbeats),
            avg_cost_per_run=round(avg_cost_per_hb, 6) if avg_cost_per_hb > 0 else None,
        ))

    # --- Recurring task forecast ---
    recurring_tasks = (await db.execute(
        select(Task).where(
            Task.status == "active",
            Task.recurrence.isnot(None),
        )
    )).scalars().all()

    if recurring_tasks:
        # Estimate avg cost per task from recent spawned runs.
        # Group by parent_task_id (the schedule template) so each task gets
        # its own cost average rather than sharing a per-bot average.
        # Use correlation_id (unique per run) instead of session_id, which can
        # be shared across runs or swapped during stale-session recovery.
        from collections import defaultdict

        template_ids = [t.id for t in recurring_tasks]
        recent_runs = (await db.execute(
            select(Task).where(
                Task.parent_task_id.in_(template_ids),
                Task.correlation_id.isnot(None),
                Task.completed_at >= seven_days_ago,
            )
        )).scalars().all()

        # Map correlation_id → parent_task_id for cost attribution
        corr_parent: dict[str, str] = {}
        task_correlation_ids = []
        for run in recent_runs:
            if run.correlation_id and run.parent_task_id:
                cid = str(run.correlation_id)
                corr_parent[cid] = str(run.parent_task_id)
                task_correlation_ids.append(run.correlation_id)

        # Sum cost per correlation_id, then attribute to parent template
        corr_costs: dict[str, float] = defaultdict(float)
        if task_correlation_ids:
            task_events = (await db.execute(
                select(TraceEvent).where(
                    TraceEvent.event_type == "token_usage",
                    TraceEvent.correlation_id.in_(task_correlation_ids),
                )
            )).scalars().all()

            for ev in task_events:
                cid = str(ev.correlation_id) if ev.correlation_id else None
                if not cid:
                    continue
                d = ev.data or {}
                cost = _resolve_event_cost(d, pricing, ptype_map)
                if cost is not None:
                    corr_costs[cid] += cost

        template_run_costs = _group_costs_by_template(corr_parent, corr_costs)
        task_daily = _compute_recurring_task_daily(recurring_tasks, template_run_costs)

        components.append(ForecastComponent(
            source="recurring_tasks",
            label="Recurring tasks",
            daily_cost=round(task_daily, 4),
            monthly_cost=round(task_daily * 30, 4),
            count=len(recurring_tasks),
        ))

    # --- Fixed plan costs ---
    from app.services.providers import _registry as _provider_registry
    plan_daily = 0.0
    plan_count = 0
    for prow in _provider_registry.values():
        if prow.billing_type == "plan" and prow.plan_cost:
            if prow.plan_period == "weekly":
                plan_daily += prow.plan_cost / 7
            else:  # monthly
                plan_daily += prow.plan_cost / 30
            plan_count += 1
    if plan_count > 0:
        components.append(ForecastComponent(
            source="fixed_plans",
            label="Fixed plans",
            daily_cost=round(plan_daily, 4),
            monthly_cost=round(plan_daily * 30, 4),
            count=plan_count,
        ))

    # --- Trajectory (extrapolation from current pace) ---
    if hours_elapsed >= 1.0:
        traj_daily = daily_spend / hours_elapsed * 24
        traj_monthly = monthly_spend / days_elapsed * 30 if days_elapsed >= 1.0 else traj_daily * 30
        components.append(ForecastComponent(
            source="trajectory",
            label="Current pace",
            daily_cost=round(traj_daily, 4),
            monthly_cost=round(traj_monthly, 4),
        ))

    # Projected = max(trajectory, scheduled_variable) + fixed_plans
    # Trajectory already includes variable scheduled costs (heartbeats + tasks) that
    # ran today, so we take the higher of trajectory vs scheduled variable costs.
    # Fixed plan costs are always added on top since they're unavoidable flat fees.
    fixed_plan_daily = next((c.daily_cost for c in components if c.source == "fixed_plans"), 0.0)
    fixed_plan_monthly = next((c.monthly_cost for c in components if c.source == "fixed_plans"), 0.0)
    variable_scheduled_daily = sum(c.daily_cost for c in components if c.source not in ("trajectory", "fixed_plans"))
    variable_scheduled_monthly = sum(c.monthly_cost for c in components if c.source not in ("trajectory", "fixed_plans"))
    trajectory_daily = next((c.daily_cost for c in components if c.source == "trajectory"), 0.0)
    trajectory_monthly = next((c.monthly_cost for c in components if c.source == "trajectory"), 0.0)
    projected_daily = max(trajectory_daily, variable_scheduled_daily) + fixed_plan_daily
    projected_monthly = max(trajectory_monthly, variable_scheduled_monthly) + fixed_plan_monthly

    # --- Limit forecasts ---
    from app.services.usage_limits import _limits, _period_start
    limit_forecasts: list[LimitForecast] = []
    for limit in _limits:
        since = _period_start(limit.period)
        # Compute current spend for this limit's scope
        base_q = select(TraceEvent).where(
            TraceEvent.event_type == "token_usage",
            TraceEvent.created_at >= since,
        )
        if limit.scope_type == "bot":
            base_q = base_q.where(TraceEvent.bot_id == limit.scope_value)
        elif limit.scope_type == "model":
            base_q = base_q.where(TraceEvent.data["model"].astext == limit.scope_value)

        limit_events = (await db.execute(base_q)).scalars().all()
        current = _compute_cost_for_events(limit_events, pricing)
        pct = (current / limit.limit_usd * 100) if limit.limit_usd > 0 else 0

        # Project spend to end of period by extrapolating this scope's own pace
        if limit.period == "daily":
            projected = current / hours_elapsed * 24 if hours_elapsed >= 1.0 else current
        else:  # monthly
            projected = current / days_elapsed * 30 if days_elapsed >= 1.0 else current

        proj_pct = (projected / limit.limit_usd * 100) if limit.limit_usd > 0 else 0

        limit_forecasts.append(LimitForecast(
            scope_type=limit.scope_type,
            scope_value=limit.scope_value,
            period=limit.period,
            limit_usd=limit.limit_usd,
            current_spend=round(current, 4),
            percentage=round(pct, 1),
            projected_spend=round(projected, 4),
            projected_percentage=round(proj_pct, 1),
        ))

    return UsageForecastOut(
        daily_spend=round(daily_spend, 4),
        monthly_spend=round(monthly_spend, 4),
        projected_daily=round(projected_daily, 4),
        projected_monthly=round(projected_monthly, 4),
        components=components,
        limits=limit_forecasts,
        computed_at=now_utc.isoformat(),
        hours_elapsed_today=round(hours_elapsed, 2),
    )
