"""publish_and_enqueue — the unified channel-event writer.

The split-step API (``enqueue`` inside the txn, ``publish_typed`` after
commit) is intentional: ``persist_turn`` already manages its own commit
sequence and the outbox row needs to land in the same transaction as the
message inserts. A single one-shot helper would have to know about the
caller's transaction shape, which is the wrong direction of coupling.

Usage pattern (see ``app/services/sessions.py:persist_turn``)::

    targets = await dispatch_resolution.resolve_targets(channel)
    for record in persisted_records:
        event = ChannelEvent(
            channel_id=channel_id,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=Message.from_orm(record, channel_id=channel_id)),
        )
        await outbox.enqueue(db, channel_id, event, targets)
    await db.commit()
    for event in events_in_order:
        publish_typed(channel_id, event)
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.channel_events import ChannelEvent
from app.domain.dispatch_target import DispatchTarget
from app.services import outbox

logger = logging.getLogger(__name__)


async def enqueue_for_targets(
    db: AsyncSession,
    channel_id: uuid.UUID,
    event: ChannelEvent,
    targets: list[tuple[str, DispatchTarget]],
) -> None:
    """Insert outbox rows for an event in the caller's transaction.

    Thin wrapper around ``outbox.enqueue`` that swallows the row list
    (callers don't need it) and turns the no-target case into a no-op
    log instead of a silent skip.
    """
    if not targets:
        logger.debug(
            "outbox_publish: no targets for channel=%s kind=%s — skipping enqueue",
            channel_id, event.kind.value,
        )
        return
    await outbox.enqueue(db, channel_id, event, targets)


def publish_to_bus(channel_id: uuid.UUID, event: ChannelEvent) -> int:
    """Synchronously publish a typed event to in-memory bus subscribers.

    Wraps ``channel_events.publish_typed`` so the call site doesn't have
    to import the bus module directly. Returns the subscriber count.
    """
    from app.services.channel_events import publish_typed
    return publish_typed(channel_id, event)
