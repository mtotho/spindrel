"""Integration tests for widget @on_event dispatch — Phase B.4 Widget SDK.

Exercises the full event-bus → subscriber-task → widget.py handler loop:
  create_pin  → register_pin_events (via dashboard_pins hook)
  publish_typed(NEW_MESSAGE) on the pin's channel
  subscriber task fires invoke_event → handler writes to ctx.db
  unregister_pin_events cancels the live task
  pin DELETE cascades the widget_event_subscriptions rows
"""
from __future__ import annotations

import asyncio
import textwrap
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import (
    ApiKey,
    Bot,
    WidgetDashboardPin,
    WidgetEventSubscription,
)
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import HeartbeatTickPayload
from app.services.widget_py import clear_module_cache


_CHANNEL_ID = uuid.UUID("cccc0000-0000-0000-0000-0000000000b4")

_BOT = BotConfig(
    id="event-bot",
    name="Event Bot",
    model="test/model",
    system_prompt="",
    memory=MemoryConfig(enabled=False),
)


@pytest.fixture(autouse=True)
def _clear_module_cache():
    clear_module_cache()
    yield
    clear_module_cache()


@pytest.fixture(autouse=True)
async def _clean_registry():
    yield
    from app.services.widget_events import _subscriber_tasks
    for pin_id in list(_subscriber_tasks.keys()):
        for t in _subscriber_tasks[pin_id]:
            t.cancel()
        for t in _subscriber_tasks[pin_id]:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    _subscriber_tasks.clear()


