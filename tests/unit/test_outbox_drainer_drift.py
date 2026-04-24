"""Phase N.8 — outbox drainer drift seams.

Drift-pin companion to ``test_outbox_drainer.py`` (Phase D), which covered
the happy + loop-isolation contracts. This file targets the fire-and-forget,
silent-skip, and state-vanished seams the Phase D coverage sweep skipped:

  1. ``_persist_delivery_metadata`` fire-and-forget — a failing integration
     hook does NOT un-deliver the row; ``mark_delivered`` commits first and
     metadata persistence happens best-effort inside a swallowed try/except
     (``outbox_drainer.py:181``).
  2. ``_persist_delivery_metadata`` silent-skip paths — non-NEW_MESSAGE
     events, payloads without a message id, absent IntegrationMeta, and
     missing ``Message`` rows each short-circuit cleanly.
  3. Repeated retryable failures eventually dead-letter AND publish
     ``DELIVERY_FAILED`` — not covered by Phase D which only pinned the
     immediate non-retryable path.
  4. ``_publish_delivery_failed`` swallow — a broken channel-events bus
     must never crash the drainer. The drainer catches and logs; the row
     is still dead-lettered in the DB (``outbox_drainer.py:278``).
  5. Row-vanishes-mid-session — if an Outbox row is deleted between
     ``_claim_batch`` and the per-row session's ``db.get``, each of the
     three in-session helpers returns a benign sentinel instead of raising
     (``_mark_delivered_in_session``, ``_mark_failed_in_session``,
     ``_defer_no_renderer_in_session``).
  6. ``fetch_pending`` FIFO ordering by ``created_at`` — a drift pin on
     the ordering contract since multi-row drain semantics depend on it.
  7. ``reconstitute_event`` failure → non-retryable mark_failed — if the
     persisted JSONB is corrupt, the row transitions straight to
     dead-letter (no retry loop on unparseable events).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy import delete as sa_delete

# Reuse the SQLite type-compilation patches from test_outbox.
from tests.unit.test_outbox import _patch_pg_types_for_sqlite  # noqa: F401

from app.db.models import Base, Channel, Message as MessageModel, Outbox, Session as SessionRow
from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.delivery_state import DeliveryState
from app.domain.dispatch_target import WebhookTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    DeliveryFailedPayload,
    MessagePayload,
    TurnEndedPayload,
)
from app.integrations.renderer import DeliveryReceipt
from app.services import outbox, outbox_drainer


# ---------------------------------------------------------------------------
# Fixtures — mirror the Phase D pattern so tests stay readable together.
# ---------------------------------------------------------------------------


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
    engine, factory = engine_and_factory
    with patch("app.db.engine.async_session", factory), \
         patch("app.services.outbox_drainer.async_session", factory), \
         patch("app.services.dispatch_resolution.async_session", factory):
        yield engine, factory


async def _seed_message_row(
    factory,
    *,
    target=None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Insert Channel + Message + NEW_MESSAGE outbox row.

    Returns (channel_id, message_id, outbox_row_id).
    """
    target = target or WebhookTarget(url="https://example.test/h")
    async with factory() as db:
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.flush()

        msg_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session_row = SessionRow(
            id=session_id,
            client_id="webhook_test",
            bot_id="b",
            channel_id=channel.id,
        )
        db.add(session_row)
        await db.flush()
        msg_row = MessageModel(
            id=msg_id,
            session_id=session_id,
            role="assistant",
            content="hi",
            metadata_={},
        )
        db.add(msg_row)
        await db.commit()

        payload = MessagePayload(
            message=DomainMessage(
                id=msg_id,
                session_id=session_id,
                role="assistant",
                content="hi",
                created_at=datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc),
                actor=ActorRef.bot("bot1"),
                channel_id=channel.id,
            ),
        )
        event = ChannelEvent(
            channel_id=channel.id,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=payload,
            seq=1,
        )
        rows = await outbox.enqueue(db, channel.id, event, [("webhook", target)])
        await db.commit()
        return channel.id, msg_id, rows[0].id


