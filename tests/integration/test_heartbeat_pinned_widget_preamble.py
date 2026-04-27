"""Verifies that ``ChannelHeartbeat.include_pinned_widgets`` actually flows
the channel's pinned dashboard widget block into the heartbeat's
``system_preamble``.

The "heartbeat" context profile blocks ``allow_pinned_widgets``, so
``assemble_context`` will not inject the block on its own. ``fire_heartbeat``
has to compose it explicitly. We capture the kwargs handed to
``app.agent.loop.run`` and assert that:

  - default heartbeat (flag off) leaves the preamble free of widget content
  - flag-on, with a real Notes pin, appends the widget block to the preamble
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ApiKey, Bot, Channel, ChannelHeartbeat, Session


@contextmanager
def _patch_engine(engine):
    """Make every dynamic ``async_session()`` call open against the test
    engine. Module-level imports (``from app.db.engine import async_session``)
    bind the symbol once, so we patch each known consumer site explicitly."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with (
        patch("app.db.engine.async_session", factory),
        patch("app.services.heartbeat.async_session", factory),
    ):
        yield


async def _seed(db_session) -> tuple[uuid.UUID, ChannelHeartbeat]:
    api_key = ApiKey(
        id=uuid.uuid4(),
        name="hb-key",
        key_hash="hash",
        key_prefix="pfx",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()
    db_session.add(Bot(
        id="hb-bot",
        name="HB Bot",
        display_name="HB Bot",
        model="test/model",
        system_prompt="",
        api_key_id=api_key.id,
    ))
    channel_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name="hb-widget-channel",
        client_id=f"hb-widget-{channel_id}",
        bot_id="hb-bot",
        active_session_id=uuid.uuid4(),
    ))
    hb = ChannelHeartbeat(
        id=uuid.uuid4(),
        channel_id=channel_id,
        enabled=True,
        interval_minutes=60,
        prompt="check the pinned widgets",
        include_pinned_widgets=False,
    )
    db_session.add(hb)
    await db_session.commit()
    await db_session.refresh(hb)
    return channel_id, hb


async def _seed_harness(db_session, *, runner_mode: str | None = None) -> tuple[uuid.UUID, uuid.UUID, ChannelHeartbeat]:
    api_key = ApiKey(
        id=uuid.uuid4(),
        name="hb-harness-key",
        key_hash="hash",
        key_prefix="pfx",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()
    db_session.add(Bot(
        id="hb-harness-bot",
        name="Harness Bot",
        display_name="Harness Bot",
        model="test/model",
        system_prompt="",
        api_key_id=api_key.id,
        harness_runtime="claude_code",
    ))
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name="hb-harness-channel",
        client_id=f"hb-harness-{channel_id}",
        bot_id="hb-harness-bot",
        active_session_id=session_id,
    ))
    db_session.add(Session(
        id=session_id,
        client_id=f"hb-harness-{channel_id}",
        bot_id="hb-harness-bot",
        channel_id=channel_id,
    ))
    hb = ChannelHeartbeat(
        id=uuid.uuid4(),
        channel_id=channel_id,
        enabled=True,
        interval_minutes=60,
        prompt="check the workspace",
        runner_mode=runner_mode,
    )
    db_session.add(hb)
    await db_session.commit()
    await db_session.refresh(hb)
    return channel_id, session_id, hb


async def _pin_notes_widget(engine, channel_id: uuid.UUID, body: str) -> None:
    """Pin a Notes native widget on the channel dashboard with seeded body."""
    from app.services.dashboard_pins import create_pin
    from app.services.dashboards import ensure_channel_dashboard
    from app.services.native_app_widgets import (
        build_native_widget_preview_envelope,
        get_or_create_native_widget_instance,
    )

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        await ensure_channel_dashboard(db, channel_id)
        envelope = build_native_widget_preview_envelope(
            "core/notes_native",
            source_bot_id="hb-bot",
        )
        pin = await create_pin(
            db,
            source_kind="adhoc",
            tool_name="core/notes_native",
            envelope=envelope,
            source_bot_id="hb-bot",
            source_channel_id=channel_id,
            dashboard_key=f"channel:{channel_id}",
            zone="grid",
        )
        instance = await get_or_create_native_widget_instance(
            db,
            widget_ref="core/notes_native",
            dashboard_key=f"channel:{channel_id}",
            source_channel_id=channel_id,
            state={"body": body, "updated_at": "2026-04-26T16:00:00+00:00"},
        )
        # Re-render the pin envelope so the freshly seeded body is visible
        # to the context-export pipeline (the snapshot reads pin.envelope,
        # not the WidgetInstance directly).
        from app.services.native_app_widgets import build_envelope_for_native_instance
        pin.envelope = build_envelope_for_native_instance(instance)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(pin, "envelope")
        await db.commit()