@pytest.fixture()
async def event_pin(db_session, tmp_path, engine):
    """Seed a pin with a widget.yaml + widget.py that subscribes to heartbeat_tick."""
    from app.db.models import WidgetDashboard
    from app.services.dashboard_pins import create_pin

    api_key = ApiKey(
        id=uuid.uuid4(),
        name="event-key",
        key_hash="eventhash-int",
        key_prefix="event-int-",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()

    bot_row = Bot(
        id="event-bot",
        name="Event Bot",
        display_name="Event Bot",
        model="test/model",
        system_prompt="",
        api_key_id=api_key.id,
    )
    db_session.add(bot_row)

    if await db_session.get(WidgetDashboard, "default") is None:
        db_session.add(WidgetDashboard(slug="default", title="Default"))
    await db_session.commit()

    ws_root = tmp_path / "workspace"
    bundle_dir = ws_root / "data" / "widgets" / "event_int"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "index.html").write_text("<!-- -->")
    (bundle_dir / "widget.yaml").write_text(textwrap.dedent("""
        name: Event Int
        permissions:
          events: [heartbeat_tick]
        events:
          - kind: heartbeat_tick
            handler: on_tick
    """).lstrip())
    (bundle_dir / "widget.py").write_text(textwrap.dedent("""
        from spindrel.widget import on_event, ctx

        @on_event("heartbeat_tick")
        async def on_tick(payload):
            await ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS hb (ts TEXT, payload TEXT)"
            )
            await ctx.db.execute(
                "insert into hb(ts, payload) values (datetime('now'), ?)",
                [str(payload)],
            )
            return {"ok": True}
    """).lstrip())

    envelope = {
        "content_type": "application/vnd.spindrel.html+interactive",
        "body": "",
        "source_path": "data/widgets/event_int/index.html",
        "source_channel_id": str(_CHANNEL_ID),
        "source_bot_id": "event-bot",
    }

    # register_pin_events / subscriber loop both reach for async_session;
    # point them at the test engine.
    test_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    bot_patch = patch("app.agent.bots.get_bot", return_value=_BOT)
    ws_patch = patch(
        "app.services.channel_workspace.get_channel_workspace_root",
        return_value=str(ws_root),
    )
    session_patch = patch(
        "app.services.widget_events.async_session", test_session_factory,
    )

    with bot_patch, ws_patch, session_patch:
        pin = await create_pin(
            db_session,
            source_kind="adhoc",
            tool_name="emit_html_widget",
            envelope=envelope,
            source_channel_id=_CHANNEL_ID,
            source_bot_id="event-bot",
            display_label="Event int",
        )
        # Give the subscriber task a tick to enter its subscribe() loop.
        await asyncio.sleep(0.05)

        yield pin, ws_root, bundle_dir, bot_patch, ws_patch, session_patch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreatePinRegistersEvents:
    @pytest.mark.asyncio
    async def test_create_pin_seeds_subscription(self, db_session, event_pin):
        pin, *_ = event_pin

        rows = (await db_session.execute(
            select(WidgetEventSubscription).where(
                WidgetEventSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.event_kind == "heartbeat_tick"
        assert row.handler == "on_tick"
        assert row.enabled is True

        # Live subscriber task also spawned.
        from app.services.widget_events import _active_task_count
        assert _active_task_count(pin.id) == 1


class TestEventFanOut:
    @pytest.mark.asyncio
    async def test_publish_fires_handler(self, db_session, event_pin):
        """Publish a HEARTBEAT_TICK on the channel → handler writes to ctx.db."""
        pin, _ws_root, _bundle_dir, _bot_patch, _ws_patch, _session_patch = event_pin

        from app.services import channel_events as ce

        ev = ChannelEvent(
            channel_id=_CHANNEL_ID,
            kind=ChannelEventKind.HEARTBEAT_TICK,
            payload=HeartbeatTickPayload(bot_id="event-bot"),
        )

        # Fixture patches stay active for the life of the test — subscriber
        # task can reach the patched get_bot / workspace root from its coroutine.
        ce.publish_typed(_CHANNEL_ID, ev)
        from app.services.widget_db import resolve_db_path
        db_path = resolve_db_path(pin)

        deadline = asyncio.get_event_loop().time() + 3.0
        found = 0
        import sqlite3
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            if not Path(db_path).exists():
                continue
            try:
                conn = sqlite3.connect(db_path)
                try:
                    row = conn.execute(
                        "select count(*) from hb"
                    ).fetchone()
                    found = row[0]
                finally:
                    conn.close()
            except sqlite3.OperationalError:
                # Table not yet created by the handler.
                continue
            if found >= 1:
                break
        assert found >= 1, "heartbeat_tick handler did not write to ctx.db"

    @pytest.mark.asyncio
    async def test_non_matching_kind_does_not_fire(self, db_session, event_pin):
        """Publishing a kind the subscription didn't declare must not invoke."""
        pin, *_rest = event_pin

        from app.domain.payloads import TurnEndedPayload
        from app.services import channel_events as ce

        # Publish a TURN_ENDED (not declared in this bundle's events).
        ev = ChannelEvent(
            channel_id=_CHANNEL_ID,
            kind=ChannelEventKind.TURN_ENDED,
            payload=TurnEndedPayload(
                bot_id="event-bot",
                turn_id=uuid.uuid4(),
                result="done",
            ),
        )
        ce.publish_typed(_CHANNEL_ID, ev)
        # Wait a tick — more than long enough for the subscriber to filter
        # the event out. If it wrongly invoked, the ctx.db path would
        # raise and the count or the DB file would appear.
        await asyncio.sleep(0.15)

        from app.services.widget_db import resolve_db_path
        db_path = resolve_db_path(pin)

        # Either the DB file doesn't exist or the `hb` table has zero rows.
        import sqlite3
        if Path(db_path).exists():
            conn = sqlite3.connect(db_path)
            try:
                try:
                    row = conn.execute("select count(*) from hb").fetchone()
                    assert row[0] == 0
                except sqlite3.OperationalError:
                    # Table never created — also acceptable (handler never fired).
                    pass
            finally:
                conn.close()


class TestUnregisterAndDelete:
    @pytest.mark.asyncio
    async def test_unregister_cancels_subscriber(self, db_session, event_pin):
        pin, *_rest = event_pin

        from app.services.widget_events import (
            _active_task_count, unregister_pin_events,
        )
        assert _active_task_count(pin.id) == 1

        await unregister_pin_events(db_session, pin.id)
        assert _active_task_count(pin.id) == 0

    @pytest.mark.asyncio
    async def test_pin_delete_cascades(self, db_session, event_pin):
        pin, *_rest = event_pin

        # unregister first (mirrors dashboard_pins.delete_pin order)
        from app.services.widget_events import unregister_pin_events
        await unregister_pin_events(db_session, pin.id)

        await db_session.execute(text("PRAGMA foreign_keys = ON"))
        await db_session.delete(pin)
        await db_session.commit()

        rows = (await db_session.execute(
            select(WidgetEventSubscription).where(
                WidgetEventSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert rows == []
