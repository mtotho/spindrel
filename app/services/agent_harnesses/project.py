"""Channel project-directory helpers for native agent harnesses."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig
from app.db.models import Channel
from app.services.agent_harnesses.base import HarnessContextHint
from app.services.shared_workspace import shared_workspace_service
from app.services.workspace import workspace_service

PROJECT_WORKSPACE_ID_KEY = "project_workspace_id"
PROJECT_PATH_KEY = "project_path"


@dataclass(frozen=True)
class ProjectDirectory:
    workspace_id: str
    path: str
    host_path: str


@dataclass(frozen=True)
class HarnessPathResolution:
    workdir: str
    source: str
    bot_workspace_dir: str
    project_dir: ProjectDirectory | None = None


def normalize_project_path(raw: str | None) -> str | None:
    """Normalize a workspace-relative project path.

    Stored paths are relative to the shared workspace root. Absolute paths and
    parent traversal are rejected so a channel cannot escape its workspace.
    """
    if raw is None:
        return None
    value = str(raw).strip().replace("\\", "/")
    if not value or value in {".", "/"}:
        return None
    if value.startswith("/"):
        value = value.lstrip("/")
    parts = [part for part in value.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError("project_path must stay inside the workspace")
    return "/".join(parts) or None


def _config_dict(channel: Channel | None) -> dict[str, Any]:
    if channel is None or not isinstance(channel.config, dict):
        return {}
    return dict(channel.config)


def resolve_project_workspace_id(channel: Channel | None, bot: BotConfig | None = None) -> str | None:
    cfg = _config_dict(channel)
    raw = cfg.get(PROJECT_WORKSPACE_ID_KEY)
    if raw:
        return str(raw)
    if channel is not None and channel.workspace_id:
        return str(channel.workspace_id)
    if bot is not None and bot.shared_workspace_id:
        return str(bot.shared_workspace_id)
    return None


def resolve_channel_project_directory(channel: Channel | None, bot: BotConfig | None = None) -> ProjectDirectory | None:
    cfg = _config_dict(channel)
    rel_path = normalize_project_path(cfg.get(PROJECT_PATH_KEY))
    if not rel_path:
        return None
    workspace_id = resolve_project_workspace_id(channel, bot)
    if not workspace_id:
        raise ValueError("project_path requires a resolved workspace_id")
    root = os.path.realpath(shared_workspace_service.ensure_host_dirs(workspace_id))
    host_path = os.path.realpath(os.path.join(root, rel_path))
    root_prefix = root.rstrip(os.sep) + os.sep
    if host_path != root and not host_path.startswith(root_prefix):
        raise ValueError("project_path must stay inside the workspace")
    os.makedirs(host_path, exist_ok=True)
    return ProjectDirectory(workspace_id=workspace_id, path=rel_path, host_path=host_path)


def project_directory_payload(project_dir: ProjectDirectory | None) -> dict[str, Any] | None:
    if project_dir is None:
        return None
    return {
        "workspace_id": project_dir.workspace_id,
        "path": project_dir.path,
        "host_path": project_dir.host_path,
    }


async def resolve_harness_paths(
    db: AsyncSession,
    *,
    channel_id: uuid.UUID | None,
    bot: BotConfig,
) -> HarnessPathResolution:
    bot_workspace_dir = workspace_service.ensure_host_dir(bot.id, bot)
    channel = await db.get(Channel, channel_id) if channel_id is not None else None
    project_dir = resolve_channel_project_directory(channel, bot)
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
