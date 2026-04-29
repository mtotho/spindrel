"""Project roots shared by multiple channels inside a SharedWorkspace."""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import BotConfig
from app.db.models import Channel, Project
from app.services.shared_workspace import shared_workspace_service

PROJECT_WORKSPACE_ID_KEY = "project_workspace_id"
PROJECT_PATH_KEY = "project_path"
PROJECT_KB_PATH = ".spindrel/knowledge-base"


@dataclass(frozen=True)
class ProjectDirectory:
    workspace_id: str
    path: str
    host_path: str
    project_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class WorkSurface:
    kind: Literal["project", "channel"]
    root_host_path: str
    display_path: str
    index_root_host_path: str
    index_prefix: str
    knowledge_index_prefix: str
    workspace_id: str | None
    channel_id: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    prompt: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "root_host_path": self.root_host_path,
            "display_path": self.display_path,
            "index_root_host_path": self.index_root_host_path,
            "index_prefix": self.index_prefix,
            "knowledge_index_prefix": self.knowledge_index_prefix,
            "workspace_id": self.workspace_id,
            "channel_id": self.channel_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
        }


def normalize_project_path(raw: str | None) -> str | None:
    """Normalize a workspace-relative project path."""
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


def normalize_project_slug(raw: str | None, *, fallback: str) -> str:
    value = (raw or fallback or "project").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "project"


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


def _project_directory_from_values(
    *,
    workspace_id: str,
    path: str,
    project_id: str | None = None,
    name: str | None = None,
) -> ProjectDirectory:
    root = os.path.realpath(shared_workspace_service.ensure_host_dirs(workspace_id))
    host_path = os.path.realpath(os.path.join(root, path))
    root_prefix = root.rstrip(os.sep) + os.sep
    if host_path != root and not host_path.startswith(root_prefix):
        raise ValueError("project_path must stay inside the workspace")
    os.makedirs(host_path, exist_ok=True)
    os.makedirs(os.path.join(host_path, PROJECT_KB_PATH), exist_ok=True)
    return ProjectDirectory(
        workspace_id=workspace_id,
        path=path,
        host_path=host_path,
        project_id=project_id,
        name=name,
    )


def project_directory_from_project(project: Project) -> ProjectDirectory:
    return _project_directory_from_values(
        workspace_id=str(project.workspace_id),
        path=project.root_path,
        project_id=str(project.id),
        name=project.name,
    )


def resolve_legacy_channel_project_directory(
    channel: Channel | None,
    bot: BotConfig | None = None,
) -> ProjectDirectory | None:
    cfg = _config_dict(channel)
    rel_path = normalize_project_path(cfg.get(PROJECT_PATH_KEY))
    if not rel_path:
        return None
    workspace_id = resolve_project_workspace_id(channel, bot)
    if not workspace_id:
        raise ValueError("project_path requires a resolved workspace_id")
    return _project_directory_from_values(workspace_id=workspace_id, path=rel_path)


async def resolve_channel_project_directory(
    db: AsyncSession,
    channel: Channel | None,
    bot: BotConfig | None = None,
) -> ProjectDirectory | None:
    """Resolve a channel's primary Project, falling back to legacy config."""
    if channel is None:
        return None
    project_id = getattr(channel, "project_id", None)
    if project_id:
        project = await db.get(Project, project_id)
        if project is not None:
            return project_directory_from_project(project)
    return resolve_legacy_channel_project_directory(channel, bot)


async def resolve_project_directory_for_channel_id(
    db: AsyncSession,
    channel_id: uuid.UUID | str | None,
    bot: BotConfig | None = None,
) -> ProjectDirectory | None:
    if channel_id is None:
        return None
    try:
        ch_uuid = uuid.UUID(str(channel_id))
    except ValueError:
        return None
    channel = await db.get(Channel, ch_uuid)
    return await resolve_channel_project_directory(db, channel, bot)


def project_directory_payload(project_dir: ProjectDirectory | None) -> dict[str, Any] | None:
    if project_dir is None:
        return None
    return {
        "project_id": project_dir.project_id,
        "name": project_dir.name,
        "workspace_id": project_dir.workspace_id,
        "path": project_dir.path,
        "host_path": project_dir.host_path,
    }


def project_workspace_path(project_dir: ProjectDirectory) -> str:
    return f"/workspace/{project_dir.path.strip('/')}" if project_dir.path else "/workspace"


