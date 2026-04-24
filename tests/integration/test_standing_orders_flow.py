"""Integration: Standing Order pin creation + native-widget cron dispatch."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models import Bot, Channel, WidgetInstance
from app.services import standing_orders as so
from app.services.dashboard_pins import create_pin
from app.services.native_app_widgets import build_native_widget_preview_envelope


async def _ensure_channel(db) -> uuid.UUID:
    """Seed a channel so channel-dashboard pinning has a real FK target."""
    bot = Bot(
        id="so-test-bot",
        name="so-test-bot",
        model="noop",
    )
    db.add(bot)
    await db.flush()
    ch = Channel(
        id=uuid.uuid4(),
        bot_id=bot.id,
        name="so-test-channel",
    )
    db.add(ch)
    await db.commit()
    return ch.id


def _initial_state(**overrides):
    base = so.build_initial_state(
        goal="Integration test",
        strategy="timer",
        strategy_args={},
        interval_seconds=30,
        max_iterations=10,
        completion={"kind": "after_n_iterations", "n": 2},
        message_on_complete="integration done",
        owning_bot_id="bot-integration",
        owning_channel_id=str(uuid.uuid4()),
    )
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_two_standing_orders_coexist_on_same_channel(db_session):
    """Regression guard: Notes/Todo are scope-unique per channel, but Standing
    Orders need multiple instances per channel. The ``override_widget_instance``
    path on ``create_pin`` makes that work.
    """
    channel_id = await _ensure_channel(db_session)

    instance_a = await so.create_standing_order_instance(
        db_session, initial_state=_initial_state(goal="Order A")
    )
    envelope_a = build_native_widget_preview_envelope(
        so.STANDING_ORDER_WIDGET_REF,
        display_label="Order A",
        state=instance_a.state,
        widget_instance_id=instance_a.id,
        source_bot_id=None,
    )
    pin_a = await create_pin(
        db_session,
        source_kind="channel",
        tool_name="spawn_standing_order",
        envelope=envelope_a,
        source_channel_id=channel_id,
        source_bot_id=None,
        dashboard_key=f"channel:{channel_id}",
        zone="grid",
        override_widget_instance=instance_a,
    )

    instance_b = await so.create_standing_order_instance(
        db_session, initial_state=_initial_state(goal="Order B")
    )
    envelope_b = build_native_widget_preview_envelope(
        so.STANDING_ORDER_WIDGET_REF,
        display_label="Order B",
        state=instance_b.state,
        widget_instance_id=instance_b.id,
        source_bot_id=None,
    )
    pin_b = await create_pin(
        db_session,
        source_kind="channel",
        tool_name="spawn_standing_order",
        envelope=envelope_b,
        source_channel_id=channel_id,
        source_bot_id=None,
        dashboard_key=f"channel:{channel_id}",
        zone="grid",
        override_widget_instance=instance_b,
    )

    assert pin_a.id != pin_b.id
    assert pin_a.widget_instance_id == instance_a.id
    assert pin_b.widget_instance_id == instance_b.id
    assert instance_a.scope_ref != instance_b.scope_ref
    # Both rows are distinct WidgetInstances keyed by unique synthetic scopes.
    rows = (
        await db_session.execute(
            select(WidgetInstance).where(
                WidgetInstance.widget_kind == "native_app",
                WidgetInstance.widget_ref == so.STANDING_ORDER_WIDGET_REF,
            )
        )
    ).scalars().all()
    scope_refs = {row.scope_ref for row in rows}
    assert len(scope_refs) >= 2


@pytest.mark.asyncio
async def test_pin_sees_standing_order_state_in_context_export(db_session):
    """The bot's context_export should surface the owning bot's standing orders."""
    from app.services.widget_context import _summarize_standing_order_state

    channel_id = await _ensure_channel(db_session)

    instance = await so.create_standing_order_instance(
        db_session,
        initial_state=_initial_state(
            goal="Watch the deploy", owning_channel_id=str(channel_id)
        ),
    )
    # Simulate a tick having landed
    state = dict(instance.state)
    state["iterations"] = 3
    state["log"] = [
        {"at": datetime.now(timezone.utc).isoformat(), "text": "GET https://x -> 200"}
    ]
    instance.state = state

    envelope = build_native_widget_preview_envelope(
        so.STANDING_ORDER_WIDGET_REF,
        display_label="Watch the deploy",
        state=instance.state,
        widget_instance_id=instance.id,
        source_bot_id="bot-integration",
    )
    pin_dict = {
        "id": uuid.uuid4(),
        "envelope": envelope,
        "source_bot_id": "bot-integration",
    }
    summary = _summarize_standing_order_state(pin_dict, now=datetime.now(timezone.utc))

    assert summary is not None
    assert "Watch the deploy" in summary
    assert "running" in summary
    assert "3 tick" in summary
    assert "GET https://x -> 200" in summary
