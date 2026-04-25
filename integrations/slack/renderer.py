"""SlackRenderer — Phase F of the Integration Delivery refactor.

The single, in-process Slack delivery path. Replaces:

- ``integrations/slack/dispatcher.py`` (the legacy ``SlackDispatcher`` —
  the main-process queued path).
- ``integrations/slack/message_handlers.py:_run_dispatch`` (the
  in-subprocess long-poll path that posted directly to Slack).

The original user-reported bug — Slack mobile sometimes never refreshes
to the agent's final reply — was caused by these two paths racing each
other on ``chat.update`` storms with no shared rate limiter and no
coalesce window. SlackRenderer collapses both into one path with:

1. A single shared ``SlackRateLimiter`` (per-method token bucket).
2. A 0.8s ``chat.update`` coalesce window (matches the legacy debounce).
3. A "safety pass" — if a token arrives while a flush is in flight,
   the latest accumulated text is queued and one final ``chat.update``
   fires after the in-flight call completes.

The renderer subscribes to the channel-events bus via the registry
``app.integrations.renderer_registry``. NEW_MESSAGE events reach this
renderer via the outbox drainer ONLY — ``IntegrationDispatcherTask``
short-circuits outbox-durable kinds in its dispatch loop, so there is
no longer a "two paths racing for the same msg.id" foot-gun (see
``ChannelEventKind.is_outbox_durable``). Streaming kinds
(``TURN_STREAM_*``, ``TURN_STARTED``, ``TURN_ENDED``) still flow via
the bus because they're inherently ephemeral.
"""
from __future__ import annotations

import logging
from typing import ClassVar

from integrations.sdk import (
    Capability, ChannelEvent, ChannelEventKind,
    DispatchTarget, OutboundAction, DeliveryReceipt,
    ToolResultRenderingSupport,
    renderer_registry,
)
from integrations.slack.approval_delivery import SlackApprovalDelivery
from integrations.slack.client import bot_attribution
from integrations.slack.ephemeral_delivery import SlackEphemeralDelivery
from integrations.slack.message_delivery import SlackMessageDelivery
from integrations.slack.streaming import STREAMING_KINDS, SlackStreamingDelivery
from integrations.slack.target import SlackTarget
from integrations.slack.transport import call_slack

logger = logging.getLogger(__name__)


