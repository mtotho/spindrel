"""Usage & Cost analytics API — /admin/usage/

Provides aggregated cost analysis by joining token_usage trace events
with ProviderModel pricing data at read time.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Bot, Channel, ChannelHeartbeat, HeartbeatRun,
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
    cached_input_rate_str: str | None = None,
) -> float | None:
    """Compute cost from token counts and per-1M-token rate strings.

    Resolution order for cached-token pricing (when ``cached_tokens > 0``):
      1. Explicit ``cached_input_rate_str`` (column ``cached_input_cost_per_1m``)
         — authoritative per-(provider, model) rate from the DB.
      2. ``cache_discount`` fraction off the input rate — fallback heuristic by
         provider-type when the admin hasn't set an explicit cached rate.
    """
    input_rate = _parse_cost_str(input_rate_str)
    output_rate = _parse_cost_str(output_rate_str)
    cached_rate = _parse_cost_str(cached_input_rate_str)
    if input_rate is None and output_rate is None:
        return None
    cost = 0.0
    if input_rate is not None:
        if cached_tokens > 0 and cached_rate is not None:
            uncached = max(prompt_tokens - cached_tokens, 0)
            cost += uncached * input_rate / 1_000_000
            cost += cached_tokens * cached_rate / 1_000_000
        elif cached_tokens > 0 and cache_discount > 0:
            uncached = max(prompt_tokens - cached_tokens, 0)
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
    pricing: dict[tuple[str, str], tuple[str | None, str | None, str | None]],
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
    input_rate, output_rate, cached_rate = _lookup_pricing(pricing, ev_provider, ev_model)
    cached = d.get("cached_tokens", 0)
    # Cache discount fallback only kicks in when no explicit cached_rate is set.
    discount = (
        _cache_discount_for_provider(ev_provider, provider_type_map)
        if cached and not cached_rate
        else 0.0
    )
    computed = _compute_cost(
        pt, ct, input_rate, output_rate, cached, discount,
        cached_input_rate_str=cached_rate,
    )
    # Plan-billed calls: marginal cost is 0 (flat rate), suppress "no pricing" warnings
    if computed is None and _is_plan_billed(ev_provider, ev_model):
        return 0.0
    return computed


async def _load_pricing_map(
    db: AsyncSession,
) -> dict[tuple[str, str], tuple[str | None, str | None, str | None]]:
    """Bulk load pricing from DB ProviderModel rows + LiteLLM model info cache.

    LiteLLM cached entries are added first, then DB rows override so that
    user-configured pricing always wins. Tuple shape is
    ``(input_rate, output_rate, cached_input_rate)``.
    """
    result: dict[tuple[str, str], tuple[str | None, str | None, str | None]] = {}

    # Seed from LiteLLM model info cache (auto-fetched from /model/info at startup)
    from app.services.providers import _model_info_cache
    litellm_entries = 0
    for provider_id, models in _model_info_cache.items():
        pid = provider_id or "__env__"
        for model_id, info in models.items():
            inp = info.get("input_cost_per_1m")
            out = info.get("output_cost_per_1m")
            if inp or out:
                result[(pid, model_id)] = (inp, out, None)
                litellm_entries += 1

    # DB rows override LiteLLM cache
    rows = (await db.execute(
        select(
            ProviderModel.provider_id,
            ProviderModel.model_id,
            ProviderModel.input_cost_per_1m,
            ProviderModel.output_cost_per_1m,
            ProviderModel.cached_input_cost_per_1m,
        )
    )).all()
    db_entries = 0
    for r in rows:
        if r.input_cost_per_1m or r.output_cost_per_1m or r.cached_input_cost_per_1m:
            result[(r.provider_id, r.model_id)] = (
                r.input_cost_per_1m,
                r.output_cost_per_1m,
                r.cached_input_cost_per_1m,
            )
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
    pricing_map: dict[tuple[str, str], tuple[str | None, str | None, str | None]],
    provider_id: str | None,
    model: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Find ``(input, output, cached_input)`` pricing for a (provider_id, model) pair.

    Resolution order:
    1. Exact (provider_id, model) match in ProviderModel DB rows.
    2. Model-only match in DB rows (for old events without provider_id).
    3. LiteLLM model info cache (auto-fetched from /model/info at startup).
    """
    if not model:
        return (None, None, None)
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
            return (inp, out, None)
    return (None, None, None)


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
    key: str = ""
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


