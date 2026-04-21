"""Outbox drainer — background worker that delivers durable channel events.

Phase D of the Integration Delivery refactor. The drainer is the consumer
side of the outbox: it pulls pending rows, looks up the renderer for each
row's ``target_integration_id``, performs capability gating, and calls
``renderer.render(event, target)``. Success → ``mark_delivered``. Failure
→ ``mark_failed`` (with retryable/permanent semantics) → exponential
backoff or dead-letter.

The drainer is a single asyncio task started from ``app/main.py`` lifespan,
but it uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so scaling to N workers
in the future requires zero code changes.

Phase F's ``SlackRenderer`` will be the first registered renderer that
does *real* outbound work for live channel deliveries. Until then, the
drainer is exercisable only against webhook-targeted channels via
``WebhookRenderer``.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.db.engine import async_session
from app.db.models import Outbox
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.delivery_state import DeliveryState
from app.domain.payloads import DeliveryFailedPayload
from app.integrations import renderer_registry
from app.integrations.renderer import DeliveryReceipt
from app.services import outbox

logger = logging.getLogger(__name__)


IDLE_SLEEP_SECONDS = 1.0
"""Sleep when there are no rows to drain. Tighter while there's work."""

BUSY_SLEEP_SECONDS = 0.05
"""Sleep between batches when there's still work pending."""


async def outbox_drainer_worker() -> None:
    """Background loop that drains the outbox table.

    Started from ``app/main.py`` lifespan via ``safe_create_task``. Runs
    until cancelled at shutdown. Each loop iteration:

    1. Locks up to N pending rows in one transaction (``mark_in_flight``).
    2. Releases the lock immediately so the rest of the system isn't
       blocked while renderers run.
    3. Calls ``_deliver_one`` for each row in its own short transaction.

    Errors in any single row are logged and isolated; the drainer keeps
    running.
    """
    logger.info("outbox_drainer started")
    while True:
        try:
            rows = await _claim_batch()
            for row in rows:
                try:
                    await _deliver_one(row)
                except Exception:
                    logger.exception(
                        "outbox_drainer: unexpected error delivering row %s", row.id
                    )
            await asyncio.sleep(BUSY_SLEEP_SECONDS if rows else IDLE_SLEEP_SECONDS)
        except asyncio.CancelledError:
            logger.info("outbox_drainer cancelled, exiting")
            raise
        except Exception:
            logger.exception("outbox_drainer loop error")
            await asyncio.sleep(IDLE_SLEEP_SECONDS)


async def _claim_batch() -> list[Outbox]:
    """Fetch + mark a batch of pending rows in one short transaction."""
    async with async_session() as db:
        rows = await outbox.fetch_pending(db)
        for row in rows:
            await outbox.mark_in_flight(db, row)
        await db.commit()
        # Detach from this session so the next per-row session can re-fetch.
        for row in rows:
            db.expunge(row)
        return rows


async def _deliver_one(row: Outbox) -> None:
    """Deliver one outbox row through the renderer registry."""
    integration_id = row.target_integration_id
    renderer = renderer_registry.get(integration_id)
    if renderer is None:
        # Don't dead-letter immediately — the renderer may register later
        # (e.g. SlackRenderer is loaded by Phase F). Put the row back to
        # pending with a short delay; ``attempts`` is NOT incremented but
        # ``defer_count`` IS, so the row eventually dead-letters if the
        # renderer never registers (see ``DEFER_DEAD_LETTER_AFTER`` in
        # ``app/services/outbox.py``).
        logger.debug(
            "outbox_drainer: no renderer for integration_id=%s, deferring row %s",
            integration_id, row.id,
        )
        new_state = await _defer_no_renderer_in_session(row)
        if new_state == DeliveryState.DEAD_LETTER.value:
            await _publish_delivery_failed(
                row, "no renderer registered after maximum defer attempts"
            )
        return

    # Reconstitute the typed event + target from the persisted row.
    try:
        event = outbox.reconstitute_event(row)
        target = outbox.reconstitute_target(row)
    except Exception as exc:
        logger.exception(
            "outbox_drainer: failed to reconstitute row %s", row.id
        )
        await _mark_failed_in_session(
            row, error=f"reconstitution failed: {exc}", retryable=False
        )
        return

    # Capability gating: silently skip events the renderer cannot handle.
    required = event.kind.required_capabilities()
    if required and not required.issubset(renderer.capabilities):
        logger.debug(
            "outbox_drainer: capability skip row=%s kind=%s required=%s",
            row.id, event.kind.value, sorted(c.value for c in required),
        )
        await _mark_delivered_in_session(row)
        return

    # Call the renderer.
    try:
        receipt: DeliveryReceipt = await renderer.render(event, target)
    except Exception as exc:
        logger.exception(
            "outbox_drainer: renderer raised for row %s (integration=%s, kind=%s)",
            row.id, integration_id, event.kind.value,
        )
        await _mark_failed_in_session(
            row, error=f"renderer raised: {exc}", retryable=True
        )
        return

    if receipt.success:
        await _mark_delivered_in_session(row, event=event, target=target, receipt=receipt)
        return

    new_state = await _mark_failed_in_session(
        row, error=receipt.error or "renderer returned failed", retryable=receipt.retryable
    )
    if new_state == DeliveryState.DEAD_LETTER.value:
        await _publish_delivery_failed(row, receipt.error or "delivery failed")


