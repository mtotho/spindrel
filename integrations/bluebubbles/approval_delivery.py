"""BlueBubbles text-only approval delivery."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from integrations.sdk import ChannelEvent, DeliveryReceipt
from integrations.bluebubbles.target import BlueBubblesTarget

SendText = Callable[..., Awaitable[DeliveryReceipt]]


class BlueBubblesApprovalDelivery:
    """Render approval prompts as plain text for iMessage."""

    def __init__(self, *, send_text: SendText) -> None:
        self._send_text = send_text

    async def render(
        self,
        event: ChannelEvent,
        target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        payload = event.payload
        approval_id = getattr(payload, "approval_id", "") or ""
        bot_id = getattr(payload, "bot_id", "") or ""
        tool_name = getattr(payload, "tool_name", "") or ""
        arguments = getattr(payload, "arguments", {}) or {}
        reason = getattr(payload, "reason", None)

        args_preview = json.dumps(arguments, indent=2)[:500]
        text = (
            f"Tool approval required\n"
            f"Bot: {bot_id} | Tool: {tool_name}\n"
            f"Reason: {reason or 'Policy requires approval'}\n"
            f"Args: {args_preview}\n\n"
            f"Approve via the web UI (approval ID: {approval_id})"
        )
        return await self._send_text(
            target,
            text,
            failure_message=f"BB approval send failed for chat {target.chat_guid}",
        )


__all__ = ["BlueBubblesApprovalDelivery"]
