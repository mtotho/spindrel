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

    `session_id` is set when the event is bridged onto a different session's
    bus than the one it logically belongs to — today this is sub-session
    pipeline children whose turn lifecycle publishes on the PARENT channel's
    bus (so the run-view modal, subscribed there, can receive it) but which
    must NOT drive the parent channel's chat state. Parent-channel UI
    subscribers filter by `session_id` to drop these bridged events; legacy
    events with `session_id=None` pass through unchanged.
    """

    bot_id: str
    turn_id: uuid.UUID
    task_id: str | None = None
    reason: str = "user_message"
    """One of: 'user_message', 'queued_task_starting', 'heartbeat', 'workflow'."""
    session_id: uuid.UUID | None = None


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
    session_id: uuid.UUID | None = None
    """See `TurnStartedPayload.session_id` — set when bridged from a
    sub-session onto a parent channel's bus so UI subscribers can filter."""


@dataclass(frozen=True)
class TurnStreamThinkingPayload:
    """Payload for `turn_stream_thinking` events — incremental reasoning text.

    Separate from `TurnStreamTokenPayload` so UI subscribers can route the
    delta into the channel's thinking display without interleaving it with
    assistant content. Renderers with STREAMING_EDIT that don't surface
    thinking can safely ignore this kind; those that do (the web UI) append
    the delta to the turn's `thinkingContent`.
    """

    bot_id: str
    turn_id: uuid.UUID
    delta: str
    session_id: uuid.UUID | None = None


@dataclass(frozen=True)
class TurnStreamToolStartPayload:
    """Payload for `turn_stream_tool_start` events — agent began invoking a tool."""

    bot_id: str
    turn_id: uuid.UUID
    tool_name: str
    tool_call_id: str | None = None
    arguments: dict = field(default_factory=dict)
    surface: str | None = None
    summary: dict | None = None
    session_id: uuid.UUID | None = None


@dataclass(frozen=True)
class TurnStreamToolResultPayload:
    """Payload for `turn_stream_tool_result` events — tool returned.

    ``envelope`` carries the rendered ``ToolResultEnvelope.compact_dict()``
    so the web UI can pick a mimetype-keyed renderer (markdown / json-tree
    / diff / file-listing / sandboxed-html) without per-tool knowledge.
    Optional for backward compat with legacy publishers that haven't been
    migrated to populate it.
    """

    bot_id: str
    turn_id: uuid.UUID
    tool_name: str
    result_summary: str
    tool_call_id: str | None = None
    is_error: bool = False
    envelope: dict | None = None
    surface: str | None = None
    summary: dict | None = None
    session_id: uuid.UUID | None = None


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
    session_id: uuid.UUID | None = None
    """See `TurnStartedPayload.session_id` — set when bridged from a
    sub-session onto a parent channel's bus so UI subscribers can filter."""


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
    turn_id: uuid.UUID | None = None
    """The turn that requested approval. Optional only because legacy
    publishers may emit approvals outside a turn context (script-driven
    admin approvals, etc.). The web UI uses this to route the approval
    decision back to the correct in-flight turn slot — without it, a
    member-bot turn requesting approval while the primary turn is still
    active would land in the primary's slot and never resolve."""
    session_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ApprovalResolvedPayload:
    """Payload for `approval_resolved` events — user clicked approve/deny."""

    approval_id: str
    decision: str
    """'approved' | 'denied' | 'allow_always'."""
    session_id: uuid.UUID | None = None


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


@dataclass(frozen=True)
class ContextBudgetPayload:
    """Payload for `context_budget` events — mid-turn context budget snapshot.

    Emitted by `app/agent/loop.py` after context assembly so the UI (and
    E2E tests) can surface how full the context window is for this turn.
    """

    bot_id: str
    turn_id: uuid.UUID
    consumed_tokens: int
    total_tokens: int
    utilization: float
    model: str = ""
    available_budget: int = 0
    live_history_tokens: int = 0
    live_history_utilization: float = 0.0
    base_tokens: int = 0
    static_injection_tokens: int = 0
    tool_schema_tokens: int = 0


@dataclass(frozen=True)
class MemorySchemeBootstrapPayload:
    """Payload for `memory_scheme_bootstrap` events.

    Emitted when a workspace-files bot reads its memory index / bootstrap
    block into context for a turn. Gives the UI a hook to show the user
    "your bot just loaded its memory" and lets context-discovery tests
    assert the bootstrap path fired.
    """

    bot_id: str
    turn_id: uuid.UUID
    scheme: str
    files_loaded: int = 0


