"""Mission Control bot tools — kanban board management via tasks.md."""
from __future__ import annotations

import re
import uuid

from integrations import _register as reg


# ---------------------------------------------------------------------------
# tasks.md parser/serializer — shared between tools and dashboard
# ---------------------------------------------------------------------------

def _generate_card_id() -> str:
    """Generate a short card ID like mc-a1b2c3."""
    return f"mc-{uuid.uuid4().hex[:6]}"


def _parse_card(raw: str) -> dict:
    """Parse a single card block (everything after ### Title)."""
    lines = raw.strip().splitlines()
    if not lines:
        return {"title": "", "meta": {}, "description": ""}

    title = lines[0].strip()
    meta: dict[str, str] = {}
    desc_lines: list[str] = []
    in_desc = False

    for line in lines[1:]:
        m = re.match(r"^- \*\*(\w+)\*\*:\s*(.*)$", line)
        if m and not in_desc:
            meta[m.group(1)] = m.group(2).strip()
        else:
            in_desc = True
            desc_lines.append(line)

    return {
        "title": title,
        "meta": meta,
        "description": "\n".join(desc_lines).strip(),
    }


def _serialize_card(card: dict) -> str:
    """Serialize a card dict back to markdown."""
    lines = [f"### {card['title']}"]
    for key, value in card["meta"].items():
        lines.append(f"- **{key}**: {value}")
    if card.get("description"):
        lines.append("")
        lines.append(card["description"])
    return "\n".join(lines)


def parse_tasks_md(content: str) -> list[dict]:
    """Parse tasks.md into a list of columns with cards.

    Returns: [{"name": "Backlog", "cards": [{"title": ..., "meta": {...}, "description": ...}, ...]}, ...]
    """
    columns: list[dict] = []

    # Split by ## headers (columns)
    parts = re.split(r"(?m)^## ", content)

    for part in parts[1:]:  # skip preamble before first ##
        lines = part.split("\n", 1)
        col_name = lines[0].strip()
        col_body = lines[1] if len(lines) > 1 else ""

        cards: list[dict] = []
        card_parts = re.split(r"(?m)^### ", col_body)

        for card_raw in card_parts[1:]:  # skip text before first ###
            card = _parse_card(card_raw)
            if card["title"]:
                cards.append(card)

        columns.append({"name": col_name, "cards": cards})

    return columns


def serialize_tasks_md(columns: list[dict]) -> str:
    """Serialize columns back to tasks.md format."""
    lines = ["# Tasks", ""]

    for col in columns:
        lines.append(f"## {col['name']}")
        lines.append("")
        for card in col.get("cards", []):
            lines.append(_serialize_card(card))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _default_columns() -> list[dict]:
    """Default kanban columns for a new tasks.md."""
    return [
        {"name": "Backlog", "cards": []},
        {"name": "In Progress", "cards": []},
        {"name": "Review", "cards": []},
        {"name": "Done", "cards": []},
    ]


async def _read_tasks_md(channel_id: str) -> tuple[str, list[dict]]:
    """Read and parse tasks.md for a channel. Creates it if missing."""
    from app.agent.bots import get_bot
    from app.services.channel_workspace import read_workspace_file

    # Try to find the bot for this channel
    bot = None
    try:
        from app.db.session import async_session_factory
        from app.db.models import Channel
        async with async_session_factory() as db:
            ch = await db.get(Channel, channel_id)
            if ch:
                bot = get_bot(ch.bot_id)
    except Exception:
        bot = get_bot("default")

    if bot is None:
        bot = get_bot("default")

    content = read_workspace_file(channel_id, bot, "tasks.md")
    if content:
        return content, parse_tasks_md(content)

    # No tasks.md yet — return default structure
    columns = _default_columns()
    return serialize_tasks_md(columns), columns


async def _write_tasks_md(channel_id: str, columns: list[dict]) -> str:
    """Serialize and write tasks.md for a channel."""
    from app.agent.bots import get_bot
    from app.services.channel_workspace import (
        ensure_channel_workspace,
        write_workspace_file,
    )

    bot = None
    try:
        from app.db.session import async_session_factory
        from app.db.models import Channel
        async with async_session_factory() as db:
            ch = await db.get(Channel, channel_id)
            if ch:
                bot = get_bot(ch.bot_id)
    except Exception:
        bot = get_bot("default")

    if bot is None:
        bot = get_bot("default")

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

    card_id = _generate_card_id()
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
