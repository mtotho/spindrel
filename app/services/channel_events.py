"""General-purpose in-memory channel event bus.

Any part of the system (integrations, workflows, heartbeats, the web UI SSE
endpoint) can publish or subscribe to lightweight notification events scoped
to a channel_id.  Events are notification-only — consumers refetch from DB.

Usage::

    from app.services.channel_events import publish, subscribe

    # Publisher (fire-and-forget):
    publish(channel_id, "new_message")

    # Subscriber (async generator):
    async for event in subscribe(channel_id):
        ...
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator

logger = logging.getLogger(__name__)

QUEUE_MAX_SIZE = 512


@dataclass(frozen=True)
class ChannelEvent:
    channel_id: uuid.UUID
    event_type: str
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# channel_id → set of subscriber queues
_subscribers: dict[uuid.UUID, set[asyncio.Queue[ChannelEvent]]] = defaultdict(set)


def publish(channel_id: uuid.UUID, event_type: str, metadata: dict | None = None) -> int:
    """Publish an event to all subscribers of a channel.

    Non-blocking: drops events for subscribers whose queues are full.
    Returns the number of subscribers that received the event.
    """
    subs = _subscribers.get(channel_id)
    if not subs:
        return 0
    event = ChannelEvent(
        channel_id=channel_id,
        event_type=event_type,
        metadata=metadata or {},
    )
    delivered = 0
    for q in subs:
        try:
            q.put_nowait(event)
            delivered += 1
        except asyncio.QueueFull:
            logger.debug(
                "Dropping event %s for channel %s (subscriber queue full)",
                event_type, channel_id,
            )
    return delivered


async def subscribe(channel_id: uuid.UUID) -> AsyncIterator[ChannelEvent]:
    """Subscribe to events for a channel. Yields events as they arrive.

    Auto-cleans up when the consumer exits (e.g. SSE disconnect).
    """
    q: asyncio.Queue[ChannelEvent] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
    _subscribers[channel_id].add(q)
    try:
        while True:
            event = await q.get()
            yield event
    finally:
        _subscribers[channel_id].discard(q)
        if not _subscribers[channel_id]:
            del _subscribers[channel_id]


def subscriber_count(channel_id: uuid.UUID) -> int:
    """Return the number of active subscribers for a channel."""
    return len(_subscribers.get(channel_id, set()))
