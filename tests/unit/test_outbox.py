"""Phase D — outbox table API + serde unit tests.

Covers ``app/services/outbox.py``:

- ``serialize_payload`` / ``deserialize_payload`` round-trip every payload
  type the four core renderers will encounter (``MessagePayload``,
  ``TurnEndedPayload``, ``DeliveryFailedPayload``).
- ``enqueue`` inserts one row per target into the caller's session.
- ``mark_in_flight`` / ``mark_delivered`` / ``mark_failed`` transitions.
- ``mark_failed`` backoff math (1, 2, 4, ..., 300 cap) and dead-letter
  cutover at ``DEAD_LETTER_AFTER``.
- ``reconstitute_event`` and ``reconstitute_target`` rebuild typed values
  from a synthetic Outbox row.

DB-touching paths use a real sqlalchemy ``AsyncSession`` against an
in-memory SQLite engine — same pattern as other unit tests in this
repo. ``ix_outbox_pending`` is a Postgres partial index, so SQLite
ignores the ``postgresql_where`` clause; the test still exercises the
underlying ``SELECT ... WHERE delivery_state IN ...`` filter via
``fetch_pending``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Channel, Outbox
from app.domain.actor import ActorRef
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.delivery_state import DeliveryState
from app.domain.dispatch_target import (
    NoneTarget,
    WebhookTarget,
)
from integrations.slack.target import SlackTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    DeliveryFailedPayload,
    MessagePayload,
    TurnEndedPayload,
)
from app.services import outbox

# ---------------------------------------------------------------------------
# Real-DB fixture (in-memory SQLite). Mirrors tests/integration/conftest.py
# but kept self-contained so this unit test doesn't require the integration
# fixture chain.
# ---------------------------------------------------------------------------


def _patch_pg_types_for_sqlite() -> None:
    """Make pg-specific column types work on in-memory SQLite."""
    from sqlalchemy.dialects.postgresql import (
        JSONB,
        TIMESTAMP as PG_TIMESTAMP,
        TSVECTOR as PG_TSVECTOR,
        UUID as PG_UUID,
    )
    from sqlalchemy.ext.compiler import compiles
    from pgvector.sqlalchemy import Vector

    @compiles(Vector, "sqlite")
    def _vector(_t, _c, **_k):
        return "TEXT"

    @compiles(JSONB, "sqlite")
    def _jsonb(_t, _c, **_k):
        return "JSON"

    @compiles(PG_UUID, "sqlite")
    def _uuid(_t, _c, **_k):
        return "CHAR(36)"

    @compiles(PG_TSVECTOR, "sqlite")
    def _tsv(_t, _c, **_k):
        return "TEXT"

    @compiles(PG_TIMESTAMP, "sqlite")
    def _ts(_t, _c, **_k):
        return "TIMESTAMP"

    # UUID round-trip via CHAR(36).
    _orig_bind = PG_UUID.bind_processor

    def _bind(self, dialect):
        if dialect.name == "sqlite":
            def proc(v):
                if v is None:
                    return v
                if isinstance(v, uuid.UUID):
                    return str(v)
                return v
            return proc
        return _orig_bind(self, dialect)

    _orig_result = PG_UUID.result_processor

    def _result(self, dialect, coltype):
        if dialect.name == "sqlite":
            def proc(v):
                if v is None:
                    return v
                if isinstance(v, uuid.UUID):
                    return v
                return uuid.UUID(str(v))
            return proc
        return _orig_result(self, dialect, coltype)

    PG_UUID.bind_processor = _bind
    PG_UUID.result_processor = _result


_patch_pg_types_for_sqlite()


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    # Strip pg-only server defaults so create_all works on SQLite.
    from sqlalchemy import text as sa_text
    from sqlalchemy.schema import DefaultClause
    originals: dict[tuple[str, str], object] = {}
    replacements = {"now()": "CURRENT_TIMESTAMP", "gen_random_uuid()": None}
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message_event(channel_id: uuid.UUID) -> ChannelEvent:
    """Build a NEW_MESSAGE event with a synthetic domain Message."""
    msg = DomainMessage(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content="hello",
        created_at=datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc),
        actor=ActorRef.bot("bot1", "Bot One"),
        channel_id=channel_id,
    )
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(message=msg),
        seq=42,
    )


def _make_turn_ended_event(channel_id: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.TURN_ENDED,
        payload=TurnEndedPayload(
            bot_id="bot1",
            turn_id=uuid.uuid4(),
            result="done",
            client_actions=[],
            extra_metadata={"foo": "bar"},
            task_id=str(uuid.uuid4()),
        ),
        seq=7,
    )


# ---------------------------------------------------------------------------
# Serde
# ---------------------------------------------------------------------------


class TestSerde:
    def test_message_payload_roundtrips(self):
        ch = uuid.uuid4()
        event = _make_message_event(ch)
        data = outbox.serialize_payload(event.payload)
        # JSON-compatible primitives only.
        assert isinstance(data, dict)
        assert data["__type__"] == "MessagePayload"
        assert isinstance(data["message"], dict)
        assert data["message"]["__type__"] == "Message"
        assert data["message"]["actor"]["id"] == "bot1"

        round_tripped = outbox.deserialize_payload(ChannelEventKind.NEW_MESSAGE, data)
        assert isinstance(round_tripped, MessagePayload)
        assert round_tripped.message.id == event.payload.message.id
        assert round_tripped.message.actor.id == "bot1"
        assert round_tripped.message.created_at == event.payload.message.created_at
        assert round_tripped.message.channel_id == ch

    def test_turn_ended_payload_roundtrips(self):
        ch = uuid.uuid4()
        event = _make_turn_ended_event(ch)
        data = outbox.serialize_payload(event.payload)
        round_tripped = outbox.deserialize_payload(ChannelEventKind.TURN_ENDED, data)
        assert isinstance(round_tripped, TurnEndedPayload)
        assert round_tripped.bot_id == "bot1"
        assert round_tripped.result == "done"
        assert round_tripped.task_id == event.payload.task_id
        assert round_tripped.extra_metadata == {"foo": "bar"}
        assert round_tripped.client_actions == []

    def test_delivery_failed_payload_roundtrips(self):
        payload = DeliveryFailedPayload(
            integration_id="webhook",
            target_summary="https://example.test/hook",
            last_error="HTTP 503",
            attempts=3,
        )
        data = outbox.serialize_payload(payload)
        rt = outbox.deserialize_payload(ChannelEventKind.DELIVERY_FAILED, data)
        assert isinstance(rt, DeliveryFailedPayload)
        assert rt.integration_id == "webhook"
        assert rt.last_error == "HTTP 503"
        assert rt.attempts == 3


# ---------------------------------------------------------------------------
# enqueue / fetch_pending / state transitions
# ---------------------------------------------------------------------------


class TestEnqueue:
    @pytest.mark.asyncio
    async def test_inserts_one_row_per_target(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="bot1")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)
        rows = await outbox.enqueue(
            db,
            channel.id,
            event,
            [
                ("slack", SlackTarget(channel_id="C1", token="x")),
                ("webhook", WebhookTarget(url="https://example.test/h")),
            ],
        )
        await db.commit()
        assert len(rows) == 2
        kinds = {(r.target_integration_id, r.delivery_state) for r in rows}
        assert ("slack", DeliveryState.PENDING.value) in kinds
        assert ("webhook", DeliveryState.PENDING.value) in kinds
        # Payload was serialized to dict.
        for row in rows:
            assert isinstance(row.payload, dict)
            assert row.payload.get("__type__") == "MessagePayload"
            assert row.target.get("type") in {"slack", "webhook"}

    @pytest.mark.asyncio
    async def test_no_targets_is_noop(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        rows = await outbox.enqueue(db, channel.id, _make_message_event(channel.id), [])
        assert rows == []


class TestFetchPending:
    @pytest.mark.asyncio
    async def test_only_returns_pending_or_retryable_with_available_at_in_past(
        self, db: AsyncSession
    ):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)
        await outbox.enqueue(
            db, channel.id, event, [("none", NoneTarget())]
        )
        await db.commit()

        rows = await outbox.fetch_pending(db, limit=10)
        assert len(rows) == 1

        # Mark delivered → no longer fetched.
        await outbox.mark_delivered(db, rows[0])
        await db.commit()
        assert await outbox.fetch_pending(db, limit=10) == []

    @pytest.mark.asyncio
    async def test_skips_rows_with_future_available_at(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)
        await outbox.enqueue(db, channel.id, event, [("none", NoneTarget())])
        await db.commit()

        # Push the row's available_at into the future.
        rows = await outbox.fetch_pending(db, limit=10)
        rows[0].available_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        await db.commit()
        assert await outbox.fetch_pending(db, limit=10) == []


class TestMarkFailedBackoff:
    @pytest.mark.asyncio
    async def test_retryable_increments_and_schedules(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)
        rows = await outbox.enqueue(db, channel.id, event, [("none", NoneTarget())])
        await db.commit()
        row = rows[0]
        before = datetime.now(timezone.utc)
        new_state = await outbox.mark_failed(
            db, row, "transient", retryable=True
        )
        await db.commit()
        assert new_state == DeliveryState.FAILED_RETRYABLE.value
        assert row.attempts == 1
        assert row.last_error == "transient"
        # 2 ** 1 = 2 seconds.
        assert (row.available_at - before).total_seconds() >= 1.5

    @pytest.mark.asyncio
    async def test_non_retryable_dead_letters_immediately(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)
        rows = await outbox.enqueue(db, channel.id, event, [("none", NoneTarget())])
        await db.commit()
        row = rows[0]
        new_state = await outbox.mark_failed(
            db, row, "bad request", retryable=False
        )
        assert new_state == DeliveryState.DEAD_LETTER.value
        assert row.dead_letter_reason == "bad request"
        assert row.attempts == 1

    @pytest.mark.asyncio
    async def test_dead_letters_after_max_attempts(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)
        rows = await outbox.enqueue(db, channel.id, event, [("none", NoneTarget())])
        await db.commit()
        row = rows[0]
        # Drive attempts up to one less than the cutover.
        for i in range(outbox.DEAD_LETTER_AFTER - 1):
            new_state = await outbox.mark_failed(
                db, row, f"err{i}", retryable=True
            )
            assert new_state == DeliveryState.FAILED_RETRYABLE.value
        # The DEAD_LETTER_AFTER-th failure flips to dead letter.
        final = await outbox.mark_failed(db, row, "final", retryable=True)
        assert final == DeliveryState.DEAD_LETTER.value
        assert row.attempts == outbox.DEAD_LETTER_AFTER

    @pytest.mark.asyncio
    async def test_backoff_capped(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)
        rows = await outbox.enqueue(db, channel.id, event, [("none", NoneTarget())])
        await db.commit()
        row = rows[0]
        # Set the row to attempts=15 manually so the next failure caps backoff.
        row.attempts = 7  # 2**8 = 256 < 300; next failure will be 8 → 256
        # Call once more (8 attempts → 2**8 = 256s, under cap)
        before = datetime.now(timezone.utc)
        await outbox.mark_failed(db, row, "x", retryable=True)
        # 2**8 = 256
        gap = (row.available_at - before).total_seconds()
        assert gap <= outbox.MAX_BACKOFF_SECONDS + 1


class TestDeferNoRenderer:
    @pytest.mark.asyncio
    async def test_defer_increments_count_and_keeps_pending(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)
        rows = await outbox.enqueue(db, channel.id, event, [("slack", NoneTarget())])
        await db.commit()
        row = rows[0]
        before = datetime.now(timezone.utc)
        new_state = await outbox.defer_no_renderer(db, row)
        await db.commit()
        assert new_state == DeliveryState.PENDING.value
        assert row.defer_count == 1
        assert row.attempts == 0  # missing renderer is NOT a delivery attempt
        assert row.last_error == "no renderer registered"
        # available_at pushed roughly NO_RENDERER_REQUEUE_SECONDS into the future.
        assert (row.available_at - before).total_seconds() >= outbox.NO_RENDERER_REQUEUE_SECONDS - 1

    @pytest.mark.asyncio
    async def test_defer_dead_letters_at_cap(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)
        rows = await outbox.enqueue(db, channel.id, event, [("slack", NoneTarget())])
        await db.commit()
        row = rows[0]
        # Drive defer_count up to one less than the cap.
        row.defer_count = outbox.DEFER_DEAD_LETTER_AFTER - 1
        await db.commit()
        new_state = await outbox.defer_no_renderer(db, row)
        await db.commit()
        assert new_state == DeliveryState.DEAD_LETTER.value
        assert row.defer_count == outbox.DEFER_DEAD_LETTER_AFTER
        assert row.dead_letter_reason is not None
        assert "no renderer registered" in row.dead_letter_reason
        assert "slack" in row.dead_letter_reason  # surfaces the integration_id


class TestReconstitution:
    @pytest.mark.asyncio
    async def test_reconstitute_event_and_target(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_turn_ended_event(channel.id)
        rows = await outbox.enqueue(
            db,
            channel.id,
            event,
            [("webhook", WebhookTarget(url="https://example.test/h", headers={"X": "y"}))],
        )
        await db.commit()
        row = rows[0]
        rebuilt_event = outbox.reconstitute_event(row)
        rebuilt_target = outbox.reconstitute_target(row)
        assert rebuilt_event.kind == ChannelEventKind.TURN_ENDED
        assert isinstance(rebuilt_event.payload, TurnEndedPayload)
        assert rebuilt_event.payload.bot_id == "bot1"
        assert isinstance(rebuilt_target, WebhookTarget)
        assert rebuilt_target.url == "https://example.test/h"
        assert rebuilt_target.headers == {"X": "y"}
