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
    project_instance_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class WorkSurface:
    kind: Literal["project", "project_instance", "channel"]
    root_host_path: str
    display_path: str
    index_root_host_path: str
    index_prefix: str
    knowledge_index_prefix: str
    workspace_id: str | None
    channel_id: str | None = None
    project_id: str | None = None
    project_instance_id: str | None = None
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
            "project_instance_id": self.project_instance_id,
            "project_name": self.project_name,
        }


class WorkSurfaceResolutionError(ValueError):
    """Raised when a claimed Project/instance work surface cannot be resolved."""


def is_project_like_surface(surface: WorkSurface | None) -> bool:
    return surface is not None and surface.kind in {"project", "project_instance"}


def _uuid_values_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return uuid.UUID(str(left)) == uuid.UUID(str(right))
    except (TypeError, ValueError):
        return str(left) == str(right)


def ensure_path_within_work_surface(surface: WorkSurface, host_path: str) -> str:
    """Validate that a host path stays inside the active WorkSurface root."""
    root = os.path.realpath(surface.root_host_path)
    resolved = os.path.realpath(host_path)
    if resolved != root and not resolved.startswith(root.rstrip(os.sep) + os.sep):
        label = "Project instance" if surface.kind == "project_instance" else "Project"
        display_path = getattr(surface, "display_path", surface.root_host_path)
        raise WorkSurfaceResolutionError(
            f"{label} path must stay inside the active Project work surface: {display_path}"
        )
    return resolved


def resolve_work_surface_host_path(surface: WorkSurface, raw_path: str | None) -> str:
    """Resolve an optional cwd/path under the active WorkSurface root."""
    value = (raw_path or "").strip()
    if not value:
        return os.path.realpath(surface.root_host_path)
    if value.startswith("/workspace/") or value == "/workspace":
        if not surface.workspace_id:
            raise WorkSurfaceResolutionError("Project WorkSurface is missing a workspace id")
        target = shared_workspace_service.translate_path(str(surface.workspace_id), value)
    elif os.path.isabs(value):
        target = value
    else:
        target = os.path.join(surface.root_host_path, value)
    return ensure_path_within_work_surface(surface, target)


