"""Outbox — pure DB API for the channel-event durability layer.

Phase D of the Integration Delivery refactor. The outbox table is the
durability story for the channel-events bus: every typed event published
during a turn is recorded as one row per ``(channel, target integration)``
in the same DB transaction as the message inserts. A background drainer
(``app/services/outbox_drainer.py``) pulls rows, routes them through
``renderer_registry``, and updates the row state when the renderer returns.

This module is **pure DB**. It does not import the bus, the renderer
registry, or any HTTP client. The drainer composes this module with
``app/integrations/renderer_registry.py`` and the publishers compose it
with ``app/services/sessions.py:persist_turn``.

State machine
=============

::

    pending ──drainer pickup──▶ in_flight ──ok──▶ delivered
                                    │
                                    ├──failed (retryable, attempts < 10)──▶ failed_retryable ──backoff──▶ pending
                                    │
                                    └──failed (permanent OR attempts ≥ 10)──▶ dead_letter

``failed_retryable`` is functionally equivalent to ``pending`` for the
fetch query (the partial index covers both); the distinction is just so
operators can grep for stuck rows.
"""
from __future__ import annotations

import dataclasses
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Outbox
from app.domain.channel_events import ChannelEvent, ChannelEventKind, _KIND_PAYLOAD
from app.domain.delivery_state import DeliveryState
from app.domain.dispatch_target import DispatchTarget, parse_dispatch_target

if TYPE_CHECKING:
    from app.domain.payloads import ChannelEventPayload

logger = logging.getLogger(__name__)


# ---- Tunables ---------------------------------------------------------------

DEAD_LETTER_AFTER = 10
"""Maximum retry attempts before a row transitions to ``dead_letter``."""

MAX_BACKOFF_SECONDS = 300
"""Cap for exponential backoff between retries."""

DEFAULT_FETCH_LIMIT = 32


# ---- Payload (de)serialization ---------------------------------------------
#
# Outbox rows store the typed payload as JSONB. The drainer reconstitutes the
# original payload class via the kind→class table on ChannelEventKind. This
# serde walks frozen dataclass payloads (which may contain nested dataclasses
# like ``Message`` inside ``MessagePayload`` or ``OutboundAction`` variants
# inside ``TurnEndedPayload.client_actions``) and converts to/from
# JSON-compatible dicts.

def _to_jsonable(value: Any) -> Any:
    """Recursively convert a value into a JSON-compatible Python primitive."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: dict[str, Any] = {}
        for f in dataclasses.fields(value):
            out[f.name] = _to_jsonable(getattr(value, f.name))
        # Stash the class name so the deserializer can discriminate
        # OutboundAction variants etc. without needing the kind context.
        out["__type__"] = type(value).__name__
        return out
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    # Last-ditch: stringify. Better to lose precision than to crash on enqueue.
    logger.warning("outbox._to_jsonable: stringifying unsupported type %s", type(value).__name__)
    return str(value)


def serialize_payload(payload: "ChannelEventPayload") -> dict:
    """Serialize a typed ChannelEventPayload into a JSONB-compatible dict."""
    result = _to_jsonable(payload)
    if not isinstance(result, dict):
        raise TypeError(f"payload {type(payload).__name__} did not serialize to a dict")
    return result


def _build_dataclass_registry() -> dict[str, type]:
    """Collect every concrete dataclass that can appear inside a payload.

    Used by ``_from_jsonable`` to reconstruct nested dataclasses from the
    ``__type__`` discriminator stamped at serialize time.
    """
    from app.domain import outbound_action, payloads
    from app.domain.actor import ActorRef
    from app.domain.message import AttachmentBrief, Message

    registry: dict[str, type] = {
        ActorRef.__name__: ActorRef,
        Message.__name__: Message,
        AttachmentBrief.__name__: AttachmentBrief,
    }
    for mod in (payloads, outbound_action):
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and dataclasses.is_dataclass(obj):
                registry[name] = obj
    return registry


_DATACLASS_REGISTRY: dict[str, type] | None = None


def _get_dataclass_registry() -> dict[str, type]:
    global _DATACLASS_REGISTRY
    if _DATACLASS_REGISTRY is None:
        _DATACLASS_REGISTRY = _build_dataclass_registry()
    return _DATACLASS_REGISTRY


def _from_jsonable(value: Any, target_type: type | None = None) -> Any:
    """Reconstruct a typed value from its JSONB form.

    If ``target_type`` is provided, the value is coerced toward it
    (used for top-level payload reconstruction). Nested dataclasses
    self-discriminate via the ``__type__`` key the serializer stamped.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        type_name = value.get("__type__")
        cls = None
        if type_name:
            cls = _get_dataclass_registry().get(type_name)
        if cls is None and target_type is not None and dataclasses.is_dataclass(target_type):
            cls = target_type
        if cls is not None and dataclasses.is_dataclass(cls):
            field_types = {f.name: f.type for f in dataclasses.fields(cls)}
            kwargs: dict[str, Any] = {}
            for f in dataclasses.fields(cls):
                if f.name not in value:
                    continue
                raw = value[f.name]
                kwargs[f.name] = _from_jsonable(raw, _resolve_field_type(field_types.get(f.name)))
            try:
                return cls(**kwargs)
            except TypeError as exc:
                raise ValueError(
                    f"failed to reconstruct {cls.__name__} from outbox payload: {exc}"
                ) from exc
        # Plain dict (e.g. arguments / extra_metadata).
        return {k: v for k, v in value.items() if k != "__type__"}
    if isinstance(value, list):
        return [_from_jsonable(v) for v in value]
    if target_type is uuid.UUID and isinstance(value, str):
        return uuid.UUID(value)
    if target_type is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _resolve_field_type(annotation: Any) -> type | None:
    """Best-effort: resolve a dataclass field annotation to a concrete type.

    Field annotations on frozen dataclasses with ``from __future__ import
    annotations`` are stored as strings. We don't need full type resolution
    here — only ``UUID`` and ``datetime`` need coercion, and those are
    distinguishable by their string repr.
    """
    if annotation is None:
        return None
    if isinstance(annotation, type):
        return annotation
    if isinstance(annotation, str):
        if "uuid.UUID" in annotation or annotation.endswith("UUID"):
            return uuid.UUID
        if "datetime" in annotation:
            return datetime
    return None


