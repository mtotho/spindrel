"""Slack approval-request delivery."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from integrations.sdk import ChannelEvent, DeliveryReceipt
from integrations.slack.approval_blocks import (
    build_capability_approval_blocks,
    build_tool_approval_blocks,
)
from integrations.slack.target import SlackTarget

SlackCall = Callable[[str, str, dict], Awaitable[Any]]
BotAttribution = Callable[[str], dict]


class SlackApprovalDelivery:
    """Deliver ``APPROVAL_REQUESTED`` events to Slack."""

    def __init__(
        self,
        *,
        call_slack: SlackCall,
        bot_attribution: BotAttribution,
    ) -> None:
        self._call_slack = call_slack
        self._bot_attribution = bot_attribution

    async def render(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        approval_id = getattr(payload, "approval_id", "") or ""
        bot_id = getattr(payload, "bot_id", "") or ""
        tool_name = getattr(payload, "tool_name", "") or ""
        arguments = getattr(payload, "arguments", {}) or {}
        reason = getattr(payload, "reason", None)
        capability = getattr(payload, "capability", None)

        attrs = self._bot_attribution(bot_id) if bot_id else {}
        if capability:
            blocks = build_capability_approval_blocks(
                approval_id, bot_id, capability,
            )
            fallback = (
                f"Capability activation: {capability.get('name', 'unknown')} "
                f"(approval {approval_id})"
            )
        else:
            blocks = build_tool_approval_blocks(
                approval_id, bot_id, tool_name, arguments, reason,
            )
            fallback = (
                f"Tool approval required: {tool_name} (approval {approval_id})"
            )

        body: dict = {
            "channel": target.channel_id,
            "text": fallback,
            "blocks": blocks,
            **attrs,
        }
        if target.thread_ts and target.reply_in_thread:
            body["thread_ts"] = target.thread_ts

        return (await self._call_slack(
            "chat.postMessage", target.token, body
        )).to_receipt()


__all__ = ["SlackApprovalDelivery"]
