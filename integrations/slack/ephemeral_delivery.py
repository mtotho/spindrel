"""Slack ephemeral-message delivery."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from integrations.sdk import ChannelEvent, DeliveryReceipt
from integrations.slack.target import SlackTarget

SlackCall = Callable[[str, str, dict], Awaitable[Any]]
BotAttribution = Callable[[str], dict]


class SlackEphemeralDelivery:
    """Deliver ``EPHEMERAL_MESSAGE`` events via ``chat.postEphemeral``."""

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
        message = getattr(payload, "message", None)
        recipient_user_id = getattr(payload, "recipient_user_id", "") or ""
        if message is None or not recipient_user_id:
            return DeliveryReceipt.skipped(
                "ephemeral_message missing message or recipient_user_id"
            )
        text = (getattr(message, "content", "") or "").strip()
        if not text:
            return DeliveryReceipt.skipped("ephemeral_message empty text")

        bot_id = ""
        actor = getattr(message, "actor", None)
        if actor is not None and getattr(actor, "kind", "") == "bot":
            bot_id = getattr(actor, "id", "") or ""
        attrs = self._bot_attribution(bot_id) if bot_id else {}

        body: dict = {
            "channel": target.channel_id,
            "user": recipient_user_id,
            "text": text,
            **attrs,
        }
        if target.thread_ts and target.reply_in_thread:
            body["thread_ts"] = target.thread_ts
        return (await self._call_slack(
            "chat.postEphemeral", target.token, body
        )).to_receipt()


__all__ = ["SlackEphemeralDelivery"]
