"""Phase D — outbox drainer unit tests.

Covers ``app/services/outbox_drainer.py:_deliver_one`` end-to-end with a
mocked renderer registry. The drainer's outer loop is exercised
indirectly via ``_claim_batch`` + ``_deliver_one`` since the
``while True`` loop is just a thin wrapper.

Each test patches:

- ``app.integrations.renderer_registry.get`` to return a fake renderer.
- ``app.services.channel_events.publish_typed`` to capture
  ``DELIVERY_FAILED`` events on dead-letter transitions.

Real DB sessions are used (in-memory SQLite) because the drainer
operates on real ``Outbox`` rows; mocking the SQLAlchemy session would
hide more bugs than it would simplify.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

# Reuse the SQLite type-compilation patches from test_outbox.
from tests.unit.test_outbox import _patch_pg_types_for_sqlite  # noqa: F401  patch installed

from app.db.models import Base, Channel, Outbox
from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.delivery_state import DeliveryState
from app.domain.dispatch_target import NoneTarget, WebhookTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    DeliveryFailedPayload,
    MessagePayload,
    TurnEndedPayload,
)
from app.integrations.renderer import DeliveryReceipt
from app.services import outbox, outbox_drainer


@pytest_asyncio.fixture
async def engine_and_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
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
    yield engine, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def patched_engine(engine_and_factory):
    """Replace ``app.db.engine.async_session`` with the test factory."""
    engine, factory = engine_and_factory
    with patch("app.db.engine.async_session", factory), \
         patch("app.services.outbox_drainer.async_session", factory), \
         patch("app.services.dispatch_resolution.async_session", factory):
        yield engine, factory


async def _seed_row(
    factory,
    *,
    integration_id: str = "webhook",
    target=None,
    kind: ChannelEventKind = ChannelEventKind.TURN_ENDED,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a Channel + a single Outbox row, return (channel_id, row_id)."""
    target = target or WebhookTarget(url="https://example.test/h")
    async with factory() as db:
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        if kind == ChannelEventKind.NEW_MESSAGE:
            payload = MessagePayload(
                message=DomainMessage(
                    id=uuid.uuid4(),
                    session_id=uuid.uuid4(),
                    role="assistant",
                    content="hi",
                    created_at=datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc),
                    actor=ActorRef.bot("bot1"),
                    channel_id=channel.id,
                ),
            )
        else:
            payload = TurnEndedPayload(
                bot_id="bot1",
                turn_id=uuid.uuid4(),
                result="done",
                task_id=str(uuid.uuid4()),
            )
        event = ChannelEvent(
            channel_id=channel.id,
            kind=kind,
            payload=payload,
            seq=1,
        )
        rows = await outbox.enqueue(
            db, channel.id, event, [(integration_id, target)]
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

    def __init__(self):
        self.calls = 0

    async def render(self, event, target):
        self.calls += 1
        return DeliveryReceipt.ok()

    async def handle_outbound_action(self, action, target):
        return DeliveryReceipt.ok()

    async def delete_attachment(self, _meta, _target):
        return False


class _RetryableFailRenderer(_OkRenderer):
    async def render(self, event, target):
        self.calls += 1
        return DeliveryReceipt.failed("HTTP 503", retryable=True)


class _PermanentFailRenderer(_OkRenderer):
    async def render(self, event, target):
        self.calls += 1
        return DeliveryReceipt.failed("HTTP 400", retryable=False)


class _NoCapsRenderer:
    """Renderer that declares zero capabilities — every event should be capability-skipped."""
    integration_id = "webhook"
    capabilities = frozenset()

    def __init__(self):
        self.calls = 0

    async def render(self, event, target):
        self.calls += 1
        return DeliveryReceipt.ok()

    async def handle_outbound_action(self, action, target):
        return DeliveryReceipt.ok()

    async def delete_attachment(self, _meta, _target):
        return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeliverOneHappyPath:
    @pytest.mark.asyncio
    async def test_renders_and_marks_delivered(self, patched_engine):
        _engine, factory = patched_engine
        channel_id, row_id = await _seed_row(factory)

        renderer = _OkRenderer()
        with patch("app.integrations.renderer_registry.get", return_value=renderer):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DELIVERED.value
        assert final.delivered_at is not None
        assert renderer.calls == 1


class TestDeliverOneRetryable:
    @pytest.mark.asyncio
    async def test_failed_retryable_increments_attempts(self, patched_engine):
        _engine, factory = patched_engine
        channel_id, row_id = await _seed_row(factory)
        renderer = _RetryableFailRenderer()
        with patch("app.integrations.renderer_registry.get", return_value=renderer):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)
        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.FAILED_RETRYABLE.value
        assert final.attempts == 1
        assert "503" in (final.last_error or "")


