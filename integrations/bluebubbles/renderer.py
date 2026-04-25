"""BlueBubblesRenderer — iMessage delivery via BlueBubbles.

Non-streaming renderer: ``NEW_MESSAGE`` (outbox-durable) is the only text
delivery path. ``TURN_ENDED`` is a no-op because iMessage has no edit/update
API and there is no streaming placeholder to finalize.

Self-registers via ``_register()`` at module import time.
"""
from __future__ import annotations

import logging
from typing import ClassVar

from integrations.sdk import (
    Capability,
    ChannelEvent,
    ChannelEventKind,
    DeliveryReceipt,
    DispatchTarget,
    OutboundAction,
    UploadFile,
    UploadImage,
    renderer_registry,
)
from integrations.bluebubbles.approval_delivery import BlueBubblesApprovalDelivery
from integrations.bluebubbles.lifecycle_delivery import BlueBubblesLifecycleDelivery
from integrations.bluebubbles.message_delivery import (
    BlueBubblesMessageDelivery,
    _split_text,
)
from integrations.bluebubbles.target import BlueBubblesTarget
from integrations.bluebubbles.upload_delivery import BlueBubblesUploadDelivery

logger = logging.getLogger(__name__)


class BlueBubblesRenderer:
    """Channel renderer for BlueBubbles / iMessage delivery."""

    integration_id: ClassVar[str] = "bluebubbles"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.TEXT,
        Capability.IMAGE_UPLOAD,
        Capability.FILE_UPLOAD,
        Capability.TYPING_INDICATOR,
    })
    tool_result_rendering = None

    def __init__(self) -> None:
        self._messages = BlueBubblesMessageDelivery()
        self._lifecycle = BlueBubblesLifecycleDelivery()
        self._approvals = BlueBubblesApprovalDelivery(
            send_text=self._messages.send_text,
        )
        self._uploads = BlueBubblesUploadDelivery(
            send_text=self._messages.send_text,
        )

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if not isinstance(target, BlueBubblesTarget):
            return DeliveryReceipt.failed(
                f"BlueBubblesRenderer received non-bluebubbles target: "
                f"{type(target).__name__}",
                retryable=False,
            )

        kind = event.kind
        try:
            if kind == ChannelEventKind.TURN_STARTED:
                return await self._lifecycle.turn_started(event, target)
            if kind == ChannelEventKind.TURN_ENDED:
                return await self._lifecycle.turn_ended(event, target)
            if kind == ChannelEventKind.NEW_MESSAGE:
                return await self._messages.render(event, target)
            if kind == ChannelEventKind.APPROVAL_REQUESTED:
                return await self._approvals.render(event, target)
        except Exception as exc:
            logger.exception(
                "BlueBubblesRenderer.render: unexpected failure for %s",
                kind.value,
            )
            return DeliveryReceipt.failed(f"unexpected: {exc}", retryable=True)

        return DeliveryReceipt.skipped(
            f"bluebubbles does not handle {kind.value}"
        )

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if not isinstance(target, BlueBubblesTarget):
            return DeliveryReceipt.skipped("not a bluebubbles target")

        if isinstance(action, UploadImage):
            return await self._uploads.render(action, target)
        if isinstance(action, UploadFile):
            return await self._uploads.render(action, target)

        return DeliveryReceipt.skipped(
            f"bluebubbles does not handle outbound action {action.type}"
        )

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        return False


def _register() -> None:
    if renderer_registry.get(BlueBubblesRenderer.integration_id) is None:
        renderer_registry.register(BlueBubblesRenderer())


_register()

__all__ = ["BlueBubblesRenderer", "_split_text"]
