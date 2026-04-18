"""E.6 — outbox.enqueue idempotency on duplicate (channel_id, seq, target).

Seam class: multi-row sync (unique constraint)
Suspected drift: the enqueue docstring claims ``(channel_id, seq,
target_integration_id)`` is unique and that re-enqueue raises
``IntegrityError``. Migration 188 explicitly dropped that constraint:
the comment on line 19 of the migration reads *"Per-row-id uniqueness is
sufficient"*.

Actual behavior: no unique constraint exists. Re-enqueue of the same
tuple silently inserts a second row. A batch that contains a duplicate
target_integration_id against the same channel+seq commits all rows —
none are rolled back. Callers that relied on the docstring's
"IntegrityError on duplicate" for idempotency protection are not
getting it.

Pin the actual behavior so:
  (a) future hardening (adding the constraint back) has a regression
      surface, and
  (b) the misleading docstring is documented as a known lie.

For each test ask: *if this invariant silently drifted, would my
assertion fail?* Drift-pin tests are labelled in their docstrings.
"""
from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import DefaultClause
from sqlalchemy import text as sa_text

from tests.unit.test_outbox import _patch_pg_types_for_sqlite  # noqa: F401

from app.db.models import Base, Channel, Outbox
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.dispatch_target import NoneTarget
from app.domain.payloads import TurnEndedPayload
from app.services import outbox


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

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


async def _seed_channel(db: AsyncSession) -> Channel:
    channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
    db.add(channel)
    await db.commit()
    return channel


async def _count_outbox_rows(db: AsyncSession, channel_id: uuid.UUID) -> int:
    result = await db.execute(
        select(Outbox).where(Outbox.channel_id == channel_id)
    )
    return len(result.scalars().all())


# ---------------------------------------------------------------------------
# Normal enqueue path
# ---------------------------------------------------------------------------


class TestEnqueueNormalPath:
    @pytest.mark.asyncio
    async def test_enqueue_multiple_targets_creates_one_row_per_target(
        self, db: AsyncSession
    ):
        channel = await _seed_channel(db)
        event = _turn_ended_event(channel.id, seq=7)
        targets = [
            ("integration-a", NoneTarget()),
            ("integration-b", NoneTarget()),
            ("integration-c", NoneTarget()),
        ]

        rows = await outbox.enqueue(db, channel.id, event, targets)
        await db.commit()

        assert len(rows) == 3
        integration_ids = {r.target_integration_id for r in rows}
        assert integration_ids == {"integration-a", "integration-b", "integration-c"}
        assert all(r.seq == 7 for r in rows)
        assert all(r.channel_id == channel.id for r in rows)

    @pytest.mark.asyncio
    async def test_enqueue_empty_targets_returns_empty_list_with_no_db_writes(
        self, db: AsyncSession
    ):
        channel = await _seed_channel(db)
        event = _turn_ended_event(channel.id)

        rows = await outbox.enqueue(db, channel.id, event, [])
        await db.commit()

        assert rows == []
        assert await _count_outbox_rows(db, channel.id) == 0

    @pytest.mark.asyncio
    async def test_enqueue_single_target_row_has_correct_fields(
        self, db: AsyncSession
    ):
        channel = await _seed_channel(db)
        event = _turn_ended_event(channel.id, seq=42)

        rows = await outbox.enqueue(db, channel.id, event, [("my-integration", NoneTarget())])
        await db.commit()

        assert len(rows) == 1
        row = rows[0]
        assert row.channel_id == channel.id
        assert row.seq == 42
        assert row.target_integration_id == "my-integration"
        assert row.kind == ChannelEventKind.TURN_ENDED.value
        assert row.attempts == 0


# ---------------------------------------------------------------------------
# Drift-seam pins — no unique constraint → silent duplicates
# ---------------------------------------------------------------------------


