"""Streaming-turn delivery for SlackRenderer.

This module owns the Slack placeholder lifecycle and coalesced
``chat.update`` behavior that keeps streaming turns stable across Slack
clients. Durable message delivery remains in ``renderer.py``.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass

from integrations.sdk import (
    ChannelEvent,
    ChannelEventKind,
    DeliveryReceipt,
    count_pending_outbox,
)
from integrations.slack.formatting import markdown_to_slack_mrkdwn, split_for_slack
from integrations.slack.render_context import (
    STREAM_FLUSH_INTERVAL,
    STREAM_MAX_CHARS,
    TurnContext,
    slack_render_contexts,
)
from integrations.slack.target import SlackTarget
from integrations.slack.transport import SlackCallResult

logger = logging.getLogger(__name__)

BotAttribution = Callable[[str], dict]
SlackCall = Callable[[str, str, dict], Awaitable[SlackCallResult]]

STREAMING_KINDS = frozenset({
    ChannelEventKind.TURN_STARTED,
    ChannelEventKind.TURN_STREAM_TOKEN,
    ChannelEventKind.TURN_STREAM_TOOL_START,
    ChannelEventKind.TURN_STREAM_TOOL_RESULT,
    ChannelEventKind.TURN_ENDED,
})


class SlackStreamingDelivery:
    """Render Slack streaming events into one editable placeholder."""

    def __init__(
        self,
        *,
        call_slack: SlackCall,
        bot_attribution: BotAttribution,
    ) -> None:
        self._call_slack = call_slack
        self._bot_attribution = bot_attribution

    async def render(
        self,
        event: ChannelEvent,
        target: SlackTarget,
    ) -> DeliveryReceipt:
        kind = event.kind
        if kind == ChannelEventKind.TURN_STARTED:
            return await self._handle_turn_started(event, target)
        if kind == ChannelEventKind.TURN_STREAM_TOKEN:
            return await self._handle_stream_token(event, target)
        if kind == ChannelEventKind.TURN_STREAM_TOOL_START:
            return await self._handle_tool_start(event, target)
        if kind == ChannelEventKind.TURN_STREAM_TOOL_RESULT:
            return await self._handle_tool_result(event, target)
        if kind == ChannelEventKind.TURN_ENDED:
            return await self._handle_turn_ended(event, target)
        return DeliveryReceipt.skipped(f"slack streaming does not handle {kind.value}")

    async def _handle_turn_started(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        bot_id = getattr(payload, "bot_id", "") or ""
        turn_id = str(getattr(payload, "turn_id", "") or "")
        if not turn_id:
            return DeliveryReceipt.failed("turn_started without turn_id", retryable=False)

        ctx = slack_render_contexts.get_or_create(
            target.channel_id, turn_id, bot_id=bot_id
        )
        if ctx.thinking_ts is not None:
            return DeliveryReceipt.ok(external_id=ctx.thinking_ts)

        reason = getattr(payload, "reason", "")
        if reason == "user_message":
            await wait_for_pending_outbox(event.channel_id, timeout=1.5)

        attrs = self._bot_attribution(bot_id) if bot_id else {}
        body: dict = {
            "channel": target.channel_id,
            "text": "\u23f3 _thinking..._",
            **attrs,
        }
        if target.thread_ts and target.reply_in_thread:
            body["thread_ts"] = target.thread_ts

        result = await self._call_slack("chat.postMessage", target.token, body)
        if not result.success:
            return result.to_receipt()
        data = result.data or {}
        ctx.thinking_ts = data.get("ts")
        ctx.thinking_channel = data.get("channel")
        ctx.last_flush_at = time.monotonic()
        return DeliveryReceipt.ok(external_id=ctx.thinking_ts)

    async def _handle_stream_token(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        delta = getattr(payload, "delta", "") or ""
        ctx = slack_render_contexts.get(target.channel_id, turn_id)
        if ctx is None:
            ctx = slack_render_contexts.get_or_create(
                target.channel_id,
                turn_id,
                bot_id=getattr(payload, "bot_id", "") or "",
            )

        ctx.accumulated_text += delta
        return await self._maybe_flush(ctx, target)

    async def _handle_tool_start(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        await self._force_flush(event, target)
        return DeliveryReceipt.ok()

    async def _handle_tool_result(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        await self._force_flush(event, target)
        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        envelope = getattr(payload, "envelope", None)
        if envelope and turn_id:
            ctx = slack_render_contexts.get(target.channel_id, turn_id)
            if ctx is None:
                ctx = slack_render_contexts.get_or_create(
                    target.channel_id,
                    turn_id,
                    bot_id=getattr(payload, "bot_id", "") or "",
                )
            ctx.tool_envelopes.append(envelope)
        return DeliveryReceipt.skipped("tool_result subsumed by next stream flush")

    async def _handle_turn_ended(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        turn_id = str(getattr(event.payload, "turn_id", "") or "")
        ctx = slack_render_contexts.get(target.channel_id, turn_id)

        if ctx is not None:
            async with ctx.flush_lock:
                return await self._handle_turn_ended_locked(event, target, ctx)
        return await self._handle_turn_ended_locked(event, target, None)

    async def _handle_turn_ended_locked(
        self,
        event: ChannelEvent,
        target: SlackTarget,
        ctx: TurnContext | None,
    ) -> DeliveryReceipt:
        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        bot_id = getattr(payload, "bot_id", "") or ""

        if ctx is None or not ctx.thinking_ts or not ctx.thinking_channel:
            return DeliveryReceipt.ok()

        result_text = getattr(payload, "result", None) or ""
        error_text = getattr(payload, "error", None) or ""

        if result_text:
            body_text = result_text
        elif error_text:
            body_text = f":warning: _Agent error: {error_text}_"
        else:
            body_text = "_(no response)_"

        slack_text = markdown_to_slack_mrkdwn(body_text)
        chunks = split_for_slack(slack_text) or [slack_text]
        attrs = self._bot_attribution(bot_id) if bot_id else {}

        update_body: dict = {
            "channel": ctx.thinking_channel,
            "ts": ctx.thinking_ts,
            "text": chunks[0],
            **attrs,
        }
        update_result = await self._call_slack(
            "chat.update", target.token, update_body
        )
        if not update_result.success:
            slack_render_contexts.discard(target.channel_id, turn_id)
            return update_result.to_receipt()

        client_actions = getattr(payload, "client_actions", None) or []
        if client_actions:
            await self._upload_actions(target, attrs, client_actions)

        return DeliveryReceipt.ok(external_id=ctx.thinking_ts)

    async def _maybe_flush(
        self, ctx: TurnContext, target: SlackTarget
    ) -> DeliveryReceipt:
        now = time.monotonic()
        if now - ctx.last_flush_at < STREAM_FLUSH_INTERVAL:
            ctx.pending_text = ctx.accumulated_text
            return DeliveryReceipt.ok()

        if ctx.flush_lock.locked():
            ctx.pending_text = ctx.accumulated_text
            return DeliveryReceipt.ok()

        return await self._do_flush(ctx, target)

    async def _force_flush(
        self, event: ChannelEvent, target: SlackTarget
    ) -> None:
        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        ctx = slack_render_contexts.get(target.channel_id, turn_id)
        if ctx is None or not ctx.accumulated_text:
            return
        await self._do_flush(ctx, target)

    async def _do_flush(
        self, ctx: TurnContext, target: SlackTarget
    ) -> DeliveryReceipt:
        async with ctx.flush_lock:
            if ctx.thinking_ts is None or ctx.thinking_channel is None:
                return DeliveryReceipt.ok()

            text = truncate_for_stream(ctx.accumulated_text)
            attrs = self._bot_attribution(ctx.bot_id) if ctx.bot_id else {}
            body: dict = {
                "channel": ctx.thinking_channel,
                "ts": ctx.thinking_ts,
                "text": text,
                **attrs,
            }
            result = await self._call_slack("chat.update", target.token, body)
            ctx.last_flush_at = time.monotonic()

            if (
                ctx.pending_text is not None
                and ctx.pending_text != ctx.accumulated_text
            ):
                queued = ctx.pending_text
                ctx.pending_text = None
                queued_text = truncate_for_stream(queued)
                queued_body = {**body, "text": queued_text}
                await self._call_slack("chat.update", target.token, queued_body)
                ctx.last_flush_at = time.monotonic()
            else:
                ctx.pending_text = None

            return result.to_receipt()

    async def _upload_actions(
        self,
        target: SlackTarget,
        attrs: dict,
        actions: list,
    ) -> None:
        try:
            from integrations.slack.uploads import upload_image
        except Exception:
            logger.exception("SlackStreamingDelivery: failed to import upload helper")
            return

        for action in actions:
            action_dict = action if isinstance(action, dict) else action_to_dict(action)
            if action_dict.get("type") not in ("upload_image", "upload_file"):
                continue
            try:
                await upload_image(
                    token=target.token,
                    channel_id=target.channel_id,
                    thread_ts=target.thread_ts,
                    reply_in_thread=target.reply_in_thread,
                    action=action_dict,
                    username=attrs.get("username"),
                    icon_emoji=attrs.get("icon_emoji"),
                )
            except Exception:
                logger.exception("SlackStreamingDelivery: upload_image failed for action")


def truncate_for_stream(text: str) -> str:
    """Mirror the legacy ``SlackStreamBuffer._build_display`` truncation."""
    text = (text or "").lstrip()
    if not text:
        return ""
    if len(text) > STREAM_MAX_CHARS - 4:
        return text[:STREAM_MAX_CHARS - 4] + " ..."
    return text + " ..."


def action_to_dict(action) -> dict:
    """Best-effort conversion of an OutboundAction dataclass into a dict."""
    if isinstance(action, dict):
        return action
    try:
        if is_dataclass(action) and not isinstance(action, type):
            return asdict(action)
    except Exception:
        pass
    return {}


async def wait_for_pending_outbox(
    channel_id: uuid.UUID,
    *,
    timeout: float = 1.5,
    poll_interval: float = 0.05,
) -> None:
    """Block until no undelivered Slack outbox rows remain for this channel."""
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            pending = await asyncio.wait_for(
                count_pending_outbox(channel_id, "slack"),
                timeout=max(0.001, min(poll_interval, remaining)),
            )
            if not pending:
                return
            await asyncio.sleep(poll_interval)
    except asyncio.TimeoutError:
        logger.debug("wait_for_pending_outbox poll timed out; continuing")
    except Exception:
        logger.debug("wait_for_pending_outbox poll failed; continuing", exc_info=True)
