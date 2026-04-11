"""ChannelEventPayload — discriminated union of payloads keyed by ChannelEventKind.

Each ChannelEventKind has a corresponding payload dataclass. ChannelEvent
(in `app/domain/channel_events.py`) carries a `kind` plus its matching
payload. The pairing is enforced at construction time by ChannelEvent's
factory helpers, and at consume time by renderer match statements.

Phase A defines the types. Subsequent phases publish them.

Note: payloads stay JSON-serializable so they can be persisted to the
outbox table as JSONB and replayed across process restarts.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.message import Message
from app.domain.outbound_action import OutboundAction

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class MessagePayload:
    """Payload for `new_message` events.

    Carries a domain Message. Renderers consume this directly to render a
    message in the integration.
    """

    message: Message
    reply_in_thread: bool = False
    """A hint to the renderer. Renderers honor it only if their integration
    supports threading and the channel is configured for threaded responses.
    Today this is effectively always False (no integrations use threading)."""


@dataclass(frozen=True)
class MessageUpdatedPayload:
    """Payload for `message_updated` events — in-place edit of an existing message."""

    message: Message


@dataclass(frozen=True)
class TurnStartedPayload:
    """Payload for `turn_started` events.

    Slack/Discord renderers post a "thinking…" placeholder when this fires
    and store the resulting message ts in their per-channel RenderContext.

    `turn_id` correlates every event from a single agent turn. Parallel
    multi-bot turns on the same channel are demultiplexed by it.
    """

    bot_id: str
    turn_id: uuid.UUID
    task_id: str | None = None
    reason: str = "user_message"
    """One of: 'user_message', 'queued_task_starting', 'heartbeat', 'workflow'."""


@dataclass(frozen=True)
class TurnStreamTokenPayload:
    """Payload for `turn_stream_token` events — incremental text from the agent.

    Renderers with the STREAMING_EDIT capability accumulate these into a
    coalesced buffer and update the placeholder. Renderers without
    STREAMING_EDIT silently skip them (and the outbox marks the row
    DELIVERED with skip_reason="capability_missing:streaming_edit").
    """

    bot_id: str
    turn_id: uuid.UUID
    delta: str


@dataclass(frozen=True)
class TurnStreamToolStartPayload:
    """Payload for `turn_stream_tool_start` events — agent began invoking a tool."""

    bot_id: str
    turn_id: uuid.UUID
    tool_name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TurnStreamToolResultPayload:
    """Payload for `turn_stream_tool_result` events — tool returned."""

    bot_id: str
    turn_id: uuid.UUID
    tool_name: str
    result_summary: str
    is_error: bool = False


@dataclass(frozen=True)
class TurnEndedPayload:
    """Payload for `turn_ended` events — terminal event for an agent turn.

    Replaces the legacy `dispatcher.deliver(task, result_text, client_actions=...)`
    call signature. The renderer finalizes its placeholder edit, posts the
    message body, and uploads any attached images/files declared in
    `client_actions`.

    On error paths (timeout, rate limit, exception), `result` is None and
    `error` is set. The renderer is expected to render a user-visible
    error message in those cases.
    """

    bot_id: str
    turn_id: uuid.UUID
    result: str | None = None
    error: str | None = None
    client_actions: list[OutboundAction] = field(default_factory=list)
    extra_metadata: dict = field(default_factory=dict)
    task_id: str | None = None
    kind_hint: str | None = None
    """Optional hint for the renderer to format differently — e.g. 'heartbeat'
    triggers the 💓 prefix in Slack."""


@dataclass(frozen=True)
class ApprovalRequestedPayload:
    """Payload for `approval_requested` events — tool/capability approval gate.

    Renderers with APPROVAL_BUTTONS render Block Kit / Discord buttons.
    Renderers without it fall back to plain-text approval messages.
    """

    approval_id: str
    bot_id: str
    tool_name: str
    arguments: dict = field(default_factory=dict)
    reason: str | None = None
    capability: dict | None = None
    """Set when the approval is for a capability activation rather than a
    raw tool call — see SlackDispatcher._build_capability_approval_blocks
    in the legacy code."""


@dataclass(frozen=True)
class ApprovalResolvedPayload:
    """Payload for `approval_resolved` events — user clicked approve/deny."""

    approval_id: str
    decision: str
    """'approved' | 'denied' | 'allow_always'."""


@dataclass(frozen=True)
class AttachmentDeletedPayload:
    """Payload for `attachment_deleted` events — server-side attachment removed.

    Renderers with FILE_DELETE call the integration's file-delete API
    (e.g. Slack files.delete). Renderers without it silently skip.

    Note: the synchronous `delete_attachment` ChannelRenderer method
    (called from `app/services/attachments.py:215-217`) coexists with
    this event for the case where the HTTP caller needs the bool result.
    """

    attachment_id: uuid.UUID
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryFailedPayload:
    """Payload for `delivery_failed` events.

    Published by the outbox drainer when a row exhausts retries and
    moves to DEAD_LETTER. Lets the web UI render a red indicator on
    the originating message.
    """

    integration_id: str
    target_summary: str
    last_error: str
    attempts: int
    related_message_id: uuid.UUID | None = None


@dataclass(frozen=True)
class WorkflowProgressPayload:
    """Payload for `workflow_progress` events.

    Replaces the dispatcher.post_message call from
    app/services/workflow_executor.py:67-73.
    """

    run_id: str
    event: str
    """'started' | 'step_done' | 'step_failed' | 'completed' | 'failed'."""
    detail: str = ""
    bot_id: str | None = None
    step_index: int | None = None


@dataclass(frozen=True)
class HeartbeatTickPayload:
    """Payload for `heartbeat_tick` events — scheduled heartbeat fired.

    Lets renderers display a heartbeat-style update without it being
    a full turn_ended.
    """

    bot_id: str
    schedule_id: str | None = None


@dataclass(frozen=True)
class ToolActivityPayload:
    """Payload for `tool_activity` events — generic tool execution status.

    Distinct from `turn_stream_tool_*` (which is per-token streaming).
    Used for tools that produce status independent of an agent turn,
    e.g. workflows or scheduled tools.
    """

    bot_id: str
    tool_name: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class ShutdownPayload:
    """Payload for `shutdown` events — server is shutting down.

    Subscribers should gracefully close their connections.
    """

    pass


@dataclass(frozen=True)
class ReplayLapsedPayload:
    """Payload for `replay_lapsed` events — the subscriber needs to refetch.

    Two flavors, distinguished by ``reason``:

    - ``"client_lag"``: a subscriber reconnected with ``since`` older than
      the buffer's earliest seq. ``oldest_available`` is the lowest seq the
      bus can still serve. The client should refetch from REST and resume.
    - ``"subscriber_overflow"``: a slow consumer's queue overflowed. The bus
      drained its queue and pushed this sentinel; the consumer is expected
      to disconnect and reconnect with ``since=last_seq`` to replay from
      the ring buffer.
    """

    requested_since: int
    oldest_available: int
    reason: str = "client_lag"


# Discriminated union of all known payloads.
ChannelEventPayload = (
    MessagePayload
    | MessageUpdatedPayload
    | TurnStartedPayload
    | TurnStreamTokenPayload
    | TurnStreamToolStartPayload
    | TurnStreamToolResultPayload
    | TurnEndedPayload
    | ApprovalRequestedPayload
    | ApprovalResolvedPayload
    | AttachmentDeletedPayload
    | DeliveryFailedPayload
    | WorkflowProgressPayload
    | HeartbeatTickPayload
    | ToolActivityPayload
    | ShutdownPayload
    | ReplayLapsedPayload
)
