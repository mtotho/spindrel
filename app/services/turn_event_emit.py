"""Run-stream → typed bus event translator.

The agent loop's ``run_stream`` async generator yields untyped event dicts
(``{"type": "text_delta", "delta": ..., ...}``). The bus speaks typed
``ChannelEvent``s. Several call sites — ``turn_worker.run_turn`` (the
primary chat path) and ``_run_member_bot_reply`` (the member-bot path) —
need the same translation: text_delta → TURN_STREAM_TOKEN, tool_start →
TURN_STREAM_TOOL_START, etc.

This module is the single home for that translation. ``emit_run_stream_events``
is an async-iterator wrapper: it forwards every underlying event dict
unchanged so callers can still inspect the special cases (``response``,
``assistant_text``, ``cancelled``, ``context_budget``, ``delegation_post``)
that need caller-specific state, but as a side effect it publishes the
five mechanical kinds onto the typed channel-events bus.

The caller is expected to publish ``TURN_STARTED`` before iterating and
``TURN_ENDED`` (success or error) after, since those carry caller-side
state (``response_text``, ``error_text``, ``client_actions``) that this
helper has no view into.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import (
    ApprovalRequestedPayload,
    ApprovalResolvedPayload,
    ContextBudgetPayload,
    LlmStatusPayload,
    MemorySchemeBootstrapPayload,
    SkillAutoInjectPayload,
    TurnStreamThinkingPayload,
    TurnStreamTokenPayload,
    TurnStreamToolResultPayload,
    TurnStreamToolStartPayload,
)
from app.services.channel_events import publish_typed
from app.services.tool_presentation import derive_tool_presentation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EmitContext:
    channel_id: uuid.UUID
    bot_id: str
    turn_id: uuid.UUID
    session_id: uuid.UUID | None


def _coerce_tool_arguments(raw: Any) -> dict:
    """Normalize tool-call ``args`` into a plain dict for the typed payload.

    The agent loop yields OpenAI-format tool calls, where
    ``tc["function"]["arguments"]`` is a **JSON string**, not a dict
    (`app/agent/loop.py:919, 1107`). Older callers and some providers
    pass an already-parsed dict instead. ``TurnStreamToolStartPayload``
    requires a dict, so this helper handles both.

    Returns ``{}`` for any value that can't be parsed into a dict.
    """
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {"_raw": raw}
        if isinstance(parsed, dict):
            return parsed
        return {"_raw": parsed}
    # Last-ditch: stringify and stash so the bus payload still validates.
    return {"_raw": str(raw)}


def _tool_presentation_from_event(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any = None,
    envelope: Any = None,
    error: Any = None,
    surface: Any = None,
    summary: Any = None,
) -> tuple[str | None, dict | None]:
    if isinstance(surface, str) and isinstance(summary, dict):
        return surface, summary
    derived_surface, derived_summary = derive_tool_presentation(
        tool_name=tool_name,
        arguments=arguments,
        result=str(result) if isinstance(result, str) else None,
        envelope=envelope if isinstance(envelope, dict) else None,
        error=str(error) if isinstance(error, str) else None,
    )
    return derived_surface, derived_summary


def _build_text_delta_event(event: dict, ctx: _EmitContext) -> ChannelEvent:
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.TURN_STREAM_TOKEN,
        payload=TurnStreamTokenPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            delta=event.get("delta", ""),
            session_id=ctx.session_id,
        ),
    )


def _build_thinking_event(event: dict, ctx: _EmitContext) -> ChannelEvent | None:
    delta = event.get("delta", "")
    if not delta:
        return None
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.TURN_STREAM_THINKING,
        payload=TurnStreamThinkingPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            delta=delta,
            session_id=ctx.session_id,
        ),
    )


def _build_tool_start_event(event: dict, ctx: _EmitContext) -> ChannelEvent:
    arguments = _coerce_tool_arguments(event.get("args"))
    surface, summary = _tool_presentation_from_event(
        tool_name=event.get("tool", ""),
        arguments=arguments,
        surface=event.get("surface"),
        summary=event.get("summary"),
    )
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.TURN_STREAM_TOOL_START,
        payload=TurnStreamToolStartPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            tool_name=event.get("tool", ""),
            tool_call_id=event.get("tool_call_id"),
            arguments=arguments,
            surface=surface,
            summary=summary,
            session_id=ctx.session_id,
        ),
    )


def _build_tool_result_event(event: dict, ctx: _EmitContext) -> ChannelEvent:
    result_text = event.get("result") or event.get("error") or ""
    arguments = _coerce_tool_arguments(event.get("args"))
    surface, summary = _tool_presentation_from_event(
        tool_name=event.get("tool", ""),
        arguments=arguments,
        result=event.get("result"),
        envelope=event.get("envelope"),
        error=event.get("error"),
        surface=event.get("surface"),
        summary=event.get("summary"),
    )
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.TURN_STREAM_TOOL_RESULT,
        payload=TurnStreamToolResultPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            tool_name=event.get("tool", ""),
            tool_call_id=event.get("tool_call_id"),
            result_summary=str(result_text)[:500],
            is_error=bool(event.get("error")),
            envelope=event.get("envelope"),
            surface=surface,
            summary=summary,
            session_id=ctx.session_id,
        ),
    )


def _build_approval_requested_event(event: dict, ctx: _EmitContext) -> ChannelEvent:
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.APPROVAL_REQUESTED,
        payload=ApprovalRequestedPayload(
            approval_id=event.get("approval_id", ""),
            bot_id=ctx.bot_id,
            tool_name=event.get("tool", ""),
            arguments=_coerce_tool_arguments(event.get("args")),
            reason=event.get("reason"),
            turn_id=ctx.turn_id,
            session_id=ctx.session_id,
            tool_type=event.get("tool_type"),
        ),
    )


def _build_approval_resolved_event(event: dict, ctx: _EmitContext) -> ChannelEvent:
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.APPROVAL_RESOLVED,
        payload=ApprovalResolvedPayload(
            approval_id=event.get("approval_id", ""),
            decision=event.get("verdict") or event.get("decision") or "",
            session_id=ctx.session_id,
        ),
    )


def _build_context_budget_event(event: dict, ctx: _EmitContext) -> ChannelEvent:
    try:
        utilization = float(event.get("utilization") or 0)
    except (TypeError, ValueError):
        utilization = 0.0
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.CONTEXT_BUDGET,
        payload=ContextBudgetPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            consumed_tokens=int(event.get("consumed_tokens") or 0),
            total_tokens=int(event.get("total_tokens") or 0),
            utilization=utilization,
            session_id=ctx.session_id,
            model=str(event.get("model") or ""),
            context_profile=event.get("context_profile"),
            context_origin=event.get("context_origin"),
            live_history_turns=event.get("live_history_turns"),
            available_budget=int(event.get("available_budget") or 0),
            live_history_tokens=int(event.get("live_history_tokens") or 0),
            live_history_utilization=float(event.get("live_history_utilization") or 0),
            base_tokens=int(event.get("base_tokens") or 0),
            static_injection_tokens=int(event.get("static_injection_tokens") or 0),
            tool_schema_tokens=int(event.get("tool_schema_tokens") or 0),
            mandatory_static_injections=event.get("mandatory_static_injections") or [],
            optional_static_injections=event.get("optional_static_injections") or [],
        ),
    )


def _build_memory_scheme_bootstrap_event(event: dict, ctx: _EmitContext) -> ChannelEvent:
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.MEMORY_SCHEME_BOOTSTRAP,
        payload=MemorySchemeBootstrapPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            scheme=str(event.get("scheme") or event.get("memory_scheme") or ""),
            files_loaded=int(event.get("files_loaded") or 0),
        ),
    )


def _build_llm_status_event(event: dict, ctx: _EmitContext) -> ChannelEvent | None:
    etype = event.get("type")
    if etype == "llm_retry":
        payload = LlmStatusPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            status="retry",
            model=str(event.get("model", "")),
            reason=str(event.get("reason", "")),
            attempt=int(event.get("attempt", 0)),
            max_retries=int(event.get("max_retries", 0)),
            wait_seconds=float(event.get("wait_seconds", 0)),
        )
    elif etype == "llm_fallback":
        payload = LlmStatusPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            status="fallback",
            model=str(event.get("from_model", "")),
            reason=str(event.get("reason", "")),
            fallback_model=str(event.get("to_model", "")),
        )
    elif etype == "llm_cooldown_skip":
        payload = LlmStatusPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            status="cooldown_skip",
            model=str(event.get("model", "")),
            fallback_model=str(event.get("using", "")),
        )
    elif etype == "llm_error":
        payload = LlmStatusPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            status="error",
            model=str(event.get("model", "")),
            reason=str(event.get("reason", "")),
            error=str(event.get("error", "")),
        )
    else:
        return None
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.LLM_STATUS,
        payload=payload,
    )


def _build_skill_auto_inject_event(event: dict, ctx: _EmitContext) -> ChannelEvent:
    return ChannelEvent(
        channel_id=ctx.channel_id,
        kind=ChannelEventKind.SKILL_AUTO_INJECT,
        payload=SkillAutoInjectPayload(
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            skill_id=str(event.get("skill_id", "")),
            skill_name=str(event.get("skill_name", "")),
            similarity=float(event.get("similarity") or 0.0),
            source=str(event.get("source", "")),
        ),
    )


def _typed_event_from_run_stream_event(event: dict, ctx: _EmitContext) -> ChannelEvent | None:
    etype = event.get("type")
    if etype == "text_delta":
        return _build_text_delta_event(event, ctx)
    if etype == "thinking":
        return _build_thinking_event(event, ctx)
    if etype == "tool_start":
        return _build_tool_start_event(event, ctx)
    if etype == "tool_result":
        return _build_tool_result_event(event, ctx)
    if etype == "approval_request":
        return _build_approval_requested_event(event, ctx)
    if etype == "approval_resolved":
        return _build_approval_resolved_event(event, ctx)
    if etype == "context_budget":
        return _build_context_budget_event(event, ctx)
    if etype == "memory_scheme_bootstrap":
        return _build_memory_scheme_bootstrap_event(event, ctx)
    if etype in {"llm_retry", "llm_fallback", "llm_cooldown_skip", "llm_error"}:
        return _build_llm_status_event(event, ctx)
    if etype == "auto_inject":
        return _build_skill_auto_inject_event(event, ctx)
    return None


async def emit_run_stream_events(
    run_stream_iter: AsyncIterator[dict],
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    turn_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
) -> AsyncIterator[dict]:
    """Wrap a ``run_stream`` async iterator and publish typed bus events.

    Forwards every underlying event dict unchanged so the caller can still
    match on ``event.get("type")``. As a side effect, publishes the
    mechanically translatable kinds:

    - ``text_delta`` → ``TURN_STREAM_TOKEN``
    - ``thinking`` → ``TURN_STREAM_THINKING`` (reasoning deltas)
    - ``tool_start`` → ``TURN_STREAM_TOOL_START``
    - ``tool_result`` → ``TURN_STREAM_TOOL_RESULT`` (``is_error`` set when
      the underlying event has a non-empty ``error`` field)
    - ``approval_request`` → ``APPROVAL_REQUESTED``
    - ``approval_resolved`` → ``APPROVAL_RESOLVED``

    Other event types (``response``, ``assistant_text``, ``cancelled``,
    ``context_budget``, ``delegation_post``, ``thinking_content``,
    ``warning``, ``rate_limit_wait``, ``context_pruning``) are forwarded
    unchanged with no bus publish — the caller decides what to do with
    them. ``thinking_content`` is intentionally *not* republished because
    its text is the accumulation of the ``thinking`` deltas this helper
    already emitted, so rebroadcasting would double-append in the UI.
    ``TURN_STARTED`` and ``TURN_ENDED`` are the caller's responsibility.
    """
    ctx = _EmitContext(
        channel_id=channel_id,
        bot_id=bot_id,
        turn_id=turn_id,
        session_id=session_id,
    )
    async for event in run_stream_iter:
        typed_event = _typed_event_from_run_stream_event(event, ctx)
        if typed_event is not None:
            publish_typed(channel_id, typed_event)
        yield event
