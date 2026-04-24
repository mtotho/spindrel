"""In-memory channel event bus — typed events as the only event shape.

Any part of the system (integrations, workflows, heartbeats, the web UI SSE
endpoint) can publish or subscribe to events scoped to a channel_id. Events
carry a per-channel monotonic sequence number and are buffered in a small
ring per channel for replay-on-reconnect.

Usage::

    from app.services.channel_events import publish_typed, publish_message, subscribe
    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.payloads import TurnStartedPayload

    publish_typed(channel_id, ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.TURN_STARTED,
        payload=TurnStartedPayload(bot_id="...", turn_id=uuid.uuid4()),
    ))

    # Convenience for new_message / message_updated:
    publish_message(channel_id, message_orm_row)

    # Subscribe (typed events):
    async for event in subscribe(channel_id):
        match event.kind:
            case ChannelEventKind.NEW_MESSAGE:
                ...

    # Reconnect with replay:
    async for event in subscribe(channel_id, since=42):
        ...

The bus deals exclusively in `app.domain.channel_events.ChannelEvent`
(frozen dataclass with a typed payload). There is no untyped publish path
and no legacy envelope wrapping. The single ``event_to_sse_dict`` helper
serializes events for the browser SSE wire.

See `project-notes/Track - Integration Delivery.md` for
the broader rationale.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import replace as _dc_replace
from typing import TYPE_CHECKING, AsyncIterator, Deque

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import (
    MessagePayload,
    MessageUpdatedPayload,
    ReplayLapsedPayload,
    ShutdownPayload,
)

logger = logging.getLogger(__name__)

QUEUE_MAX_SIZE = 512
REPLAY_BUFFER_SIZE = 256  # events per channel retained for replay-on-reconnect

if TYPE_CHECKING:
    from app.db.models import Message as ORMMessage


# channel_id → set of subscriber queues
_subscribers: dict[uuid.UUID, set[asyncio.Queue[ChannelEvent]]] = defaultdict(set)

# Global subscribers receive every event published to every channel.
# Used by `IntegrationDispatcherTask` (one per registered renderer) to fan
# out the bus to integration-side delivery without requiring callers to
# know which integrations are bound to which channels. Subscribe via
# `subscribe_all()`.
_global_subscribers: set[asyncio.Queue[ChannelEvent]] = set()

# channel_id → next sequence number. Persists for the life of the process,
# even after the last subscriber leaves, so a reconnecting client can replay.
_next_seq: dict[uuid.UUID, int] = defaultdict(int)

# channel_id → ring buffer of recent events for replay-on-reconnect.
_replay_buffer: dict[uuid.UUID, Deque[ChannelEvent]] = defaultdict(
    lambda: deque(maxlen=REPLAY_BUFFER_SIZE)
)

# Set during server shutdown to break SSE loops
_shutdown_event: asyncio.Event | None = None


def get_shutdown_event() -> asyncio.Event:
    """Return (and lazily create) the shutdown event."""
    global _shutdown_event
    if _shutdown_event is None:
        _shutdown_event = asyncio.Event()
    return _shutdown_event


def signal_shutdown() -> None:
    """Signal all SSE subscribers to disconnect.

    Sets the shutdown event AND pushes a typed SHUTDOWN sentinel to every
    queue so subscribers wake up immediately instead of waiting for the
    next keepalive timeout.
    """
    get_shutdown_event().set()
    sentinel = ChannelEvent(
        channel_id=uuid.UUID(int=0),
        kind=ChannelEventKind.SHUTDOWN,
        payload=ShutdownPayload(),
    )
    total = 0
    for subs in _subscribers.values():
        for q in subs:
            try:
                q.put_nowait(sentinel)
                total += 1
            except asyncio.QueueFull:
                pass
    for q in _global_subscribers:
        try:
            q.put_nowait(sentinel)
            total += 1
        except asyncio.QueueFull:
            pass
    logger.info("Channel events: shutdown signalled, pushed sentinel to %d subscriber(s)", total)


def _deliver_to_queue(
    q: asyncio.Queue[ChannelEvent],
    event: ChannelEvent,
) -> bool:
    """Push `event` onto a subscriber queue, recovering from overflow.

    On `QueueFull` (subscriber too slow): drains the queue and pushes a
    single `replay_lapsed` sentinel marking the gap. The subscriber's
    `subscribe()` / `subscribe_all()` generator yields the sentinel and
    exits cleanly; the consumer (SSE handler, `IntegrationDispatcherTask`,
    etc.) is expected to reconnect with `since=last_seq_received` and
    replay missed events from the ring buffer.

    Returns True if the original event was delivered, False if it was
    replaced with a lapsed sentinel.

    Silent drops are not safe — a slow subscriber could invisibly miss
    events forever, leaving its local cache permanently out of sync with
    no way to recover.
    """
    try:
        q.put_nowait(event)
        return True
    except asyncio.QueueFull:
        pass

    # Subscriber too slow. Drain the queue so the consumer sees the
    # lapsed sentinel as the next item, then exits.
    while True:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break

    sentinel = ChannelEvent(
        channel_id=event.channel_id,
        kind=ChannelEventKind.REPLAY_LAPSED,
        payload=ReplayLapsedPayload(
            requested_since=event.seq,
            oldest_available=event.seq,
            reason="subscriber_overflow",
        ),
        seq=event.seq,
    )
    try:
        q.put_nowait(sentinel)
    except asyncio.QueueFull:
        # Should never happen — we just drained the queue. Log for sanity.
        logger.error(
            "channel_events: failed to push lapsed sentinel after drain "
            "for channel %s seq=%d (this is a bug)",
            event.channel_id,
            event.seq,
        )
    logger.debug(
        "channel_events: subscriber overflowed at seq=%d for channel %s; "
        "pushed replay_lapsed sentinel, subscriber will reconnect",
        event.seq,
        event.channel_id,
    )
    return False


def _fanout(channel_id: uuid.UUID, event: ChannelEvent) -> int:
    """Deliver `event` to per-channel subscribers and global subscribers.

    Returns the count of subscribers that received the original event.
    Subscribers whose queue overflowed receive a `replay_lapsed` sentinel
    instead and are NOT counted in the return value, since the original
    event did not reach them.
    """
    delivered = 0
    subs = _subscribers.get(channel_id)
    if subs:
        for q in subs:
            if _deliver_to_queue(q, event):
                delivered += 1
    if _global_subscribers:
        for q in _global_subscribers:
            if _deliver_to_queue(q, event):
                delivered += 1
    return delivered


def publish_typed(channel_id: uuid.UUID, event: ChannelEvent) -> int:
    """Publish a typed ChannelEvent to all subscribers of a channel.

    Assigns the per-channel monotonic sequence number, appends to the
    replay buffer, and fans out to live subscribers (per-channel and
    global). Returns the number of subscribers that received the event.

    The event is appended to the replay buffer regardless of whether any
    subscribers are currently connected, so a future reconnecting client
    can replay missed events via `subscribe(..., since=N)`.

    Backpressure: if a subscriber's queue is full, the queue is drained
    and a `replay_lapsed` sentinel is pushed in its place. See
    `_deliver_to_queue` for details.
    """
    _next_seq[channel_id] += 1
    seq = _next_seq[channel_id]
    # ChannelEvent is frozen — use dataclasses.replace to set the seq.
    sealed = _dc_replace(event, channel_id=channel_id, seq=seq)
    _replay_buffer[channel_id].append(sealed)
    return _fanout(channel_id, sealed)


def publish_message(
    channel_id: uuid.UUID,
    message: "ORMMessage",
    *,
    event_type: str = "new_message",
) -> int:
    """Publish a Message ORM row as a typed channel event.

    Wraps the row in a ``domain.Message`` + ``MessagePayload`` and calls
    ``publish_typed``. Use ``event_type="message_updated"`` (or call
    ``publish_message_updated``) for in-place edits.
    """
    from app.domain.message import Message as DomainMessage

    domain_msg = DomainMessage.from_orm(message, channel_id=channel_id)
    if event_type == "message_updated":
        kind = ChannelEventKind.MESSAGE_UPDATED
        payload = MessageUpdatedPayload(message=domain_msg)
    else:
        kind = ChannelEventKind.NEW_MESSAGE
        payload = MessagePayload(message=domain_msg)

    event = ChannelEvent(channel_id=channel_id, kind=kind, payload=payload)
    return publish_typed(channel_id, event)


def publish_message_updated(channel_id: uuid.UUID, message: "ORMMessage") -> int:
    """Publish an in-place edit of an existing message.

    Used by `workflow_executor` when it updates a step-progress message
    in place rather than creating a new one. Clients should patch the
    matching message id in their local cache.
    """
    return publish_message(channel_id, message, event_type="message_updated")


# ---- SSE wire format -------------------------------------------------------


def event_to_sse_dict(event: ChannelEvent) -> dict:
    """Serialize a typed ChannelEvent to a JSON-safe dict for the SSE wire.

    Uses ``outbox.serialize_payload`` (which already walks frozen
    dataclasses, UUIDs, datetimes, and nested ``Message`` /
    ``OutboundAction`` variants) so the wire format and the outbox
    storage format use the same serializer.
    """
    from app.services.outbox import serialize_payload

    return {
        "kind": event.kind.value,
        "channel_id": str(event.channel_id),
        "seq": event.seq,
        "ts": event.timestamp.isoformat(),
        "payload": serialize_payload(event.payload),
    }


# ---- Subscribe -------------------------------------------------------------


async def subscribe(
    channel_id: uuid.UUID,
    *,
    since: int | None = None,
) -> AsyncIterator[ChannelEvent]:
    """Subscribe to events for a channel. Yields typed events as they arrive.

    If `since` is provided, replays buffered events with seq > since
    BEFORE tailing live events. If the buffer no longer covers `since`
    (events were evicted), yields a `replay_lapsed` sentinel first so
    the client knows to refetch from REST and resume from the new seq.

    Live events that overlap with replayed events (by seq) are skipped,
    so the consumer never sees a duplicate.

    Backpressure handling: if the publisher overflows this subscriber's
    queue, `_deliver_to_queue` drains the queue and pushes a single
    `replay_lapsed` sentinel with ``reason="subscriber_overflow"``. This
    generator yields the sentinel and then exits — the consumer (SSE
    handler, browser EventSource) is expected to reconnect with
    `since=last_seq` to resume from the ring buffer.

    Auto-cleans up when the consumer exits (e.g. SSE disconnect).
    """
    q: asyncio.Queue[ChannelEvent] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)

    # Register the subscriber FIRST so we don't miss any live events
    # published between the buffer snapshot and the start of the tail loop.
    _subscribers[channel_id].add(q)
    try:
        replayed_seqs: set[int] = set()
        if since is not None:
            buf = list(_replay_buffer.get(channel_id, ()))
            if buf:
                oldest_seq = buf[0].seq
                if oldest_seq > since + 1:
                    # Gap: we've lost events between `since` and `oldest_seq - 1`.
                    yield ChannelEvent(
                        channel_id=channel_id,
                        kind=ChannelEventKind.REPLAY_LAPSED,
                        payload=ReplayLapsedPayload(
                            requested_since=since,
                            oldest_available=oldest_seq,
                            reason="client_lag",
                        ),
                        seq=since,
                    )
                for ev in buf:
                    if ev.seq > since:
                        replayed_seqs.add(ev.seq)
                        yield ev

        while True:
            event = await q.get()
            # Skip live events whose seq we already delivered via replay.
            if event.seq in replayed_seqs:
                continue
            # If a publisher overflowed our queue, _deliver_to_queue drained
            # the queue and pushed a `replay_lapsed` sentinel with
            # reason == "subscriber_overflow". Yield it once and exit so
            # the consumer reconnects.
            if (
                event.kind is ChannelEventKind.REPLAY_LAPSED
                and isinstance(event.payload, ReplayLapsedPayload)
                and event.payload.reason == "subscriber_overflow"
            ):
                yield event
                return
            yield event
    finally:
        _subscribers[channel_id].discard(q)
        if not _subscribers[channel_id]:
            del _subscribers[channel_id]


async def subscribe_all() -> AsyncIterator[ChannelEvent]:
    """Subscribe to typed events from EVERY channel.

    Used by `IntegrationDispatcherTask`: one long-lived task per
    registered renderer, demuxing events to per-channel `RenderContext`
    inside the task. Justified by:

    1. Slack/Discord/BlueBubbles all have process-wide rate limits — a
       single rate-limiter per task is correct.
    2. Per-channel ephemeral state (`thinking_ts`, stream buffers, etc.)
       lives in the task's `dict[channel_id, RenderContext]`.
    3. Subscriber-queue overflow is per-subscriber: N integrations vs
       N×channels paths is the difference.
    4. Channels don't have an "active vs idle" lifecycle in the bus today.

    No `since` semantics: this is a process-internal subscriber started at
    boot. Durability for restarts is the outbox's job, not the bus's.

    Backpressure: same `replay_lapsed` semantics as `subscribe()`. If the
    publisher overflows this task's queue, the queue is drained and a
    sentinel is pushed; the generator yields it and exits. The
    `IntegrationDispatcherTask` is expected to restart its subscription
    on the next bus loop iteration.

    Auto-cleans up when the consumer exits.
    """
    q: asyncio.Queue[ChannelEvent] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
    _global_subscribers.add(q)
    try:
        while True:
            event = await q.get()
            if (
                event.kind is ChannelEventKind.REPLAY_LAPSED
                and isinstance(event.payload, ReplayLapsedPayload)
                and event.payload.reason == "subscriber_overflow"
            ):
                yield event
                return
            yield event
    finally:
        _global_subscribers.discard(q)


def global_subscriber_count() -> int:
    """Return the number of active `subscribe_all()` subscribers."""
    return len(_global_subscribers)


def subscriber_count(channel_id: uuid.UUID) -> int:
    """Return the number of active subscribers for a channel."""
    return len(_subscribers.get(channel_id, set()))


def current_seq(channel_id: uuid.UUID) -> int:
    """Return the current (last-assigned) seq for a channel, or 0 if none."""
    return _next_seq.get(channel_id, 0)


def reset_channel_state(channel_id: uuid.UUID) -> None:
    """Forget all retained state for a channel.

    Used by tests for isolation, and could be used by an explicit
    "purge" admin operation if a channel is deleted.
    """
    _subscribers.pop(channel_id, None)
    _next_seq.pop(channel_id, None)
    _replay_buffer.pop(channel_id, None)
