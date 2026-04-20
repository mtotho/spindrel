"""Widget SDK Phase B.3 — cron scheduler integration.

Reconciles ``widget_cron_subscriptions`` rows against a pin's bundle
``widget.yaml`` on pin create / envelope update, and fires
``widget_py.invoke_cron(pin, cron_name)`` under the pin's ``source_bot_id``
when ``next_fire_at`` falls due. Pin deletion cascades via the FK; this
module never needs to clean up live scheduler state because all state
lives in the DB and the worker re-queries each tick.

Public surface
--------------
register_pin_crons(db, pin)     — upsert subscription rows from widget.yaml
unregister_pin_crons(db, pin_id) — delete all rows for a pin (used on envelope drop)
spawn_due_widget_crons()        — task_worker tick (awaited from app/agent/tasks.py)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import WidgetCronSubscription, WidgetDashboardPin
from app.services.cron_utils import next_fire_at as _cron_next

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registration — reconcile DB rows against the pin's widget.yaml manifest
# ---------------------------------------------------------------------------


def _load_pin_manifest(pin: WidgetDashboardPin):
    """Return the parsed ``WidgetManifest`` for a pin, or ``None``.

    Returns ``None`` for inline widgets (no source_path), bundles without a
    widget.yaml, or pins whose bundle directory can't be resolved — none of
    which are errors at registration time; the pin simply has no crons.
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
            "pin %s widget.yaml invalid, skipping cron registration: %s",
            pin.id, exc,
        )
        return None


async def register_pin_crons(db: AsyncSession, pin: WidgetDashboardPin) -> None:
    """Upsert ``widget_cron_subscriptions`` rows to match the pin's manifest.

    Strategy: load the current set of rows for ``pin_id``, diff against
    ``manifest.cron``, then:
      - INSERT rows for cron names not yet present (seed ``next_fire_at``)
      - UPDATE rows whose schedule/handler changed (recompute ``next_fire_at``
        from now — a schedule edit resets the clock, which is the intuitive
        behavior)
      - DELETE rows whose cron name is no longer declared in the manifest

    Idempotent: running it twice with no manifest changes is a no-op beyond
    reading. Callers must not commit before calling — this function issues
    its own ``db.commit()`` so the scheduler tick sees the rows immediately.
    """
    manifest = _load_pin_manifest(pin)
    desired = {entry.name: entry for entry in (manifest.cron if manifest else [])}

    existing_rows = (await db.execute(
        select(WidgetCronSubscription).where(
            WidgetCronSubscription.pin_id == pin.id
        )
    )).scalars().all()
    existing = {row.cron_name: row for row in existing_rows}

    now = datetime.now(timezone.utc)

    # UPDATE / leave-alone
    for name, entry in desired.items():
        row = existing.get(name)
        if row is None:
            continue
        if row.schedule != entry.schedule or row.handler != entry.handler:
            row.schedule = entry.schedule
            row.handler = entry.handler
            row.enabled = True
            try:
                row.next_fire_at = _cron_next(entry.schedule, now)
            except Exception:
                logger.exception(
                    "pin %s cron %r has invalid schedule %r — disabling",
                    pin.id, name, entry.schedule,
                )
                row.enabled = False
                row.next_fire_at = None
            row.updated_at = now

    # INSERT
    for name, entry in desired.items():
        if name in existing:
            continue
        try:
            next_at = _cron_next(entry.schedule, now)
            enabled = True
        except Exception:
            logger.exception(
                "pin %s cron %r has invalid schedule %r — inserting disabled",
                pin.id, name, entry.schedule,
            )
            next_at = None
            enabled = False
        db.add(WidgetCronSubscription(
            pin_id=pin.id,
            cron_name=name,
            schedule=entry.schedule,
            handler=entry.handler,
            enabled=enabled,
            next_fire_at=next_at,
        ))

    # DELETE — name no longer in manifest
    for name, row in existing.items():
        if name not in desired:
            await db.delete(row)

    await db.commit()


async def unregister_pin_crons(db: AsyncSession, pin_id: uuid.UUID) -> None:
    """Delete all ``widget_cron_subscriptions`` rows for a pin.

    On pin ``DELETE`` the DB cascade handles this automatically; this helper
    exists for the envelope-change path where ``source_path`` could switch
    to a bundle that has no crons (or to an inline widget).
    """
    await db.execute(
        delete(WidgetCronSubscription).where(
            WidgetCronSubscription.pin_id == pin_id
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Scheduler tick — called once per iteration of app/agent/tasks.py task_worker
# ---------------------------------------------------------------------------


async def _fire_widget_cron(sub_id: uuid.UUID) -> None:
    """Advance + invoke a single subscription.

    Advances ``next_fire_at`` and commits BEFORE invoking the handler so a
    handler crash (or slow handler) can't cause the scheduler to re-fire
    the same row every 5s. Mirrors ``_fire_subscription`` in tasks.py.
    """
    from app.services.widget_py import invoke_cron

    async with async_session() as db:
        sub = await db.get(WidgetCronSubscription, sub_id)
        if sub is None or not sub.enabled or sub.next_fire_at is None:
            return

        pin = await db.get(WidgetDashboardPin, sub.pin_id)
        if pin is None:
            # Shouldn't happen — FK CASCADE should have deleted the sub row.
            logger.warning(
                "widget cron sub %s has no pin (pin_id=%s) — deleting",
                sub.id, sub.pin_id,
            )
            await db.delete(sub)
            await db.commit()
            return

        now = datetime.now(timezone.utc)
        try:
            sub.next_fire_at = _cron_next(sub.schedule, now)
        except Exception:
            logger.exception(
                "widget cron %s (%r) — invalid schedule %r — disabling",
                sub.id, sub.cron_name, sub.schedule,
            )
            sub.next_fire_at = None
            sub.enabled = False
        sub.last_fired_at = now
        sub.updated_at = now
        handler_name = sub.handler
        cron_name = sub.cron_name
        await db.commit()

        try:
            await invoke_cron(pin, cron_name)
        except FileNotFoundError as exc:
            logger.warning(
                "widget cron %s: bundle missing widget.py (%s) — pin=%s",
                cron_name, exc, pin.id,
            )
        except KeyError:
            logger.warning(
                "widget cron %s: no @on_cron handler named %r — pin=%s",
                cron_name, handler_name, pin.id,
            )
        except PermissionError as exc:
            logger.warning(
                "widget cron %s: permission denied: %s — pin=%s",
                cron_name, exc, pin.id,
            )
        except Exception:
            logger.exception(
                "widget cron %s failed — pin=%s handler=%s",
                cron_name, pin.id, handler_name,
            )


async def spawn_due_widget_crons() -> None:
    """Find enabled widget cron subscriptions whose ``next_fire_at`` is due."""
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = (
            select(WidgetCronSubscription.id)
            .where(WidgetCronSubscription.enabled.is_(True))
            .where(WidgetCronSubscription.next_fire_at.isnot(None))
            .where(WidgetCronSubscription.next_fire_at <= now)
            .limit(50)
        )
        sub_ids = list((await db.execute(stmt)).scalars().all())

    for sid in sub_ids:
        try:
            await _fire_widget_cron(sid)
        except Exception:
            logger.exception("Failed to fire widget cron %s", sid)
