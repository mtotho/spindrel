"""Mission Control bot tools — kanban board management via tasks.md + timeline.

Thin wrappers around integrations.mission_control.services.
"""
from __future__ import annotations

import logging

from integrations import sdk as reg
from integrations.mission_control.services import (
    append_timeline,
    create_card,
    move_card,
    parse_timeline_md,
)

logger = logging.getLogger(__name__)

# Re-export for backward compatibility (router + tools/plans.py import these)
_append_timeline = append_timeline


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
    result = await create_card(
        channel_id, title, column=column, priority=priority,
        assigned=assigned, tags=tags, due=due, description=description,
    )
    return f"Created task card '{title}' (id: {result['card_id']}) in column '{result['column']}'"


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
    try:
        result = await move_card(channel_id, task_id, to_column)
    except ValueError as e:
        return str(e)
    return f"Moved '{result['card']['title']}' from '{result['from_column']}' to '{result['to_column']}'"


@reg.register({"type": "function", "function": {
    "name": "append_timeline_event",
    "description": (
        "Log a notable event to the channel's timeline.md activity log. "
        "Use for deployments, decisions, meetings, milestones, incidents, "
        "or any significant event worth recording. "
        "Task card moves and creation are auto-logged — you don't need to "
        "call this tool for those."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "Channel UUID"},
            "event": {
                "type": "string",
                "description": (
                    "Short description of the event. "
                    "Use **bold** for emphasis. Examples: "
                    "'Deployed v2.1.0 to production', "
                    "'DEC-005 recorded: \"Use Redis for caching\"', "
                    "'Sprint 5 retrospective completed — all 6 cards delivered'"
                ),
            },
        },
        "required": ["channel_id", "event"],
    },
}})
async def append_timeline_event(
    channel_id: str,
    event: str,
) -> str:
    """Log a notable event to the channel's timeline.md activity log."""
    await append_timeline(channel_id, event)
    return f"Logged timeline event: {event}"
