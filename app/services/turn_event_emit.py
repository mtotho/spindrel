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
    TurnStreamTokenPayload,
    TurnStreamToolResultPayload,
    TurnStreamToolStartPayload,
)
from app.services.channel_events import publish_typed

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


async def emit_run_stream_events(
    run_stream_iter: AsyncIterator[dict],
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    turn_id: uuid.UUID,
) -> AsyncIterator[dict]:
    """Wrap a ``run_stream`` async iterator and publish typed bus events.

    Forwards every underlying event dict unchanged so the caller can still
    match on ``event.get("type")``. As a side effect, publishes the five
    mechanically translatable kinds:

    - ``text_delta`` → ``TURN_STREAM_TOKEN``
    - ``tool_start`` → ``TURN_STREAM_TOOL_START``
    - ``tool_result`` → ``TURN_STREAM_TOOL_RESULT`` (``is_error`` set when
      the underlying event has a non-empty ``error`` field)
    - ``approval_request`` → ``APPROVAL_REQUESTED``
    - ``approval_resolved`` → ``APPROVAL_RESOLVED``

    Other event types (``response``, ``assistant_text``, ``cancelled``,
    ``context_budget``, ``delegation_post``, ``thinking_content``,
    ``warning``, ``rate_limit_wait``, ``context_pruning``) are forwarded
    unchanged with no bus publish — the caller decides what to do with
    them. ``TURN_STARTED`` and ``TURN_ENDED`` are the caller's
    responsibility.
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
                    ),
                ),
            )

        elif etype == "tool_start":
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.TURN_STREAM_TOOL_START,
                    payload=TurnStreamToolStartPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        tool_name=event.get("tool", ""),
                        arguments=_coerce_tool_arguments(event.get("args")),
                    ),
                ),
            )

        elif etype == "tool_result":
            _result_text = event.get("result") or event.get("error") or ""
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.TURN_STREAM_TOOL_RESULT,
                    payload=TurnStreamToolResultPayload(
                        bot_id=bot_id,
                        turn_id=turn_id,
                        tool_name=event.get("tool", ""),
                        result_summary=str(_result_text)[:500],
                        is_error=bool(event.get("error")),
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
                    ),
                ),
            )

        elif etype == "approval_resolved":
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.APPROVAL_RESOLVED,
                    payload=ApprovalResolvedPayload(
                        approval_id=event.get("approval_id", ""),
                        decision=event.get("decision", ""),
                    ),
                ),
            )

        yield event
