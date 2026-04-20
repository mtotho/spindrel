"""MC Timeline handlers — add manual timeline events from the iframe.

Shares its SQLite DB with `mc_kanban` and `mc_tasks` via the Mission Control
suite (see `suites/mission-control/suite.yaml`).
"""
from __future__ import annotations

import uuid

from spindrel.widget import ctx, on_action


@on_action("add_event")
async def add_event(args):
    """Insert a manual timeline event.

    Args: ``{ title: str, body?: str }``
    """
    title = (args or {}).get("title", "").strip()
    if not title:
        raise ValueError("title is required")
    body = (args or {}).get("body") or None

    await ctx.db.execute(
        """
        INSERT INTO items (id, kind, title, body)
        VALUES (?, 'timeline_event', ?, ?)
        """,
        [str(uuid.uuid4()), title, body],
    )
    await ctx.notify_reload()
    return {"ok": True}


@on_action("delete_event")
async def delete_event(args):
    item_id = (args or {}).get("id", "")
    if not item_id:
        raise ValueError("id is required")
    await ctx.db.execute(
        "DELETE FROM items WHERE id = ? AND kind = 'timeline_event'",
        [item_id],
    )
    await ctx.notify_reload()
    return {"ok": True}