class TestEnqueueIdempotencyDriftPins:
    @pytest.mark.asyncio
    async def test_drift_pin_reenqueue_same_tuple_silently_inserts_duplicate_not_integrity_error(
        self, db: AsyncSession
    ):
        """DRIFT PIN — docstring claims IntegrityError on duplicate (channel_id, seq, target_integration_id).

        Migration 188 explicitly omitted the unique constraint (the migration
        comment on lines 18-26 explains why: seq is assigned post-commit by
        the in-memory bus, making a pre-commit unique constraint unreliable).
        Actual behavior: re-enqueue of the same tuple silently inserts a second
        row. No IntegrityError. No rollback. Any caller treating IntegrityError
        as an idempotency guard is NOT getting that protection.

        Pin the actual (no-guard) behavior so adding the constraint later has
        a failing regression test to confirm it.
        """
        channel = await _seed_channel(db)
        event = _turn_ended_event(channel.id, seq=1)

        # First enqueue — one row.
        rows1 = await outbox.enqueue(db, channel.id, event, [("slack", NoneTarget())])
        await db.commit()
        assert len(rows1) == 1

        # Second enqueue of the exact same (channel_id=channel.id, seq=1, target="slack").
        # The docstring says IntegrityError. Actual: silent duplicate insert.
        rows2 = await outbox.enqueue(db, channel.id, event, [("slack", NoneTarget())])
        await db.commit()  # must not raise

        assert len(rows2) == 1
        # Two rows exist for the same tuple — no unique constraint enforced.
        total = await _count_outbox_rows(db, channel.id)
        assert total == 2, (
            "Expected 2 rows (no unique constraint → duplicate silently inserted). "
            "If this fails, the unique constraint has been added — update the docstring "
            "and invert this test."
        )

    @pytest.mark.asyncio
    async def test_drift_pin_batch_with_duplicate_target_id_all_rows_land_no_rollback(
        self, db: AsyncSession
    ):
        """DRIFT PIN — batch enqueue with a duplicate target_integration_id does not roll back.

        The docstring suggests that enqueuing a duplicate within a batch
        raises IntegrityError, rolling back the innocent sibling inserts.
        Actual behavior (no unique constraint): all rows land, including the
        duplicate target. The caller can end up with duplicate outbox rows
        for the same target, each of which the drainer will attempt to deliver.

        Pin the actual behavior: a batch of 3 targets where target-2 repeats
        the same integration_id as a prior row inserts all 3 rows without error.
        """
        channel = await _seed_channel(db)
        event = _turn_ended_event(channel.id, seq=5)

        # First enqueue: seed one row for "integration-dup".
        await outbox.enqueue(db, channel.id, event, [("integration-dup", NoneTarget())])
        await db.commit()

        # Batch of 3: target-2 duplicates "integration-dup" (already exists at same seq).
        targets = [
            ("integration-innocent-1", NoneTarget()),
            ("integration-dup", NoneTarget()),  # duplicate
            ("integration-innocent-2", NoneTarget()),
        ]
        rows = await outbox.enqueue(db, channel.id, event, targets)
        await db.commit()  # must not raise; no unique constraint to trip

        # All 3 rows from the batch were inserted.
        assert len(rows) == 3
        # Total: 1 (seeded) + 3 (batch) = 4.
        total = await _count_outbox_rows(db, channel.id)
        assert total == 4, (
            "Expected 4 rows: 1 seeded + 3 batch (duplicate target silently inserts). "
            "If this fails, a unique constraint has been added — invert this test."
        )
        # Both innocent inserts landed (they must NOT have been rolled back).
        result = await db.execute(
            select(Outbox).where(Outbox.target_integration_id == "integration-innocent-1")
        )
        assert result.scalars().first() is not None, "innocent-1 must have been inserted"
        result2 = await db.execute(
            select(Outbox).where(Outbox.target_integration_id == "integration-innocent-2")
        )
        assert result2.scalars().first() is not None, "innocent-2 must have been inserted"