class TestDeliverOnePermanent:
    @pytest.mark.asyncio
    async def test_non_retryable_dead_letters_immediately(self, patched_engine):
        _engine, factory = patched_engine
        channel_id, row_id = await _seed_row(factory)
        renderer = _PermanentFailRenderer()

        published: list[ChannelEvent] = []

        def _capture(_ch, event):
            published.append(event)
            return 1

        with patch("app.integrations.renderer_registry.get", return_value=renderer), \
             patch("app.services.channel_events.publish_typed", side_effect=_capture):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DEAD_LETTER.value
        assert final.dead_letter_reason == "HTTP 400"
        # DELIVERY_FAILED published.
        assert any(
            ev.kind == ChannelEventKind.DELIVERY_FAILED for ev in published
        )
        df = next(
            ev for ev in published if ev.kind == ChannelEventKind.DELIVERY_FAILED
        )
        assert isinstance(df.payload, DeliveryFailedPayload)
        assert df.payload.integration_id == "webhook"
        assert df.payload.last_error == "HTTP 400"
        assert df.payload.attempts == 1


class TestDeliverOneCapabilitySkip:
    @pytest.mark.asyncio
    async def test_skips_event_without_required_capability(self, patched_engine):
        """A renderer that declares no caps should mark TURN_ENDED rows
        delivered without invoking ``render()`` (TEXT is required for
        TURN_ENDED per the channel_events.required_capabilities table)."""
        _engine, factory = patched_engine
        channel_id, row_id = await _seed_row(factory)
        renderer = _NoCapsRenderer()
        with patch("app.integrations.renderer_registry.get", return_value=renderer):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)
        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DELIVERED.value
        assert renderer.calls == 0


class TestDeliverOneNoRenderer:
    @pytest.mark.asyncio
    async def test_missing_renderer_defers_without_counting_attempt(self, patched_engine):
        """When no renderer is registered for the target, the row goes back
        to PENDING with a delayed available_at and ``attempts`` is NOT
        incremented. The renderer may register later (e.g. SlackRenderer
        in Phase F) and delivery resumes. This is the build-up window
        behavior — never dead-letter for missing renderers."""
        _engine, factory = patched_engine
        channel_id, row_id = await _seed_row(factory)
        with patch("app.integrations.renderer_registry.get", return_value=None):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)
        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.PENDING.value
        assert final.attempts == 0
        assert "no renderer registered" in (final.last_error or "")
        # available_at should be in the future (deferred). SQLite drops the
        # tzinfo on round-trip, so coerce both sides to naive UTC for the
        # comparison.
        from datetime import datetime, timezone
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        avail = final.available_at
        if avail.tzinfo is not None:
            avail = avail.astimezone(timezone.utc).replace(tzinfo=None)
        assert avail > now_naive


class TestClaimBatch:
    @pytest.mark.asyncio
    async def test_marks_rows_in_flight_and_releases_lock(self, patched_engine):
        _engine, factory = patched_engine
        await _seed_row(factory)
        await _seed_row(factory)
        rows = await outbox_drainer._claim_batch()
        assert len(rows) == 2
        for row in rows:
            assert row.delivery_state == DeliveryState.IN_FLIGHT.value
        # A second claim should return zero — both rows are in_flight, not pending.
        rows2 = await outbox_drainer._claim_batch()
        assert rows2 == []


def _cancel_after(n_calls: int):
    """Build an ``asyncio.sleep`` replacement that cancels the worker on the Nth call.

    The drainer's outer loop hits ``await asyncio.sleep(...)`` once per
    iteration; raising ``CancelledError`` from there is the canonical way
    to stop the worker (mirrors what ``task.cancel()`` does in production).
    Returns immediately on earlier calls so the loop continues without any
    real wall-clock delay. The ``side_effect`` patches ``asyncio.sleep``
    process-wide, so this replacement must not recurse into ``asyncio.sleep``.
    """
    state = {"calls": 0}

    async def _sleep(_seconds: float) -> None:
        state["calls"] += 1
        if state["calls"] >= n_calls:
            raise asyncio.CancelledError

    return _sleep, state