def _captured_run_kwargs():
    captured: dict = {}

    async def _fake_run(messages, bot, prompt, **kwargs):
        captured.update(kwargs)
        captured["_prompt"] = prompt
        return type("R", (), {"response": "ok"})()

    return captured, _fake_run


@pytest.mark.asyncio
async def test_fire_heartbeat_omits_widget_block_by_default(engine, db_session):
    channel_id, hb = await _seed(db_session)
    await _pin_notes_widget(engine, channel_id, "Buy milk and eggs")

    captured, fake_run = _captured_run_kwargs()
    with _patch_engine(engine), \
         patch("app.agent.loop.run", new=AsyncMock(side_effect=fake_run)), \
         patch("app.agent.bots.get_bot", return_value=type("B", (), {"id": "hb-bot"})()), \
         patch("app.services.sessions.load_or_create", new=AsyncMock(return_value=(uuid.uuid4(), []))), \
         patch("app.services.sessions.persist_turn", new=AsyncMock()):
        from app.services.heartbeat import fire_heartbeat
        await fire_heartbeat(hb)

    preamble = captured.get("system_preamble") or ""
    assert "SCHEDULED HEARTBEAT TASK" in preamble
    assert "Buy milk" not in preamble
    assert "pinned in this channel" not in preamble


@pytest.mark.asyncio
async def test_fire_heartbeat_appends_widget_block_when_flag_on(engine, db_session):
    channel_id, hb = await _seed(db_session)
    # Flip the flag.
    hb.include_pinned_widgets = True
    db_session.add(hb)
    await db_session.commit()
    await db_session.refresh(hb)
    await _pin_notes_widget(engine, channel_id, "Buy milk and eggs")

    captured, fake_run = _captured_run_kwargs()
    with _patch_engine(engine), \
         patch("app.agent.loop.run", new=AsyncMock(side_effect=fake_run)), \
         patch("app.agent.bots.get_bot", return_value=type("B", (), {"id": "hb-bot"})()), \
         patch("app.services.sessions.load_or_create", new=AsyncMock(return_value=(uuid.uuid4(), []))), \
         patch("app.services.sessions.persist_turn", new=AsyncMock()):
        from app.services.heartbeat import fire_heartbeat
        await fire_heartbeat(hb)

    preamble = captured.get("system_preamble") or ""
    assert "SCHEDULED HEARTBEAT TASK" in preamble, preamble
    assert "pinned in this channel" in preamble, preamble
    assert "Buy milk" in preamble, preamble
    # The widget block must NOT pollute the user prompt itself — heartbeat
    # opt-in routes through the system_preamble, not the heartbeat's prompt.
    user_prompt = captured.get("_prompt") or ""
    assert "Buy milk" not in user_prompt


@pytest.mark.asyncio
async def test_harness_heartbeat_defaults_to_context_hint(engine, db_session):
    _channel_id, session_id, hb = await _seed_harness(db_session)

    with _patch_engine(engine), \
         patch("app.agent.loop.run", new=AsyncMock()) as run_mock, \
         patch("app.agent.bots.get_bot", return_value=type("B", (), {"id": "hb-harness-bot", "harness_runtime": "claude_code"})()):
        from app.services.heartbeat import fire_heartbeat
        await fire_heartbeat(hb)

    run_mock.assert_not_awaited()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        session = await db.get(Session, session_id)
        hints = (session.metadata_ or {}).get("harness_context_hints") or []
    assert len(hints) == 1
    assert hints[0]["kind"] == "heartbeat"
    assert "TASK PROMPT:" in hints[0]["text"]
    assert "check the workspace" in hints[0]["text"]


@pytest.mark.asyncio
async def test_harness_heartbeat_spindrel_runner_uses_normal_loop(engine, db_session):
    _channel_id, _session_id, hb = await _seed_harness(db_session, runner_mode="spindrel")

    captured, fake_run = _captured_run_kwargs()
    with _patch_engine(engine), \
         patch("app.agent.loop.run", new=AsyncMock(side_effect=fake_run)), \
         patch("app.agent.bots.get_bot", return_value=type("B", (), {"id": "hb-harness-bot", "memory": {}})()), \
         patch("app.services.sessions.load_or_create", new=AsyncMock(return_value=(uuid.uuid4(), []))), \
         patch("app.services.sessions.persist_turn", new=AsyncMock()):
        from app.services.heartbeat import fire_heartbeat
        await fire_heartbeat(hb)

    assert captured.get("_prompt") == "check the workspace"
    assert "SCHEDULED HEARTBEAT TASK" in (captured.get("system_preamble") or "")
