"""Todo widget handlers — one focused list per pin.

Exposes four ``@on_action`` handlers that are also bot-callable (see
``widget.yaml`` ``handlers:`` block). Runs under the pin's ``source_bot_id``
regardless of who invokes — the iframe user or a bot in the channel.
"""
from __future__ import annotations

import uuid

from spindrel.widget import ctx, on_action


def _serialize(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "done": bool(row["done"]),
        "position": int(row["position"]),
    }


@on_action("list_todos")
async def list_todos(args):
    rows = await ctx.db.query(
        "SELECT id, title, done, position, updated_at FROM todos "
        "ORDER BY done ASC, position ASC, datetime(updated_at) DESC"
    )
    return [_serialize(r) for r in rows]


@on_action("add_todo")
async def add_todo(args):
    title = ((args or {}).get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    if len(title) > 500:
        raise ValueError("title is too long (max 500 chars)")

    row = await ctx.db.query(
        "SELECT COALESCE(MAX(position), -1) AS mx FROM todos WHERE done = 0"
    )
    next_pos = (row[0]["mx"] if row else -1) + 1
    todo_id = str(uuid.uuid4())
    await ctx.db.execute(
        "INSERT INTO todos (id, title, position) VALUES (?, ?, ?)",
        [todo_id, title, next_pos],
    )
    await ctx.notify_reload()
    return {"id": todo_id, "title": title}


@on_action("toggle_done")
async def toggle_done(args):
    todo_id = ((args or {}).get("id") or "").strip()
    if not todo_id:
        raise ValueError("id is required")
    rows = await ctx.db.query(
        "SELECT done FROM todos WHERE id = ?", [todo_id],
    )
    if not rows:
        raise ValueError(f"unknown todo id: {todo_id}")
    new_done = 0 if rows[0]["done"] else 1
    await ctx.db.execute(
        "UPDATE todos SET done = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "WHERE id = ?",
        [new_done, todo_id],
    )
    await ctx.notify_reload()
    return {"id": todo_id, "done": bool(new_done)}


@on_action("delete_todo")
async def delete_todo(args):
    todo_id = ((args or {}).get("id") or "").strip()
    if not todo_id:
        raise ValueError("id is required")
    rows = await ctx.db.query(
        "SELECT id FROM todos WHERE id = ?", [todo_id],
    )
    if not rows:
        return {"id": todo_id, "deleted": False}
    await ctx.db.execute("DELETE FROM todos WHERE id = ?", [todo_id])
    await ctx.notify_reload()
    return {"id": todo_id, "deleted": True}