def project_knowledge_base_index_prefix(project_dir: ProjectDirectory) -> str:
    return f"{project_dir.path.rstrip('/')}/{PROJECT_KB_PATH}".strip("/")


def _project_prompt_from_project(project: Project) -> str | None:
    pieces: list[str] = []
    if project.prompt:
        pieces.append(project.prompt.strip())
    prompt_file = normalize_project_path(project.prompt_file_path)
    if prompt_file:
        project_dir = project_directory_from_project(project)
        path = Path(project_dir.host_path) / prompt_file
        try:
            resolved = path.resolve()
            root = Path(project_dir.host_path).resolve()
            if resolved == root or root in resolved.parents:
                content = resolved.read_text().strip()
                if content:
                    pieces.append(content)
        except Exception:
            pass
    prompt = "\n\n".join(piece for piece in pieces if piece)
    return prompt or None


def work_surface_from_project_directory(
    project_dir: ProjectDirectory,
    *,
    prompt: str | None = None,
    channel_id: str | None = None,
) -> WorkSurface:
    index_root = shared_workspace_service.get_host_root(project_dir.workspace_id)
    return WorkSurface(
        kind="project",
        root_host_path=project_dir.host_path,
        display_path=project_workspace_path(project_dir),
        index_root_host_path=str(Path(index_root).resolve()),
        index_prefix=project_dir.path,
        knowledge_index_prefix=project_knowledge_base_index_prefix(project_dir),
        workspace_id=project_dir.workspace_id,
        channel_id=channel_id,
        project_id=project_dir.project_id,
        project_name=project_dir.name,
        prompt=prompt,
    )


def channel_work_surface(
    channel: Channel,
    bot: BotConfig,
) -> WorkSurface:
    from app.services.channel_workspace import (
        _get_ws_root,
        ensure_channel_workspace,
        get_channel_knowledge_base_index_prefix,
        get_channel_workspace_index_prefix,
    )

    channel_id = str(channel.id)
    root = ensure_channel_workspace(channel_id, bot, display_name=getattr(channel, "name", None))
    index_root = Path(_get_ws_root(bot)).resolve()
    return WorkSurface(
        kind="channel",
        root_host_path=root,
        display_path=f"/workspace/channels/{channel_id}",
        index_root_host_path=str(index_root),
        index_prefix=get_channel_workspace_index_prefix(channel_id),
        knowledge_index_prefix=get_channel_knowledge_base_index_prefix(channel_id),
        workspace_id=resolve_project_workspace_id(channel, bot),
        channel_id=channel_id,
    )


async def resolve_channel_work_surface(
    db: AsyncSession,
    channel: Channel | None,
    bot: BotConfig,
    *,
    include_prompt: bool = False,
) -> WorkSurface | None:
    if channel is None:
        return None
    project_id = getattr(channel, "project_id", None)
    if project_id:
        project = await db.get(Project, project_id)
        if project is not None:
            project_dir = project_directory_from_project(project)
            prompt = _project_prompt_from_project(project) if include_prompt else None
            return work_surface_from_project_directory(
                project_dir,
                prompt=prompt,
                channel_id=str(channel.id),
            )
    project_dir = resolve_legacy_channel_project_directory(channel, bot)
    if project_dir is not None:
        return work_surface_from_project_directory(
            project_dir,
            channel_id=str(channel.id),
        )
    return channel_work_surface(channel, bot)


async def resolve_channel_work_surface_by_id(
    db: AsyncSession,
    channel_id: uuid.UUID | str | None,
    bot: BotConfig,
    *,
    include_prompt: bool = False,
) -> WorkSurface | None:
    if channel_id is None:
        return None
    try:
        ch_uuid = uuid.UUID(str(channel_id))
    except ValueError:
        return None
    channel = await db.get(Channel, ch_uuid)
    return await resolve_channel_work_surface(db, channel, bot, include_prompt=include_prompt)


async def resolve_project_prompt(db: AsyncSession, channel: Channel | None) -> str | None:
    if channel is None or not getattr(channel, "project_id", None):
        return None
    project = await db.get(Project, channel.project_id)
    if project is None:
        return None
    return _project_prompt_from_project(project)


async def find_project_by_root(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID | str,
    root_path: str,
) -> Project | None:
    normalized = normalize_project_path(root_path)
    if not normalized:
        return None
    return (await db.execute(
        select(Project).where(
            Project.workspace_id == uuid.UUID(str(workspace_id)),
            Project.root_path == normalized,
        )
    )).scalar_one_or_none()
