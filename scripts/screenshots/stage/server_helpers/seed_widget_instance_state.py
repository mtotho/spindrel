"""Seed ``WidgetInstance.state`` for screenshot-staged native widgets.

Usage:
    python - <channel_id> <widget_ref> <state_json>

Native widgets (``core/notes_native``, ``core/todo_native``, etc.) render from
``WidgetInstance.state`` on the server side — ``envelope.state`` passed to the
pin create call is cosmetic. To make screenshots show realistic content, we
update the WidgetInstance directly after the pin lands.

Idempotent: overwrites existing state. The WidgetInstance is looked up by
(widget_ref, scope_kind='channel', scope_ref=<channel_id>), matching the
channel-dashboard singleton that ``get_or_create_native_widget_instance``
creates for each (widget_ref, channel) pair.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid


async def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: python - <channel_id> <widget_ref> <state_json>")

    channel_id = sys.argv[1]
    widget_ref = sys.argv[2]
    state_raw = sys.argv[3]

    try:
        state = json.loads(state_raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"state_json is not valid JSON: {e}")

    if not isinstance(state, dict):
        raise SystemExit("state_json must be a JSON object")

    channel_uuid = uuid.UUID(channel_id)

    from app.db.engine import async_session  # type: ignore
    from app.db.models import WidgetInstance  # type: ignore
    from sqlalchemy import select  # type: ignore

    async with async_session() as db:
        row = (
            await db.execute(
                select(WidgetInstance).where(
                    WidgetInstance.widget_kind == "native_app",
                    WidgetInstance.widget_ref == widget_ref,
                    WidgetInstance.scope_kind == "channel",
                    WidgetInstance.scope_ref == str(channel_uuid),
                )
            )
        ).scalar_one_or_none()

        if row is None:
            raise SystemExit(
                f"WidgetInstance not found: widget_ref={widget_ref!r} "
                f"channel_id={channel_id}"
            )

        merged = dict(row.state or {})
        merged.update(state)
        row.state = merged
        await db.commit()
        print(f"ok widget_ref={widget_ref} channel_id={channel_id} keys={sorted(merged.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