def deserialize_payload(kind: ChannelEventKind, data: dict) -> "ChannelEventPayload":
    """Reconstruct a typed payload for a given event kind from a JSONB dict."""
    payload_cls = _KIND_PAYLOAD.get(kind)
    if payload_cls is None:
        raise ValueError(f"unknown ChannelEventKind for outbox row: {kind!r}")
    return _from_jsonable(data, payload_cls)


# ---- Public API -------------------------------------------------------------


async def enqueue(
    db: AsyncSession,
    channel_id: uuid.UUID,
    event: ChannelEvent,
    targets: list[tuple[str, DispatchTarget]],
) -> list[Outbox]:
    """Insert one outbox row per target inside the caller's transaction.

    The caller is responsible for committing the transaction. Returns the
    list of newly-created (still-uncommitted) ``Outbox`` instances.

    Idempotency: ``(channel_id, seq, target_integration_id)`` is unique.
    Re-enqueue of the same tuple raises ``IntegrityError`` from the
    underlying DB; callers using ``publish_and_enqueue`` should never hit
    this in practice because seq is monotonic per channel.
    """
    if not targets:
        return []
    payload_data = serialize_payload(event.payload)
    rows: list[Outbox] = []
    for integration_id, target in targets:
        row = Outbox(
            channel_id=channel_id,
            seq=event.seq,
            kind=event.kind.value,
            payload=payload_data,
            target_integration_id=integration_id,
            target=target.to_dict(),
            delivery_state=DeliveryState.PENDING.value,
            attempts=0,
        )
        db.add(row)
        rows.append(row)
    return rows


async def fetch_pending(
    db: AsyncSession, limit: int = DEFAULT_FETCH_LIMIT
) -> list[Outbox]:
    """Fetch the next batch of deliverable rows for the drainer.

    Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple drainer workers
    can run concurrently without dispatching the same row twice. SQLite
    silently ignores ``with_for_update`` and the test environment is
    single-process so the semantics still hold there.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(Outbox)
        .where(
            Outbox.delivery_state.in_(
                [DeliveryState.PENDING.value, DeliveryState.FAILED_RETRYABLE.value]
            ),
            Outbox.available_at <= now,
        )
        .order_by(Outbox.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_in_flight(db: AsyncSession, row: Outbox) -> None:
    await db.execute(
        update(Outbox)
        .where(Outbox.id == row.id)
        .values(delivery_state=DeliveryState.IN_FLIGHT.value)
    )
    row.delivery_state = DeliveryState.IN_FLIGHT.value


async def reset_stale_in_flight(db: AsyncSession) -> int:
    """Recover IN_FLIGHT rows from a previous process that crashed mid-delivery.

    The drainer marks rows IN_FLIGHT in one transaction, then runs the
    renderer in a separate session, then marks DELIVERED / FAILED in a
    third. If the process crashes between mark_in_flight and the final
    state transition, the row is stranded in IN_FLIGHT forever — the
    fetch_pending query only selects PENDING / FAILED_RETRYABLE, so
    these rows are invisible to a fresh drainer.

    Call this once at startup BEFORE the drainer task launches. Resets
    every IN_FLIGHT row back to PENDING with ``available_at = now`` so
    the next batch picks them up immediately. ``attempts`` is NOT
    incremented — the prior in-flight attempt never reached a renderer
    receipt, so it doesn't count against the retry budget.

    Returns the number of rows recovered.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Outbox)
        .where(Outbox.delivery_state == DeliveryState.IN_FLIGHT.value)
        .values(
            delivery_state=DeliveryState.PENDING.value,
            available_at=now,
            last_error="recovered from stale in_flight on startup",
        )
    )
    await db.commit()
    return result.rowcount or 0