class UsageAnomalyMetric(BaseModel):
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost: float | None = None
    has_cost_data: bool = True


class UsageAnomalySource(BaseModel):
    source_type: str = "unknown"
    title: str | None = None
    task_id: str | None = None
    task_type: str | None = None
    bot_id: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    model: str | None = None
    provider_id: str | None = None
    provider_name: str | None = None


class UsageAnomalySignal(BaseModel):
    id: str
    kind: str
    label: str
    severity: str = "info"
    reason: str
    created_at: str | None = None
    bucket: str | None = None
    correlation_id: str | None = None
    dimension: str | None = None
    dimension_value: str | None = None
    metric: UsageAnomalyMetric
    baseline: UsageAnomalyMetric | None = None
    ratio: float | None = None
    cost_confidence: str = "unknown"
    source: UsageAnomalySource = Field(default_factory=UsageAnomalySource)


class UsageAnomaliesOut(BaseModel):
    window_start: str
    window_end: str
    baseline_start: str
    baseline_end: str
    bucket_size: str
    time_spikes: list[UsageAnomalySignal] = Field(default_factory=list)
    trace_bursts: list[UsageAnomalySignal] = Field(default_factory=list)
    contributors: list[UsageAnomalySignal] = Field(default_factory=list)


def _metric_from_events(
    events: list[TraceEvent],
    pricing: dict,
    ptype_map: dict[str | None, str],
) -> UsageAnomalyMetric:
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    calls = 0
    cost_total = 0.0
    has_cost_data = True
    for ev in events:
        d = ev.data or {}
        pt = int(d.get("prompt_tokens") or 0)
        ct = int(d.get("completion_tokens") or 0)
        tt = int(d.get("total_tokens") or (pt + ct))
        total_tokens += tt
        prompt_tokens += pt
        completion_tokens += ct
        calls += 1
        cost = _resolve_event_cost(d, pricing, ptype_map)
        if cost is None:
            has_cost_data = False
        else:
            cost_total += cost
    return UsageAnomalyMetric(
        tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        calls=calls,
        cost=round(cost_total, 6) if cost_total > 0 else None,
        has_cost_data=has_cost_data,
    )


def _metric_ratio(current: UsageAnomalyMetric, baseline: UsageAnomalyMetric | None) -> float | None:
    if not baseline or baseline.tokens <= 0:
        return None
    return round(current.tokens / baseline.tokens, 2)


def _severity(metric: UsageAnomalyMetric, ratio: float | None) -> str:
    if metric.tokens >= 100_000 or (ratio is not None and ratio >= 5):
        return "danger"
    if metric.tokens >= 25_000 or (ratio is not None and ratio >= 2):
        return "warning"
    return "info"


def _source_type_for_trace(correlation_id: uuid.UUID | None, task_by_corr: dict[str, Task]) -> str:
    if not correlation_id:
        return "agent"
    task = task_by_corr.get(str(correlation_id))
    if not task:
        return "agent"
    if task.task_type == "heartbeat":
        return "heartbeat"
    if task.task_type in ("memory_hygiene", "skill_review"):
        return "maintenance"
    if task.parent_task_id or task.recurrence:
        return "task"
    return task.task_type or "task"


def _cost_confidence_for_events(
    events: list[TraceEvent],
    pricing: dict,
    provider_type_map: dict[str | None, str],
) -> str:
    if not events:
        return "unknown"
    states: set[str] = set()
    for ev in events:
        d = ev.data or {}
        provider_id = d.get("provider_id")
        model = d.get("model")
        if _is_plan_billed(provider_id, model):
            states.add("plan")
            continue
        ptype = provider_type_map.get(provider_id)
        if ptype in {"ollama", "local"} or (model and str(model).startswith("ollama/")):
            states.add("local")
            continue
        if _resolve_event_cost(d, pricing, provider_type_map) is not None:
            states.add("metered")
        else:
            states.add("missing")
    if "metered" in states:
        return "metered"
    if "plan" in states:
        return "plan"
    if "local" in states:
        return "local"
    if "missing" in states:
        return "missing"
    return "unknown"


