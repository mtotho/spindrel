"""F.2 — outbox_drainer crash between claim and deliver strands IN_FLIGHT rows.

Seam class: multi-row sync + partial-commit
Suspected drift: ``_claim_batch`` flips N rows to IN_FLIGHT in one commit,
then returns detached objects. If the drainer worker is cancelled or crashes
before ``_deliver_one`` runs for row K, rows K..N are stranded in IN_FLIGHT.
``fetch_pending`` only selects PENDING / FAILED_RETRYABLE — so stranded rows
are invisible to the running drainer. The only recovery path is
``reset_stale_in_flight``, called once at startup in ``app/main.py``.

Pins:
- Crash gap: all claimed rows remain IN_FLIGHT, not auto-recovered by the
  running drainer (startup sweeper ``reset_stale_in_flight`` is the sole fix)
- ``fetch_pending`` contract: IN_FLIGHT rows are invisible to new drainer
  iterations (no self-healing path mid-run)
- no-renderer defer path: ``defer_count`` increments; ``attempts`` stays 0;
  at ``DEFER_DEAD_LETTER_AFTER`` the row transitions to ``DEAD_LETTER`` and
  DELIVERY_FAILED is published
- renderer exception path: ``render()`` raising is treated as retryable
  failure (same as returning a failed receipt, different error-message prefix)

Loose Ends: stranded-IN_FLIGHT gap is already mitigated by
``reset_stale_in_flight`` at startup (see ``app/services/outbox.py:326`` and
``app/main.py:791``). A running drainer cannot self-heal mid-batch without a
restart — document as an accepted constraint, not an urgent hardening gap.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.unit.test_outbox import _patch_pg_types_for_sqlite  # noqa: F401

from app.db.models import Base, Channel, Outbox
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.delivery_state import DeliveryState
from app.domain.dispatch_target import WebhookTarget
from app.domain.payloads import TurnEndedPayload
from app.integrations.renderer import DeliveryReceipt
from app.services import outbox, outbox_drainer
from app.services.outbox import DEFER_DEAD_LETTER_AFTER


# ---------------------------------------------------------------------------
# Fixtures (mirrors test_outbox_drainer.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine_and_factory():
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
    yield engine, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def patched_engine(engine_and_factory):
    """Replace ``app.db.engine.async_session`` with the test factory."""
    engine, factory = engine_and_factory
    with (
        patch("app.db.engine.async_session", factory),
        patch("app.services.outbox_drainer.async_session", factory),
        patch("app.services.dispatch_resolution.async_session", factory),
    ):
        yield engine, factory


async def _seed_row(factory, *, integration_id: str = "webhook") -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a Channel + one PENDING Outbox row; return (channel_id, row_id)."""
    async with factory() as db:
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = ChannelEvent(
            channel_id=channel.id,
            kind=ChannelEventKind.TURN_ENDED,
            payload=TurnEndedPayload(
                bot_id="bot1",
                turn_id=uuid.uuid4(),
                result="done",
                task_id=str(uuid.uuid4()),
            ),
            seq=1,
        )
        rows = await outbox.enqueue(
            db, channel.id, event, [(integration_id, WebhookTarget(url="https://example.test/h"))]
        )
        await db.commit()
        return channel.id, rows[0].id


async def _get_row(factory, row_id: uuid.UUID) -> Outbox:
    async with factory() as db:
        return await db.get(Outbox, row_id)


# ---------------------------------------------------------------------------
# Fake renderers
# ---------------------------------------------------------------------------


class _OkRenderer:
    integration_id = "webhook"
    capabilities = frozenset({Capability.TEXT})

    async def render(self, event, target):
        return DeliveryReceipt.ok()

    async def handle_outbound_action(self, action, target):
        return DeliveryReceipt.ok()

    async def delete_attachment(self, _meta, _target):
        return False


class _RaisingRenderer(_OkRenderer):
    """Renderer whose ``render()`` raises to exercise the exception-catch path."""

    async def render(self, event, target):
        raise RuntimeError("simulated renderer crash")


# ---------------------------------------------------------------------------
# Tests: _claim_batch commit + crash-gap pins
# ---------------------------------------------------------------------------


class TestClaimBatchCrashGap:
    @pytest.mark.asyncio
    async def test_rows_committed_as_in_flight_before_return(self, patched_engine):
        """_claim_batch commits IN_FLIGHT state to the DB before returning the list.

        Confirms the subsequent per-row sessions can re-fetch by PK because
        the state is durably on disk, not just in the Python objects.
        """
        _engine, factory = patched_engine
        _, row1_id = await _seed_row(factory)
        _, row2_id = await _seed_row(factory)
        _, row3_id = await _seed_row(factory)

        rows = await outbox_drainer._claim_batch()

        assert len(rows) == 3
        for row in rows:
            assert row.delivery_state == DeliveryState.IN_FLIGHT.value

        # Fresh-session read confirms the commit landed on disk.
        for row_id in (row1_id, row2_id, row3_id):
            db_row = await _get_row(factory, row_id)
            assert db_row.delivery_state == DeliveryState.IN_FLIGHT.value

    @pytest.mark.asyncio
    async def test_crash_gap_all_rows_stranded_in_flight(self, patched_engine):
        """DRIFT PIN — crash between _claim_batch and first _deliver_one strands all rows.

        After _claim_batch commits, if the process crashes before any
        _deliver_one invocation, all N rows stay IN_FLIGHT permanently.
        The running drainer has no self-healing path — only
        ``reset_stale_in_flight`` called at next startup recovers them.
        """
        _engine, factory = patched_engine
        _, row1_id = await _seed_row(factory)
        _, row2_id = await _seed_row(factory)
        _, row3_id = await _seed_row(factory)

        # Simulate process crash: claim the batch, call no _deliver_one.
        rows = await outbox_drainer._claim_batch()
        assert len(rows) == 3

        # All 3 rows are stranded IN_FLIGHT with no running-drainer recovery.
        for row_id in (row1_id, row2_id, row3_id):
            db_row = await _get_row(factory, row_id)
            assert db_row.delivery_state == DeliveryState.IN_FLIGHT.value, (
                f"Expected IN_FLIGHT (crash gap), got {db_row.delivery_state!r}"
            )


