"""Tests for ``app/services/outbox_publish.py``.

Three public entry points:

- ``enqueue_for_targets`` — thin wrapper around ``outbox.enqueue`` that
  no-ops on an empty target list.
- ``enqueue_new_message_for_channel`` — fire-and-forget self-contained
  enqueue that opens its own session, looks up the channel, resolves
  dispatch targets, and inserts one outbox row per target. Failure modes
  are logged + swallowed.
- ``publish_to_bus`` — synchronous wrapper around
  ``channel_events.publish_typed`` that returns the subscriber count.

Real DB sessions used throughout (in-memory SQLite). The PG-type compile
patches from ``test_outbox.py`` are imported for side-effect.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Reuse the SQLite type-compilation patches from test_outbox.
from tests.unit.test_outbox import _patch_pg_types_for_sqlite  # noqa: F401

from app.db.models import Base, Channel, Outbox
from app.domain.actor import ActorRef
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.delivery_state import DeliveryState
from app.domain.dispatch_target import NoneTarget, WebhookTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import MessagePayload, ShutdownPayload
from app.services import outbox_publish
from app.services.channel_events import (
    _next_seq,
    _replay_buffer,
    _subscribers,
    publish_typed,
    subscribe,
)


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
async def db(engine_and_factory) -> AsyncSession:
    _engine, factory = engine_and_factory
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def patched_async_session(engine_and_factory):
    """Point every ``async_session()`` import at the test factory."""
    _engine, factory = engine_and_factory
    with patch("app.db.engine.async_session", factory), \
         patch("app.services.dispatch_resolution.async_session", factory):
        yield factory


@pytest.fixture(autouse=True)
def _clean_bus():
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()


def _make_domain_msg(channel_id: uuid.UUID, content: str = "hi") -> DomainMessage:
    return DomainMessage(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content=content,
        created_at=datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
        actor=ActorRef.bot("bot1", "Bot One"),
        channel_id=channel_id,
    )


def _make_message_event(channel_id: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(message=_make_domain_msg(channel_id)),
        seq=1,
    )


# ---------------------------------------------------------------------------
# enqueue_for_targets
# ---------------------------------------------------------------------------


class TestEnqueueForTargets:
    @pytest.mark.asyncio
    async def test_when_targets_present_then_inserts_one_row_per_target(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)

        await outbox_publish.enqueue_for_targets(
            db,
            channel.id,
            event,
            [("slack", NoneTarget()), ("webhook", WebhookTarget(url="https://x.test/h"))],
        )
        await db.commit()

        rows = (await db.execute(select(Outbox))).scalars().all()
        assert {r.target_integration_id for r in rows} == {"slack", "webhook"}

    @pytest.mark.asyncio
    async def test_when_no_targets_then_noop(self, db: AsyncSession):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        event = _make_message_event(channel.id)

        await outbox_publish.enqueue_for_targets(db, channel.id, event, [])
        await db.commit()

        rows = (await db.execute(select(Outbox))).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# enqueue_new_message_for_channel
# ---------------------------------------------------------------------------


class TestEnqueueNewMessageForChannel:
    @pytest.mark.asyncio
    async def test_when_channel_resolves_targets_then_outbox_rows_inserted(
        self, db: AsyncSession, patched_async_session
    ):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        msg = _make_domain_msg(channel.id, content="hello world")
        # No bound integrations → resolve_targets returns [("none", NoneTarget())].

        await outbox_publish.enqueue_new_message_for_channel(channel.id, msg)

        rows = (await db.execute(select(Outbox))).scalars().all()
        assert len(rows) == 1
        assert rows[0].target_integration_id == "none"
        assert rows[0].channel_id == channel.id
        assert rows[0].kind == ChannelEventKind.NEW_MESSAGE.value
        assert rows[0].delivery_state == DeliveryState.PENDING.value

    @pytest.mark.asyncio
    async def test_when_channel_missing_then_silently_skips(
        self, db: AsyncSession, patched_async_session
    ):
        ghost_channel_id = uuid.uuid4()
        msg = _make_domain_msg(ghost_channel_id)

        await outbox_publish.enqueue_new_message_for_channel(ghost_channel_id, msg)

        rows = (await db.execute(select(Outbox))).scalars().all()
        assert rows == []

    @pytest.mark.asyncio
    async def test_when_resolve_targets_raises_then_exception_swallowed(
        self, db: AsyncSession, patched_async_session
    ):
        channel = Channel(id=uuid.uuid4(), name="c", bot_id="b")
        db.add(channel)
        await db.commit()
        msg = _make_domain_msg(channel.id)

        # resolve_targets is imported inside the function — patch the source.
        with patch(
            "app.services.dispatch_resolution.resolve_targets",
            side_effect=RuntimeError("DB unreachable"),
        ):
            # Should NOT raise — durable delivery failure for one publish must
            # not break the caller.
            await outbox_publish.enqueue_new_message_for_channel(channel.id, msg)

        rows = (await db.execute(select(Outbox))).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# publish_to_bus
# ---------------------------------------------------------------------------


class TestPublishToBus:
    def test_when_no_subscribers_then_returns_zero(self):
        ch = uuid.uuid4()
        event = ChannelEvent(
            channel_id=ch,
            kind=ChannelEventKind.SHUTDOWN,
            payload=ShutdownPayload(),
        )

        delivered = outbox_publish.publish_to_bus(ch, event)

        assert delivered == 0

    @pytest.mark.asyncio
    async def test_when_subscribers_attached_then_returns_subscriber_count(self):
        import asyncio
        ch = uuid.uuid4()
        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch):
                received.append(ev)
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        event = ChannelEvent(
            channel_id=ch,
            kind=ChannelEventKind.SHUTDOWN,
            payload=ShutdownPayload(),
        )

        delivered = outbox_publish.publish_to_bus(ch, event)

        await asyncio.wait_for(task, timeout=1.0)
        assert delivered == 1
        assert received[0].kind is ChannelEventKind.SHUTDOWN
