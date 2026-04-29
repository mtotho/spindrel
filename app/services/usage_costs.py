"""Shared usage pricing and token-usage query helpers."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProviderModel, TraceEvent

logger = logging.getLogger(__name__)


def _parse_time(value: str) -> datetime | None:
    """Parse an ISO timestamp or relative time string like '30m', '2h', '1d'."""
    if not value:
        return None
    value = value.strip()
    if value and value[-1] in ("m", "h", "d") and value[:-1].replace(".", "").isdigit():
        num = float(value[:-1])
        unit = value[-1]
        delta = {"m": timedelta(minutes=num), "h": timedelta(hours=num), "d": timedelta(days=num)}[unit]
        return datetime.now(timezone.utc) - delta
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None




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
    def normalize(costs: tuple[str | None, ...]) -> tuple[str | None, str | None, str | None]:
        if len(costs) == 2:
            return (costs[0], costs[1], None)
        return (costs[0], costs[1], costs[2])

    if not model:
        return (None, None, None)
    if provider_id:
        key = (provider_id, model)
        if key in pricing_map:
            return normalize(pricing_map[key])
    else:
        # No provider_id — try the .env LiteLLM fallback key
        env_key = ("__env__", model)
        if env_key in pricing_map:
            return normalize(pricing_map[env_key])
    # Fallback: match on model_id alone across all providers
    for (pid, mid), costs in pricing_map.items():
        if mid == model:
            return normalize(costs)
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