async def _usage_source_maps(
    db: AsyncSession,
    events: list[TraceEvent],
) -> tuple[dict[str, Task], dict[str, str], dict[str, str]]:
    corr_ids = [ev.correlation_id for ev in events if ev.correlation_id]
    tasks_by_corr: dict[str, Task] = {}
    if corr_ids:
        task_rows = (await db.execute(
            select(Task).where(Task.correlation_id.in_(corr_ids))
        )).scalars().all()
        tasks_by_corr = {str(task.correlation_id): task for task in task_rows if task.correlation_id}

    channel_ids: set[str] = set()
    for ev in events:
        cid = (ev.data or {}).get("channel_id")
        if cid:
            channel_ids.add(str(cid))
    for task in tasks_by_corr.values():
        if task.channel_id:
            channel_ids.add(str(task.channel_id))

    channel_name_map: dict[str, str] = {}
    valid_channel_ids: list[uuid.UUID] = []
    for cid in channel_ids:
        try:
            valid_channel_ids.append(uuid.UUID(cid))
        except ValueError:
            pass
    if valid_channel_ids:
        rows = (await db.execute(
            select(Channel.id, Channel.name).where(Channel.id.in_(valid_channel_ids))
        )).all()
        channel_name_map = {str(row.id): row.name for row in rows}

    provider_names: dict[str, str] = {}
    provider_rows = (await db.execute(
        select(ProviderConfig.id, ProviderConfig.display_name)
    )).all()
    for row in provider_rows:
        provider_names[row.id] = row.display_name

    return tasks_by_corr, channel_name_map, provider_names


def _source_for_events(
    events: list[TraceEvent],
    task_by_corr: dict[str, Task],
    channel_names: dict[str, str],
    provider_names: dict[str, str],
) -> UsageAnomalySource:
    first = events[0] if events else None
    if not first:
        return UsageAnomalySource()
    d = first.data or {}
    corr = str(first.correlation_id) if first.correlation_id else None
    task = task_by_corr.get(corr or "")
    channel_id = str(task.channel_id) if task and task.channel_id else d.get("channel_id")
    source_type = _source_type_for_trace(first.correlation_id, task_by_corr)
    title = None
    if task:
        title = task.title or task.task_type
    return UsageAnomalySource(
        source_type=source_type,
        title=title,
        task_id=str(task.id) if task else None,
        task_type=task.task_type if task else None,
        bot_id=first.bot_id or (task.bot_id if task else None),
        channel_id=str(channel_id) if channel_id else None,
        channel_name=channel_names.get(str(channel_id)) if channel_id else None,
        model=d.get("model"),
        provider_id=d.get("provider_id"),
        provider_name=provider_names.get(d.get("provider_id")) if d.get("provider_id") else None,
    )


