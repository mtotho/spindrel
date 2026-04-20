"""Agent tools for creating and managing persistent todos."""
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, delete

from app.agent.context import current_bot_id, current_channel_id
from app.db.engine import async_session
from app.db.models import Todo
from app.tools.registry import register


def _get_scope():
    """Return (bot_id, channel_id) from context, raising on missing values."""
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()
    if not bot_id:
        return None, None, "Error: no bot_id in context."
    if not channel_id:
        return None, None, "Error: no channel_id in context."
    return bot_id, channel_id, None


@register({
    "type": "function",
    "function": {
        "name": "create_todo",
        "description": "Create a new todo item. Use for tracking work that persists across conversations.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The todo text."
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority level (0=normal, higher=more important). Defaults to 0."
                }
            },
            "required": ["content"]
        }
    }
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "content": {"type": "string"},
        "status": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def create_todo(content: str, priority: int = 0) -> str:
    priority = int(priority)
    bot_id, channel_id, err = _get_scope()
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    if not content or not content.strip():
        return json.dumps({"error": "content must not be empty."}, ensure_ascii=False)

    now = datetime.now(timezone.utc)
    todo = Todo(
        bot_id=bot_id,
        channel_id=channel_id,
        content=content.strip(),
        status="pending",
        priority=priority,
        created_at=now,
        updated_at=now,
    )
    async with async_session() as db:
        db.add(todo)
        await db.commit()
        await db.refresh(todo)

    return json.dumps({"id": str(todo.id), "content": todo.content, "status": "pending"}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "list_todos",
        "description": "List todo items for this bot and channel. Defaults to pending items, ordered by priority (highest first).",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: pending, done, or all.",
                    "enum": ["pending", "done", "all"]
                }
            },
            "required": []
        }
    }
}, requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "count": {"type": "integer"},
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "content": {"type": "string"},
                    "status": {"type": "string"},
                    "priority": {"type": "integer"},
                },
                "required": ["id", "content", "status", "priority"],
            },
        },
        "error": {"type": "string"},
    },
    "required": ["count", "todos"],
})
async def list_todos(status: str = "pending") -> str:
    bot_id, channel_id, err = _get_scope()
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    async with async_session() as db:
        stmt = (
            select(Todo)
            .where(Todo.bot_id == bot_id, Todo.channel_id == channel_id)
            .order_by(Todo.priority.desc(), Todo.created_at.asc())
        )
        if status != "all":
            stmt = stmt.where(Todo.status == status)
        todos = (await db.execute(stmt)).scalars().all()

    items = [{"id": str(t.id), "content": t.content, "status": t.status, "priority": t.priority} for t in todos]
    return json.dumps({"count": len(items), "todos": items}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "complete_todo",
        "description": "Mark a todo as done by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "todo_id": {
                    "type": "string",
                    "description": "UUID of the todo to complete."
                }
            },
            "required": ["todo_id"]
        }
    }
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "todo_id": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def complete_todo(todo_id: str) -> str:
    try:
        tid = uuid.UUID(todo_id)
    except ValueError:
        return json.dumps({"error": f"invalid todo_id: {todo_id}"}, ensure_ascii=False)

    bot_id, channel_id, err = _get_scope()
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    async with async_session() as db:
        todo = await db.get(Todo, tid)
        if not todo or todo.bot_id != bot_id or todo.channel_id != channel_id:
            return json.dumps({"error": f"todo {todo_id} not found."}, ensure_ascii=False)
        todo.status = "done"
        todo.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return json.dumps({"ok": True, "todo_id": todo_id}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "update_todo",
        "description": "Update a todo's content, priority, or status.",
        "parameters": {
            "type": "object",
            "properties": {
                "todo_id": {
                    "type": "string",
                    "description": "UUID of the todo to update."
                },
                "content": {
                    "type": "string",
                    "description": "New content text."
                },
                "priority": {
                    "type": "integer",
                    "description": "New priority level."
                },
                "status": {
                    "type": "string",
                    "description": "New status.",
                    "enum": ["pending", "done"]
                }
            },
            "required": ["todo_id"]
        }
    }
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "todo_id": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def update_todo(todo_id: str, content: str | None = None,
                      priority: int | None = None, status: str | None = None) -> str:
    try:
        tid = uuid.UUID(todo_id)
    except ValueError:
        return json.dumps({"error": f"invalid todo_id: {todo_id}"}, ensure_ascii=False)

    bot_id, channel_id, err = _get_scope()
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    async with async_session() as db:
        todo = await db.get(Todo, tid)
        if not todo or todo.bot_id != bot_id or todo.channel_id != channel_id:
            return json.dumps({"error": f"todo {todo_id} not found."}, ensure_ascii=False)
        if content is not None:
            todo.content = content
        if priority is not None:
            priority = int(priority)
            todo.priority = priority
        if status is not None:
            todo.status = status
        todo.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return json.dumps({"ok": True, "todo_id": todo_id}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "delete_todo",
        "description": "Delete a todo by ID. Use for removing items that are no longer relevant.",
        "parameters": {
            "type": "object",
            "properties": {
                "todo_id": {
                    "type": "string",
                    "description": "UUID of the todo to delete."
                }
            },
            "required": ["todo_id"]
        }
    }
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "todo_id": {"type": "string"},
        "error": {"type": "string"},
    },
})
async def delete_todo(todo_id: str) -> str:
    try:
        tid = uuid.UUID(todo_id)
    except ValueError:
        return json.dumps({"error": f"invalid todo_id: {todo_id}"}, ensure_ascii=False)

    bot_id, channel_id, err = _get_scope()
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    async with async_session() as db:
        todo = await db.get(Todo, tid)
        if not todo or todo.bot_id != bot_id or todo.channel_id != channel_id:
            return json.dumps({"error": f"todo {todo_id} not found."}, ensure_ascii=False)
        await db.delete(todo)
        await db.commit()

    return json.dumps({"ok": True, "todo_id": todo_id}, ensure_ascii=False)
