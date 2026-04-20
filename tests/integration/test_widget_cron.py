"""Integration tests for widget cron scheduler — Phase B.3 Widget SDK.

Exercises the full loop:
  create_pin  → register_pin_crons (via dashboard_pins hook)
  scheduler tick → spawn_due_widget_crons → _fire_widget_cron → invoke_cron
  handler writes to ctx.db → we read the SQLite file directly to confirm
  pin DELETE cascades the widget_cron_subscriptions rows
"""
from __future__ import annotations

import textwrap
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import (
    ApiKey,
    Bot,
    WidgetCronSubscription,
    WidgetDashboardPin,
)
from app.services.widget_py import clear_module_cache

_CHANNEL_ID = uuid.UUID("cccc0000-0000-0000-0000-000000000088")

_BOT = BotConfig(
    id="cron-bot",
    name="Cron Bot",
    model="test/model",
    system_prompt="",
    memory=MemoryConfig(enabled=False),
)


@pytest.fixture(autouse=True)
def _clear_module_cache():
    clear_module_cache()
    yield
    clear_module_cache()


@pytest.fixture()
async def cron_pin(db_session, tmp_path):
    """Seed a pin + write a bundle with widget.yaml + widget.py."""
    from app.db.models import WidgetDashboard
    from app.services.dashboard_pins import create_pin

    api_key = ApiKey(
        id=uuid.uuid4(),
        name="cron-key",
        key_hash="cronhash-int",
        key_prefix="cron-int-",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()

    bot_row = Bot(
        id="cron-bot",
        name="Cron Bot",
        display_name="Cron Bot",
        model="test/model",
        system_prompt="",
        api_key_id=api_key.id,
    )
    db_session.add(bot_row)

    if await db_session.get(WidgetDashboard, "default") is None:
        db_session.add(WidgetDashboard(slug="default", title="Default"))
    await db_session.commit()

    ws_root = tmp_path / "workspace"
    bundle_dir = ws_root / "data" / "widgets" / "cron_int"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "index.html").write_text("<!-- -->")
    (bundle_dir / "widget.yaml").write_text(textwrap.dedent("""
        name: Cron Int
        cron:
          - name: every_minute
            schedule: "* * * * *"
            handler: tick
    """).lstrip())
    (bundle_dir / "widget.py").write_text(textwrap.dedent("""
        from spindrel.widget import on_cron, ctx

        @on_cron("every_minute")
        async def tick():
            await ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS ticks (ts TEXT)"
            )
            await ctx.db.execute(
                "insert into ticks(ts) values (datetime('now'))"
            )
            return {"ok": True}
    """).lstrip())

    envelope = {
        "content_type": "application/vnd.spindrel.html+interactive",
        "body": "",
        "source_path": "data/widgets/cron_int/index.html",
        "source_channel_id": str(_CHANNEL_ID),
        "source_bot_id": "cron-bot",
    }

    bot_patch = patch("app.agent.bots.get_bot", return_value=_BOT)
    ws_patch = patch(
        "app.services.channel_workspace.get_channel_workspace_root",
        return_value=str(ws_root),
    )
    with bot_patch, ws_patch:
        pin = await create_pin(
            db_session,
            source_kind="adhoc",
            tool_name="emit_html_widget",
            envelope=envelope,
            source_channel_id=_CHANNEL_ID,
            source_bot_id="cron-bot",
            display_label="Cron int",
        )

    return pin, ws_root, bundle_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreatePinRegistersCrons:
    @pytest.mark.asyncio
    async def test_create_pin_seeds_subscription(self, db_session, cron_pin):
        pin, _ws_root, _bundle_dir = cron_pin

        rows = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.cron_name == "every_minute"
        assert row.schedule == "* * * * *"
        assert row.handler == "tick"
        assert row.enabled is True
        assert row.next_fire_at is not None


class TestSchedulerTickFires:
    @pytest.mark.asyncio
    async def test_tick_fires_due_handler(self, engine, db_session, cron_pin):
        """Force next_fire_at into the past and run the scheduler tick."""
        from app.services.widget_cron import spawn_due_widget_crons

        pin, ws_root, _bundle_dir = cron_pin

        # Push the row into "overdue" and point widget_cron at the test engine.
        sub = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalar_one()
        sub.next_fire_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db_session.commit()

        test_session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )

        bot_patch = patch("app.agent.bots.get_bot", return_value=_BOT)
        ws_patch = patch(
            "app.services.channel_workspace.get_channel_workspace_root",
            return_value=str(ws_root),
        )
        session_patch = patch(
            "app.services.widget_cron.async_session", test_session_factory,
        )
        # widget_db also creates its own sessions, but its ctx.db path doesn't
        # go through SQLAlchemy — it's a direct aiosqlite handle. No patching
        # needed there.
        with bot_patch, ws_patch, session_patch:
            await spawn_due_widget_crons()

            # After firing, next_fire_at should have advanced past now.
            await db_session.refresh(sub)
            assert sub.last_fired_at is not None
            assert sub.next_fire_at is not None
            assert sub.next_fire_at > datetime.now(timezone.utc) - timedelta(seconds=5)

            # And the handler should have written a row to the bundle's sqlite.
            from app.services.widget_db import resolve_db_path
            db_path = resolve_db_path(pin)

        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("select count(*) from ticks").fetchone()
        finally:
            conn.close()
        assert rows[0] == 1


class TestPinDeleteCascades:
    @pytest.mark.asyncio
    async def test_pin_delete_cascades(self, db_session, cron_pin):
        pin, _ws_root, _bundle_dir = cron_pin

        # Enable SQLite FK enforcement so ondelete=CASCADE actually fires.
        await db_session.execute(text("PRAGMA foreign_keys = ON"))

        await db_session.delete(pin)
        await db_session.commit()

        rows = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert rows == []
