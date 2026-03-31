"""Mission Control bot tools — kanban board management via tasks.md."""
from __future__ import annotations

import logging

from integrations import _register as reg
from app.services.task_board import (
    generate_card_id,
    parse_tasks_md,
    serialize_tasks_md,
    default_columns,
)

logger = logging.getLogger(__name__)


async def _resolve_bot(channel_id: str):
    """Resolve the bot config for a channel. Falls back to first available bot."""
    import uuid as _uuid
    from app.agent.bots import get_bot, list_bots
    try:
        from app.db.engine import async_session
        from app.db.models import Channel
        async with async_session() as db:
            ch = await db.get(Channel, _uuid.UUID(channel_id))
            if ch:
                return get_bot(ch.bot_id)
    except Exception:
        logger.warning("Could not resolve bot for channel %s, falling back", channel_id, exc_info=True)
    # Fallback: try "default", then first available bot
    try:
        return get_bot("default")
    except Exception:
        bots = list_bots()
        if bots:
            return bots[0]
        raise ValueError("No bots configured — cannot resolve workspace path")


async def _read_tasks_md(channel_id: str) -> tuple[str, list[dict]]:
    """Read and parse tasks.md for a channel. Creates it if missing."""
    from app.services.channel_workspace import read_workspace_file

    bot = await _resolve_bot(channel_id)
    content = read_workspace_file(channel_id, bot, "tasks.md")
    if content:
        return content, parse_tasks_md(content)

    # No tasks.md yet — return default structure
    columns = default_columns()
    return serialize_tasks_md(columns), columns


async def _write_tasks_md(channel_id: str, columns: list[dict]) -> str:
    """Serialize and write tasks.md for a channel."""
    from app.services.channel_workspace import (
        ensure_channel_workspace,
        write_workspace_file,
    )

    bot = await _resolve_bot(channel_id)
    ensure_channel_workspace(channel_id, bot)
    content = serialize_tasks_md(columns)
    write_workspace_file(channel_id, bot, "tasks.md", content)
    return content


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@reg.register({"type": "function", "function": {
    "name": "create_task_card",
    "description": (
        "Create a new task card in the channel's tasks.md kanban board. "
        "The card is added to the specified column (default: Backlog)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Channel UUID"},
            "title": {"type": "string", "description": "Task card title"},
            "column": {
                "type": "string",
                "description": "Target column name (default: Backlog)",
                "default": "Backlog",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
                "description": "Priority level (default: medium)",
                "default": "medium",
            },
            "assigned": {
                "type": "string",
                "description": "Bot or person assigned to this task",
            },
            "tags": {
                "type": "string",
                "description": "Comma-separated tags",
            },
            "due": {
                "type": "string",
                "description": "Due date (YYYY-MM-DD format)",
            },
            "description": {
                "type": "string",
                "description": "Task description (free text)",
            },
        },
        "required": ["channel_id", "title"],
    },
}})
async def create_task_card(
    channel_id: str,
    title: str,
    column: str = "Backlog",
    priority: str = "medium",
    assigned: str = "",
    tags: str = "",
    due: str = "",
    description: str = "",
) -> str:
    """Create a new task card in the channel's tasks.md kanban board."""
    from datetime import date

    _raw, columns = await _read_tasks_md(channel_id)

    # Find or create target column
    target_col = None
    for col in columns:
        if col["name"].lower() == column.lower():
            target_col = col
            break

    if target_col is None:
        target_col = {"name": column, "cards": []}
        # Insert before Done if it exists, else append
        done_idx = next((i for i, c in enumerate(columns) if c["name"].lower() == "done"), None)
        if done_idx is not None:
            columns.insert(done_idx, target_col)
        else:
            columns.append(target_col)

    card_id = generate_card_id()
    meta: dict[str, str] = {"id": card_id}
    if assigned:
        meta["assigned"] = assigned
    meta["priority"] = priority
    meta["created"] = date.today().isoformat()
    if tags:
        meta["tags"] = tags
    if due:
        meta["due"] = due

    card = {"title": title, "meta": meta, "description": description}
    target_col["cards"].append(card)

    await _write_tasks_md(channel_id, columns)
    return f"Created task card '{title}' (id: {card_id}) in column '{target_col['name']}'"


@reg.register({"type": "function", "function": {
    "name": "move_task_card",
    "description": (
        "Move a task card to a different kanban column in the channel's tasks.md. "
        "Identifies the card by its mc-XXXXXX id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Channel UUID"},
            "task_id": {"type": "string", "description": "Task card ID (e.g. mc-a1b2c3)"},
            "to_column": {"type": "string", "description": "Target column name"},
        },
        "required": ["channel_id", "task_id", "to_column"],
    },
}})
async def move_task_card(
    channel_id: str,
    task_id: str,
    to_column: str,
) -> str:
    """Move a task card to a different kanban column."""
    from datetime import date

    _raw, columns = await _read_tasks_md(channel_id)

    # Find the card
    found_card = None
    source_col_name = None
    for col in columns:
        for i, card in enumerate(col["cards"]):
            if card["meta"].get("id") == task_id:
                found_card = col["cards"].pop(i)
                source_col_name = col["name"]
                break
        if found_card:
            break

    if not found_card:
        return f"Task card '{task_id}' not found in tasks.md"

    # Find or create target column
    target_col = None
    for col in columns:
        if col["name"].lower() == to_column.lower():
            target_col = col
            break

    if target_col is None:
        target_col = {"name": to_column, "cards": []}
        columns.append(target_col)

    # Add transition metadata
    if to_column.lower() == "in progress":
        found_card["meta"]["started"] = date.today().isoformat()
    elif to_column.lower() == "done":
        found_card["meta"]["completed"] = date.today().isoformat()

    target_col["cards"].append(found_card)
    await _write_tasks_md(channel_id, columns)
    return f"Moved '{found_card['title']}' from '{source_col_name}' to '{target_col['name']}'"
