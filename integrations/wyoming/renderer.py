"""WyomingRenderer -- minimal renderer for the Wyoming integration.

The Wyoming integration is synchronous request-response: the satellite
sends audio, the handler transcribes + dispatches + TTS and sends audio
back on the same TCP connection. So the renderer is mostly a no-op --
delivery happens inside the Wyoming server process, not via the bus.

This renderer exists to satisfy the integration framework contract and
handle any outbox-durable events that the system might route to us.
"""
from __future__ import annotations

import logging
from typing import ClassVar

from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent
from app.domain.dispatch_target import DispatchTarget
from app.domain.outbound_action import OutboundAction
from app.integrations.renderer import DeliveryReceipt
from app.integrations import renderer_registry

logger = logging.getLogger(__name__)


class WyomingRenderer:
    """Channel renderer for Wyoming voice delivery.

    Capabilities are minimal -- voice is text-only (the spoken response).
    """

    integration_id: ClassVar[str] = "wyoming"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.TEXT,
    })

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        # Primary delivery happens synchronously on the TCP connection
        # inside wyoming_server.py. Bus events are informational only.
        return DeliveryReceipt.skipped("wyoming delivers synchronously on TCP connection")

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.skipped("wyoming does not support outbound actions")

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        return False


renderer_registry.register(WyomingRenderer())
