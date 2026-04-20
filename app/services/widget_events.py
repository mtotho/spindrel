"""Widget SDK Phase B.4 — channel event subscriptions.

Reconciles ``widget_event_subscriptions`` rows against a pin's bundle
``widget.yaml`` on pin create / envelope update, spawns one long-lived
``asyncio.Task`` per enabled row that reads
``app.services.channel_events.subscribe(pin.source_channel_id)`` and
fires ``widget_py.invoke_event(pin, event_kind, handler, payload)`` under
the pin's ``source_bot_id`` whenever a matching ``ChannelEvent`` arrives.

Unlike B.3's cron scheduler — which polls the DB every 5s and has no live
state — event subscribers MUST cancel their tasks on pin delete. The DB
cascade drops the row, but the in-process ``asyncio.Task`` is the other
half of the lifecycle. ``app/services/dashboard_pins.py::delete_pin``
calls ``unregister_pin_events`` before the row is dropped; the FastAPI
lifespan restores tasks on boot from the reconciled table.

Public surface
--------------
register_pin_events(db, pin)        — reconcile rows + (re)spawn tasks from manifest
unregister_pin_events(pin_id)       — cancel live tasks + drop rows for a pin
register_all_pins_on_startup()       — lifespan entrypoint; called once on server boot
unregister_all_on_shutdown()         — lifespan exit; cancels every live task
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import WidgetDashboardPin, WidgetEventSubscription
from app.domain.channel_events import ChannelEventKind

if TYPE_CHECKING:
    from app.services.widget_manifest import WidgetManifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-process registry of live subscriber tasks, keyed by pin_id
# ---------------------------------------------------------------------------

_subscriber_tasks: dict[uuid.UUID, list[asyncio.Task]] = {}


def _active_task_count(pin_id: uuid.UUID) -> int:
    """Test/debug helper — how many live subscriber tasks for a pin."""
    return len(_subscriber_tasks.get(pin_id, []))


async def _cancel_pin_tasks(pin_id: uuid.UUID) -> None:
    """Cancel and await every live subscriber task for ``pin_id``."""
    tasks = _subscriber_tasks.pop(pin_id, [])
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# Manifest loader — shared shape with widget_cron._load_pin_manifest
# ---------------------------------------------------------------------------


def _load_pin_manifest(pin: WidgetDashboardPin):
    """Return the parsed ``WidgetManifest`` for a pin, or ``None``.

    Mirrors ``widget_cron._load_pin_manifest`` — returns ``None`` for
    inline widgets, bundles without a widget.yaml, or resolve failures.
    None of those are errors at registration time; the pin simply has no
    event subscriptions.
    """
    from app.services.widget_manifest import ManifestError, parse_manifest
    from app.services.widget_py import _resolve_bundle_dir

    try:
        bundle_dir = _resolve_bundle_dir(pin)
    except ValueError:
        return None

    yaml_path = bundle_dir / "widget.yaml"
    if not yaml_path.is_file():
        return None
    try:
        return parse_manifest(yaml_path)
    except ManifestError as exc:
        logger.warning(
            "pin %s widget.yaml invalid, skipping event registration: %s",
            pin.id, exc,
        )
        return None


def _desired_event_rows(manifest: "WidgetManifest | None") -> dict[tuple[str, str], bool]:
    """Map ``(event_kind, handler) -> enabled`` from a manifest.

    ``enabled`` is False when the handler's ``kind`` is NOT in the
    manifest's ``permissions.events`` allowlist — the row persists for
    visibility but no subscriber task is spawned. Fail-loud by being
    visible in the DB, without failing the pin write.
    """
    if manifest is None:
        return {}
    allowed = set(manifest.permissions.events or [])
    out: dict[tuple[str, str], bool] = {}
    for entry in manifest.events or []:
        # Manifest validation (B.0) already guarantees entry.kind is a
        # valid ChannelEventKind value; being defensive here is cheap.
        enabled = (
            entry.kind in allowed
            if allowed
            else True  # no allowlist declared → open (matches permissions.tools)
        )
        out[(entry.kind, entry.handler)] = enabled
    return out


# ---------------------------------------------------------------------------
# Subscriber task — one per (pin, event_kind, handler) row
# ---------------------------------------------------------------------------


async def _event_subscriber_loop(
    pin_id: uuid.UUID,
    channel_id: uuid.UUID,
    event_kind: str,
    handler_name: str,
) -> None:
    """Live subscriber: forwards matching channel events to a widget handler.

    Re-enters ``channel_events.subscribe()`` if the generator exits (e.g.
    the overflow-drop ``REPLAY_LAPSED`` sentinel) so a noisy publisher
    can't permanently silence a widget. The outer ``while True`` exits
    only on cancellation.
    """
    from app.services import channel_events as ce
    from app.services.outbox import serialize_payload
    from app.services.widget_py import invoke_event

    while True:
        try:
            async for event in ce.subscribe(channel_id):
                # Sentinels — shutdown means the server is going down; treat
                # as exit. Replay-lapsed (subscriber overflow) means we got
                # dropped; break out and re-enter subscribe() with fresh
                # state rather than dying.
                if event.kind is ChannelEventKind.SHUTDOWN:
                    logger.info(
                        "widget_events: shutdown received, exiting subscriber "
                        "pin=%s kind=%s handler=%s",
                        pin_id, event_kind, handler_name,
                    )
                    return
                if event.kind is ChannelEventKind.REPLAY_LAPSED:
                    logger.warning(
                        "widget_events: replay lapsed for pin=%s kind=%s handler=%s "
                        "(resubscribing)",
                        pin_id, event_kind, handler_name,
                    )
                    continue
                if event.kind.value != event_kind:
                    continue

                # Re-load the pin each fire so envelope changes mid-run don't
                # leak a stale pin into the handler; cheap (single PK lookup)
                # and matches how _fire_widget_cron handles identity.
                async with async_session() as db:
                    pin = await db.get(WidgetDashboardPin, pin_id)
                    if pin is None:
                        logger.info(
                            "widget_events: pin %s gone; exiting subscriber "
                            "kind=%s handler=%s",
                            pin_id, event_kind, handler_name,
                        )
                        return

                try:
                    payload = serialize_payload(event.payload)
                    await invoke_event(pin, event_kind, handler_name, payload)
                except FileNotFoundError as exc:
                    logger.warning(
                        "widget_events: bundle missing widget.py (%s) pin=%s "
                        "kind=%s handler=%s",
                        exc, pin_id, event_kind, handler_name,
                    )
                except KeyError:
                    logger.warning(
                        "widget_events: no @on_event(%s) handler %r in widget.py "
                        "pin=%s",
                        event_kind, handler_name, pin_id,
                    )
                except PermissionError as exc:
                    logger.warning(
                        "widget_events: permission denied: %s pin=%s kind=%s "
                        "handler=%s",
                        exc, pin_id, event_kind, handler_name,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "widget_events: handler failed pin=%s kind=%s handler=%s",
                        pin_id, event_kind, handler_name,
                    )
            # subscribe() generator exited cleanly — resubscribe on next loop.
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "widget_events: subscriber loop crashed pin=%s kind=%s handler=%s "
                "(resubscribing in 1s)",
                pin_id, event_kind, handler_name,
            )
            await asyncio.sleep(1.0)


# ---------------------------------------------------------------------------
# Register / Unregister
# ---------------------------------------------------------------------------


async def register_pin_events(db: AsyncSession, pin: WidgetDashboardPin) -> None:
    """Reconcile ``widget_event_subscriptions`` rows for a pin and (re)spawn tasks.

    Always cancels any live tasks for the pin first, then re-reads the
    manifest, reconciles DB rows (insert/update/delete), and spawns fresh
    tasks for enabled rows. Idempotent — calling twice with unchanged
    manifest only refreshes tasks (no persistent state beyond the DB rows
    and the module registry).

    Callers must not commit before calling — this function issues its own
    ``db.commit()`` so the startup scan sees rows immediately.
    """
    # Always drop live tasks before reconciling — a manifest change means
    # old subscriptions are invalidated even if the DB row survives.
    await _cancel_pin_tasks(pin.id)

    manifest = _load_pin_manifest(pin)
    desired = _desired_event_rows(manifest)

    existing_rows = (await db.execute(
        select(WidgetEventSubscription).where(
            WidgetEventSubscription.pin_id == pin.id
        )
    )).scalars().all()
    existing = {(r.event_kind, r.handler): r for r in existing_rows}

    # UPDATE rows whose enabled flag drifted
    for key, want_enabled in desired.items():
        row = existing.get(key)
        if row is None:
            continue
        if row.enabled != want_enabled:
            row.enabled = want_enabled

    # INSERT missing
    for (kind, handler), want_enabled in desired.items():
        if (kind, handler) in existing:
            continue
        db.add(WidgetEventSubscription(
            pin_id=pin.id,
            event_kind=kind,
            handler=handler,
            enabled=want_enabled,
        ))

    # DELETE rows no longer declared
    for key, row in existing.items():
        if key not in desired:
            await db.delete(row)

    await db.commit()

    # Spawn subscriber tasks — only for enabled rows with a resolvable channel.
    channel_id = pin.source_channel_id
    if channel_id is None:
        # Dashboard pins without a source channel can't subscribe to channel
        # events. Rows persist for visibility but no tasks spawn.
        return

    spawned: list[asyncio.Task] = []
    for (kind, handler), want_enabled in desired.items():
        if not want_enabled:
            continue
        task = asyncio.create_task(
            _event_subscriber_loop(pin.id, channel_id, kind, handler),
            name=f"widget_event[{pin.id}][{kind}][{handler}]",
        )
        spawned.append(task)
    if spawned:
        _subscriber_tasks[pin.id] = spawned


async def unregister_pin_events(
    db: AsyncSession, pin_id: uuid.UUID,
) -> None:
    """Cancel live tasks + delete rows for a pin.

    Called from ``dashboard_pins.delete_pin`` BEFORE the pin row is
    deleted (so a subscriber can't briefly observe a missing pin). Takes
    a session so the operation shares the caller's transaction — in
    particular, tests using an in-memory SQLite engine pass through the
    same bind.
    """
    await _cancel_pin_tasks(pin_id)
    await db.execute(
        delete(WidgetEventSubscription).where(
            WidgetEventSubscription.pin_id == pin_id
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Lifespan hooks
# ---------------------------------------------------------------------------


async def register_all_pins_on_startup() -> None:
    """Scan every widget dashboard pin and (re)register its event subscribers.

    Called once from ``app/main.py`` lifespan. Wraps each pin in its own
    try/except so a single broken bundle cannot block server boot.
    """
    async with async_session() as db:
        pins = (await db.execute(select(WidgetDashboardPin))).scalars().all()

    if not pins:
        logger.info("widget_events: no pins to register at startup")
        return

    total = 0
    failed = 0
    for pin in pins:
        try:
            async with async_session() as db:
                pin_reloaded = await db.get(WidgetDashboardPin, pin.id)
                if pin_reloaded is None:
                    continue
                await register_pin_events(db, pin_reloaded)
                total += _active_task_count(pin.id)
        except Exception:
            failed += 1
            logger.exception("widget_events: startup register failed pin=%s", pin.id)
    logger.info(
        "widget_events: startup registered %d subscriber task(s) across %d pins "
        "(%d pins failed)",
        total, len(pins), failed,
    )


async def unregister_all_on_shutdown() -> None:
    """Cancel every live subscriber task across every pin. Lifespan exit hook."""
    pin_ids = list(_subscriber_tasks.keys())
    for pin_id in pin_ids:
        await _cancel_pin_tasks(pin_id)
    logger.info(
        "widget_events: shutdown cancelled subscribers for %d pin(s)",
        len(pin_ids),
    )
