"""E.5 — outbox state machine has no guards (drift-seam tests).

Seam class: silent-UPDATE
Suspected drift: mark_in_flight / mark_delivered / mark_failed all write the
new state with no pre-check on the prior state. A double-ack or a stale
drainer can flip DELIVERED → FAILED_RETRYABLE (re-queuing an already-delivered
message) or IN_FLIGHT → IN_FLIGHT (re-claiming a live row). Pin current
behavior so future hardening has a regression surface.

For each test ask: *if this invariant silently drifted, would my assertion
fail?* Drift-pin tests are labelled in their docstrings.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.unit.test_outbox import _patch_pg_types_for_sqlite  # noqa: F401

from app.db.models import Base, Channel, Outbox
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.delivery_state import DeliveryState
from app.domain.dispatch_target import NoneTarget
from app.domain.actor import ActorRef
from app.domain.message import Message as DomainMessage
from app.domain.payloads import TurnEndedPayload
from app.services import outbox


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    from sqlalchemy import text as sa_text
    from sqlalchemy.schema import DefaultClause

    replacements = {"now()": "CURRENT_TIMESTAMP", "gen_random_uuid()": None}
    originals: dict[tuple[str, str], object] = {}
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            txt = str(sd.arg) if hasattr(sd, "arg") else str(sd)
            new_default: str | None = None
            replaced = False
            for pg_expr, sqlite_expr in replacements.items():
                if pg_expr in txt:
                    replaced = True
                    new_default = sqlite_expr
                    break
            if not replaced and "::jsonb" in txt:
                replaced = True
                new_default = txt.replace("::jsonb", "")
            if not replaced and "::json" in txt:
                replaced = True
                new_default = txt.replace("::json", "")
            if replaced:
                originals[(table.name, col.name)] = sd
                col.server_default = (
                    DefaultClause(sa_text(new_default)) if new_default else None
                )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    for (tname, cname), default in originals.items():
        Base.metadata.tables[tname].c[cname].server_default = default
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _turn_ended_event(channel_id: uuid.UUID, seq: int = 1) -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.TURN_ENDED,
        payload=TurnEndedPayload(
            bot_id="b",
            turn_id=uuid.uuid4(),
            result="done",
            client_actions=[],
            extra_metadata={},
            task_id=str(uuid.uuid4()),
        ),
        seq=seq,
    )


async def _seed_row(db: AsyncSession, channel_id: uuid.UUID, seq: int = 1) -> Outbox:
    """Enqueue one PENDING row and commit it."""
    event = _turn_ended_event(channel_id, seq)
    rows = await outbox.enqueue(db, channel_id, event, [("none", NoneTarget())])
    await db.commit()
    return rows[0]


# ---------------------------------------------------------------------------
# Normal state transitions (anchor for the drift pins below)
# ---------------------------------------------------------------------------


class TestNormalStateTransitions:
    @pytest.mark.asyncio
    async def test_pending_to_in_flight_preserves_attempts(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        row = await _seed_row(db, channel.id)
        assert row.delivery_state == DeliveryState.PENDING.value

        await outbox.mark_in_flight(db, row)
        await db.commit()

        assert row.delivery_state == DeliveryState.IN_FLIGHT.value
        assert row.attempts == 0  # claim does not increment attempts

    @pytest.mark.asyncio
    async def test_in_flight_to_delivered_sets_delivered_at(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        row = await _seed_row(db, channel.id)
        await outbox.mark_in_flight(db, row)
        await db.commit()

        before = datetime.now(timezone.utc)
        await outbox.mark_delivered(db, row)
        await db.commit()

        assert row.delivery_state == DeliveryState.DELIVERED.value
        assert row.delivered_at is not None
        delivered_at = row.delivered_at
        if delivered_at.tzinfo is None:
            delivered_at = delivered_at.replace(tzinfo=timezone.utc)
        assert delivered_at >= before

    @pytest.mark.asyncio
    async def test_in_flight_to_failed_retryable_increments_attempts_and_schedules_backoff(
        self, db: AsyncSession
    ):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        row = await _seed_row(db, channel.id)
        await outbox.mark_in_flight(db, row)
        await db.commit()

        before = datetime.now(timezone.utc)
        new_state = await outbox.mark_failed(db, row, "transient", retryable=True)
        await db.commit()

        assert new_state == DeliveryState.FAILED_RETRYABLE.value
        assert row.delivery_state == DeliveryState.FAILED_RETRYABLE.value
        assert row.attempts == 1
        available_at = row.available_at
        if available_at.tzinfo is None:
            available_at = available_at.replace(tzinfo=timezone.utc)
        assert available_at > before  # backoff pushes into future

    @pytest.mark.asyncio
    async def test_failed_retryable_to_dead_letter_via_non_retryable_mark_failed(
        self, db: AsyncSession
    ):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        row = await _seed_row(db, channel.id)
        await outbox.mark_in_flight(db, row)
        await outbox.mark_failed(db, row, "transient", retryable=True)
        await db.commit()
        assert row.delivery_state == DeliveryState.FAILED_RETRYABLE.value

        new_state = await outbox.mark_failed(db, row, "permanent failure", retryable=False)
        await db.commit()

        assert new_state == DeliveryState.DEAD_LETTER.value
        assert row.delivery_state == DeliveryState.DEAD_LETTER.value
        assert row.dead_letter_reason == "permanent failure"


# ---------------------------------------------------------------------------
# Drift-seam pins — backward / sideways transitions with no guard
# ---------------------------------------------------------------------------


class TestStateTransitionDriftPins:
    @pytest.mark.asyncio
    async def test_drift_pin_double_ack_delivered_to_delivered_is_silent(
        self, db: AsyncSession
    ):
        """DRIFT PIN — DELIVERED → mark_delivered again: no guard, no error.

        A double-ack happens when the drainer retries after a network hiccup
        but the renderer already confirmed delivery. The second mark_delivered
        is a no-op at the value level (idempotent) but there is no pre-check
        guarding against it. Pin current behavior: call succeeds, state stays
        DELIVERED.
        """
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        row = await _seed_row(db, channel.id)
        await outbox.mark_delivered(db, row)
        await db.commit()
        assert row.delivery_state == DeliveryState.DELIVERED.value

        # Second mark_delivered — no error should be raised.
        await outbox.mark_delivered(db, row)
        await db.commit()

        assert row.delivery_state == DeliveryState.DELIVERED.value

    @pytest.mark.asyncio
    async def test_drift_pin_delivered_to_failed_retryable_silently_succeeds(
        self, db: AsyncSession
    ):
        """DRIFT PIN — DELIVERED → mark_failed(retryable=True): no guard.

        A stale drainer process ACKs failure after a fresher process already
        delivered successfully. Without a state-machine guard, this flips an
        already-DELIVERED row back to FAILED_RETRYABLE, causing re-delivery.
        Pin current behavior: the transition silently succeeds. Future
        hardening should raise or no-op here.
        """
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        row = await _seed_row(db, channel.id)
        await outbox.mark_delivered(db, row)
        await db.commit()
        assert row.delivery_state == DeliveryState.DELIVERED.value

        new_state = await outbox.mark_failed(db, row, "stale failure", retryable=True)
        await db.commit()

        # Current behavior: silently flips backward to FAILED_RETRYABLE.
        assert new_state == DeliveryState.FAILED_RETRYABLE.value
        assert row.delivery_state == DeliveryState.FAILED_RETRYABLE.value
        assert row.attempts == 1

    @pytest.mark.asyncio
    async def test_drift_pin_in_flight_to_in_flight_is_silent(
        self, db: AsyncSession
    ):
        """DRIFT PIN — IN_FLIGHT → mark_in_flight again: no guard.

        Two drainer workers racing on the same row (e.g., before
        FOR UPDATE SKIP LOCKED was added, or in a future regression) could
        both call mark_in_flight. The second call is a no-op at the value
        level but does not raise. Pin current behavior.
        """
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        row = await _seed_row(db, channel.id)
        await outbox.mark_in_flight(db, row)
        await db.commit()
        assert row.delivery_state == DeliveryState.IN_FLIGHT.value

        # Second mark_in_flight — no error.
        await outbox.mark_in_flight(db, row)
        await db.commit()

        assert row.delivery_state == DeliveryState.IN_FLIGHT.value
        assert row.attempts == 0  # never incremented by mark_in_flight

    @pytest.mark.asyncio
    async def test_drift_pin_failed_retryable_to_delivered_silently_succeeds(
        self, db: AsyncSession
    ):
        """DRIFT PIN — FAILED_RETRYABLE → mark_delivered: no guard.

        A delayed ACK from a renderer that eventually succeeded (after the
        drainer had already marked the row retryable) lands after a retry
        picked it up. The mark_delivered writes over FAILED_RETRYABLE silently.
        Pin current behavior: succeeds, delivered_at is set.
        """
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        row = await _seed_row(db, channel.id)
        await outbox.mark_failed(db, row, "transient", retryable=True)
        await db.commit()
        assert row.delivery_state == DeliveryState.FAILED_RETRYABLE.value

        await outbox.mark_delivered(db, row)
        await db.commit()

        assert row.delivery_state == DeliveryState.DELIVERED.value
        assert row.delivered_at is not None