class SlackRenderer:
    """Channel renderer for Slack delivery.

    Capability declaration is the full Slack feature set. Anything the
    drainer passes us is something Slack supports — gating happens
    upstream so we don't have to handle the "Slack can't do this"
    case here.
    """

    integration_id: ClassVar[str] = "slack"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.TEXT,
        Capability.RICH_TEXT,
        Capability.THREADING,
        Capability.REACTIONS,
        Capability.INLINE_BUTTONS,
        Capability.ATTACHMENTS,
        Capability.IMAGE_UPLOAD,
        Capability.FILE_UPLOAD,
        Capability.FILE_DELETE,
        Capability.STREAMING_EDIT,
        Capability.RICH_TOOL_RESULTS,
        Capability.APPROVAL_BUTTONS,
        Capability.DISPLAY_NAMES,
        Capability.MENTIONS,
        Capability.EPHEMERAL,
        Capability.MODALS,
    })
    tool_result_rendering: ClassVar[ToolResultRenderingSupport | None] = (
        ToolResultRenderingSupport.from_manifest({
            "modes": ["compact", "full", "none"],
            "content_types": [
                "text/plain",
                "text/markdown",
                "application/json",
                "application/vnd.spindrel.components+json",
                "application/vnd.spindrel.diff+text",
                "application/vnd.spindrel.file-listing+json",
            ],
            "view_keys": [
                "core.search_results",
                "core.command_result",
                "core.machine_target_status",
            ],
            "interactive": False,
            "unsupported_fallback": "badge",
            "placement": "same_message",
            "limits": {
                "max_blocks": 50,
                "max_table_rows": 20,
                "max_links": 10,
                "max_code_chars": 2900,
            },
        })
    )

    def __init__(self) -> None:
        self._streaming = SlackStreamingDelivery(
            call_slack=call_slack,
            bot_attribution=bot_attribution,
        )
        self._messages = SlackMessageDelivery(
            call_slack=call_slack,
            bot_attribution=bot_attribution,
            tool_result_rendering=self.tool_result_rendering,
        )
        self._approvals = SlackApprovalDelivery(
            call_slack=call_slack,
            bot_attribution=bot_attribution,
        )
        self._ephemeral = SlackEphemeralDelivery(
            call_slack=call_slack,
            bot_attribution=bot_attribution,
        )

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if not isinstance(target, SlackTarget):
            return DeliveryReceipt.failed(
                f"SlackRenderer received non-slack target: {type(target).__name__}",
                retryable=False,
            )

        kind = event.kind
        try:
            if kind in STREAMING_KINDS:
                return await self._streaming.render(event, target)
            if kind == ChannelEventKind.NEW_MESSAGE:
                return await self._messages.render(event, target)
            if kind == ChannelEventKind.MESSAGE_UPDATED:
                return await self._handle_message_updated(event, target)
            if kind == ChannelEventKind.APPROVAL_REQUESTED:
                return await self._approvals.render(event, target)
            if kind == ChannelEventKind.EPHEMERAL_MESSAGE:
                return await self._ephemeral.render(event, target)
            if kind == ChannelEventKind.ATTACHMENT_DELETED:
                return await self._handle_attachment_deleted(event, target)
        except Exception as exc:
            logger.exception("SlackRenderer.render: unexpected failure for %s", kind.value)
            return DeliveryReceipt.failed(f"unexpected: {exc}", retryable=True)

        # Anything else (workflow_progress, heartbeat, tool_activity,
        # delivery_failed, replay_lapsed, shutdown): silently skip. The
        # outbox drainer marks the row delivered with the skip reason.
        return DeliveryReceipt.skipped(f"slack does not handle {kind.value}")

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        # Phase F focuses on bus-driven rendering. Sideband
        # ``OutboundAction``s (image upload, reaction toggle, raw
        # approval) come through ``TurnEndedPayload.client_actions``
        # and are handled inside ``_handle_turn_ended``.
        return DeliveryReceipt.skipped("slack outbound actions are handled inline")

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        if not isinstance(target, SlackTarget):
            return False
        slack_file_id = (attachment_metadata or {}).get("slack_file_id")
        if not target.token or not slack_file_id:
            return False
        try:
            from integrations.slack.uploads import delete_slack_file
            return await delete_slack_file(target.token, slack_file_id)
        except Exception:
            logger.exception("SlackRenderer.delete_attachment failed for %s", slack_file_id)
            return False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_message_updated(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        # Slack's chat.update needs a message ts to address. The legacy
        # path stored that on dispatch_config; the new flow expects it
        # on the typed payload. Until upstream publishers thread the
        # external_id through MessageUpdatedPayload, treat this as a
        # no-op skip.
        return DeliveryReceipt.skipped(
            "message_updated needs an external_id slack ts (not yet wired)"
        )

    async def _handle_attachment_deleted(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        metadata = getattr(payload, "metadata", {}) or {}
        slack_file_id = metadata.get("slack_file_id")
        if not slack_file_id:
            return DeliveryReceipt.skipped("attachment_deleted without slack_file_id")
        try:
            from integrations.slack.uploads import delete_slack_file
            ok = await delete_slack_file(target.token, slack_file_id)
        except Exception as exc:
            logger.exception("SlackRenderer: file delete failed for %s", slack_file_id)
            return DeliveryReceipt.failed(str(exc), retryable=True)
        return DeliveryReceipt.ok() if ok else DeliveryReceipt.failed(
            "delete_slack_file returned False", retryable=True,
        )


# ---------------------------------------------------------------------------
# Self-registration — same idempotent pattern as core_renderers.py
# ---------------------------------------------------------------------------


def _register() -> None:
    if renderer_registry.get(SlackRenderer.integration_id) is None:
        renderer_registry.register(SlackRenderer())


_register()
