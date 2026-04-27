"""In-memory user event bus for cross-session UI updates."""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Deque

logger = logging.getLogger(__name__)

QUEUE_MAX_SIZE = 256
REPLAY_BUFFER_SIZE = 128


@dataclass(frozen=True, slots=True)
class UserEvent:
    user_id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    seq: int = 0
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_subscribers: dict[uuid.UUID, set[asyncio.Queue[UserEvent]]] = defaultdict(set)
_next_seq: dict[uuid.UUID, int] = defaultdict(int)
_replay_buffer: dict[uuid.UUID, Deque[UserEvent]] = defaultdict(lambda: deque(maxlen=REPLAY_BUFFER_SIZE))
_shutdown_event: asyncio.Event | None = None


def get_shutdown_event() -> asyncio.Event:
    global _shutdown_event
    if _shutdown_event is None:
        _shutdown_event = asyncio.Event()
    return _shutdown_event


def signal_shutdown() -> None:
    get_shutdown_event().set()
    sentinel = UserEvent(user_id=uuid.UUID(int=0), kind="shutdown", payload={})
    for queues in list(_subscribers.values()):
        for queue in list(queues):
            try:
                queue.put_nowait(sentinel)
            except asyncio.QueueFull:
                pass


def _publish_event(event: UserEvent) -> int:
    _next_seq[event.user_id] += 1
    sealed = UserEvent(
        user_id=event.user_id,
        kind=event.kind,
        payload=event.payload,
        seq=_next_seq[event.user_id],
        ts=event.ts,
    )
    _replay_buffer[event.user_id].append(sealed)
    delivered = 0
    for queue in list(_subscribers.get(event.user_id, ())):
        try:
            queue.put_nowait(sealed)
            delivered += 1
        except asyncio.QueueFull:
            logger.debug("user_events: subscriber overflow for user %s", event.user_id)
    return delivered


def publish(user_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> int:
    return _publish_event(UserEvent(user_id=user_id, kind=kind, payload=payload))


def event_to_sse_dict(event: UserEvent) -> dict[str, Any]:
    from app.services.outbox import serialize_payload

    return {
        "kind": event.kind,
        "user_id": str(event.user_id),
        "seq": event.seq,
        "ts": event.ts.isoformat(),
        "payload": serialize_payload(event.payload),
    }


async def subscribe(user_id: uuid.UUID, *, since: int | None = None) -> AsyncIterator[UserEvent]:
    queue: asyncio.Queue[UserEvent] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
    _subscribers[user_id].add(queue)
    try:
        if since is not None:
            for event in list(_replay_buffer.get(user_id, ())):
                if event.seq > since:
                    yield event
        while True:
            event = await queue.get()
            yield event
            if event.kind == "shutdown":
                return
    finally:
        _subscribers[user_id].discard(queue)
        if not _subscribers[user_id]:
            _subscribers.pop(user_id, None)
