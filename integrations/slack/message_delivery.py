"""Slack durable ``NEW_MESSAGE`` delivery.

Streaming events own the live placeholder lifecycle. This module owns the
outbox-durable handoff that either reuses that placeholder or posts the final
Slack message directly.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from integrations.sdk import (
    ChannelEvent,
    DeliveryReceipt,
    ToolOutputDisplay,
    ToolResultRenderingSupport,
    get_channel_for_integration,
)
from integrations.slack.formatting import markdown_to_slack_mrkdwn, split_for_slack
from integrations.slack.render_context import slack_render_contexts
from integrations.slack.target import SlackTarget
from integrations.slack.tool_result_adapter import build_tool_result_blocks

logger = logging.getLogger(__name__)

SlackCall = Callable[[str, str, dict], Awaitable[Any]]
BotAttribution = Callable[[str], dict]


async def _seed_feedback_reactions(
    call_slack: SlackCall,
    *,
    token: str,
    channel: str,
    ts: str | None,
    enabled: bool,
) -> None:
    if not enabled or not ts:
        return
    for name in ("thumbsup", "thumbsdown"):
        try:
            result = await call_slack(
                "reactions.add",
                token,
                {"channel": channel, "timestamp": ts, "name": name},
            )
            if not getattr(result, "success", False):
                error = getattr(result, "error", None) or (
                    getattr(result, "data", None) or {}
                ).get("error")
                if error not in {"already_reacted"}:
                    logger.warning(
                        "failed to seed feedback reaction %s on %s/%s: %s",
                        name, channel, ts, error,
                    )
        except Exception:
            logger.debug(
                "failed to seed feedback reaction %s on %s/%s",
                name, channel, ts,
                exc_info=True,
            )


class SlackMessageDelivery:
    """Deliver durable Slack ``NEW_MESSAGE`` events."""

    def __init__(
        self,
        *,
        call_slack: SlackCall,
        bot_attribution: BotAttribution,
        tool_result_rendering: ToolResultRenderingSupport | None,
    ) -> None:
        self._call_slack = call_slack
        self._bot_attribution = bot_attribution
        self._tool_result_rendering = tool_result_rendering

    async def render(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        msg = getattr(payload, "message", None)
        if msg is None:
            return DeliveryReceipt.skipped("new_message without message payload")

        # Task-run envelopes are UI-only. Dispatch only the separate
        # task-run summary message, which flows through this same path.
        msg_meta_early = getattr(msg, "metadata", None) or {}
        if msg_meta_early.get("kind") == "task_run" or msg_meta_early.get("ui_only"):
            return DeliveryReceipt.skipped("slack skips UI-only task_run envelope")

        role = getattr(msg, "role", "") or ""
        if role in ("tool", "system"):
            return DeliveryReceipt.skipped(f"slack skips internal role={role}")

        if role == "user":
            msg_metadata = getattr(msg, "metadata", None) or {}
            if msg_metadata.get("source") == "slack":
                return DeliveryReceipt.skipped(
                    "slack skips own-origin user message (echo prevention)"
                )
            actor = getattr(msg, "actor", None)
            actor_id = getattr(actor, "id", "") or "" if actor is not None else ""
            if actor_id.startswith("slack:"):
                return DeliveryReceipt.skipped(
                    "slack skips own-origin user message (echo prevention)"
                )

        actor = getattr(msg, "actor", None)
        attrs: dict = {}
        if actor is not None and getattr(actor, "kind", "") == "bot":
            attrs = self._bot_attribution(getattr(actor, "id", ""))
        elif actor is not None:
            display_name = getattr(actor, "display_name", None)
            if display_name:
                attrs["username"] = display_name

        text = getattr(msg, "content", "") or ""
        if not text.strip():
            return DeliveryReceipt.skipped("new_message with empty content")
        slack_text = markdown_to_slack_mrkdwn(text)
        chunks = split_for_slack(slack_text) or [slack_text]

        msg_metadata = getattr(msg, "metadata", None) or {}
        prebuilt_blocks = msg_metadata.get("slack_blocks") or []
        if isinstance(prebuilt_blocks, list) and prebuilt_blocks:
            body: dict = {
                "channel": target.channel_id,
                "text": text,
                "blocks": prebuilt_blocks[:50],
                **attrs,
            }
            if target.thread_ts and target.reply_in_thread:
                body["thread_ts"] = target.thread_ts
            return (await self._call_slack(
                "chat.postMessage", target.token, body
            )).to_receipt()

        tool_results = msg_metadata.get("tool_results") or []
        tool_blocks: list[dict] = []
        if tool_results and role != "user":
            display_mode = await resolve_tool_output_display(target.channel_id)
            tool_blocks = build_tool_result_blocks(
                tool_results,
                display_mode=display_mode,
                support=self._tool_result_rendering,
            )
        tool_blocks = tool_blocks[:50]

        correlation_id = str(getattr(msg, "correlation_id", "") or "")
        feedback_enabled = role == "assistant"
        ctx_info = (
            slack_render_contexts.find_by_turn_id(correlation_id)
            if correlation_id else None
        )
        if ctx_info is not None and role != "user":
            ctx_channel_id, ctx = ctx_info
            if ctx.thinking_ts and ctx.thinking_channel:
                update_body: dict = {
                    "channel": ctx.thinking_channel,
                    "ts": ctx.thinking_ts,
                    "text": chunks[0],
                    **attrs,
                }
                if len(chunks) == 1 and tool_blocks:
                    update_body["blocks"] = [
                        {"type": "section", "text": {"type": "mrkdwn", "text": chunks[0]}},
                        *tool_blocks,
                    ]
                    tool_blocks = []
                elif len(chunks) == 1:
                    update_body["blocks"] = [
                        {"type": "section", "text": {"type": "mrkdwn", "text": chunks[0]}}
                    ]
                update_result = await self._call_slack(
                    "chat.update", target.token, update_body
                )
                if update_result.success:
                    updated_ts = (update_result.data or {}).get("ts") if update_result.data else None
                    await _seed_feedback_reactions(
                        self._call_slack,
                        token=target.token,
                        channel=ctx.thinking_channel,
                        ts=updated_ts or ctx.thinking_ts,
                        enabled=feedback_enabled,
                    )
                    chunks = chunks[1:]
            slack_render_contexts.discard(ctx_channel_id, correlation_id)

        latest_ts: str | None = None
        if ctx_info is not None and not chunks:
            latest_ts = ctx_info[1].thinking_ts
        for idx, chunk in enumerate(chunks):
            is_last = idx == len(chunks) - 1
            body: dict = {
                "channel": target.channel_id,
                "text": chunk,
                **attrs,
            }
            if is_last and tool_blocks:
                body["blocks"] = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": chunk}},
                    *tool_blocks,
                ]
                tool_blocks = []
            if target.thread_ts and target.reply_in_thread:
                body["thread_ts"] = target.thread_ts
            result = await self._call_slack("chat.postMessage", target.token, body)
            if not result.success:
                return result.to_receipt()
            ts = (result.data or {}).get("ts") if result.data else None
            if ts:
                latest_ts = ts
                if is_last:
                    await _seed_feedback_reactions(
                        self._call_slack,
                        token=target.token,
                        channel=target.channel_id,
                        ts=ts,
                        enabled=feedback_enabled,
                    )

        return DeliveryReceipt.ok(external_id=latest_ts)


async def resolve_tool_output_display(slack_channel_id: str) -> str:
    """Look up the channel's ``tool_output_display`` setting."""
    client_id = f"slack:{slack_channel_id}"
    try:
        channel = await get_channel_for_integration("slack", client_id)
        if channel is not None:
            return ToolOutputDisplay.normalize(channel.tool_output_display)
    except Exception:
        logger.debug("tool_output_display lookup failed, using default", exc_info=True)
    return ToolOutputDisplay.COMPACT


__all__ = ["SlackMessageDelivery", "resolve_tool_output_display"]