async def _mark_delivered_in_session(
    row: Outbox,
    *,
    event: ChannelEvent | None = None,
    target: object | None = None,
    receipt: DeliveryReceipt | None = None,
) -> None:
    async with async_session() as db:
        # Re-load the row from the new session to attach it.
        attached = await db.get(Outbox, row.id)
        if attached is None:
            return
        await outbox.mark_delivered(db, attached)
        # Persist the integration's external id back onto the Message so
        # downstream consumers (thread-ref builder, inbound thread-reply
        # router) can walk from Spindrel Message → external message id.
        # Fire-and-forget style: swallow errors so a metadata-persist hiccup
        # never un-delivers the outbox row.
        if event is not None and receipt is not None and receipt.external_id:
            try:
                await _persist_delivery_metadata(db, row, event, target, receipt)
            except Exception:
                logger.exception(
                    "outbox_drainer: persist_delivery_metadata failed for row %s",
                    row.id,
                )
        await db.commit()


async def _persist_delivery_metadata(
    db,
    row: Outbox,
    event: ChannelEvent,
    target: object | None,
    receipt: DeliveryReceipt,
) -> None:
    """Mutate ``Message.metadata_`` after a successful outbound delivery.

    Only runs for ``NEW_MESSAGE`` events carrying a message id. Resolves
    the integration's ``persist_delivery_metadata`` hook to stamp
    platform-specific fields (Slack: ``slack_ts``/``slack_channel``;
    Discord: ``discord_message_id``/``discord_channel_id``). Uses the house
    JSONB mutation pattern (deepcopy + flag_modified) so SQLAlchemy emits
    the UPDATE.
    """
    import copy as _copy

    from sqlalchemy.orm.attributes import flag_modified

    from app.agent.hooks import get_integration_meta
    from app.db.models import Message as MessageModel

    if event.kind != ChannelEventKind.NEW_MESSAGE:
        return
    msg_payload = getattr(event.payload, "message", None)
    msg_id = getattr(msg_payload, "id", None) if msg_payload else None
    if msg_id is None:
        return
    meta = get_integration_meta(row.target_integration_id)
    if meta is None or meta.persist_delivery_metadata is None:
        return

    msg_row = await db.get(MessageModel, msg_id)
    if msg_row is None:
        return
    mutable = _copy.deepcopy(msg_row.metadata_ or {})
    meta.persist_delivery_metadata(mutable, receipt.external_id, target)
    msg_row.metadata_ = mutable
    flag_modified(msg_row, "metadata_")


async def _defer_no_renderer_in_session(row: Outbox) -> str:
    async with async_session() as db:
        attached = await db.get(Outbox, row.id)
        if attached is None:
            return DeliveryState.DELIVERED.value  # row vanished — nothing to do
        new_state = await outbox.defer_no_renderer(db, attached)
        await db.commit()
        row.delivery_state = attached.delivery_state
        row.available_at = attached.available_at
        row.last_error = attached.last_error
        row.defer_count = attached.defer_count
        row.dead_letter_reason = attached.dead_letter_reason
        return new_state


async def _mark_failed_in_session(row: Outbox, *, error: str, retryable: bool) -> str:
    async with async_session() as db:
        attached = await db.get(Outbox, row.id)
        if attached is None:
            return DeliveryState.DELIVERED.value  # row vanished — nothing to do
        new_state = await outbox.mark_failed(db, attached, error, retryable=retryable)
        await db.commit()
        # Mirror updated fields onto the original instance for caller use.
        row.delivery_state = attached.delivery_state
        row.attempts = attached.attempts
        row.last_error = attached.last_error
        return new_state


async def _publish_delivery_failed(row: Outbox, error: str) -> None:
    """Publish a DELIVERY_FAILED event to the bus on dead-letter transition.

    Lets the web UI render a red indicator on the originating message.
    """
    try:
        from app.services.channel_events import publish_typed
        event = ChannelEvent(
            channel_id=row.channel_id,
            kind=ChannelEventKind.DELIVERY_FAILED,
            payload=DeliveryFailedPayload(
                integration_id=row.target_integration_id,
                target_summary=str(row.target or {})[:200],
                last_error=error,
                attempts=row.attempts,
            ),
        )
        publish_typed(row.channel_id, event)
    except Exception:
        logger.exception(
            "outbox_drainer: failed to publish DELIVERY_FAILED for row %s", row.id
        )
