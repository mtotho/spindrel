"""General-purpose in-memory channel event bus.

Any part of the system (integrations, workflows, heartbeats, the web UI SSE
endpoint) can publish or subscribe to events scoped to a channel_id. Events
carry a per-channel monotonic sequence number and are buffered in a small
ring per channel for replay-on-reconnect.

Usage::

    from app.services.channel_events import publish_message, subscribe

    # Publisher (fire-and-forget) — ships the actual Message row:
    publish_message(channel_id, message_row)

    # Lightweight notification publisher (no row):
    publish(channel_id, "stream_event", {"stream_id": ..., "event": {...}})

    # Subscriber (async generator):
    async for event in subscribe(channel_id):
        ...

    # Reconnect with replay:
    async for event in subscribe(channel_id, since=42):
        ...

This module is the source of truth for live channel events. Consumers should
treat events as authoritative — the `new_message` and `message_updated`
event types ship the full serialized Message row in their metadata, so
clients can append to local state without refetching from REST.

See `vault/Projects/agent-server/Track - Streaming Architecture.md` for
the broader rationale and phased rollout plan.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncIterator, Deque

from app.schemas.messages import MessageOut

logger = logging.getLogger(__name__)

QUEUE_MAX_SIZE = 512
REPLAY_BUFFER_SIZE = 256  # events per channel retained for replay-on-reconnect

if TYPE_CHECKING:
    from app.db.models import Message


@dataclass(frozen=True)
class ChannelEvent:
    channel_id: uuid.UUID
    event_type: str
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    seq: int = 0  # per-channel monotonic; assigned by publish()


# channel_id → set of subscriber queues
_subscribers: dict[uuid.UUID, set[asyncio.Queue[ChannelEvent]]] = defaultdict(set)

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

    Sets the shutdown event AND pushes a sentinel to every queue so
    subscribers wake up immediately instead of waiting for the next
    keepalive timeout.
    """
    get_shutdown_event().set()
    total = 0
    sentinel = ChannelEvent(
        channel_id=uuid.UUID(int=0),
        event_type="shutdown",
    )
    for subs in _subscribers.values():
        for q in subs:
            try:
                q.put_nowait(sentinel)
                total += 1
            except asyncio.QueueFull:
                pass
    logger.info("Channel events: shutdown signalled, pushed sentinel to %d subscriber(s)", total)


def publish(channel_id: uuid.UUID, event_type: str, metadata: dict | None = None) -> int:
    """Publish an event to all subscribers of a channel.

    Assigns a per-channel monotonic sequence number, appends to the replay
    buffer, and fans out to live subscribers. Non-blocking: drops events for
    subscribers whose queues are full (logged at debug level).

    Returns the number of subscribers that received the event.

    The event is appended to the replay buffer regardless of whether any
    subscribers are currently connected, so a future reconnecting client
    can replay missed events via `subscribe(..., since=N)`.
    """
    _next_seq[channel_id] += 1
    seq = _next_seq[channel_id]
    event = ChannelEvent(
        channel_id=channel_id,
        event_type=event_type,
        metadata=metadata or {},
        seq=seq,
    )
    _replay_buffer[channel_id].append(event)

    subs = _subscribers.get(channel_id)
    if not subs:
        return 0
    delivered = 0
    for q in subs:
        try:
            q.put_nowait(event)
            delivered += 1
        except asyncio.QueueFull:
            logger.debug(
                "Dropping event %s (seq=%d) for channel %s (subscriber queue full)",
                event_type, seq, channel_id,
            )
    return delivered


def publish_message(
    channel_id: uuid.UUID,
    message: "Message",
    *,
    event_type: str = "new_message",
) -> int:
    """Publish a Message row as a channel event.

    Serializes the row via MessageOut so the SSE payload carries the
    actual data. Subscribers can append to their local cache instead
    of triggering a DB refetch.

    Use `event_type="message_updated"` (or call `publish_message_updated`)
    for in-place edits, e.g. workflow lifecycle progress messages.
    """
    serialized = MessageOut.from_orm(message).model_dump(mode="json")
    return publish(channel_id, event_type, {"message": serialized})


def publish_message_updated(channel_id: uuid.UUID, message: "Message") -> int:
    """Publish an in-place edit of an existing message.

    Used by `workflow_executor` when it updates a step-progress message
    in place rather than creating a new one. Clients should patch the
    matching message id in their local cache.
    """
    return publish_message(channel_id, message, event_type="message_updated")


async def subscribe(
    channel_id: uuid.UUID,
    *,
    since: int | None = None,
) -> AsyncIterator[ChannelEvent]:
    """Subscribe to events for a channel. Yields events as they arrive.

    If `since` is provided, replays buffered events with seq > since
    BEFORE tailing live events. If the buffer no longer covers `since`
    (events were evicted), yields a `replay_lapsed` sentinel first so
    the client knows to refetch from REST and resume from the new seq.

    Live events that overlap with replayed events (by seq) are skipped,
    so the consumer never sees a duplicate.

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
                        event_type="replay_lapsed",
                        metadata={
                            "requested_since": since,
                            "oldest_available": oldest_seq,
                        },
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
            yield event
    finally:
        _subscribers[channel_id].discard(q)
        if not _subscribers[channel_id]:
            del _subscribers[channel_id]


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