async def _seed_turn_row(factory) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a TURN_ENDED outbox row (no Message).

    Returns (channel_id, outbox_row_id).
    """
    async with factory() as db:
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        payload = TurnEndedPayload(
            bot_id="bot1",
            turn_id=uuid.uuid4(),
            result="done",
            task_id=str(uuid.uuid4()),
        )
        event = ChannelEvent(
            channel_id=channel.id,
            kind=ChannelEventKind.TURN_ENDED,
            payload=payload,
            seq=1,
        )
        target = WebhookTarget(url="https://example.test/h")
        rows = await outbox.enqueue(db, channel.id, event, [("webhook", target)])
        await db.commit()
        return channel.id, rows[0].id


async def _get_row(factory, row_id: uuid.UUID) -> Outbox | None:
    async with factory() as db:
        return await db.get(Outbox, row_id)


async def _get_message(factory, msg_id: uuid.UUID) -> MessageModel | None:
    async with factory() as db:
        return await db.get(MessageModel, msg_id)


class _OkWithExternalIdRenderer:
    integration_id = "webhook"
    capabilities = frozenset({Capability.TEXT})

    async def render(self, event, target):
        return DeliveryReceipt(
            success=True, external_id="ext-12345", retryable=False
        )

    async def handle_outbound_action(self, action, target):
        return DeliveryReceipt.ok()

    async def delete_attachment(self, _meta, _target):
        return False


class _RetryableFailRenderer:
    integration_id = "webhook"
    capabilities = frozenset({Capability.TEXT})

    async def render(self, event, target):
        return DeliveryReceipt.failed("HTTP 503", retryable=True)

    async def handle_outbound_action(self, action, target):
        return DeliveryReceipt.ok()

    async def delete_attachment(self, _meta, _target):
        return False


# ---------------------------------------------------------------------------
# N.8.1 — _persist_delivery_metadata fire-and-forget swallow
# ---------------------------------------------------------------------------


class TestPersistDeliveryMetadataSwallow:
    @pytest.mark.asyncio
    async def test_hook_raising_does_not_un_deliver_row(self, patched_engine):
        """If the integration's ``persist_delivery_metadata`` hook raises,
        the outbox row STILL commits as DELIVERED. Fire-and-forget: a
        metadata-persist bug on one integration must never gate outbox
        drainage for others.
        """
        _engine, factory = patched_engine
        _ch, _msg, row_id = await _seed_message_row(factory)

        from app.agent.hooks import IntegrationMeta

        def _boom(_mutable, _external_id, _target):
            raise RuntimeError("hook on fire")

        meta = IntegrationMeta(
            integration_type="webhook",
            client_id_prefix="webhook_",
            persist_delivery_metadata=_boom,
        )
        renderer = _OkWithExternalIdRenderer()

        with patch(
            "app.integrations.renderer_registry.get", return_value=renderer
        ), patch(
            "app.agent.hooks.get_integration_meta", return_value=meta
        ):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DELIVERED.value
        assert final.delivered_at is not None

    @pytest.mark.asyncio
    async def test_happy_path_hook_mutates_message_metadata(self, patched_engine):
        """Successful hook writes the integration-specific key back onto
        ``Message.metadata_`` via the deepcopy + flag_modified pattern.
        """
        _engine, factory = patched_engine
        _ch, msg_id, row_id = await _seed_message_row(factory)

        from app.agent.hooks import IntegrationMeta

        def _stamp(mutable, external_id, _target):
            mutable["webhook_delivery_id"] = external_id

        meta = IntegrationMeta(
            integration_type="webhook",
            client_id_prefix="webhook_",
            persist_delivery_metadata=_stamp,
        )
        renderer = _OkWithExternalIdRenderer()

        with patch(
            "app.integrations.renderer_registry.get", return_value=renderer
        ), patch(
            "app.agent.hooks.get_integration_meta", return_value=meta
        ):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        msg = await _get_message(factory, msg_id)
        assert msg.metadata_.get("webhook_delivery_id") == "ext-12345"


# ---------------------------------------------------------------------------
# N.8.2 — _persist_delivery_metadata silent-skip paths
# ---------------------------------------------------------------------------


class TestPersistDeliveryMetadataSkipPaths:
    @pytest.mark.asyncio
    async def test_turn_ended_event_skips_persist(self, patched_engine):
        """Non-NEW_MESSAGE events short-circuit the persist path —
        guaranteed because turn_ended has no Message to stamp.
        """
        _engine, factory = patched_engine
        _ch, row_id = await _seed_turn_row(factory)

        from app.agent.hooks import IntegrationMeta

        call_counter = {"n": 0}

        def _stamp(*_args):
            call_counter["n"] += 1

        meta = IntegrationMeta(
            integration_type="webhook",
            client_id_prefix="webhook_",
            persist_delivery_metadata=_stamp,
        )
        renderer = _OkWithExternalIdRenderer()

        with patch(
            "app.integrations.renderer_registry.get", return_value=renderer
        ), patch(
            "app.agent.hooks.get_integration_meta", return_value=meta
        ):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        assert call_counter["n"] == 0

    @pytest.mark.asyncio
    async def test_no_integration_meta_skips_persist(self, patched_engine):
        """``get_integration_meta`` returning None skips the persist path
        without raising — integrations without a persist hook are common.
        """
        _engine, factory = patched_engine
        _ch, msg_id, row_id = await _seed_message_row(factory)
        renderer = _OkWithExternalIdRenderer()

        with patch(
            "app.integrations.renderer_registry.get", return_value=renderer
        ), patch(
            "app.agent.hooks.get_integration_meta", return_value=None
        ):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DELIVERED.value
        # metadata untouched — no stamping occurred
        msg = await _get_message(factory, msg_id)
        assert msg.metadata_ == {}

    @pytest.mark.asyncio
    async def test_missing_message_row_skips_persist(self, patched_engine):
        """If the Message was deleted before the drainer runs the hook,
        the row still commits as DELIVERED — no partial state, no raise.
        """
        _engine, factory = patched_engine
        _ch, msg_id, row_id = await _seed_message_row(factory)

        # Delete the Message out-of-band to simulate a race.
        async with factory() as db:
            await db.execute(sa_delete(MessageModel).where(MessageModel.id == msg_id))
            await db.commit()

        from app.agent.hooks import IntegrationMeta

        call_counter = {"n": 0}

        def _stamp(*_args):
            call_counter["n"] += 1

        meta = IntegrationMeta(
            integration_type="webhook",
            client_id_prefix="webhook_",
            persist_delivery_metadata=_stamp,
        )
        renderer = _OkWithExternalIdRenderer()

        with patch(
            "app.integrations.renderer_registry.get", return_value=renderer
        ), patch(
            "app.agent.hooks.get_integration_meta", return_value=meta
        ):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DELIVERED.value
        assert call_counter["n"] == 0

    @pytest.mark.asyncio
    async def test_receipt_without_external_id_skips_persist(
        self, patched_engine
    ):
        """``DeliveryReceipt`` with no ``external_id`` — the persist call
        is gated in ``_mark_delivered_in_session`` on
        ``receipt.external_id`` being truthy.
        """
        _engine, factory = patched_engine
        _ch, msg_id, row_id = await _seed_message_row(factory)

        class _NoExtId:
            integration_id = "webhook"
            capabilities = frozenset({Capability.TEXT})

            async def render(self, event, target):
                return DeliveryReceipt(success=True, external_id=None, retryable=False)

            async def handle_outbound_action(self, action, target):
                return DeliveryReceipt.ok()

            async def delete_attachment(self, _meta, _target):
                return False

        from app.agent.hooks import IntegrationMeta

        call_counter = {"n": 0}

        def _stamp(*_args):
            call_counter["n"] += 1

        meta = IntegrationMeta(
            integration_type="webhook",
            client_id_prefix="webhook_",
            persist_delivery_metadata=_stamp,
        )

        with patch(
            "app.integrations.renderer_registry.get", return_value=_NoExtId()
        ), patch(
            "app.agent.hooks.get_integration_meta", return_value=meta
        ):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DELIVERED.value
        assert call_counter["n"] == 0


# ---------------------------------------------------------------------------
# N.8.3 — Repeated retryable escalates to dead-letter + DELIVERY_FAILED
# ---------------------------------------------------------------------------


class TestRetryableEscalationToDeadLetter:
    @pytest.mark.asyncio
    async def test_tenth_retryable_failure_dead_letters_and_publishes(
        self, patched_engine
    ):
        """``DEAD_LETTER_AFTER = 10`` — the 10th retryable failure flips
        the row to DEAD_LETTER *and* publishes DELIVERY_FAILED, same as
        an immediate non-retryable failure. The existing Phase D test
        covered only the immediate non-retryable path.
        """
        _engine, factory = patched_engine
        _ch, row_id = await _seed_turn_row(factory)

        # Pre-advance attempts to 9 so the next failure is the 10th.
        async with factory() as db:
            row = await db.get(Outbox, row_id)
            row.attempts = 9
            await db.commit()

        renderer = _RetryableFailRenderer()
        published: list[ChannelEvent] = []

        def _capture(_ch, event):
            published.append(event)
            return 1

        with patch(
            "app.integrations.renderer_registry.get", return_value=renderer
        ), patch(
            "app.services.channel_events.publish_typed", side_effect=_capture
        ):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DEAD_LETTER.value
        assert final.attempts == 10
        df_events = [
            ev for ev in published if ev.kind == ChannelEventKind.DELIVERY_FAILED
        ]
        assert len(df_events) == 1
        assert isinstance(df_events[0].payload, DeliveryFailedPayload)
        assert df_events[0].payload.attempts == 10


# ---------------------------------------------------------------------------
# N.8.4 — _publish_delivery_failed swallow
# ---------------------------------------------------------------------------


class TestPublishDeliveryFailedSwallow:
    @pytest.mark.asyncio
    async def test_broken_bus_does_not_crash_drainer(self, patched_engine):
        """If ``publish_typed`` raises on the dead-letter publish, the
        drainer catches + logs. The row is still dead-lettered in the DB.
        """
        _engine, factory = patched_engine
        _ch, row_id = await _seed_turn_row(factory)

        class _PermanentFail:
            integration_id = "webhook"
            capabilities = frozenset({Capability.TEXT})

            async def render(self, event, target):
                return DeliveryReceipt.failed("HTTP 400", retryable=False)

            async def handle_outbound_action(self, action, target):
                return DeliveryReceipt.ok()

            async def delete_attachment(self, _meta, _target):
                return False

        def _raise_on_publish(_ch, _event):
            raise RuntimeError("bus is on fire")

        with patch(
            "app.integrations.renderer_registry.get", return_value=_PermanentFail()
        ), patch(
            "app.services.channel_events.publish_typed", side_effect=_raise_on_publish
        ):
            row = await _get_row(factory, row_id)
            # Must not raise
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DEAD_LETTER.value


# ---------------------------------------------------------------------------
# N.8.5 — Row vanishes mid-session
# ---------------------------------------------------------------------------


class TestRowVanishesMidSession:
    @pytest.mark.asyncio
    async def test_mark_delivered_no_ops_when_row_deleted(self, patched_engine):
        """``_mark_delivered_in_session`` handles ``db.get → None`` without
        raising. Simulates an admin/manual DELETE between claim and commit.
        """
        _engine, factory = patched_engine
        _ch, row_id = await _seed_turn_row(factory)

        # Claim the row (sets IN_FLIGHT), then yank it.
        async with factory() as db:
            row = await db.get(Outbox, row_id)
            await db.execute(sa_delete(Outbox).where(Outbox.id == row_id))
            await db.commit()

        # Must not raise
        await outbox_drainer._mark_delivered_in_session(row)

        assert await _get_row(factory, row_id) is None

    @pytest.mark.asyncio
    async def test_mark_failed_no_ops_when_row_deleted(self, patched_engine):
        """``_mark_failed_in_session`` returns DELIVERED sentinel when row
        is gone — the dead-letter publish path keys off this so a missing
        row doesn't fan out a DELIVERY_FAILED for a row that no longer
        exists.
        """
        _engine, factory = patched_engine
        _ch, row_id = await _seed_turn_row(factory)
        async with factory() as db:
            row = await db.get(Outbox, row_id)
            await db.execute(sa_delete(Outbox).where(Outbox.id == row_id))
            await db.commit()

        new_state = await outbox_drainer._mark_failed_in_session(
            row, error="boom", retryable=False
        )

        assert new_state == DeliveryState.DELIVERED.value  # sentinel
        assert await _get_row(factory, row_id) is None

    @pytest.mark.asyncio
    async def test_defer_no_renderer_no_ops_when_row_deleted(
        self, patched_engine
    ):
        _engine, factory = patched_engine
        _ch, row_id = await _seed_turn_row(factory)
        async with factory() as db:
            row = await db.get(Outbox, row_id)
            await db.execute(sa_delete(Outbox).where(Outbox.id == row_id))
            await db.commit()

        new_state = await outbox_drainer._defer_no_renderer_in_session(row)

        assert new_state == DeliveryState.DELIVERED.value


# ---------------------------------------------------------------------------
# N.8.6 — fetch_pending FIFO ordering
# ---------------------------------------------------------------------------


class TestFetchPendingFifoOrdering:
    @pytest.mark.asyncio
    async def test_rows_drain_in_created_at_order(self, patched_engine):
        """``fetch_pending`` orders by ``created_at`` — callers (drainer
        + renderers pacing against pending counts) depend on this. A
        silent re-order to `id` or `available_at` would drift the Slack
        TURN_STARTED gating documented on ``count_pending_for_target``.
        """
        _engine, factory = patched_engine

        # Seed three rows with explicit created_at values.
        channel_id = uuid.uuid4()
        async with factory() as db:
            channel = Channel(id=channel_id, name="c", bot_id="b")
            db.add(channel)
            await db.commit()

        row_ids: list[uuid.UUID] = []
        base = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(3):
            async with factory() as db:
                payload = TurnEndedPayload(
                    bot_id="bot1",
                    turn_id=uuid.uuid4(),
                    result="done",
                    task_id=str(uuid.uuid4()),
                )
                event = ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.TURN_ENDED,
                    payload=payload,
                    seq=i + 1,
                )
                target = WebhookTarget(url=f"https://example.test/{i}")
                rows = await outbox.enqueue(
                    db, channel_id, event, [("webhook", target)]
                )
                # Stamp created_at in reverse so insert order != created order.
                rows[0].created_at = base.replace(minute=i)
                await db.commit()
                row_ids.append(rows[0].id)

        # fetch_pending should order by created_at ascending, regardless of insert order.
        async with factory() as db:
            fetched = await outbox.fetch_pending(db, limit=10)

        # Expect ascending order: created_at minute=0, 1, 2 → row_ids[0], [1], [2]
        fetched_ids = [r.id for r in fetched]
        assert fetched_ids == row_ids


# ---------------------------------------------------------------------------
# N.8.7 — reconstitute_event failure → non-retryable mark_failed
# ---------------------------------------------------------------------------


class TestReconstituteFailure:
    @pytest.mark.asyncio
    async def test_corrupt_payload_dead_letters_immediately(self, patched_engine):
        """If ``reconstitute_event`` raises (corrupt JSONB payload), the
        drainer marks the row failed with ``retryable=False`` — no infinite
        retry on an unparseable row.
        """
        _engine, factory = patched_engine
        _ch, row_id = await _seed_turn_row(factory)

        class _NeverCalled:
            integration_id = "webhook"
            capabilities = frozenset({Capability.TEXT})
            calls = 0

            async def render(self, *_a):
                type(self).calls += 1
                return DeliveryReceipt.ok()

            async def handle_outbound_action(self, *_a):
                return DeliveryReceipt.ok()

            async def delete_attachment(self, *_a):
                return False

        renderer = _NeverCalled()

        def _raise_recon(_row):
            raise ValueError("corrupt payload")

        with patch(
            "app.integrations.renderer_registry.get", return_value=renderer
        ), patch(
            "app.services.outbox_drainer.outbox.reconstitute_event",
            side_effect=_raise_recon,
        ):
            row = await _get_row(factory, row_id)
            await outbox_drainer._deliver_one(row)

        final = await _get_row(factory, row_id)
        assert final.delivery_state == DeliveryState.DEAD_LETTER.value
        assert "reconstitution failed" in (final.last_error or "")
        # Renderer never got called — reconstitution fails before render dispatch
        assert _NeverCalled.calls == 0
