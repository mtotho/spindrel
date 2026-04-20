"""MC Kanban handlers — columns, cards, drag-between-columns, timeline echo.

Shares its SQLite DB with `mc_timeline` and `mc_tasks` via the Mission
Control suite (see `mission-control/suite.yaml`).
"""
from __future__ import annotations

import uuid

from spindrel.widget import ctx, on_action


DEFAULT_COLUMNS = ["Backlog", "Doing", "Done"]


@on_action("seed_default_columns")
async def seed_default_columns(args):
    """One-shot seed of Backlog / Doing / Done if no columns exist."""
    existing = await ctx.db.query("SELECT COUNT(*) AS n FROM kanban_columns")
    if existing and existing[0]["n"] > 0:
        return {"ok": True, "seeded": 0}
    for i, name in enumerate(DEFAULT_COLUMNS):
        await ctx.db.execute(
            "INSERT INTO kanban_columns (id, name, position) VALUES (?, ?, ?)",
            [str(uuid.uuid4()), name, i],
        )
    await ctx.notify_reload()
    return {"ok": True, "seeded": len(DEFAULT_COLUMNS)}


@on_action("add_column")
async def add_column(args):
    name = (args or {}).get("name", "").strip()
    if not name:
        raise ValueError("name is required")
    row = await ctx.db.query("SELECT COALESCE(MAX(position), -1) AS mx FROM kanban_columns")
    next_pos = (row[0]["mx"] if row else -1) + 1
    await ctx.db.execute(
        "INSERT INTO kanban_columns (id, name, position) VALUES (?, ?, ?)",
        [str(uuid.uuid4()), name, next_pos],
    )
    await ctx.notify_reload()
    return {"ok": True}


@on_action("delete_column")
async def delete_column(args):
    col_id = (args or {}).get("id", "")
    if not col_id:
        raise ValueError("id is required")
    # Cards in this column become orphaned — put them back in the first column
    # if any, otherwise delete them.
    remaining = await ctx.db.query(
        "SELECT id FROM kanban_columns WHERE id != ? ORDER BY position ASC LIMIT 1",
        [col_id],
    )
    if remaining:
        await ctx.db.execute(
            "UPDATE items SET column_id = ? WHERE column_id = ? AND kind = 'kanban_card'",
            [remaining[0]["id"], col_id],
        )
    else:
        await ctx.db.execute(
            "DELETE FROM items WHERE column_id = ? AND kind = 'kanban_card'",
            [col_id],
        )
    await ctx.db.execute("DELETE FROM kanban_columns WHERE id = ?", [col_id])
    await ctx.notify_reload()
    return {"ok": True}


@on_action("add_card")
async def add_card(args):
    column_id = (args or {}).get("column_id", "")
    title = (args or {}).get("title", "").strip()
    if not column_id or not title:
        raise ValueError("column_id and title are required")
    # Confirm the column exists.
    col = await ctx.db.query("SELECT name FROM kanban_columns WHERE id = ?", [column_id])
    if not col:
        raise ValueError(f"unknown column_id: {column_id}")
    row = await ctx.db.query(
        "SELECT COALESCE(MAX(position), -1) AS mx FROM items WHERE column_id = ? AND kind = 'kanban_card'",
        [column_id],
    )
    next_pos = (row[0]["mx"] if row else -1) + 1
    await ctx.db.execute(
        "INSERT INTO items (id, kind, title, column_id, position) VALUES (?, 'kanban_card', ?, ?, ?)",
        [str(uuid.uuid4()), title, column_id, next_pos],
    )
    await ctx.notify_reload()
    return {"ok": True}


@on_action("move_card")
async def move_card(args):
    card_id = (args or {}).get("card_id", "")
    column_id = (args or {}).get("column_id", "")
    if not card_id or not column_id:
        raise ValueError("card_id and column_id are required")

    # Look up the current state so we can emit a meaningful timeline event.
    before = await ctx.db.query(
        "SELECT i.title, i.column_id AS from_col, c.name AS from_name "
        "FROM items i LEFT JOIN kanban_columns c ON c.id = i.column_id "
        "WHERE i.id = ? AND i.kind = 'kanban_card'",
        [card_id],
    )
    if not before:
        raise ValueError(f"unknown card_id: {card_id}")
    from_col = before[0]["from_col"]
    from_name = before[0].get("from_name")
    title = before[0]["title"]

    target = await ctx.db.query("SELECT name FROM kanban_columns WHERE id = ?", [column_id])
    if not target:
        raise ValueError(f"unknown column_id: {column_id}")
    to_name = target[0]["name"]

    # Compute next position in the destination column.
    row = await ctx.db.query(
        "SELECT COALESCE(MAX(position), -1) AS mx FROM items WHERE column_id = ? AND kind = 'kanban_card'",
        [column_id],
    )
    next_pos = (row[0]["mx"] if row else -1) + 1

    await ctx.db.execute(
        "UPDATE items SET column_id = ?, position = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ? AND kind = 'kanban_card'",
        [column_id, next_pos, card_id],
    )

    # Echo onto the timeline — but only when the card actually crossed columns.
    if from_col != column_id:
        echo_body = f"{from_name or 'Unfiled'} → {to_name}"
        await ctx.db.execute(
            "INSERT INTO items (id, kind, title, body, source_kind, source_id) "
            "VALUES (?, 'timeline_event', ?, ?, 'kanban', ?)",
            [str(uuid.uuid4()), f"Moved: {title}", echo_body, card_id],
        )

    await ctx.notify_reload()
    return {"ok": True}


@on_action("delete_card")
async def delete_card(args):
    card_id = (args or {}).get("id", "")
    if not card_id:
        raise ValueError("id is required")
    await ctx.db.execute(
        "DELETE FROM items WHERE id = ? AND kind = 'kanban_card'",
        [card_id],
    )
    await ctx.notify_reload()
    return {"ok": True}
