"""Memory scheme bootstrap and management.

Creates the memory/ directory structure for bots using the workspace-files
memory scheme.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)

MEMORY_DIR = "memory"
LOGS_DIR = os.path.join(MEMORY_DIR, "logs")
REFERENCE_DIR = os.path.join(MEMORY_DIR, "reference")

MEMORY_MD_TEMPLATE = """\
# Memory

_Curated stable facts, preferences, and key decisions._
_Keep under ~100 lines. Edit in place._

## User Preferences
_Updated: {date}_

(No preferences recorded yet.)

## Key Decisions
_Updated: {date}_

(No decisions recorded yet.)
"""


def get_memory_rel_path(bot: BotConfig) -> str:
    """Return the relative path to memory/ from the bot's workspace root.

    For shared workspace orchestrators, memory is scoped to a per-bot
    subdirectory (``bots/{bot_id}/memory``) to avoid collisions when
    multiple orchestrators share the same workspace root.
    """
    if bot.shared_workspace_id and getattr(bot, "shared_workspace_role", None) == "orchestrator":
        return os.path.join("bots", bot.id, MEMORY_DIR)
    return MEMORY_DIR


def bootstrap_memory_scheme(bot: BotConfig, *, ws_root: str | None = None) -> str:
    """Create memory directory structure for a bot.

    Returns the absolute path to the memory/ directory.
    Idempotent — safe to call multiple times.
    """
    from app.services.workspace import workspace_service

    if ws_root is None:
        ws_root = workspace_service.get_workspace_root(bot.id, bot)

    os.makedirs(ws_root, exist_ok=True)

    rel = get_memory_rel_path(bot)
    memory_root = os.path.join(ws_root, rel)
    logs_dir = os.path.join(memory_root, "logs")
    reference_dir = os.path.join(memory_root, "reference")

    os.makedirs(memory_root, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(reference_dir, exist_ok=True)

    # Create MEMORY.md if it doesn't exist
    memory_md = os.path.join(memory_root, "MEMORY.md")
    if not os.path.exists(memory_md):
        from datetime import date
        content = MEMORY_MD_TEMPLATE.format(date=date.today().isoformat())
        Path(memory_md).write_text(content)
        logger.info("Created bootstrap MEMORY.md at %s", memory_md)

    return memory_root


def get_memory_root(bot: BotConfig, *, ws_root: str | None = None) -> str:
    """Return the absolute path to the bot's memory/ directory."""
    from app.services.workspace import workspace_service
    if ws_root is None:
        ws_root = workspace_service.get_workspace_root(bot.id, bot)
    return os.path.join(ws_root, get_memory_rel_path(bot))
