"""ChannelEvent — the unit of delivery on the channel-events bus.

A ChannelEvent has a `kind` (StrEnum) and a `payload` (one variant of
the ChannelEventPayload union, must match the kind). It carries the
channel id, sequence number, and timestamp the bus assigns at publish
time.

Phase A introduces the type and a parallel `publish_typed` API on
`app/services/channel_events.py`. The legacy
`publish(channel_id, event_type, metadata)` continues to work as a
compat shim that wraps a dict into a `ChannelEvent`.

Subsequent phases migrate publishers to publish_typed. Renderers (Phase B+)
consume only typed events.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from app.domain.capability import Capability
from app.domain.payloads import (
    ApprovalRequestedPayload,
    ApprovalResolvedPayload,
    AttachmentDeletedPayload,
    ChannelEventPayload,
    DeliveryFailedPayload,
    HeartbeatTickPayload,
    MessagePayload,
    MessageUpdatedPayload,
    ReplayLapsedPayload,
    ShutdownPayload,
    ToolActivityPayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamToolResultPayload,
    TurnStreamToolStartPayload,
    TurnStreamTokenPayload,
    WorkflowProgressPayload,
)


class ChannelEventKind(StrEnum):
    NEW_MESSAGE = "new_message"
    MESSAGE_UPDATED = "message_updated"
    TURN_STARTED = "turn_started"
    TURN_STREAM_TOKEN = "turn_stream_token"
    TURN_STREAM_TOOL_START = "turn_stream_tool_start"
    TURN_STREAM_TOOL_RESULT = "turn_stream_tool_result"
    TURN_ENDED = "turn_ended"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    ATTACHMENT_DELETED = "attachment_deleted"
    DELIVERY_FAILED = "delivery_failed"
    WORKFLOW_PROGRESS = "workflow_progress"
    HEARTBEAT_TICK = "heartbeat_tick"
    TOOL_ACTIVITY = "tool_activity"
    SHUTDOWN = "shutdown"
    REPLAY_LAPSED = "replay_lapsed"

    def required_capabilities(self) -> frozenset[Capability]:
        """The capability set a renderer must declare to receive this kind.

        The outbox drainer (Phase D) checks this against the renderer's
        declared capabilities and silently skips events the renderer
        cannot handle.
        """
        return _REQUIRED_CAPS.get(self, frozenset())

    @property
    def is_outbox_durable(self) -> bool:
        """Whether renderer delivery for this kind goes ONLY through the outbox.

        Kinds in this set are delivered to renderers exclusively via
        ``outbox_drainer`` — ``IntegrationDispatcherTask`` short-circuits
        them in ``_dispatch`` to avoid the dual-path delivery foot-gun
        (the same event reaching ``renderer.render()`` twice). Publishers
        of these kinds MUST also enqueue an outbox row via
        ``outbox_publish.enqueue_new_message_for_channel`` (or, inside an
        existing transaction, ``outbox_publish.enqueue_for_targets``);
        otherwise the event flows to SSE subscribers but never reaches
        Slack/Discord/etc.

        ``NEW_MESSAGE`` is the only kind that needs durability today —
        the streaming kinds (``TURN_STREAM_*``, ``TURN_STARTED``,
        ``TURN_ENDED``) are inherently ephemeral (a missed token is fine,
        the next one supersedes it) and continue to flow via the bus.
        """
        return self in _OUTBOX_DURABLE_KINDS


# Kinds whose renderer delivery is the outbox drainer's exclusive
# responsibility. Publishers must enqueue an outbox row in addition to
# (or instead of) calling ``publish_typed``; ``IntegrationDispatcherTask``
# short-circuits these kinds in its dispatch loop.
_OUTBOX_DURABLE_KINDS: frozenset["ChannelEventKind"] = frozenset()  # populated below


# Each kind → the minimum capabilities a renderer must support to receive it.
# Empty frozenset = "every renderer can handle this" (e.g. shutdown).
_REQUIRED_CAPS: dict[ChannelEventKind, frozenset[Capability]] = {
    ChannelEventKind.NEW_MESSAGE: frozenset({Capability.TEXT}),
    ChannelEventKind.MESSAGE_UPDATED: frozenset({Capability.STREAMING_EDIT}),
    ChannelEventKind.TURN_STARTED: frozenset({Capability.TEXT}),
    ChannelEventKind.TURN_STREAM_TOKEN: frozenset({Capability.STREAMING_EDIT}),
    ChannelEventKind.TURN_STREAM_TOOL_START: frozenset({Capability.STREAMING_EDIT}),
    ChannelEventKind.TURN_STREAM_TOOL_RESULT: frozenset({Capability.STREAMING_EDIT}),
    ChannelEventKind.TURN_ENDED: frozenset({Capability.TEXT}),
    ChannelEventKind.APPROVAL_REQUESTED: frozenset({Capability.TEXT}),
    ChannelEventKind.APPROVAL_RESOLVED: frozenset(),
    ChannelEventKind.ATTACHMENT_DELETED: frozenset({Capability.FILE_DELETE}),
    ChannelEventKind.DELIVERY_FAILED: frozenset(),
    ChannelEventKind.WORKFLOW_PROGRESS: frozenset({Capability.TEXT}),
    ChannelEventKind.HEARTBEAT_TICK: frozenset({Capability.TEXT}),
    ChannelEventKind.TOOL_ACTIVITY: frozenset({Capability.TEXT}),
    ChannelEventKind.SHUTDOWN: frozenset(),
    ChannelEventKind.REPLAY_LAPSED: frozenset(),
}


# Populate the outbox-durable set after the enum exists. NEW_MESSAGE is
# the only kind that needs durable renderer delivery; everything else is
# either ephemeral (streaming tokens, turn lifecycle) or always handled
# inline (delivery_failed is published by the drainer itself).
_OUTBOX_DURABLE_KINDS = frozenset({ChannelEventKind.NEW_MESSAGE})


# kind → expected payload class. Used by ChannelEvent.__post_init__ to
# validate that publishers haven't paired the wrong payload with a kind.
_KIND_PAYLOAD: dict[ChannelEventKind, type] = {
    ChannelEventKind.NEW_MESSAGE: MessagePayload,
    ChannelEventKind.MESSAGE_UPDATED: MessageUpdatedPayload,
    ChannelEventKind.TURN_STARTED: TurnStartedPayload,
    ChannelEventKind.TURN_STREAM_TOKEN: TurnStreamTokenPayload,
    ChannelEventKind.TURN_STREAM_TOOL_START: TurnStreamToolStartPayload,
    ChannelEventKind.TURN_STREAM_TOOL_RESULT: TurnStreamToolResultPayload,
    ChannelEventKind.TURN_ENDED: TurnEndedPayload,
    ChannelEventKind.APPROVAL_REQUESTED: ApprovalRequestedPayload,
    ChannelEventKind.APPROVAL_RESOLVED: ApprovalResolvedPayload,
    ChannelEventKind.ATTACHMENT_DELETED: AttachmentDeletedPayload,
    ChannelEventKind.DELIVERY_FAILED: DeliveryFailedPayload,
    ChannelEventKind.WORKFLOW_PROGRESS: WorkflowProgressPayload,
    ChannelEventKind.HEARTBEAT_TICK: HeartbeatTickPayload,
    ChannelEventKind.TOOL_ACTIVITY: ToolActivityPayload,
    ChannelEventKind.SHUTDOWN: ShutdownPayload,
    ChannelEventKind.REPLAY_LAPSED: ReplayLapsedPayload,
}


@dataclass(frozen=True)
class ChannelEvent:
    """A typed event delivered on the channel-events bus.

    `seq` is assigned at publish time by the bus, NOT at construction
    time. Construct events with seq=0 and let publish_typed assign the
    real value.

    Validation: __post_init__ asserts the payload type matches the kind.
    """

    channel_id: uuid.UUID
    kind: ChannelEventKind
    payload: ChannelEventPayload
    seq: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        expected = _KIND_PAYLOAD.get(self.kind)
        if expected is None:
            raise ValueError(f"unknown ChannelEventKind: {self.kind!r}")
        if not isinstance(self.payload, expected):
            raise TypeError(
                f"ChannelEvent kind={self.kind} requires payload of type "
                f"{expected.__name__}, got {type(self.payload).__name__}"
            )