# ---------------------------------------------------------------------------
# Tests: fetch_pending excludes IN_FLIGHT (no running-drainer recovery path)
# ---------------------------------------------------------------------------


class TestFetchPendingExcludesInFlight:
    @pytest.mark.asyncio
    async def test_in_flight_rows_invisible_to_fetch_pending(self, patched_engine):
        """DRIFT PIN — fetch_pending only selects PENDING / FAILED_RETRYABLE rows.

        IN_FLIGHT rows are invisible to a new drainer iteration, pinning that
        the running drainer has no self-healing path for crash-stranded rows.
        ``reset_stale_in_flight`` (called once at startup) is the sole recovery.
        """
        _engine, factory = patched_engine
        await _seed_row(factory)

        # Claim the batch — row is now IN_FLIGHT in DB.
        claimed = await outbox_drainer._claim_batch()
        assert len(claimed) == 1
        assert claimed[0].delivery_state == DeliveryState.IN_FLIGHT.value

        # A fresh fetch_pending sees nothing — no recovery in the running drainer.
        async with factory() as db:
            pending = await outbox.fetch_pending(db)

        assert pending == [], (
            "IN_FLIGHT rows must not appear in fetch_pending — "
            "they are only recovered by reset_stale_in_flight at startup"
        )


# ---------------------------------------------------------------------------
# Tests: no-renderer defer path (defer_count vs attempts + dead-letter)
# ---------------------------------------------------------------------------


class TestNoRendererDeferPath:
    @pytest.mark.asyncio
    async def test_defer_increments_defer_count_not_attempts(self, patched_engine):
        """No renderer → defer_count increments; attempts stays 0.

        A missing renderer is a configuration gap, not a delivery failure.
        The retry budget (attempts) is preserved for when the renderer
        eventually registers.
        """
        _engine, factory = patched_engine
        _, row_id = await _seed_row(factory)

        with patch("app.integrations.renderer_registry.get", return_value=None):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.defer_count == 1
        assert final.attempts == 0
        assert final.delivery_state == DeliveryState.PENDING.value

    @pytest.mark.asyncio
    async def test_dead_letters_at_defer_threshold(self, patched_engine):
        """After DEFER_DEAD_LETTER_AFTER defers, row transitions to DEAD_LETTER.

        At the threshold the outbox gives up waiting for the renderer and
        publishes a DELIVERY_FAILED event. ``attempts`` remains 0 throughout
        because the defer path never increments it.
        """
        _engine, factory = patched_engine
        _, row_id = await _seed_row(factory)

        # Pre-advance defer_count to one below the threshold.
        async with factory() as db:
            await db.execute(
                update(Outbox)
                .where(Outbox.id == row_id)
                .values(defer_count=DEFER_DEAD_LETTER_AFTER - 1)
            )
            await db.commit()

        published: list = []

        def _capture(_ch, event):
            published.append(event)
            return 1

        with (
            patch("app.integrations.renderer_registry.get", return_value=None),
            patch("app.services.channel_events.publish_typed", side_effect=_capture),
        ):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DEAD_LETTER.value
        assert final.defer_count == DEFER_DEAD_LETTER_AFTER
        assert final.attempts == 0  # defer path never increments attempts

        # DELIVERY_FAILED published to bus on the dead-letter transition.
        assert any(e.kind == ChannelEventKind.DELIVERY_FAILED for e in published)


# ---------------------------------------------------------------------------
# Tests: renderer exception path
# ---------------------------------------------------------------------------


class TestRendererExceptionPath:
    @pytest.mark.asyncio
    async def test_renderer_raises_transitions_to_failed_retryable(self, patched_engine):
        """renderer.render() raising is treated as a retryable failure.

        Contrasts with renderer returning ``DeliveryReceipt.failed(retryable=True)``
        (the receipt path). The exception path in ``_deliver_one`` wraps the
        error with a "renderer raised: " prefix and marks FAILED_RETRYABLE with
        ``attempts`` incremented and ``available_at`` pushed into the future for
        exponential backoff.
        """
        _engine, factory = patched_engine
        _, row_id = await _seed_row(factory)

        with patch("app.integrations.renderer_registry.get", return_value=_RaisingRenderer()):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.FAILED_RETRYABLE.value
        assert final.attempts == 1
        assert "renderer raised" in (final.last_error or "")

        # available_at is pushed into the future for exponential backoff.
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        avail = final.available_at
        if avail.tzinfo is not None:
            avail = avail.astimezone(timezone.utc).replace(tzinfo=None)
        assert avail > now_naive
