"""Seed ``WidgetInstance.state`` for screenshot-staged native widgets.

Usage:
    python - <scope_ref>     <widget_ref> <state_json> [scope_kind]
    python - <instance_uuid> _            <state_json> instance

``scope_kind`` defaults to ``"channel"``. Pass ``"dashboard"`` and a
dashboard slug (e.g. ``"workspace:spatial"``) as ``scope_ref`` to seed
non-singleton pins, OR pass ``"instance"`` and a WidgetInstance UUID to
target one specific instance directly (used by the spatial canvas where
each pin owns a synthetic-scope-ref WidgetInstance).

Native widgets (``core/notes_native``, ``core/todo_native``, etc.) render
from ``WidgetInstance.state`` on the server side — ``envelope.state``
passed to the pin create call is cosmetic. To make screenshots show
realistic content, we update the WidgetInstance directly after the pin
lands.

Idempotent: overwrites matching keys; falls back to creating the row if
none exists yet (handy when seeding before any pin actually mounts).
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid


async def main() -> None:
    if len(sys.argv) not in (4, 5):
        raise SystemExit("usage: python - <scope_ref> <widget_ref> <state_json> [scope_kind]")

    scope_ref = sys.argv[1]
    widget_ref = sys.argv[2]
    state_raw = sys.argv[3]
    scope_kind = sys.argv[4] if len(sys.argv) == 5 else "channel"

    if scope_kind not in {"channel", "dashboard", "instance"}:
        raise SystemExit(
            f"scope_kind must be 'channel', 'dashboard', or 'instance', got {scope_kind!r}"
        )

    try:
        state = json.loads(state_raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"state_json is not valid JSON: {e}")

    if not isinstance(state, dict):
        raise SystemExit("state_json must be a JSON object")

    # Channel scopes need a UUID; dashboard slug uses raw value; instance
    # mode interprets ``scope_ref`` as a WidgetInstance.id UUID and ignores
    # ``widget_ref`` entirely (passed as a placeholder).
    if scope_kind == "channel":
        scope_ref = str(uuid.UUID(scope_ref))
    elif scope_kind == "instance":
        scope_ref = str(uuid.UUID(scope_ref))

    from app.db.engine import async_session  # type: ignore
    from app.db.models import WidgetInstance  # type: ignore
    from sqlalchemy import select  # type: ignore

    async with async_session() as db:
        if scope_kind == "instance":
            row = (
                await db.execute(
                    select(WidgetInstance).where(WidgetInstance.id == scope_ref)
                )
            ).scalar_one_or_none()
        else:
            row = (
                await db.execute(
                    select(WidgetInstance).where(
                        WidgetInstance.widget_kind == "native_app",
                        WidgetInstance.widget_ref == widget_ref,
                        WidgetInstance.scope_kind == scope_kind,
                        WidgetInstance.scope_ref == scope_ref,
                    )
                )
            ).scalar_one_or_none()

        if row is None:
            raise SystemExit(
                f"WidgetInstance not found: widget_ref={widget_ref!r} "
                f"scope_kind={scope_kind} scope_ref={scope_ref}"
            )

        merged = dict(row.state or {})
        merged.update(state)
        row.state = merged
        await db.commit()
        print(f"ok widget_ref={widget_ref} scope={scope_kind}:{scope_ref} keys={sorted(merged.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