@dataclass(frozen=True)
class SkillAutoInjectPayload:
    """Payload for ``skill_auto_inject`` events.

    Emitted when context assembly pre-loads an enrolled skill into context
    because it's semantically relevant to the conversation. The UI can
    show a brief indicator like "Loaded: DIY Proofing Methods (0.62)".
    """

    bot_id: str
    turn_id: uuid.UUID
    skill_id: str
    skill_name: str
    similarity: float
    source: str  # enrollment source: authored, fetched, manual


@dataclass(frozen=True)
class LlmStatusPayload:
    """Payload for ``llm_status`` events -- LLM retry/fallback/cooldown status.

    Published during the retry/fallback chain so the UI can reset its
    observer timeout and display retry status to the user.
    """

    bot_id: str
    turn_id: uuid.UUID
    status: str  # "retry" | "fallback" | "cooldown_skip" | "error"
    model: str = ""
    reason: str = ""
    attempt: int = 0
    max_retries: int = 0
    wait_seconds: float = 0.0
    fallback_model: str = ""
    error: str = ""


@dataclass(frozen=True)
class PinnedFileUpdatedPayload:
    """Payload for ``pinned_file_updated`` events — a pinned file's content changed.

    Body is NOT included in the payload. The web UI re-fetches content via
    ``GET /api/v1/workspaces/{wid}/files/content?path=...`` when it receives
    this event, keeping the event lightweight.
    """

    channel_id: uuid.UUID
    path: str
    content_type: str


@dataclass(frozen=True)
class EphemeralMessagePayload:
    """Payload for ``ephemeral_message`` events — visible only to one recipient.

    Wraps a domain ``Message`` plus a recipient identifier, interpreted by
    the consuming renderer in its integration-native form (Slack user id
    like ``U0ALICE``, Discord snowflake, etc.).

    ``target_integration_id`` scopes delivery to exactly one bound
    integration on the channel. The dispatcher's per-binding filter in
    ``IntegrationDispatcherTask._dispatch`` compares this against the
    subscribing renderer's ``integration_id`` and silently drops the
    event on every renderer except the target. ``respond_privately``
    sets it based on which integration natively owns the recipient's
    user id (``U...`` → ``slack``, etc.); see ``ephemeral_dispatch.
    deliver_ephemeral``. Without a target binding, the tool returns
    ``unsupported`` rather than falling back to a channel broadcast —
    that fallback was a privacy violation hiding behind ergonomics.
    """

    message: Message
    recipient_user_id: str
    target_integration_id: str | None = None


@dataclass(frozen=True)
class WidgetReloadPayload:
    """Payload for `widget_reload` events — a dashboard-pinned widget's
    backend handler asked the iframe to re-fetch its data.

    Phase B.5 of the Widget SDK. Published by ``ctx.notify_reload()`` from
    inside a ``widget.py`` handler. Consumed only by iframes (via the
    ``spindrel.stream`` SSE multiplexer + a generated preamble auto-
    subscription); not delivered to integration renderers.

    ``pin_id`` identifies which pinned instance the signal targets. Widget
    iframes filter by ``pin_id === self.dashboardPinId`` so peer pins of
    the same bundle on the same channel don't react unless the handler
    fires once per pin.
    """

    pin_id: uuid.UUID


@dataclass(frozen=True)
class ModalSubmittedPayload:
    """Payload for ``modal_submitted`` events — the user filled out a form.

    ``callback_id`` correlates this submission with the waiter created by
    the ``open_modal`` tool. ``values`` is the flat dict of field-id →
    submitted-value pairs. ``submitted_by`` carries the integration-
    native user id so downstream audit trails can attribute the action;
    ``metadata`` relays opaque bookkeeping the tool set on ``OpenModal``.
    """

    callback_id: str
    submitted_by: str
    values: dict
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SessionPlanUpdatedPayload:
    """Payload for `session_plan_updated` events on the session bus."""

    session_id: uuid.UUID
    reason: str
    state: dict
    plan: dict | None = None


# Discriminated union of all known payloads.
ChannelEventPayload = (
    MessagePayload
    | MessageUpdatedPayload
    | TurnStartedPayload
    | TurnStreamTokenPayload
    | TurnStreamThinkingPayload
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
    | ContextBudgetPayload
    | MemorySchemeBootstrapPayload
    | PinnedFileUpdatedPayload
    | LlmStatusPayload
    | EphemeralMessagePayload
    | ModalSubmittedPayload
    | WidgetReloadPayload
    | SessionPlanUpdatedPayload
)
