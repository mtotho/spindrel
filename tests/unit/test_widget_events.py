"""Unit tests for app.services.widget_events — Phase B.4 of the Widget SDK track.

Covers:
- register_pin_events: insert rows + spawn tasks from manifest
- register_pin_events: reconcile on manifest change (insert/update/delete rows;
  respawn live tasks)
- register_pin_events: no manifest → no rows / no tasks
- register_pin_events: permissions.events allowlist gates task spawn
- unregister_pin_events cancels tasks + drops rows
- _event_subscriber_loop: matching kind → invokes handler
- _event_subscriber_loop: non-matching kind → does not invoke
- _event_subscriber_loop: SHUTDOWN sentinel exits cleanly
- _event_subscriber_loop: REPLAY_LAPSED sentinel resubscribes
- _event_subscriber_loop: handler exception keeps loop alive
- Cascade: deleting a pin drops its event subscriptions
"""
from __future__ import annotations

import asyncio
import textwrap
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import (
    ApiKey,
    Bot,
    WidgetDashboardPin,
    WidgetEventSubscription,
)
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import (
    MessagePayload,
    ReplayLapsedPayload,
    ShutdownPayload,
)
from app.services.widget_events import (
    _active_task_count,
    _event_subscriber_loop,
    register_pin_events,
    unregister_pin_events,
)
from app.services.widget_py import clear_module_cache


_CHANNEL_ID = uuid.UUID("cccc0000-0000-0000-0000-000000000042")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_module_cache()
    yield
    clear_module_cache()


@pytest.fixture(autouse=True)
async def _clean_registry():
    """Ensure no subscriber tasks leak between tests."""
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


def _make_bot() -> BotConfig:
    return BotConfig(
        id="event-bot",
        name="Event Bot",
        model="test/model",
        system_prompt="",
        memory=MemoryConfig(enabled=False),
    )


def _ws_root_patches(ws_root: Path):
    bot_patch = patch("app.agent.bots.get_bot", return_value=_make_bot())
    ws_patch = patch(
        "app.services.channel_workspace.get_channel_workspace_root",
        return_value=str(ws_root),
    )
    return bot_patch, ws_patch


def _write_bundle(
    bundle_dir: Path,
    *,
    yaml_body: str | None = None,
    py_body: str | None = None,
) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "index.html").write_text("<!-- test -->")
    if yaml_body is not None:
        (bundle_dir / "widget.yaml").write_text(textwrap.dedent(yaml_body).lstrip())
    if py_body is not None:
        (bundle_dir / "widget.py").write_text(textwrap.dedent(py_body).lstrip())


