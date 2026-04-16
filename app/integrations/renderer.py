"""ChannelRenderer Protocol — the contract every integration delivery
implementation must satisfy.

A renderer takes a typed `ChannelEvent` plus a typed `DispatchTarget` and
delivers it to the integration's external system (Slack API, Discord API,
BlueBubbles webhook, etc.). The renderer is the ONLY code in the system
that knows how to talk to its integration.

The contract has three methods:

- `render(event, target) -> DeliveryReceipt` — main path. Convert the
  generic `ChannelEvent` (e.g. `new_message`, `turn_stream_token`,
  `turn_ended`, `approval_requested`) into integration-native API calls.
  Returns a `DeliveryReceipt` so the outbox drainer (Phase D) can mark
  the row delivered or retry on failure.

- `handle_outbound_action(action, target) -> DeliveryReceipt` — sideband
  actions like `UploadImage`, `AddReaction`, `RequestApproval` that the
  agent loop emits. Kept separate from `render` because actions don't
  go through the channel-events bus and don't need `ChannelEventKind`
  capability gating — they're explicit, targeted operations.

- `delete_attachment(attachment_metadata, target) -> bool` — synchronous
  delete. Stays as a Protocol method (not an event) because the admin
  endpoint at `app/services/attachments.py:215-217` returns the bool to
  its HTTP caller and synchronous delivery is unavoidable there.

Renderers also declare two ClassVars:

- `integration_id: str` — unique key in the registry. Matches the
  `DispatchTarget.integration_id` so the registry can route an event
  to the right renderer.
- `capabilities: frozenset[Capability]` — what this renderer can
  actually render. The outbox drainer (Phase D) and the in-process
  `IntegrationDispatcherTask` (this Phase B) silently skip events whose
  `kind.required_capabilities()` is not a subset.

Phase B introduces this as the contract; no concrete renderer registers
yet. Phase F replaces `integrations/slack/dispatcher.py` with
`integrations/slack/renderer.py:SlackRenderer`. Phase G does the same for
BlueBubbles. Phase H ports the BB renderer from scratch as the
acceptance test that the abstraction holds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.domain.capability import Capability
    from app.domain.channel_events import ChannelEvent
    from app.domain.dispatch_target import DispatchTarget
    from app.domain.outbound_action import OutboundAction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliveryReceipt:
    """Result of a renderer call.

    Returned by every `ChannelRenderer.render()` and
    `handle_outbound_action()` call so the caller (Phase B's
    `IntegrationDispatcherTask`, Phase D's `outbox_drainer`) can decide
    whether to mark the outbox row `DELIVERED`, retry, or dead-letter.

    Fields:

    - `success` — True if the renderer accepted and delivered the event.
      False if the renderer encountered an error.
    - `external_id` — optional external system identifier (e.g. Slack
      message `ts`, Discord message id, BB message guid). Renderers
      that support follow-up edits (`STREAMING_EDIT` capability) use
      this to address subsequent `MESSAGE_UPDATED` events.
    - `error` — human-readable error string when `success=False`.
      The drainer logs this on `last_error` and uses `retryable` to
      decide between `FAILED_RETRYABLE` and `FAILED_PERMANENT`.
    - `retryable` — True if the failure is transient (5xx, 429,
      connection error). Ignored when `success=True`.
    - `skip_reason` — set when the renderer chose not to deliver but
      did not fail (e.g. capability mismatch the renderer detected
      after target inspection, channel disabled, etc.). The drainer
      treats this as `DELIVERED` with the reason recorded.
    """

    success: bool
    external_id: str | None = None
    error: str | None = None
    retryable: bool = False
    skip_reason: str | None = None

    @classmethod
    def ok(cls, *, external_id: str | None = None) -> "DeliveryReceipt":
        return cls(success=True, external_id=external_id)

    @classmethod
    def failed(cls, error: str, *, retryable: bool = True) -> "DeliveryReceipt":
        return cls(success=False, error=error, retryable=retryable)

    @classmethod
    def skipped(cls, reason: str) -> "DeliveryReceipt":
        return cls(success=True, skip_reason=reason)


@runtime_checkable
class ChannelRenderer(Protocol):
    """Protocol every integration must implement to deliver channel events.

    See module docstring for the full contract. Renderers register
    themselves with `app.integrations.renderer_registry.register()` at
    import time. The registry validates `integration_id` uniqueness and
    that `capabilities` is a `frozenset[Capability]`.
    """

    integration_id: ClassVar[str]
    capabilities: ClassVar["frozenset[Capability]"]

    async def render(
        self,
        event: "ChannelEvent",
        target: "DispatchTarget",
    ) -> DeliveryReceipt:
        """Deliver a typed channel event to the integration."""
        ...

    async def handle_outbound_action(
        self,
        action: "OutboundAction",
        target: "DispatchTarget",
    ) -> DeliveryReceipt:
        """Execute a sideband outbound action (upload, reaction, approval)."""
        ...

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: "DispatchTarget",
    ) -> bool:
        """Synchronously delete a previously uploaded attachment.

        Returns True on success, False otherwise. Synchronous because the
        admin HTTP endpoint at `app/services/attachments.py:215-217`
        returns this bool to its caller.
        """
        ...


class SimpleRenderer:
    """Base class for non-streaming integration renderers.

    Encodes the delivery contract documented in
    ``docs/integrations/design.md``:

    - ``NEW_MESSAGE`` (durable, via outbox) is the **only** text delivery
      path. Subclasses implement ``send_text()`` and the base class calls
      it for user-visible NEW_MESSAGE events.
    - ``TURN_ENDED`` (ephemeral, via bus) is a **no-op** — non-streaming
      renderers have no placeholder to finalize.
    - Echo prevention for own-origin user messages is automatic.
    - Internal roles (``tool``, ``system``) are automatically skipped.

    **Anti-pattern this prevents**: posting new messages from
    ``TURN_ENDED``. Every assistant response is persisted as a
    ``NEW_MESSAGE`` in the outbox AND published as ``TURN_ENDED`` on the
    bus. Without dedup, renderers that handle both will deliver the
    response twice. Streaming renderers (Slack, Discord) handle this via
    idempotent ``chat.update`` / PATCH on an existing placeholder.
    Non-streaming renderers have no edit API, so the framework must
    prevent the overlap entirely — which is what this class does.

    Subclass and implement:

    - ``send_text(target, text) -> bool`` — deliver one text chunk.
    - ``send_error(target, error) -> bool`` — deliver an error message
      (optional override; default calls ``send_text`` with a prefix).

    Example::

        class TelegramRenderer(SimpleRenderer):
            integration_id = "telegram"
            capabilities = frozenset({Capability.TEXT})

            async def send_text(self, target, text: str) -> bool:
                resp = await httpx.post(f"{target.api_url}/sendMessage", ...)
                return resp.status_code == 200

        renderer_registry.register(TelegramRenderer())
    """

    integration_id: ClassVar[str]
    capabilities: ClassVar["frozenset[Capability]"]

    async def send_text(
        self,
        target: "DispatchTarget",
        text: str,
    ) -> bool:
        """Deliver a single text chunk to the external service.

        Returns True on success, False on failure (triggers outbox retry).
        Called once per chunk — long messages are NOT pre-split by the
        base class (subclasses that need chunking should override
        ``render`` or split inside ``send_text``).
        """
        raise NotImplementedError

    async def send_error(
        self,
        target: "DispatchTarget",
        error: str,
    ) -> bool:
        """Deliver an error message. Override to customize formatting."""
        return await self.send_text(target, f"Agent error: {error}")

    async def render(
        self,
        event: "ChannelEvent",
        target: "DispatchTarget",
    ) -> DeliveryReceipt:
        """Route a channel event through the delivery contract.

        Subclasses should NOT override this unless they need custom event
        handling beyond text delivery. The base implementation ensures
        the TURN_ENDED / NEW_MESSAGE contract is followed correctly.
        """
        from app.domain.channel_events import ChannelEventKind

        kind = event.kind

        # TURN_ENDED is ephemeral — no placeholder to update for
        # non-streaming renderers. Response delivery is NEW_MESSAGE's job.
        if kind == ChannelEventKind.TURN_ENDED:
            return DeliveryReceipt.skipped(
                "non-streaming renderer — delivery via NEW_MESSAGE"
            )

        if kind == ChannelEventKind.NEW_MESSAGE:
            return await self._handle_new_message(event, target)

        return DeliveryReceipt.skipped(
            f"{self.integration_id} does not handle {kind.value}"
        )

    async def _handle_new_message(
        self,
        event: "ChannelEvent",
        target: "DispatchTarget",
    ) -> DeliveryReceipt:
        """Process a NEW_MESSAGE event with standard echo prevention."""
        payload = event.payload
        msg = getattr(payload, "message", None)
        if msg is None:
            return DeliveryReceipt.skipped("new_message without message payload")

        role = getattr(msg, "role", "") or ""

        # Internal roles are never user-facing.
        if role in ("tool", "system"):
            return DeliveryReceipt.skipped(f"skips internal role={role}")

        # Echo prevention: own-origin user messages must not be sent back.
        if role == "user":
            msg_metadata = getattr(msg, "metadata", None) or {}
            if msg_metadata.get("source") == self.integration_id:
                return DeliveryReceipt.skipped(
                    f"{self.integration_id} skips own-origin user message "
                    f"(echo prevention)"
                )

        text = (getattr(msg, "content", "") or "").strip()
        if not text:
            return DeliveryReceipt.skipped("new_message with empty content")

        # Error messages from failed turns.
        error = getattr(msg, "error", None)
        if error and not text:
            ok = await self.send_error(target, error)
        else:
            ok = await self.send_text(target, text)

        if ok:
            return DeliveryReceipt.ok()
        return DeliveryReceipt.failed(
            f"{self.integration_id} send failed", retryable=True,
        )

    async def handle_outbound_action(
        self,
        action: "OutboundAction",
        target: "DispatchTarget",
    ) -> DeliveryReceipt:
        """Default: skip all outbound actions. Override to support uploads etc."""
        return DeliveryReceipt.skipped(
            f"{self.integration_id} does not handle outbound action "
            f"{getattr(action, 'type', type(action).__name__)}"
        )

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: "DispatchTarget",
    ) -> bool:
        """Default: no delete support."""
        return False
