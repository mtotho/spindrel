"""BlueBubbles turn lifecycle delivery."""
from __future__ import annotations

from integrations.sdk import ChannelEvent, DeliveryReceipt
from integrations.bluebubbles import transport
from integrations.bluebubbles.target import BlueBubblesTarget


class BlueBubblesLifecycleDelivery:
    """Deliver non-durable lifecycle affordances for BlueBubbles."""

    def __init__(self, *, set_typing=None) -> None:
        self._set_typing = set_typing or transport.set_typing

    async def turn_started(
        self,
        event: ChannelEvent,
        target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        if not target.typing_indicator:
            return DeliveryReceipt.skipped("typing indicator disabled for this binding")
        await self._set_typing(target)
        return DeliveryReceipt.skipped("typing indicator sent (fire-and-forget)")

    async def turn_ended(
        self,
        event: ChannelEvent,
        target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.skipped(
            "non-streaming renderer — delivery via NEW_MESSAGE"
        )


__all__ = ["BlueBubblesLifecycleDelivery"]
