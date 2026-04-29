"""Usage telemetry helpers for external agent harnesses."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session, TraceEvent
from app.services.agent_harnesses.session_state import (
    context_window_from_usage,
    normalize_context_usage,
)

HARNESS_PROVIDER_PREFIX = "harness:"
HARNESS_USAGE_SOURCE = "harness_sdk"


def harness_provider_id(runtime: str | None) -> str:
    value = (runtime or "unknown").strip() or "unknown"
    if value == "claude-code":
        return f"{HARNESS_PROVIDER_PREFIX}claude-code-sdk"
    if value == "codex":
        return f"{HARNESS_PROVIDER_PREFIX}codex-sdk"
    return f"{HARNESS_PROVIDER_PREFIX}{value}-sdk"


def is_harness_provider_id(provider_id: str | None) -> bool:
    return isinstance(provider_id, str) and provider_id.startswith(HARNESS_PROVIDER_PREFIX)


def is_harness_usage_event(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    return (
        data.get("usage_source") == HARNESS_USAGE_SOURCE
        or is_harness_provider_id(data.get("provider_id"))
    )


def synthetic_harness_provider_name(provider_id: str | None) -> str | None:
    if provider_id == "harness:codex-sdk":
        return "Codex SDK"
    if provider_id == "harness:claude-code-sdk":
        return "Claude Code SDK"
    if is_harness_provider_id(provider_id):
        return provider_id.removeprefix(HARNESS_PROVIDER_PREFIX).replace("-", " ").title()
    return None


def _num(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


def _harness_usage_data(
    *,
    runtime: str | None,
    model: str | None,
    channel_id: uuid.UUID | None,
    usage: dict[str, Any],
    cost_usd: float | None,
) -> dict[str, Any] | None:
    prompt_tokens = _num(usage, "last_input_tokens", "input_tokens", "prompt_tokens")
    completion_tokens = _num(usage, "last_output_tokens", "output_tokens", "completion_tokens")
    reasoning_tokens = _num(usage, "last_reasoning_output_tokens", "reasoning_output_tokens")
    cached_tokens = _num(usage, "last_cached_tokens", "cached_tokens", "cache_read_input_tokens")
    total_tokens = _num(usage, "last_total_tokens")

    computed_total = sum(
        value
        for value in (prompt_tokens, completion_tokens, reasoning_tokens)
        if isinstance(value, int)
    )
    if total_tokens is None and computed_total > 0:
        total_tokens = computed_total
    if total_tokens is None:
        total_tokens = _num(usage, "context_tokens", "context_total_tokens", "total_tokens")
    if total_tokens is None or total_tokens <= 0:
        return None

    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or max(total_tokens - prompt_tokens, 0)
    current_prompt = prompt_tokens
    if cached_tokens is not None:
        current_prompt = max(prompt_tokens - cached_tokens, 0)

    window = context_window_from_usage(usage)
    context = normalize_context_usage(
        usage,
        runtime=runtime,
        context_window_tokens=window,
        source="last_turn",
    )

    data: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "gross_prompt_tokens": prompt_tokens,
        "current_prompt_tokens": current_prompt,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "consumed_tokens": prompt_tokens,
        "model": model or f"{runtime or 'harness'}/default",
        "provider_id": harness_provider_id(runtime),
        "channel_id": str(channel_id) if channel_id else None,
        "usage_source": HARNESS_USAGE_SOURCE,
        "billing_source": HARNESS_USAGE_SOURCE,
        "billing_mode": "non_billable",
        "harness_runtime": runtime,
        "harness_reported_cost_usd": cost_usd,
        "context_window_tokens": context.get("context_window_tokens"),
        "context_tokens": context.get("context_tokens"),
        "context_remaining_pct": context.get("remaining_pct"),
        "context_confidence": context.get("confidence"),
        "context_source_fields": context.get("source_fields") or [],
        "raw_usage": usage,
    }
    if cached_tokens is not None:
        data["cached_tokens"] = cached_tokens
        data["cached_prompt_tokens"] = cached_tokens
    if reasoning_tokens is not None:
        data["reasoning_output_tokens"] = reasoning_tokens
    return data


async def record_harness_token_usage(
    db: AsyncSession,
    *,
    correlation_id: uuid.UUID,
    session_id: uuid.UUID,
    bot_id: str | None,
    runtime: str | None,
    model: str | None,
    channel_id: uuid.UUID | None,
    usage: dict[str, Any] | None,
    cost_usd: float | None,
) -> TraceEvent | None:
    if not isinstance(usage, dict) or not usage:
        return None

    session = await db.get(Session, session_id)
    effective_channel_id = channel_id
    client_id = None
    if session is not None:
        client_id = session.client_id
        effective_channel_id = effective_channel_id or session.channel_id or session.parent_channel_id

    data = _harness_usage_data(
        runtime=runtime,
        model=model,
        channel_id=effective_channel_id,
        usage=usage,
        cost_usd=cost_usd,
    )
    if data is None:
        return None

    row = TraceEvent(
        correlation_id=correlation_id,
        session_id=session_id,
        bot_id=bot_id,
        client_id=client_id,
        event_type="token_usage",
        event_name=runtime,
        data=data,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    return row