@dataclass(frozen=True)
class ProjectBlueprintMaterialization:
    folders_created: list[str]
    files_written: list[str]
    files_skipped: list[str]
    knowledge_files_written: list[str]
    knowledge_files_skipped: list[str]

    def payload(self) -> dict[str, list[str]]:
        return {
            "folders_created": self.folders_created,
            "files_written": self.files_written,
            "files_skipped": self.files_skipped,
            "knowledge_files_written": self.knowledge_files_written,
            "knowledge_files_skipped": self.knowledge_files_skipped,
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


def render_project_blueprint_root_path(
    pattern: str | None,
    *,
    project_name: str,
    project_slug: str,
) -> str:
    """Render a blueprint root path pattern into a workspace-relative path."""
    template = (pattern or "common/projects/{slug}").strip()
    path_name = normalize_project_slug(None, fallback=project_name)
    rendered = (
        template
        .replace("{project_slug}", project_slug)
        .replace("{slug}", project_slug)
        .replace("{project_name}", path_name)
        .replace("{name}", path_name)
    )
    normalized = normalize_project_path(rendered)
    if not normalized:
        raise ValueError("blueprint root path pattern produced an empty path")
    return normalized


def project_canonical_repo_entry(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the canonical repo dict from a blueprint snapshot.

    Resolution rule (Phase 4BD.0): the entry with ``canonical: true`` wins.
    If none is flagged, fall back to the first repo in the list. Returns None
    when the snapshot has no repos.
    """
    if not isinstance(snapshot, dict):
        return None
    repos = snapshot.get("repos")
    if not isinstance(repos, list) or not repos:
        return None
    typed = [repo for repo in repos if isinstance(repo, dict)]
    if not typed:
        return None
    for repo in typed:
        if repo.get("canonical") is True:
            return repo
    return typed[0]


def project_canonical_repo_relative_path(snapshot: dict[str, Any] | None) -> str | None:
    """Relative path of the canonical repo within the Project work surface."""
    repo = project_canonical_repo_entry(snapshot)
    if repo is None:
        return None
    raw = repo.get("path")
    if not isinstance(raw, str):
        return None
    return normalize_project_path(raw)


def project_canonical_repo_host_path(project: Any, snapshot: dict[str, Any] | None = None) -> str | None:
    """Absolute on-disk path of the canonical repo for a Project, or None.

    Used by skills that need to write durable artifacts (intake file, PRDs,
    Run Pack files) into the *actual git repo*, not the Spindrel-managed
    work-surface bowl that may contain several sibling repos.
    """
    if snapshot is None:
        metadata = getattr(project, "metadata_", None)
        snapshot = metadata.get("blueprint_snapshot") if isinstance(metadata, dict) else None
    rel = project_canonical_repo_relative_path(snapshot)
    if rel is None:
        return None
    project_dir = project_directory_from_project(project)
    return str(Path(project_dir.host_path) / rel)


def project_repo_host_path(project: Any, repo_path: str | None = None, snapshot: dict[str, Any] | None = None) -> str | None:
    """Absolute on-disk path for an explicit or canonical Project repo."""
    if snapshot is None:
        metadata = getattr(project, "metadata_", None)
        snapshot = metadata.get("blueprint_snapshot") if isinstance(metadata, dict) else None
    rel = normalize_project_path(repo_path) if repo_path else project_canonical_repo_relative_path(snapshot)
    if rel is None:
        return None
    project_dir = project_directory_from_project(project)
    root = Path(project_dir.host_path).resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        return None
    return str(target)


def validate_blueprint_repos_canonical(repos: list[dict[str, Any]] | None) -> None:
    """Enforce the at-most-one-canonical invariant on a repos list.

    Raises ValueError when more than one entry carries ``canonical: true``.
    """
    if not isinstance(repos, list):
        return
    canonical = [repo for repo in repos if isinstance(repo, dict) and repo.get("canonical") is True]
    if len(canonical) > 1:
        raise ValueError(
            "At most one repo entry may be marked canonical. Found "
            f"{len(canonical)}: {[repo.get('path') for repo in canonical]}"
        )


PROJECT_INTAKE_KINDS: tuple[str, ...] = (
    "unset",
    "repo_file",
    "repo_folder",
    "external_tracker",
)


def normalize_project_intake_kind(value: Any) -> str:
    """Validate and normalize an intake kind. Raises ValueError on bad input."""
    if value is None:
        return "unset"
    if not isinstance(value, str):
        raise ValueError("intake_kind must be a string")
    candidate = value.strip().lower()
    if candidate not in PROJECT_INTAKE_KINDS:
        raise ValueError(
            f"intake_kind must be one of {', '.join(PROJECT_INTAKE_KINDS)}; got {value!r}"
        )
    return candidate


def project_intake_config(project: Any) -> dict[str, Any]:
    """Return the resolved intake config for a Project as a JSON-safe dict.

    Always returns the full shape so agents can branch on `kind` without
    having to defend against missing keys. `target` is None when unset; for
    repo-relative kinds, `host_target` is the absolute on-disk path resolved
    against the canonical repo (None when no canonical repo or target).
    """
    kind = getattr(project, "intake_kind", None) or "unset"
    target = getattr(project, "intake_target", None)
    metadata = dict(getattr(project, "intake_metadata", None) or {})
    host_target: str | None = None
    if kind in {"repo_file", "repo_folder"} and target:
        canonical_host = project_canonical_repo_host_path(project)
        if canonical_host:
            normalized = target.lstrip("/").rstrip()
            if normalized:
                host_target = str(Path(canonical_host) / normalized)
    return {
        "kind": kind,
        "target": target,
        "metadata": metadata,
        "host_target": host_target,
        "configured": kind != "unset",
    }


def project_blueprint_snapshot(blueprint: Any) -> dict[str, Any]:
    snapshot = {
        "id": str(blueprint.id),
        "name": blueprint.name,
        "slug": blueprint.slug,
        "default_root_path_pattern": getattr(blueprint, "default_root_path_pattern", None),
        "prompt_file_path": getattr(blueprint, "prompt_file_path", None),
        "folders": list(getattr(blueprint, "folders", None) or []),
        "files": dict(getattr(blueprint, "files", None) or {}),
        "knowledge_files": dict(getattr(blueprint, "knowledge_files", None) or {}),
        "repos": list(getattr(blueprint, "repos", None) or []),
        "setup_commands": list(getattr(blueprint, "setup_commands", None) or []),
        "dependency_stack": dict(getattr(blueprint, "dependency_stack", None) or {}),
        "env": dict(getattr(blueprint, "env", None) or {}),
        "required_secrets": list(getattr(blueprint, "required_secrets", None) or []),
        "metadata": dict(getattr(blueprint, "metadata_", None) or {}),
    }
    # Phase 4BB.3 - orchestration policy fields. Only emit when set so legacy
    # snapshots stay byte-identical and consumers fall back to defaults.
    for field in ("stall_timeout_seconds", "turn_timeout_seconds", "max_concurrent_runs"):
        value = getattr(blueprint, field, None)
        if value is not None:
            snapshot[field] = value
    return snapshot


def _blueprint_relative_path(raw: Any, *, field: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{field} path must be a string")
    normalized = normalize_project_path(raw)
    if not normalized:
        raise ValueError(f"{field} path is required")
    return normalized


def _safe_materialized_path(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if target == resolved_root or resolved_root not in target.parents:
        raise ValueError("blueprint path must stay inside the Project root")
    return target


def materialize_project_blueprint(
    project_dir: ProjectDirectory,
    blueprint: Any,
) -> ProjectBlueprintMaterialization:
    """Create v0 blueprint folders and starter files without overwriting files."""
    root = Path(project_dir.host_path)
    folders_created: list[str] = []
    files_written: list[str] = []
    files_skipped: list[str] = []
    knowledge_files_written: list[str] = []
    knowledge_files_skipped: list[str] = []

    for folder in blueprint.folders or []:
        rel = _blueprint_relative_path(folder, field="folder")
        _safe_materialized_path(root, rel).mkdir(parents=True, exist_ok=True)
        folders_created.append(rel)

    for raw_path, raw_content in (blueprint.files or {}).items():
        rel = _blueprint_relative_path(raw_path, field="file")
        target = _safe_materialized_path(root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            files_skipped.append(rel)
            continue
        target.write_text(str(raw_content), encoding="utf-8")
        files_written.append(rel)

    kb_root = root / PROJECT_KB_PATH
    kb_root.mkdir(parents=True, exist_ok=True)
    for raw_path, raw_content in (blueprint.knowledge_files or {}).items():
        rel = _blueprint_relative_path(raw_path, field="knowledge file")
        target = _safe_materialized_path(kb_root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            knowledge_files_skipped.append(rel)
            continue
        target.write_text(str(raw_content), encoding="utf-8")
        knowledge_files_written.append(rel)

    return ProjectBlueprintMaterialization(
        folders_created=folders_created,
        files_written=files_written,
        files_skipped=files_skipped,
        knowledge_files_written=knowledge_files_written,
        knowledge_files_skipped=knowledge_files_skipped,
    )


class _SnapshotBlueprint:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.folders = list(snapshot.get("folders") or [])
        self.files = dict(snapshot.get("files") or {})
        self.knowledge_files = dict(snapshot.get("knowledge_files") or {})


def materialize_project_blueprint_snapshot(
    project_dir: ProjectDirectory,
    snapshot: dict[str, Any],
) -> ProjectBlueprintMaterialization:
    return materialize_project_blueprint(project_dir, _SnapshotBlueprint(snapshot))


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
    project_instance_id: str | None = None,
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
        project_instance_id=project_instance_id,
        name=name,
    )


def project_directory_from_project(project: Project) -> ProjectDirectory:
    return _project_directory_from_values(
        workspace_id=str(project.workspace_id),
        path=project.root_path,
        project_id=str(project.id),
        name=project.name,
    )


def project_directory_from_instance_values(
    *,
    workspace_id: uuid.UUID | str,
    root_path: str,
    project_id: uuid.UUID | str,
    project_instance_id: uuid.UUID | str,
    name: str | None = None,
) -> ProjectDirectory:
    return _project_directory_from_values(
        workspace_id=str(workspace_id),
        path=root_path,
        project_id=str(project_id),
        project_instance_id=str(project_instance_id),
        name=name,
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
        "project_instance_id": project_dir.project_instance_id,
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
    kind: Literal["project", "project_instance"] = "project",
) -> WorkSurface:
    index_root = shared_workspace_service.get_host_root(project_dir.workspace_id)
    return WorkSurface(
        kind=kind,
        root_host_path=project_dir.host_path,
        display_path=project_workspace_path(project_dir),
        index_root_host_path=str(Path(index_root).resolve()),
        index_prefix=project_dir.path,
        knowledge_index_prefix=project_knowledge_base_index_prefix(project_dir),
        workspace_id=project_dir.workspace_id,
        channel_id=channel_id,
        project_id=project_dir.project_id,
        project_instance_id=project_dir.project_instance_id,
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
    session_id: uuid.UUID | str | None = None,
) -> WorkSurface | None:
    expected_project_id = getattr(channel, "project_id", None) if channel is not None else None
    instance_surface = await _resolve_context_project_instance_surface(
        db,
        channel_id=str(channel.id) if channel is not None else None,
        expected_project_id=expected_project_id,
        include_prompt=include_prompt,
        session_id=session_id,
    )
    if instance_surface is not None:
        return instance_surface
    if channel is None:
        return None
    project_id = getattr(channel, "project_id", None)
    if project_id:
        project = await db.get(Project, project_id)
        if project is None:
            raise WorkSurfaceResolutionError(
                f"Project binding is broken: Project {project_id} was not found"
            )
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
    session_id: uuid.UUID | str | None = None,
) -> WorkSurface | None:
    if channel_id is None:
        return None
    try:
        ch_uuid = uuid.UUID(str(channel_id))
    except ValueError:
        return None
    channel = await db.get(Channel, ch_uuid)
    return await resolve_channel_work_surface(
        db,
        channel,
        bot,
        include_prompt=include_prompt,
        session_id=session_id,
    )


async def _resolve_context_project_instance_surface(
    db: AsyncSession,
    *,
    channel_id: str | None,
    expected_project_id: uuid.UUID | str | None,
    include_prompt: bool,
    session_id: uuid.UUID | str | None = None,
) -> WorkSurface | None:
    instance_id: uuid.UUID | None = None
    context_session_id: uuid.UUID | None = None
    try:
        from app.agent.context import current_project_instance_id, current_session_id

        instance_id = current_project_instance_id.get()
        context_session_id = current_session_id.get()
    except Exception:
        pass

    explicit_session_id: uuid.UUID | None = None
    if session_id is not None:
        try:
            explicit_session_id = uuid.UUID(str(session_id))
        except ValueError:
            explicit_session_id = None

    if instance_id is None and explicit_session_id is not None:
        from app.db.models import Session

        session = await db.get(Session, explicit_session_id)
        instance_id = getattr(session, "project_instance_id", None) if session is not None else None

    if instance_id is None and context_session_id is not None:
        from app.db.models import Session

        session = await db.get(Session, context_session_id)
        instance_id = getattr(session, "project_instance_id", None) if session is not None else None
    if instance_id is None:
        return None

    from app.db.models import ProjectInstance
    from app.services.project_instances import (
        INSTANCE_STATUS_READY,
        project_directory_from_instance,
    )

    instance = await db.get(ProjectInstance, instance_id)
    if instance is None:
        raise WorkSurfaceResolutionError(
            f"Project instance binding is broken: instance {instance_id} was not found"
        )
    if instance.status != INSTANCE_STATUS_READY or instance.deleted_at is not None:
        raise WorkSurfaceResolutionError(
            f"Project instance {instance_id} is not ready for this work surface"
        )
    if channel_id is not None and expected_project_id is None:
        raise WorkSurfaceResolutionError(
            "Project instance work surfaces require a Project-bound channel"
        )
    if expected_project_id is not None and not _uuid_values_equal(instance.project_id, expected_project_id):
        raise WorkSurfaceResolutionError(
            f"Project instance {instance_id} does not belong to channel Project {expected_project_id}"
        )
    project = await db.get(Project, instance.project_id)
    if project is None:
        raise WorkSurfaceResolutionError(
            f"Project instance binding is broken: Project {instance.project_id} was not found"
        )
    prompt = _project_prompt_from_project(project) if include_prompt else None
    return work_surface_from_project_directory(
        project_directory_from_instance(instance, project),
        prompt=prompt,
        channel_id=channel_id,
        kind="project_instance",
    )


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