async def mark_delivered(db: AsyncSession, row: Outbox) -> None:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(Outbox)
        .where(Outbox.id == row.id)
        .values(
            delivery_state=DeliveryState.DELIVERED.value,
            delivered_at=now,
            last_error=None,
        )
    )
    row.delivery_state = DeliveryState.DELIVERED.value
    row.delivered_at = now


NO_RENDERER_REQUEUE_SECONDS = 30
"""Delay before re-checking when no renderer is registered for a target.

Used to defer delivery during the build-up window where the outbox has
rows for an integration whose renderer hasn't been registered yet (e.g.
Slack rows accumulated before SlackRenderer landed). The row is not
counted as a failed attempt — it never reached a renderer.
"""


DEFER_DEAD_LETTER_AFTER = 480
"""Maximum ``defer_no_renderer`` invocations before a row dead-letters.

At ``NO_RENDERER_REQUEUE_SECONDS = 30`` per defer, this is roughly four
hours of waiting for a renderer to register. After that, the row is
treated as undeliverable — usually because the integration was deleted,
renamed, or permanently disabled — and we stop retrying so the outbox
table doesn't accumulate stuck rows forever.
"""


async def defer_no_renderer(db: AsyncSession, row: Outbox) -> str:
    """Put a row back to PENDING with a short delay because no renderer was found.

    Does NOT increment ``attempts``: a missing renderer is a configuration
    state, not a delivery failure. ``defer_count`` IS incremented so the
    row eventually dead-letters if the renderer never registers — see
    ``DEFER_DEAD_LETTER_AFTER`` for the cutover threshold.

    Returns the new ``delivery_state`` value so callers can detect a
    fresh dead-letter transition (e.g. to publish a ``DELIVERY_FAILED``
    event onto the bus).
    """
    new_defer_count = row.defer_count + 1
    if new_defer_count >= DEFER_DEAD_LETTER_AFTER:
        new_state = DeliveryState.DEAD_LETTER.value
        reason = (
            f"no renderer registered for target_integration_id={row.target_integration_id} "
            f"after {new_defer_count} defer attempts"
        )
        await db.execute(
            update(Outbox)
            .where(Outbox.id == row.id)
            .values(
                delivery_state=new_state,
                defer_count=new_defer_count,
                last_error="no renderer registered",
                dead_letter_reason=reason,
            )
        )
        row.delivery_state = new_state
        row.defer_count = new_defer_count
        row.last_error = "no renderer registered"
        row.dead_letter_reason = reason
        return new_state

    available_at = datetime.now(timezone.utc) + timedelta(seconds=NO_RENDERER_REQUEUE_SECONDS)
    await db.execute(
        update(Outbox)
        .where(Outbox.id == row.id)
        .values(
            delivery_state=DeliveryState.PENDING.value,
            defer_count=new_defer_count,
            available_at=available_at,
            last_error="no renderer registered",
        )
    )
    row.delivery_state = DeliveryState.PENDING.value
    row.defer_count = new_defer_count
    row.available_at = available_at
    row.last_error = "no renderer registered"
    return DeliveryState.PENDING.value


async def mark_failed(
    db: AsyncSession,
    row: Outbox,
    error: str,
    *,
    retryable: bool,
) -> str:
    """Transition a row to ``failed_retryable`` or ``dead_letter``.

    Returns the new ``delivery_state`` value so callers can detect a
    fresh dead-letter transition (e.g. to publish a ``DELIVERY_FAILED``
    event onto the bus).
    """
    new_attempts = row.attempts + 1
    if not retryable or new_attempts >= DEAD_LETTER_AFTER:
        new_state = DeliveryState.DEAD_LETTER.value
        backoff = 0
        dead_letter_reason: str | None = error
    else:
        new_state = DeliveryState.FAILED_RETRYABLE.value
        # Exponential backoff with cap. Attempt 1 → 2s, 2 → 4s, ..., capped at 300.
        backoff = min(MAX_BACKOFF_SECONDS, 2 ** new_attempts)
        dead_letter_reason = None
    available_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
    await db.execute(
        update(Outbox)
        .where(Outbox.id == row.id)
        .values(
            delivery_state=new_state,
            attempts=new_attempts,
            last_error=error,
            available_at=available_at,
            dead_letter_reason=dead_letter_reason,
        )
    )
    row.delivery_state = new_state
    row.attempts = new_attempts
    row.last_error = error
    row.available_at = available_at
    row.dead_letter_reason = dead_letter_reason
    return new_state


def reconstitute_event(row: Outbox) -> ChannelEvent:
    """Build a ChannelEvent from an Outbox row's persisted columns."""
    kind = ChannelEventKind(row.kind)
    payload = deserialize_payload(kind, row.payload or {})
    return ChannelEvent(
        channel_id=row.channel_id,
        kind=kind,
        payload=payload,
        seq=row.seq,
    )


def reconstitute_target(row: Outbox) -> DispatchTarget:
    """Reconstruct the typed DispatchTarget stored on an Outbox row."""
    return parse_dispatch_target(row.target or None)