class TestDrainerWorkerLoop:
    @pytest.mark.asyncio
    async def test_when_pending_rows_present_then_drains_and_marks_delivered(self, patched_engine):
        _engine, factory = patched_engine
        _ch1, row1_id = await _seed_row(factory)
        _ch2, row2_id = await _seed_row(factory)
        renderer = _OkRenderer()
        sleep_fn, state = _cancel_after(2)

        with patch("app.integrations.renderer_registry.get", return_value=renderer), \
             patch("app.services.outbox_drainer.asyncio.sleep", side_effect=sleep_fn):
            with pytest.raises(asyncio.CancelledError):
                await outbox_drainer.outbox_drainer_worker()

        assert renderer.calls == 2
        final1 = await _get_row(factory, row1_id)
        final2 = await _get_row(factory, row2_id)
        assert final1.delivery_state == DeliveryState.DELIVERED.value
        assert final2.delivery_state == DeliveryState.DELIVERED.value
        # First sleep is the BUSY sleep (rows present); second sleep cancels.
        assert state["calls"] == 2

    @pytest.mark.asyncio
    async def test_when_per_row_delivery_raises_then_loop_continues_for_other_rows(self, patched_engine):
        _engine, factory = patched_engine
        _, row1_id = await _seed_row(factory)
        _, row2_id = await _seed_row(factory)
        sleep_fn, _state = _cancel_after(2)

        # Capture the original to call past the patch — we wrap _deliver_one so
        # the FIRST invocation raises (simulating an unexpected drainer-side bug)
        # and the SECOND invocation runs the real delivery path so we can verify
        # the loop continued after the failure.
        original_deliver_one = outbox_drainer._deliver_one
        deliver_calls: list[uuid.UUID] = []
        renderer = _OkRenderer()

        async def _deliver(row: Outbox) -> None:
            deliver_calls.append(row.id)
            if len(deliver_calls) == 1:
                raise RuntimeError("renderer blew up")
            await original_deliver_one(row)

        with patch("app.integrations.renderer_registry.get", return_value=renderer), \
             patch("app.services.outbox_drainer._deliver_one", side_effect=_deliver), \
             patch("app.services.outbox_drainer.asyncio.sleep", side_effect=sleep_fn):
            with pytest.raises(asyncio.CancelledError):
                await outbox_drainer.outbox_drainer_worker()

        assert len(deliver_calls) == 2
        # The first row is still IN_FLIGHT — the per-row exception was swallowed
        # and never reached mark_failed; this is the documented "isolation"
        # contract (loop keeps running) AND the reason ``reset_stale_in_flight``
        # exists at startup.
        first = await _get_row(factory, deliver_calls[0])
        second = await _get_row(factory, deliver_calls[1])
        assert first.delivery_state == DeliveryState.IN_FLIGHT.value
        assert second.delivery_state == DeliveryState.DELIVERED.value

    @pytest.mark.asyncio
    async def test_when_no_pending_rows_then_loop_idles_and_exits_on_cancel(self, patched_engine):
        _engine, _factory = patched_engine
        sleep_fn, state = _cancel_after(1)

        with patch("app.services.outbox_drainer.asyncio.sleep", side_effect=sleep_fn):
            with pytest.raises(asyncio.CancelledError):
                await outbox_drainer.outbox_drainer_worker()

        # First (and only) sleep was the IDLE branch — cancelled before second batch.
        assert state["calls"] == 1

    @pytest.mark.asyncio
    async def test_when_claim_batch_raises_then_loop_logs_and_keeps_running(self, patched_engine):
        _engine, _factory = patched_engine
        sleep_fn, state = _cancel_after(2)
        claim_calls = {"n": 0}

        async def _claim() -> list[Outbox]:
            claim_calls["n"] += 1
            if claim_calls["n"] == 1:
                raise RuntimeError("transient db hiccup")
            return []

        with patch("app.services.outbox_drainer._claim_batch", side_effect=_claim), \
             patch("app.services.outbox_drainer.asyncio.sleep", side_effect=sleep_fn):
            with pytest.raises(asyncio.CancelledError):
                await outbox_drainer.outbox_drainer_worker()

        # First iteration raised → logged + slept; second iteration ran, then cancelled.
        assert claim_calls["n"] == 2
        assert state["calls"] == 2
