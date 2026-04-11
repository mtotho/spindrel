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

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.domain.capability import Capability
    from app.domain.channel_events import ChannelEvent
    from app.domain.dispatch_target import DispatchTarget
    from app.domain.outbound_action import OutboundAction


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