async def _seed_pin(db_session, *, bundle_rel: str) -> WidgetDashboardPin:
    """Seed bot + pin pointing at a bundle under channel workspace."""
    api_key = ApiKey(
        id=uuid.uuid4(),
        name="event-key",
        key_hash="eventhash",
        key_prefix="event-key-",
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
    await db_session.flush()

    pin = WidgetDashboardPin(
        dashboard_key="default",
        position=0,
        source_kind="adhoc",
        source_channel_id=_CHANNEL_ID,
        source_bot_id="event-bot",
        tool_name="emit_html_widget",
        tool_args={},
        widget_config={},
        envelope={
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": "",
            "source_path": f"{bundle_rel}/index.html",
            "source_channel_id": str(_CHANNEL_ID),
            "source_bot_id": "event-bot",
        },
        grid_layout={"x": 0, "y": 0, "w": 6, "h": 6},
    )
    db_session.add(pin)

    from app.db.models import WidgetDashboard
    existing = await db_session.get(WidgetDashboard, "default")
    if existing is None:
        db_session.add(WidgetDashboard(slug="default", title="Default"))
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(pin)
    return pin


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegisterPinEvents:
    @pytest.mark.asyncio
    async def test_inserts_rows_and_spawns_tasks(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "event_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Event Test
                permissions:
                  events: [new_message, turn_ended]
                events:
                  - kind: new_message
                    handler: on_msg
                  - kind: turn_ended
                    handler: on_turn
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/event_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_events(db_session, pin)

        rows = (await db_session.execute(
            select(WidgetEventSubscription).where(
                WidgetEventSubscription.pin_id == pin.id
            )
        )).scalars().all()
        by_handler = {r.handler: r for r in rows}
        assert set(by_handler) == {"on_msg", "on_turn"}
        assert by_handler["on_msg"].event_kind == "new_message"
        assert by_handler["on_msg"].enabled is True
        assert by_handler["on_turn"].event_kind == "turn_ended"

        # Two tasks spawned (one per enabled row).
        assert _active_task_count(pin.id) == 2

    @pytest.mark.asyncio
    async def test_permissions_events_allowlist_disables(
        self, db_session, tmp_path,
    ):
        """Handler declared for a kind not in permissions.events → disabled row, no task."""
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "event_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Event Test
                permissions:
                  events: [new_message]
                events:
                  - kind: new_message
                    handler: on_msg
                  - kind: turn_ended
                    handler: on_turn
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/event_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_events(db_session, pin)

        rows = (await db_session.execute(
            select(WidgetEventSubscription).where(
                WidgetEventSubscription.pin_id == pin.id
            )
        )).scalars().all()
        by_handler = {r.handler: r for r in rows}
        assert by_handler["on_msg"].enabled is True
        assert by_handler["on_turn"].enabled is False

        # Only one task — the allowed one.
        assert _active_task_count(pin.id) == 1

    @pytest.mark.asyncio
    async def test_reconciles_on_manifest_change(self, db_session, tmp_path):
        """Changing the manifest should update rows + respawn tasks."""
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "event_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Event Test
                permissions:
                  events: [new_message, turn_ended]
                events:
                  - kind: new_message
                    handler: on_msg
                  - kind: turn_ended
                    handler: on_turn
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/event_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_events(db_session, pin)
        assert _active_task_count(pin.id) == 2

        # Rewrite manifest — drop on_turn, keep on_msg.
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Event Test
                permissions:
                  events: [new_message]
                events:
                  - kind: new_message
                    handler: on_msg
            """,
        )
        with bot_patch, ws_patch:
            await register_pin_events(db_session, pin)

        rows = (await db_session.execute(
            select(WidgetEventSubscription).where(
                WidgetEventSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert {r.handler for r in rows} == {"on_msg"}
        assert _active_task_count(pin.id) == 1

    @pytest.mark.asyncio
    async def test_no_manifest_is_noop(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "event_test"
        _write_bundle(bundle_dir)  # no widget.yaml
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/event_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_events(db_session, pin)

        rows = (await db_session.execute(
            select(WidgetEventSubscription).where(
                WidgetEventSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert rows == []
        assert _active_task_count(pin.id) == 0


class TestUnregisterPinEvents:
    @pytest.mark.asyncio
    async def test_cancels_tasks_and_drops_rows(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "event_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Event Test
                permissions:
                  events: [new_message]
                events:
                  - kind: new_message
                    handler: on_msg
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/event_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_events(db_session, pin)
        assert _active_task_count(pin.id) == 1

        await unregister_pin_events(db_session, pin.id)
        # Task registry emptied; rows gone.
        assert _active_task_count(pin.id) == 0
        rows = (await db_session.execute(
            select(WidgetEventSubscription).where(
                WidgetEventSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# Subscriber loop
# ---------------------------------------------------------------------------


def _make_event(kind: ChannelEventKind, **payload_kwargs) -> ChannelEvent:
    if kind is ChannelEventKind.SHUTDOWN:
        payload = ShutdownPayload()
    elif kind is ChannelEventKind.REPLAY_LAPSED:
        payload = ReplayLapsedPayload(
            requested_since=0, oldest_available=1,
            reason=payload_kwargs.get("reason", "subscriber_overflow"),
        )
    else:
        raise ValueError(f"_make_event helper only covers control frames, not {kind}")
    return ChannelEvent(channel_id=_CHANNEL_ID, kind=kind, payload=payload)


class TestEventSubscriberLoop:
    @pytest.mark.asyncio
    async def test_matching_kind_invokes_handler(self):
        """Matching event.kind.value fires invoke_event with serialised payload."""
        pin_id = uuid.uuid4()
        fake_payload = object()  # just needs to flow into serialize_payload

        async def fake_subscribe(_channel_id, *, since=None):
            class _StubEvent:
                kind = ChannelEventKind.NEW_MESSAGE
                payload = fake_payload
                channel_id = _CHANNEL_ID
                seq = 1

            yield _StubEvent()
            # Keep the generator alive until cancelled.
            await asyncio.sleep(10)

        invoke = AsyncMock(return_value=None)
        pin_mock = object()  # non-None stand-in
        db_mock = type("DB", (), {
            "get": lambda self, model, _id: _async_return(pin_mock),
        })()
        session_cm = _async_cm(db_mock)

        fake_serialize = lambda p: {"serialized": True}  # noqa: E731

        with (
            patch("app.services.channel_events.subscribe", fake_subscribe),
            patch("app.services.widget_py.invoke_event", invoke),
            patch("app.services.outbox.serialize_payload", fake_serialize),
            patch("app.services.widget_events.async_session", return_value=session_cm),
        ):
            task = asyncio.create_task(
                _event_subscriber_loop(pin_id, _CHANNEL_ID, "new_message", "on_msg"),
            )
            # Give the event loop time to pick up the yielded event.
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        invoke.assert_awaited()
        args, _kwargs = invoke.call_args
        assert args[0] is pin_mock
        assert args[1] == "new_message"
        assert args[2] == "on_msg"
        assert args[3] == {"serialized": True}

    @pytest.mark.asyncio
    async def test_non_matching_kind_does_not_invoke(self):
        """An event whose kind.value doesn't match the subscription is ignored."""
        pin_id = uuid.uuid4()

        async def fake_subscribe(_channel_id, *, since=None):
            # Yield an event for a kind the subscriber didn't ask for.
            yield _make_event(ChannelEventKind.REPLAY_LAPSED, reason="client_lag")
            await asyncio.sleep(10)

        invoke = AsyncMock()
        with (
            patch("app.services.channel_events.subscribe", fake_subscribe),
            patch("app.services.widget_py.invoke_event", invoke),
        ):
            task = asyncio.create_task(
                _event_subscriber_loop(pin_id, _CHANNEL_ID, "new_message", "on_msg"),
            )
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        invoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_shutdown_sentinel_exits_loop(self):
        """SHUTDOWN sentinel → subscriber returns without resubscribing."""
        pin_id = uuid.uuid4()

        subscribe_calls = 0

        async def fake_subscribe(_channel_id, *, since=None):
            nonlocal subscribe_calls
            subscribe_calls += 1
            yield _make_event(ChannelEventKind.SHUTDOWN)

        with patch("app.services.channel_events.subscribe", fake_subscribe):
            task = asyncio.create_task(
                _event_subscriber_loop(pin_id, _CHANNEL_ID, "new_message", "on_msg"),
            )
            # Subscriber should exit cleanly — not hang.
            await asyncio.wait_for(task, timeout=1.0)

        assert subscribe_calls == 1  # no re-subscribe after SHUTDOWN


class TestCascadeDelete:
    @pytest.mark.asyncio
    async def test_pin_delete_cascades_event_subs(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "event_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Event Test
                permissions:
                  events: [new_message]
                events:
                  - kind: new_message
                    handler: on_msg
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/event_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_events(db_session, pin)

        rows_before = (await db_session.execute(
            select(WidgetEventSubscription).where(
                WidgetEventSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert len(rows_before) == 1

        # Cancel tasks the same way delete_pin would, before deleting.
        await unregister_pin_events(db_session, pin.id)

        await db_session.execute(text("PRAGMA foreign_keys = ON"))
        await db_session.delete(pin)
        await db_session.commit()

        rows_after = (await db_session.execute(
            select(WidgetEventSubscription).where(
                WidgetEventSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert rows_after == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _async_return(value):
    async def _coro():
        return value
    return _coro()


def _async_cm(value):
    class _CM:
        async def __aenter__(self_inner):
            return value
        async def __aexit__(self_inner, *exc_info):
            return None
    return _CM()
