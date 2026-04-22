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
    async for event in run_stream_iter:
        etype = event.get("type")

        if etype == "text_delta":
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.TURN_STREAM_TOKEN,
                    payload=TurnStreamTokenPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        delta=event.get("delta", ""),
                        session_id=session_id,
                    ),
                ),
            )

        # Reasoning deltas: `thinking` carries incremental reasoning text from
        # providers that stream it (OpenAI Responses summary stream, Anthropic
        # thinking_delta, DeepSeek <think> blocks). Without this publish the
        # deltas reach the run-stream consumer but never cross the bus, so the
        # web UI's thinking panel stays empty even when the provider is
        # emitting summaries. The trailing `thinking_content` event
        # (`app/agent/loop.py:757`) replays the same accumulated text, so we
        # deliberately skip that one on the bus to avoid double-appending.
        elif etype == "thinking":
            delta = event.get("delta", "")
            if delta:
                publish_typed(
                    channel_id,
                    ChannelEvent(
                        channel_id=channel_id,
                        kind=ChannelEventKind.TURN_STREAM_THINKING,
                        payload=TurnStreamThinkingPayload(
                            bot_id=bot_id,
                            turn_id=turn_id,
                            delta=delta,
                            session_id=session_id,
                        ),
                    ),
                )

        elif etype == "tool_start":
            _arguments = _coerce_tool_arguments(event.get("args"))
            _surface, _summary = _tool_presentation_from_event(
                tool_name=event.get("tool", ""),
                arguments=_arguments,
                surface=event.get("surface"),
                summary=event.get("summary"),
            )
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.TURN_STREAM_TOOL_START,
                    payload=TurnStreamToolStartPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        tool_name=event.get("tool", ""),
                        tool_call_id=event.get("tool_call_id"),
                        arguments=_arguments,
                        surface=_surface,
                        summary=_summary,
                        session_id=session_id,
                    ),
                ),
            )

        elif etype == "tool_result":
            _result_text = event.get("result") or event.get("error") or ""
            _arguments = _coerce_tool_arguments(event.get("args"))
            _surface, _summary = _tool_presentation_from_event(
                tool_name=event.get("tool", ""),
                arguments=_arguments,
                result=event.get("result"),
                envelope=event.get("envelope"),
                error=event.get("error"),
                surface=event.get("surface"),
                summary=event.get("summary"),
            )
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.TURN_STREAM_TOOL_RESULT,
                    payload=TurnStreamToolResultPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        tool_name=event.get("tool", ""),
                        tool_call_id=event.get("tool_call_id"),
                        result_summary=str(_result_text)[:500],
                        is_error=bool(event.get("error")),
                        envelope=event.get("envelope"),
                        surface=_surface,
                        summary=_summary,
                        session_id=session_id,
                    ),
                ),
            )

        elif etype == "approval_request":
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.APPROVAL_REQUESTED,
                    payload=ApprovalRequestedPayload(
                        approval_id=event.get("approval_id", ""),
                        bot_id=bot_id,
                        tool_name=event.get("tool", ""),
                        arguments=_coerce_tool_arguments(event.get("args")),
                        reason=event.get("reason"),
                        turn_id=turn_id,
                        session_id=session_id,
                    ),
                ),
            )

        elif etype == "approval_resolved":
            # `app/agent/loop.py:1049,1190` yields the legacy event with the
            # old field name ``verdict``; the typed payload uses ``decision``.
            # Translate on the way into the bus so downstream consumers see a
            # consistent ``decision`` string.
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.APPROVAL_RESOLVED,
                    payload=ApprovalResolvedPayload(
                        approval_id=event.get("approval_id", ""),
                        decision=event.get("verdict") or event.get("decision") or "",
                        session_id=session_id,
                    ),
                ),
            )

        elif etype == "context_budget":
            # Untyped metadata event yielded by `app/agent/loop.py` after
            # context assembly (~line 1522). Publishes a typed snapshot so
            # the UI can render budget bars and E2E tests can assert on the
            # stream. Pre-session-16 this was streamed via the legacy SSE
            # long-poll; after Phase E removed that path, the event never
            # reached subscribers without an explicit typed bridge.
            try:
                util = float(event.get("utilization") or 0)
            except (TypeError, ValueError):
                util = 0.0
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.CONTEXT_BUDGET,
                    payload=ContextBudgetPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        consumed_tokens=int(event.get("consumed_tokens") or 0),
                        total_tokens=int(event.get("total_tokens") or 0),
                        utilization=util,
                        model=str(event.get("model") or ""),
                        available_budget=int(event.get("available_budget") or 0),
                        live_history_tokens=int(event.get("live_history_tokens") or 0),
                        live_history_utilization=float(event.get("live_history_utilization") or 0),
                        base_tokens=int(event.get("base_tokens") or 0),
                        static_injection_tokens=int(event.get("static_injection_tokens") or 0),
                        tool_schema_tokens=int(event.get("tool_schema_tokens") or 0),
                    ),
                ),
            )

        elif etype == "memory_scheme_bootstrap":
            # Same story as context_budget — bridged onto the typed bus so
            # the stream surfaces "memory bootstrap fired" for the UI +
            # tests after Phase E killed the SSE long-poll forwarder.
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.MEMORY_SCHEME_BOOTSTRAP,
                    payload=MemorySchemeBootstrapPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        scheme=str(event.get("scheme") or event.get("memory_scheme") or ""),
                        files_loaded=int(event.get("files_loaded") or 0),
                    ),
                ),
            )

        elif etype == "llm_retry":
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.LLM_STATUS,
                    payload=LlmStatusPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        status="retry",
                        model=str(event.get("model", "")),
                        reason=str(event.get("reason", "")),
                        attempt=int(event.get("attempt", 0)),
                        max_retries=int(event.get("max_retries", 0)),
                        wait_seconds=float(event.get("wait_seconds", 0)),
                    ),
                ),
            )

        elif etype == "llm_fallback":
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.LLM_STATUS,
                    payload=LlmStatusPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        status="fallback",
                        model=str(event.get("from_model", "")),
                        reason=str(event.get("reason", "")),
                        fallback_model=str(event.get("to_model", "")),
                    ),
                ),
            )

        elif etype == "llm_cooldown_skip":
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.LLM_STATUS,
                    payload=LlmStatusPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        status="cooldown_skip",
                        model=str(event.get("model", "")),
                        fallback_model=str(event.get("using", "")),
                    ),
                ),
            )

        elif etype == "llm_error":
            # Terminal failure from the fallback chain — all models tried,
            # none succeeded. Publishing gets the error into the UI's live
            # LLM-status chip alongside the trace record emitted by
            # ``app/agent/loop.py``.
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.LLM_STATUS,
                    payload=LlmStatusPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        status="error",
                        model=str(event.get("model", "")),
                        reason=str(event.get("reason", "")),
                        error=str(event.get("error", "")),
                    ),
                ),
            )

        elif etype == "auto_inject":
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.SKILL_AUTO_INJECT,
                    payload=SkillAutoInjectPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        skill_id=str(event.get("skill_id", "")),
                        skill_name=str(event.get("skill_name", "")),
                        similarity=float(event.get("similarity") or 0.0),
                        source=str(event.get("source", "")),
                    ),
                ),
            )

        yield event
