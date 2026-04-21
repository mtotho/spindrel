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

For fire-and-forget publishers that don't have an existing transaction
(heartbeat tools, usage spike, ``_fanout``, ``turn_worker._persist_and_
publish_user_message``, etc.) use ``enqueue_new_message_for_channel``,
which opens its own session, resolves targets, enqueues, and commits in
a single self-contained call.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.dispatch_target import DispatchTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import MessagePayload
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


async def enqueue_new_message_for_channel(
    channel_id: uuid.UUID,
    domain_msg: DomainMessage,
) -> None:
    """Self-contained outbox enqueue for a NEW_MESSAGE event.

    For publishers that emit NEW_MESSAGE outside an existing DB
    transaction (``turn_worker._persist_and_publish_user_message``,
    ``_fanout``, ``heartbeat_tools.post_heartbeat_to_channel``,
    ``usage_spike`` channel-target path, ``delegation.post_child_
    response`` follow-ups, etc.).

    Opens its own ``async_session()``, looks up the channel, resolves
    every dispatch target bound to it, and inserts one outbox row per
    target inside that session's transaction. The drainer
    (``app/services/outbox_drainer.py``) picks the rows up and routes
    them through the renderer registry.

    Failure modes are logged and swallowed: durable delivery failure for
    a single ephemeral publish should not break the caller's main path.
    SSE subscribers still receive the event via the bus publish that
    sits next to the call site.
    """
    try:
        from app.db.engine import async_session
        from app.db.models import Channel
        from app.services.dispatch_resolution import resolve_targets

        async with async_session() as db:
            channel = await db.get(Channel, channel_id)
            if channel is None:
                logger.debug(
                    "enqueue_new_message_for_channel: channel %s not found — "
                    "skipping outbox enqueue (no targets to resolve)",
                    channel_id,
                )
                return

            targets = await resolve_targets(channel)
            event = ChannelEvent(
                channel_id=channel_id,
                kind=ChannelEventKind.NEW_MESSAGE,
                payload=MessagePayload(message=domain_msg),
            )
            await enqueue_for_targets(db, channel_id, event, targets)
            await db.commit()
    except Exception:
        logger.warning(
            "enqueue_new_message_for_channel failed for channel %s msg %s",
            channel_id,
            getattr(domain_msg, "id", "?"),
            exc_info=True,
        )


async def enqueue_new_message_for_target(
    channel_id: uuid.UUID,
    domain_msg: DomainMessage,
    target_integration_id: str,
) -> bool:
    """Enqueue a NEW_MESSAGE scoped to exactly one bound integration.

    Unlike ``enqueue_new_message_for_channel`` which fans out to every
    binding on the channel, this variant filters ``resolve_targets`` to
    the requested integration id and only enqueues that row. Used by
    ``open_modal`` to post the "Open form" button to the binding that
    originated the triggering message — no fan-out to surfaces that
    can't action the button.

    Returns True if a target matching ``target_integration_id`` was
    found and enqueued, False otherwise (caller can decide whether to
    surface an error).
    """
    try:
        from app.db.engine import async_session
        from app.db.models import Channel
        from app.services.dispatch_resolution import resolve_targets

        async with async_session() as db:
            channel = await db.get(Channel, channel_id)
            if channel is None:
                logger.debug(
                    "enqueue_new_message_for_target: channel %s not found",
                    channel_id,
                )
                return False

            targets = await resolve_targets(channel)
            scoped = [(iid, t) for iid, t in targets if iid == target_integration_id]
            if not scoped:
                return False

            event = ChannelEvent(
                channel_id=channel_id,
                kind=ChannelEventKind.NEW_MESSAGE,
                payload=MessagePayload(message=domain_msg),
            )
            await enqueue_for_targets(db, channel_id, event, scoped)
            await db.commit()
            return True
    except Exception:
        logger.warning(
            "enqueue_new_message_for_target failed for channel=%s integration=%s msg=%s",
            channel_id,
            target_integration_id,
            getattr(domain_msg, "id", "?"),
            exc_info=True,
        )
        return False


async def enqueue_new_message_for_thread_session(
    session_id: uuid.UUID,
    domain_msg: DomainMessage,
) -> bool:
    """Fan a thread-session Message out through the parent channel's outbox.

    Thread sessions live as ``channel_id IS NULL`` rows but share their
    parent channel's integration bindings. Outbound posts need to land in
    the integration's native thread primitive (Slack ``thread_ts``, Discord
    thread channel id, etc.), which is resolved via
    ``Session.integration_thread_refs`` + the integration's
    ``apply_thread_ref`` hook.

    No-op for non-thread sessions (returns False) so callers can use it
    as a catch-all in channel-less publish paths without pre-checking
    session_type.
    """
    try:
        from app.db.engine import async_session
        from app.db.models import Channel, Session
        from app.services.dispatch_resolution import (
            apply_session_thread_refs,
            resolve_targets,
        )
        from app.services.sub_session_bus import resolve_bus_channel_id

        async with async_session() as db:
            session_row = await db.get(Session, session_id)
            if session_row is None or session_row.session_type != "thread":
                return False

            bus_ch = await resolve_bus_channel_id(db, session_id)
            if bus_ch is None:
                return False
            channel_row = await db.get(Channel, bus_ch)
            if channel_row is None:
                return False

            targets = await resolve_targets(channel_row)
            targets = apply_session_thread_refs(session_row, targets)

            event = ChannelEvent(
                channel_id=bus_ch,
                kind=ChannelEventKind.NEW_MESSAGE,
                payload=MessagePayload(message=domain_msg),
            )
            await enqueue_for_targets(db, bus_ch, event, targets)
            await db.commit()
            return True
    except Exception:
        logger.warning(
            "enqueue_new_message_for_thread_session failed for session=%s msg=%s",
            session_id,
            getattr(domain_msg, "id", "?"),
            exc_info=True,
        )
        return False


def publish_to_bus(channel_id: uuid.UUID, event: ChannelEvent) -> int:
    """Synchronously publish a typed event to in-memory bus subscribers.

    Wraps ``channel_events.publish_typed`` so the call site doesn't have
    to import the bus module directly. Returns the subscriber count.
    """
    from app.services.channel_events import publish_typed
    return publish_typed(channel_id, event)
