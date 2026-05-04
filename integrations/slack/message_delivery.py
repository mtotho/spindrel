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


def _feedback_accessory() -> dict:
    return {
        "type": "overflow",
        "action_id": "turn_feedback_menu",
        "options": [
            {
                "text": {"type": "plain_text", "text": "👍 Useful", "emoji": True},
                "value": "up",
            },
            {
                "text": {"type": "plain_text", "text": "👎 Not useful", "emoji": True},
                "value": "down",
            },
        ],
    }


def _message_blocks(
    text: str,
    *,
    feedback_enabled: bool,
    extra_blocks: list[dict] | None = None,
) -> list[dict] | None:
    """Build Slack blocks with feedback attached to the message body."""
    if len(text) > 3000:
        return None
    section: dict = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
    }
    if feedback_enabled:
        section["accessory"] = _feedback_accessory()
    return [section, *(extra_blocks or [])]


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
                    blocks = _message_blocks(
                        chunks[0],
                        feedback_enabled=feedback_enabled,
                        extra_blocks=tool_blocks,
                    )
                    if blocks is not None:
                        update_body["blocks"] = blocks
                    tool_blocks = []
                elif len(chunks) == 1:
                    blocks = _message_blocks(
                        chunks[0],
                        feedback_enabled=feedback_enabled,
                    )
                    if blocks is not None:
                        update_body["blocks"] = blocks
                update_result = await self._call_slack(
                    "chat.update", target.token, update_body
                )
                if update_result.success:
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
                blocks = _message_blocks(
                    chunk,
                    feedback_enabled=feedback_enabled,
                    extra_blocks=tool_blocks,
                )
                if blocks is not None:
                    body["blocks"] = blocks
                tool_blocks = []
            elif is_last and feedback_enabled:
                blocks = _message_blocks(chunk, feedback_enabled=True)
                if blocks is not None:
                    body["blocks"] = blocks
            if target.thread_ts and target.reply_in_thread:
                body["thread_ts"] = target.thread_ts
            result = await self._call_slack("chat.postMessage", target.token, body)
            if not result.success:
                return result.to_receipt()
            ts = (result.data or {}).get("ts") if result.data else None
            if ts:
                latest_ts = ts

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
