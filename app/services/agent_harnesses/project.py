"""Channel Project helpers for native agent harnesses.

Compatibility wrapper around ``app.services.projects``. New code should import
from ``app.services.projects`` unless it specifically needs harness path
resolution.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig
from app.db.models import Channel
from app.services.agent_harnesses.base import HarnessContextHint
from app.services.projects import (
    PROJECT_PATH_KEY,
    PROJECT_WORKSPACE_ID_KEY,
    ProjectDirectory,
    normalize_project_path,
    project_directory_payload,
    resolve_legacy_channel_project_directory,
    resolve_project_workspace_id,
    resolve_channel_project_directory as resolve_channel_project_directory_async,
)
from app.services.workspace import workspace_service


@dataclass(frozen=True)
class HarnessPathResolution:
    workdir: str
    source: str
    bot_workspace_dir: str
    project_dir: ProjectDirectory | None = None


def resolve_channel_project_directory(channel: Channel | None, bot: BotConfig | None = None) -> ProjectDirectory | None:
    """Legacy sync resolver for channel.config project_path only."""
    return resolve_legacy_channel_project_directory(channel, bot)


async def resolve_harness_paths(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID | None,
    bot: BotConfig,
) -> HarnessPathResolution:
    bot_workspace_dir = workspace_service.ensure_host_dir(bot.id, bot)
    channel = await db.get(Channel, channel_id) if channel_id is not None else None
    project_dir = await resolve_channel_project_directory_async(db, channel, bot)
    if project_dir is not None:
        return HarnessPathResolution(
            workdir=project_dir.host_path,
            source="channel_project_dir",
            bot_workspace_dir=bot_workspace_dir,
            project_dir=project_dir,
        )
    if bot.harness_workdir:
        return HarnessPathResolution(
            workdir=bot.harness_workdir,
            source="bot_harness_workdir",
            bot_workspace_dir=bot_workspace_dir,
            project_dir=None,
        )
    return HarnessPathResolution(
        workdir=bot_workspace_dir,
        source="bot_workspace",
        bot_workspace_dir=bot_workspace_dir,
        project_dir=None,
    )


def build_workspace_files_memory_hint(bot: BotConfig, bot_workspace_dir: str) -> HarnessContextHint | None:
    if getattr(bot, "memory_scheme", None) != "workspace-files":
        return None
    return HarnessContextHint(
        kind="workspace_files_memory",
        source="spindrel",
        created_at=datetime.now(timezone.utc).isoformat(),
        consume_after_next_turn=False,
        text=(
            "Spindrel workspace-files memory is enabled for this harness bot. "
            f"The bot workspace is {bot_workspace_dir}. Treat memory files in this workspace "
            "as durable host-provided context when they exist. Use bridged Spindrel "
            "file or memory tools to inspect or update them; if no bridge tool is "
            "available, ask before assuming current memory contents."
        ),
    )
