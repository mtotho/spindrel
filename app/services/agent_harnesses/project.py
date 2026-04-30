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
    WorkSurface,
    is_project_like_surface,
    normalize_project_path,
    project_directory_payload,
    resolve_legacy_channel_project_directory,
    resolve_project_workspace_id,
    resolve_channel_work_surface,
)
from app.services.workspace import workspace_service


@dataclass(frozen=True)
class HarnessPathResolution:
    workdir: str
    source: str
    bot_workspace_dir: str
    project_dir: ProjectDirectory | None = None
    work_surface: WorkSurface | None = None


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
    surface = await resolve_channel_work_surface(db, channel, bot) if channel is not None else None
    if surface is not None:
        is_project_surface = is_project_like_surface(surface)
        project_dir = ProjectDirectory(
            workspace_id=str(surface.workspace_id or ""),
            path=surface.index_prefix,
            host_path=surface.root_host_path,
            project_id=surface.project_id,
            project_instance_id=surface.project_instance_id,
            name=surface.project_name,
        ) if is_project_surface else None
        return HarnessPathResolution(
            workdir=surface.root_host_path,
            source=(
                "project_instance"
                if surface.kind == "project_instance"
                else "channel_project_dir"
                if surface.kind == "project"
                else "channel_work_surface"
            ),
            bot_workspace_dir=bot_workspace_dir,
            project_dir=project_dir,
            work_surface=surface,
        )
    if bot.harness_workdir:
        return HarnessPathResolution(
            workdir=bot.harness_workdir,
            source="bot_harness_workdir",
            bot_workspace_dir=bot_workspace_dir,
            project_dir=None,
            work_surface=surface,
        )
    return HarnessPathResolution(
        workdir=bot_workspace_dir,
        source="bot_workspace",
        bot_workspace_dir=bot_workspace_dir,
        project_dir=None,
        work_surface=surface,
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
