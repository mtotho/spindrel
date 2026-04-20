"""MC Tasks handlers — task CRUD + promote-to-kanban.

Shares its SQLite DB with `mc_timeline` and `mc_kanban` via the Mission
Control suite (see `suites/mission-control/suite.yaml`).
"""
from __future__ import annotations

import uuid

from spindrel.widget import ctx, on_action


@on_action("add_task")
async def add_task(args):
    title = (args or {}).get("title", "").strip()
    if not title:
        raise ValueError("title is required")
    row = await ctx.db.query(
        "SELECT COALESCE(MAX(position), -1) AS mx FROM items WHERE kind = 'task'"
    )
    next_pos = (row[0]["mx"] if row else -1) + 1
    await ctx.db.execute(
        "INSERT INTO items (id, kind, title, position) VALUES (?, 'task', ?, ?)",
        [str(uuid.uuid4()), title, next_pos],
    )
    await ctx.notify_reload()
    return {"ok": True}


@on_action("toggle_done")
async def toggle_done(args):
    task_id = (args or {}).get("id", "")
    if not task_id:
        raise ValueError("id is required")
    rows = await ctx.db.query(
        "SELECT done FROM items WHERE id = ? AND kind = 'task'",
        [task_id],
    )
    if not rows:
        raise ValueError(f"unknown task id: {task_id}")
    new_done = 0 if rows[0]["done"] else 1
    await ctx.db.execute(
        "UPDATE items SET done = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ? AND kind = 'task'",
        [new_done, task_id],
    )
    await ctx.notify_reload()
    return {"ok": True, "done": bool(new_done)}


@on_action("delete_task")
async def delete_task(args):
    task_id = (args or {}).get("id", "")
    if not task_id:
        raise ValueError("id is required")
    await ctx.db.execute(
        "DELETE FROM items WHERE id = ? AND kind = 'task'", [task_id],
    )
    await ctx.notify_reload()
    return {"ok": True}


@on_action("promote_to_card")
async def promote_to_card(args):
    """Copy a task into the leftmost kanban column as a kanban_card.

    The original task row stays — the user can still tick it off separately
    (or delete it). Useful when a task graduates into active work.
    """
    task_id = (args or {}).get("id", "")
    if not task_id:
        raise ValueError("id is required")
    tasks = await ctx.db.query(
        "SELECT title FROM items WHERE id = ? AND kind = 'task'",
        [task_id],
    )
    if not tasks:
        raise ValueError(f"unknown task id: {task_id}")

    cols = await ctx.db.query(
        "SELECT id, name FROM kanban_columns ORDER BY position ASC LIMIT 1"
    )
    if not cols:
        raise ValueError(
            "no kanban columns exist yet — pin the MC Kanban widget and seed it first"
        )
    column_id = cols[0]["id"]
    column_name = cols[0]["name"]

    pos_row = await ctx.db.query(
        "SELECT COALESCE(MAX(position), -1) AS mx FROM items "
        "WHERE column_id = ? AND kind = 'kanban_card'",
        [column_id],
    )
    next_pos = (pos_row[0]["mx"] if pos_row else -1) + 1

    await ctx.db.execute(
        "INSERT INTO items (id, kind, title, column_id, position, source_kind, source_id) "
        "VALUES (?, 'kanban_card', ?, ?, ?, 'tasks', ?)",
        [str(uuid.uuid4()), tasks[0]["title"], column_id, next_pos, task_id],
    )
    # Timeline echo.
    await ctx.db.execute(
        "INSERT INTO items (id, kind, title, body, source_kind, source_id) "
        "VALUES (?, 'timeline_event', ?, ?, 'tasks', ?)",
        [
            str(uuid.uuid4()),
            f"Promoted: {tasks[0]['title']}",
            f"Tasks → Kanban ({column_name})",
            task_id,
        ],
    )
    await ctx.notify_reload()
    return {"ok": True, "column": column_name}
