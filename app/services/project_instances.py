"""Fresh Project work surfaces created from frozen Project snapshots."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Project, ProjectInstance, ProjectSecretBinding, Session
from app.services.project_setup import (
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCEEDED,
    build_project_setup_plan_from_snapshot,
    execute_project_setup_plan,
    resolve_project_secret_env,
)
from app.services.projects import (
    ProjectDirectory,
    WorkSurface,
    materialize_project_blueprint_snapshot,
    project_directory_from_instance_values,
    work_surface_from_project_directory,
)
from app.services.secret_registry import redact


INSTANCE_ROOT_PREFIX = "common/project-instances"
DEFAULT_PROJECT_INSTANCE_TTL_SECONDS = 7 * 24 * 60 * 60
INSTANCE_STATUS_PREPARING = "preparing"
INSTANCE_STATUS_READY = "ready"
INSTANCE_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class ProjectInstancePolicy:
    mode: str = "shared"

    @property
    def fresh(self) -> bool:
        return self.mode == "fresh"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def task_project_instance_policy(execution_config: dict[str, Any] | None) -> ProjectInstancePolicy:
    raw = (execution_config or {}).get("project_instance") or {}
    if isinstance(raw, dict) and raw.get("mode") == "fresh":
        return ProjectInstancePolicy(mode="fresh")
    if bool((execution_config or {}).get("fresh_project_instance")):
        return ProjectInstancePolicy(mode="fresh")
    return ProjectInstancePolicy()


def project_instance_root_path(project: Project, instance_id: uuid.UUID) -> str:
    slug = project.slug or str(project.id)
    return f"{INSTANCE_ROOT_PREFIX}/{slug}/{str(instance_id)[:12]}"


def project_instance_snapshot(project: Project) -> dict[str, Any]:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    snapshot = metadata.get("blueprint_snapshot")
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def project_directory_from_instance(instance: ProjectInstance, project: Project | None = None) -> ProjectDirectory:
    return project_directory_from_instance_values(
        workspace_id=instance.workspace_id,
        root_path=instance.root_path,
        project_id=instance.project_id,
        project_instance_id=instance.id,
        name=project.name if project is not None else None,
    )


def work_surface_from_project_instance(
    instance: ProjectInstance,
    project: Project,
    *,
    channel_id: uuid.UUID | str | None = None,
    prompt: str | None = None,
) -> WorkSurface:
    return work_surface_from_project_directory(
        project_directory_from_instance(instance, project),
        prompt=prompt,
        channel_id=str(channel_id) if channel_id is not None else None,
        kind="project_instance",
    )


async def list_project_instances(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    limit: int = 25,
) -> list[ProjectInstance]:
    return list((await db.execute(
        select(ProjectInstance)
        .where(ProjectInstance.project_id == project_id)
        .order_by(ProjectInstance.created_at.desc())
        .limit(limit)
    )).scalars().all())


async def load_project_bindings(db: AsyncSession, project_id: uuid.UUID) -> list[ProjectSecretBinding]:
    return list((await db.execute(
        select(ProjectSecretBinding)
        .options(selectinload(ProjectSecretBinding.secret_value))
        .where(ProjectSecretBinding.project_id == project_id)
        .order_by(ProjectSecretBinding.logical_name)
    )).scalars().all())


async def create_project_instance(
    db: AsyncSession,
    project: Project,
    *,
    owner_kind: str = "manual",
    owner_id: uuid.UUID | None = None,
    ttl_seconds: int = DEFAULT_PROJECT_INSTANCE_TTL_SECONDS,
    metadata: dict[str, Any] | None = None,
) -> ProjectInstance:
    snapshot = project_instance_snapshot(project)
    if not snapshot:
        raise ValueError("Project does not have an applied blueprint snapshot")

    instance_id = uuid.uuid4()
    instance = ProjectInstance(
        id=instance_id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        root_path=project_instance_root_path(project, instance_id),
        status=INSTANCE_STATUS_PREPARING,
        source="blueprint_snapshot",
        source_snapshot=snapshot,
        owner_kind=owner_kind,
        owner_id=owner_id,
        expires_at=_utcnow() + timedelta(seconds=max(60, int(ttl_seconds))),
        metadata_=metadata or {},
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)

    try:
        project_dir = project_directory_from_instance(instance, project)
        materialized = materialize_project_blueprint_snapshot(project_dir, snapshot)
        bindings = await load_project_bindings(db, project.id)
        plan = build_project_setup_plan_from_snapshot(
            project_id=project.id,
            snapshot=snapshot,
            bindings=bindings,
        )
        secret_env = await resolve_project_secret_env(db, project.id)
        if plan.get("ready"):
            setup_result = await execute_project_setup_plan(
                plan,
                project_root=project_dir.host_path,
                secret_env=secret_env,
            )
        else:
            setup_result = {
                "status": RUN_STATUS_SUCCEEDED if "empty_setup" in (plan.get("reasons") or []) else RUN_STATUS_FAILED,
                "repos": [],
                "commands": [],
                "logs": ["No setup work declared."] if "empty_setup" in (plan.get("reasons") or []) else ["Setup plan is not ready."],
                "plan": plan,
            }
        instance.setup_result = setup_result
        instance.metadata_ = {
            **(instance.metadata_ or {}),
            "materialization": materialized.payload(),
            "setup_plan": plan,
        }
        instance.status = INSTANCE_STATUS_READY if setup_result.get("status") == RUN_STATUS_SUCCEEDED else INSTANCE_STATUS_FAILED
    except Exception as exc:
        instance.status = INSTANCE_STATUS_FAILED
        instance.setup_result = {"status": RUN_STATUS_FAILED, "error": redact(str(exc))}
    instance.updated_at = _utcnow()
    await db.commit()
    await db.refresh(instance)
    return instance


async def bind_fresh_project_instance_for_task(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    channel_id: uuid.UUID | None,
    execution_config: dict[str, Any] | None,
) -> ProjectInstance | None:
    if not task_project_instance_policy(execution_config).fresh or channel_id is None:
        return None
    from app.db.models import Channel, Task

    channel = await db.get(Channel, channel_id)
    project_id = getattr(channel, "project_id", None) if channel is not None else None
    if project_id is None:
        raise ValueError("Fresh Project instance requires a Project-bound channel")
    project = await db.get(Project, project_id)
    if project is None:
        raise ValueError("Fresh Project instance requires an existing Project")
    instance = await create_project_instance(
        db,
        project,
        owner_kind="task",
        owner_id=task_id,
    )
    task = await db.get(Task, task_id)
    if task is not None:
        task.project_instance_id = instance.id
        await db.commit()
    if instance.status != INSTANCE_STATUS_READY:
        raise ValueError("Fresh Project instance setup failed")
    return instance


async def bind_fresh_project_instance_to_session(
    db: AsyncSession,
    *,
    session: Session,
    project: Project,
) -> ProjectInstance:
    instance = await create_project_instance(
        db,
        project,
        owner_kind="session",
        owner_id=session.id,
    )
    session.project_instance_id = instance.id
    await db.commit()
    await db.refresh(instance)
    if instance.status != INSTANCE_STATUS_READY:
        raise ValueError("Fresh Project instance setup failed")
    return instance


async def resolve_session_project_instance(
    db: AsyncSession,
    session_id: uuid.UUID | str | None,
) -> ProjectInstance | None:
    if session_id is None:
        return None
    try:
        session_uuid = uuid.UUID(str(session_id))
    except ValueError:
        return None
    session = await db.get(Session, session_uuid)
    if session is None or session.project_instance_id is None:
        return None
    return await db.get(ProjectInstance, session.project_instance_id)