def _bucket_key(created_at: datetime, bucket_seconds: int) -> str:
    bucket_ts = datetime.fromtimestamp(
        (int(created_at.timestamp()) // bucket_seconds) * bucket_seconds,
        tz=timezone.utc,
    )
    return bucket_ts.isoformat()


def _representative_correlation_id(events: list[TraceEvent]) -> str | None:
    """Pick the highest-token trace inside a grouped signal."""
    by_trace: dict[str, list[TraceEvent]] = {}
    for ev in events:
        if ev.correlation_id:
            by_trace.setdefault(str(ev.correlation_id), []).append(ev)
    if not by_trace:
        return None

    def trace_tokens(trace_events: list[TraceEvent]) -> int:
        total = 0
        for ev in trace_events:
            d = ev.data or {}
            total += int(d.get("total_tokens") or ((d.get("prompt_tokens") or 0) + (d.get("completion_tokens") or 0)))
        return total

    trace_id, _trace_events = max(by_trace.items(), key=lambda item: trace_tokens(item[1]))
    return trace_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

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
    """Compute high-signal usage anomalies for the selected window.

    The endpoint is intentionally read-only and stateless: anomalies are
    recalculated from token_usage trace events for the current window and the
    immediately previous matching baseline window.
    """
    now = datetime.now(timezone.utc)
    after_dt = _parse_time(after) if after else now - timedelta(hours=24)
    before_dt = _parse_time(before) if before else now
    if after_dt is None:
        after_dt = now - timedelta(hours=24)
    if before_dt is None:
        before_dt = now
    if after_dt >= before_dt:
        after_dt = before_dt - timedelta(hours=24)

    span = before_dt - after_dt
    baseline_start = after_dt - span
    baseline_end = after_dt

    pricing = await _load_pricing_map(db)
    ptype_map = _get_provider_type_map()

    events, _ = await _fetch_token_usage_events(
        db,
        after=after_dt,
        before=before_dt,
        bot_id=bot_id,
        model=model,
        provider_id=provider_id,
        channel_id=channel_id,
    )
    baseline_events, _ = await _fetch_token_usage_events(
        db,
        after=baseline_start,
        before=baseline_end,
        bot_id=bot_id,
        model=model,
        provider_id=provider_id,
        channel_id=channel_id,
    )

    task_by_corr, channel_names, provider_names = await _usage_source_maps(db, events + baseline_events)

    if source_type:
        events = [
            ev for ev in events
            if _source_type_for_trace(ev.correlation_id, task_by_corr) == source_type
        ]
        baseline_events = [
            ev for ev in baseline_events
            if _source_type_for_trace(ev.correlation_id, task_by_corr) == source_type
        ]

    span_seconds = max(1, int(span.total_seconds()))
    if span_seconds <= 36 * 3600:
        bucket_seconds = 3600
        bucket_size = "1h"
    elif span_seconds <= 7 * 86400:
        bucket_seconds = 6 * 3600
        bucket_size = "6h"
    else:
        bucket_seconds = 86400
        bucket_size = "1d"

    current_buckets: dict[str, list[TraceEvent]] = {}
    for ev in events:
        current_buckets.setdefault(_bucket_key(ev.created_at, bucket_seconds), []).append(ev)
    baseline_buckets: dict[str, list[TraceEvent]] = {}
    for ev in baseline_events:
        baseline_buckets.setdefault(_bucket_key(ev.created_at + span, bucket_seconds), []).append(ev)

    time_spikes: list[UsageAnomalySignal] = []
    for bucket, bucket_events in current_buckets.items():
        metric = _metric_from_events(bucket_events, pricing, ptype_map)
        baseline_metric = _metric_from_events(baseline_buckets.get(bucket, []), pricing, ptype_map)
        ratio = _metric_ratio(metric, baseline_metric)
        if metric.tokens < 5_000 and (ratio is None or ratio < 2):
            continue
        if ratio is not None and ratio < 1.5 and metric.tokens < 25_000:
            continue
        time_spikes.append(UsageAnomalySignal(
            id=f"time:{bucket}",
            kind="time_spike",
            label=f"Spike around {bucket}",
            severity=_severity(metric, ratio),
            reason=f"{ratio}x previous window" if ratio is not None else "High token bucket",
            created_at=bucket,
            bucket=bucket,
            correlation_id=_representative_correlation_id(bucket_events),
            metric=metric,
            baseline=baseline_metric,
            ratio=ratio,
            cost_confidence=_cost_confidence_for_events(bucket_events, pricing, ptype_map),
            source=_source_for_events(bucket_events, task_by_corr, channel_names, provider_names),
        ))
    time_spikes.sort(key=lambda item: (item.severity == "danger", item.metric.tokens), reverse=True)

    by_trace: dict[str, list[TraceEvent]] = {}
    for ev in events:
        key = str(ev.correlation_id) if ev.correlation_id else str(ev.id)
        by_trace.setdefault(key, []).append(ev)
    trace_baseline_tokens = _metric_from_events(baseline_events, pricing, ptype_map).tokens
    average_baseline_trace = max(1, trace_baseline_tokens // max(1, len({str(ev.correlation_id) for ev in baseline_events if ev.correlation_id})))

    trace_bursts: list[UsageAnomalySignal] = []
    for trace_id, trace_events in by_trace.items():
        metric = _metric_from_events(trace_events, pricing, ptype_map)
        iterations = max(int((ev.data or {}).get("iteration") or 0) for ev in trace_events)
        ratio = round(metric.tokens / average_baseline_trace, 2) if average_baseline_trace > 0 else None
        if metric.tokens < 10_000 and iterations < 4 and (ratio is None or ratio < 2):
            continue
        first = min(trace_events, key=lambda ev: ev.created_at)
        reason_parts = []
        if metric.tokens >= 10_000:
            reason_parts.append("large token trace")
        if iterations >= 4:
            reason_parts.append(f"{iterations} iterations")
        if ratio is not None and ratio >= 2:
            reason_parts.append(f"{ratio}x baseline trace")
        trace_bursts.append(UsageAnomalySignal(
            id=f"trace:{trace_id}",
            kind="trace_burst",
            label=_source_for_events(trace_events, task_by_corr, channel_names, provider_names).title or "High-usage trace",
            severity=_severity(metric, ratio),
            reason=", ".join(reason_parts) or "High trace usage",
            created_at=first.created_at.isoformat() if first.created_at else None,
            correlation_id=trace_id if trace_events[0].correlation_id else None,
            metric=metric,
            ratio=ratio,
            cost_confidence=_cost_confidence_for_events(trace_events, pricing, ptype_map),
            source=_source_for_events(trace_events, task_by_corr, channel_names, provider_names),
        ))
    trace_bursts.sort(key=lambda item: (item.severity == "danger", item.metric.tokens), reverse=True)

    def _contributors(dimension: str) -> list[UsageAnomalySignal]:
        current: dict[str, list[TraceEvent]] = {}
        previous: dict[str, list[TraceEvent]] = {}
        for ev in events:
            d = ev.data or {}
            if dimension == "bot":
                key = ev.bot_id or "unknown"
            elif dimension == "channel":
                key = d.get("channel_id") or "unknown"
            elif dimension == "provider":
                key = d.get("provider_id") or "default"
            else:
                key = d.get("model") or "unknown"
            current.setdefault(str(key), []).append(ev)
        for ev in baseline_events:
            d = ev.data or {}
            if dimension == "bot":
                key = ev.bot_id or "unknown"
            elif dimension == "channel":
                key = d.get("channel_id") or "unknown"
            elif dimension == "provider":
                key = d.get("provider_id") or "default"
            else:
                key = d.get("model") or "unknown"
            previous.setdefault(str(key), []).append(ev)
        signals: list[UsageAnomalySignal] = []
        for key, group_events in current.items():
            metric = _metric_from_events(group_events, pricing, ptype_map)
            baseline_metric = _metric_from_events(previous.get(key, []), pricing, ptype_map)
            ratio = _metric_ratio(metric, baseline_metric)
            if metric.tokens < 10_000 and (ratio is None or ratio < 2):
                continue
            label = channel_names.get(key, key) if dimension == "channel" else key
            signals.append(UsageAnomalySignal(
                id=f"{dimension}:{key}",
                kind="contributor",
                label=label,
                severity=_severity(metric, ratio),
                reason=f"{ratio}x previous window" if ratio is not None else f"Top {dimension} by tokens",
                dimension=dimension,
                dimension_value=key,
                metric=metric,
                baseline=baseline_metric,
                ratio=ratio,
                cost_confidence=_cost_confidence_for_events(group_events, pricing, ptype_map),
                source=_source_for_events(group_events, task_by_corr, channel_names, provider_names),
            ))
        return signals

    contributors = (
        _contributors("bot") +
        _contributors("channel") +
        _contributors("model") +
        _contributors("provider")
    )
    contributors.sort(key=lambda item: (item.severity == "danger", item.metric.tokens), reverse=True)

    return UsageAnomaliesOut(
        window_start=after_dt.isoformat(),
        window_end=before_dt.isoformat(),
        baseline_start=baseline_start.isoformat(),
        baseline_end=baseline_end.isoformat(),
        bucket_size=bucket_size,
        time_spikes=time_spikes[:8],
        trace_bursts=trace_bursts[:10],
        contributors=contributors[:12],
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
    _auth=Depends(require_scopes("usage:read")),
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
    _auth=Depends(require_scopes("usage:read")),
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
    _auth=Depends(require_scopes("usage:read")),
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

    # Shared lazy-loaded model average cost map (used by recurring tasks + maintenance)
    model_avg_cost: dict[str, float] | None = None

    # --- Recurring task forecast ---
    recurring_tasks = (await db.execute(
        select(Task).where(
            Task.status == "active",
            Task.recurrence.isnot(None),
        )
    )).scalars().all()

    if recurring_tasks:
        # Estimate cost per recurring task using correlation_id-based cost
        # attribution from recent spawned runs. Falls back to model-based
        # estimate for tasks without correlation data (pre-migration runs).
        from app.agent.bots import _registry as _bot_registry
        from collections import defaultdict

        template_ids = [t.id for t in recurring_tasks]

        # --- Phase 1: correlation_id-based cost (precise) ---
        recent_runs = (await db.execute(
            select(Task).where(
                Task.parent_task_id.in_(template_ids),
                Task.correlation_id.isnot(None),
                Task.completed_at >= seven_days_ago,
            )
        )).scalars().all()

        # Map correlation_id → parent_task_id
        corr_parent: dict[str, str] = {}
        task_corr_ids = []
        for run in recent_runs:
            if run.correlation_id and run.parent_task_id:
                cid = str(run.correlation_id)
                corr_parent[cid] = str(run.parent_task_id)
                task_corr_ids.append(run.correlation_id)

        # Batch fetch trace events by correlation_id
        template_run_costs: dict[str, list[float]] = defaultdict(list)
        if task_corr_ids:
            task_events = (await db.execute(
                select(TraceEvent).where(
                    TraceEvent.event_type == "token_usage",
                    TraceEvent.correlation_id.in_(task_corr_ids),
                )
            )).scalars().all()

            corr_costs: dict[str, float] = defaultdict(float)
            for ev in task_events:
                cid = str(ev.correlation_id) if ev.correlation_id else None
                if not cid:
                    continue
                d = ev.data or {}
                cost = _resolve_event_cost(d, pricing, ptype_map)
                if cost is not None:
                    corr_costs[cid] += cost

            for cid, run_cost in corr_costs.items():
                parent_id = corr_parent.get(cid)
                if parent_id:
                    template_run_costs[parent_id].append(run_cost)

        # --- Phase 2: model-based fallback for tasks without correlation data ---
        # Build avg cost-per-call by model from recent 7-day usage (lazy, only if needed)
        templates_with_data = set(template_run_costs.keys())

        task_daily = 0.0
        for task in recurring_tasks:
            runs_per_day = _recurrence_runs_per_day(task.recurrence or "")
            if runs_per_day <= 0:
                continue

            tid = str(task.id)
            if tid in templates_with_data:
                # Use actual correlation-based cost average
                costs = template_run_costs[tid]
                avg_cost = sum(costs) / len(costs) if costs else 0.0
            else:
                # Fallback: estimate from model's avg cost per call
                bot = _bot_registry.get(task.bot_id)
                model = bot.model if bot else None

                if model and _is_plan_billed(None, model):
                    continue

                # Lazy-load model averages on first fallback
                if model_avg_cost is None:
                    recent_events, _ = await _fetch_token_usage_events(db, after=seven_days_ago)
                    _mcs: dict[str, float] = defaultdict(float)
                    _mcc: dict[str, int] = defaultdict(int)
                    for ev in recent_events:
                        d = ev.data or {}
                        ev_model = d.get("model")
                        if not ev_model:
                            continue
                        c = _resolve_event_cost(d, pricing, ptype_map)
                        if c is not None:
                            _mcs[ev_model] += c
                            _mcc[ev_model] += 1
                    model_avg_cost = {
                        m: _mcs[m] / _mcc[m] for m in _mcs if _mcc[m] > 0
                    }

                avg_cost = model_avg_cost.get(model, 0.0) if model else 0.0

            task_daily += runs_per_day * avg_cost

        components.append(ForecastComponent(
            source="recurring_tasks",
            label="Recurring tasks",
            daily_cost=round(task_daily, 4),
            monthly_cost=round(task_daily * 30, 4),
            count=len(recurring_tasks),
        ))

    # --- Maintenance tasks forecast (memory_hygiene + skill_review) ---
    from app.services.memory_hygiene import resolve_config as resolve_hygiene_config

    maint_bots = (await db.execute(
        select(Bot).where(Bot.memory_scheme == "workspace-files")
    )).scalars().all()

    maint_daily = 0.0
    maint_count = 0

    if maint_bots:
        # Fetch recent completed + skipped maintenance tasks for cost & skip-rate
        maint_types = ("memory_hygiene", "skill_review")
        recent_maint = (await db.execute(
            select(Task).where(
                Task.task_type.in_(maint_types),
                Task.status.in_(("completed", "skipped")),
                Task.completed_at >= seven_days_ago,
            )
        )).scalars().all()

        # Cost per run via correlation_id (completed tasks only)
        completed_corr_ids = [
            t.correlation_id for t in recent_maint
            if t.status == "completed" and t.correlation_id
        ]
        type_run_costs: dict[str, list[float]] = {"memory_hygiene": [], "skill_review": []}
        if completed_corr_ids:
            maint_events = (await db.execute(
                select(TraceEvent).where(
                    TraceEvent.event_type == "token_usage",
                    TraceEvent.correlation_id.in_(completed_corr_ids),
                )
            )).scalars().all()

            # Sum cost per correlation_id
            from collections import defaultdict as _defaultdict
            corr_cost: dict[str, float] = _defaultdict(float)
            for ev in maint_events:
                cid = str(ev.correlation_id) if ev.correlation_id else None
                if not cid:
                    continue
                d = ev.data or {}
                cost = _resolve_event_cost(d, pricing, ptype_map)
                if cost is not None:
                    corr_cost[cid] += cost

            # Map correlation_id back to task_type
            corr_to_type = {
                str(t.correlation_id): t.task_type
                for t in recent_maint
                if t.status == "completed" and t.correlation_id
            }
            for cid, run_cost in corr_cost.items():
                tt = corr_to_type.get(cid)
                if tt and tt in type_run_costs:
                    type_run_costs[tt].append(run_cost)

        # Skip rate per job type: fraction of runs that actually executed
        type_skip_rate: dict[str, float] = {}
        for tt in maint_types:
            completed = sum(1 for t in recent_maint if t.task_type == tt and t.status == "completed")
            skipped = sum(1 for t in recent_maint if t.task_type == tt and t.status == "skipped")
            total = completed + skipped
            type_skip_rate[tt] = completed / total if total > 0 else 0.5  # default 50% if no data

        for bot in maint_bots:
            for job_type in maint_types:
                cfg = resolve_hygiene_config(bot, job_type)
                if not cfg.enabled or cfg.interval_hours <= 0:
                    continue

                maint_count += 1
                runs_per_day = 24.0 / cfg.interval_hours
                # Apply empirical execution rate (accounts for only_if_active skips)
                runs_per_day *= type_skip_rate.get(job_type, 0.5)

                costs = type_run_costs.get(job_type, [])
                if costs:
                    avg_cost = sum(costs) / len(costs)
                else:
                    # Fallback: use model-based average (same lazy-load as recurring tasks)
                    model = cfg.model
                    if not model:
                        from app.agent.bots import _registry as _bot_reg
                        b = _bot_reg.get(bot.id)
                        model = b.model if b else None
                    if model and _is_plan_billed(None, model):
                        continue
                    if model_avg_cost is None:
                        recent_events, _ = await _fetch_token_usage_events(db, after=seven_days_ago)
                        _mcs2: dict[str, float] = {}
                        _mcc2: dict[str, int] = {}
                        for ev in recent_events:
                            d = ev.data or {}
                            ev_model = d.get("model")
                            if not ev_model:
                                continue
                            c = _resolve_event_cost(d, pricing, ptype_map)
                            if c is not None:
                                _mcs2[ev_model] = _mcs2.get(ev_model, 0.0) + c
                                _mcc2[ev_model] = _mcc2.get(ev_model, 0) + 1
                        model_avg_cost = {
                            m: _mcs2[m] / _mcc2[m] for m in _mcs2 if _mcc2[m] > 0
                        }
                    avg_cost = model_avg_cost.get(model, 0.0) if model else 0.0

                maint_daily += runs_per_day * avg_cost

    if maint_count > 0:
        components.append(ForecastComponent(
            source="maintenance_tasks",
            label="Maintenance tasks",
            daily_cost=round(maint_daily, 4),
            monthly_cost=round(maint_daily * 30, 4),
            count=maint_count,
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


# ---------------------------------------------------------------------------
# Provider Health — per-(provider, model) latency + cache-hit + last-call
# ---------------------------------------------------------------------------


class ProviderHealthRow(BaseModel):
    provider_id: str | None = None
    provider_name: str | None = None
    model: str
    sample_count: int
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    cache_hit_rate: float | None = None
    last_call_ts: str | None = None
    cooldown_until_ts: str | None = None


class ProviderHealthOut(BaseModel):
    window_hours: int
    rows: list[ProviderHealthRow]


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


@router.get("/usage/provider-health", response_model=ProviderHealthOut)
async def admin_provider_health(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("providers:read")),
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
