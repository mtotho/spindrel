"""Run-scoped Docker dependency stacks for Project work."""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import DockerStack, Project, ProjectInstance, ProjectDependencyStackInstance, Task
from app.services.docker_stacks import StackError, StackValidationError, stack_service, validate_compose
from app.services.paths import local_to_host
from app.services.projects import ProjectDirectory, normalize_project_path, project_directory_from_project
from app.services.project_instances import project_directory_from_instance
from app.services.secret_registry import redact

PROJECT_DEPENDENCY_STACK_BOT_ID = "_project_dependencies"
DEFAULT_DEPENDENCY_STACK_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_COMPOSE_SOURCE_PATHS = (
    "docker-compose.project.yml",
    "docker-compose.e2e.yml",
    "compose.project.yml",
)


@dataclass(frozen=True)
class ProjectDependencyStackSpec:
    configured: bool
    source_path: str | None = None
    compose: str | None = None
    env: dict[str, str] | None = None
    commands: dict[str, str] | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot(project: Project) -> dict[str, Any]:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    snapshot = metadata.get("blueprint_snapshot")
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def project_dependency_stack_spec(project: Project) -> ProjectDependencyStackSpec:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    raw = metadata.get("dependency_stack")
    if not isinstance(raw, dict):
        raw = _snapshot(project).get("dependency_stack")
    if not isinstance(raw, dict) or raw.get("enabled") is False:
        return ProjectDependencyStackSpec(configured=False)

    compose = raw.get("compose") or raw.get("compose_definition")
    source_path = raw.get("source_path") or raw.get("compose_file") or raw.get("path")
    if source_path:
        source_path = normalize_project_path(str(source_path))
    commands = raw.get("commands") if isinstance(raw.get("commands"), dict) else {}
    env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    return ProjectDependencyStackSpec(
        configured=bool(compose or source_path or raw),
        source_path=source_path,
        compose=str(compose) if compose else None,
        env={str(key): str(value) for key, value in env.items()},
        commands={str(key): str(value) for key, value in commands.items()},
    )


def _safe_project_file(project_dir: ProjectDirectory, relative_path: str) -> Path:
    rel = normalize_project_path(relative_path)
    if not rel:
        raise ValueError("dependency stack compose source path is required")
    root = Path(project_dir.host_path).resolve()
    target = (root / rel).resolve()
    if target == root or root not in target.parents:
        raise ValueError("dependency stack compose source must stay inside the Project work surface")
    return target


def _find_default_compose(project_dir: ProjectDirectory) -> str | None:
    for rel in DEFAULT_COMPOSE_SOURCE_PATHS:
        if _safe_project_file(project_dir, rel).exists():
            return rel
    return None


def _compose_for_spec(spec: ProjectDependencyStackSpec, project_dir: ProjectDirectory) -> tuple[str, str | None]:
    if spec.compose:
        return spec.compose, spec.source_path
    source_path = spec.source_path or _find_default_compose(project_dir)
    if not source_path:
        raise ValueError("Project dependency stack is configured but no compose file exists")
    path = _safe_project_file(project_dir, source_path)
    if not path.exists():
        raise ValueError(f"Project dependency stack compose file not found: {source_path}")
    return path.read_text(encoding="utf-8"), source_path


def _dependency_stack_scratch_dir(instance_id: uuid.UUID) -> str:
    base = Path(settings.HOME_LOCAL_DIR or settings.HOME_HOST_DIR or "/tmp") / "spindrel-dependency-stacks"
    path = (base / str(instance_id)).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _render_compose_vars(compose: str, *, project: Project, project_dir: ProjectDirectory, instance_id: uuid.UUID) -> str:
    scratch = _dependency_stack_scratch_dir(instance_id)
    values = {
        "PROJECT_ROOT": local_to_host(project_dir.host_path),
        "PROJECT_SLUG": project.slug,
        "PROJECT_ID": str(project.id),
        "PROJECT_DEPENDENCY_STACK_ID": str(instance_id),
        "PROJECT_DEPENDENCY_STACK_SCRATCH": local_to_host(scratch),
    }
    rendered = compose
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
        rendered = rendered.replace("${" + key + "}", value)
    return rendered


def _validate_project_mounts(compose: str, *, project_dir: ProjectDirectory, stack_id: uuid.UUID) -> None:
    try:
        doc = yaml.safe_load(compose) or {}
    except yaml.YAMLError as exc:
        raise StackValidationError(f"Invalid YAML: {exc}") from exc
    services = doc.get("services") or {}
    root = Path(local_to_host(project_dir.host_path)).resolve()
    scratch = Path(local_to_host(_dependency_stack_scratch_dir(stack_id))).resolve()
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        for raw_volume in svc.get("volumes") or []:
            source: str | None = None
            if isinstance(raw_volume, str):
                if ":" not in raw_volume:
                    continue
                source = raw_volume.split(":", 1)[0]
            elif isinstance(raw_volume, dict):
                if raw_volume.get("type") == "volume":
                    continue
                source = raw_volume.get("source")
            if not source:
                continue
            source_text = str(source)
            if source_text.startswith((".", "~")):
                raise StackValidationError(f"Service '{svc_name}': relative host mounts are not allowed in Project dependency stacks")
            if not os.path.isabs(source_text):
                continue
            resolved = Path(source_text).resolve()
            inside_project = resolved == root or root in resolved.parents
            inside_scratch = resolved == scratch or scratch in resolved.parents
            if not inside_project and not inside_scratch:
                raise StackValidationError(f"Service '{svc_name}': host mount '{source_text}' must stay inside the Project root or dependency stack scratch")


_ENV_KEY_RE = re.compile(r"[^A-Za-z0-9]+")


def _safe_env_segment(value: str) -> str:
    cleaned = _ENV_KEY_RE.sub("_", value).strip("_").upper()
    return cleaned or "SERVICE"


def _dependency_connection_env(stack: DockerStack, spec: ProjectDependencyStackSpec) -> dict[str, str]:
    """Build env hints for agents that cannot call Docker directly.

    The agent still starts its own dev server with native bash. These values are
    only dependency endpoints for Docker-backed services such as Postgres.
    """
    host = "host.docker.internal"
    env: dict[str, str] = {
        "PROJECT_DEPENDENCY_STACK_ID": str(stack.id),
        "PROJECT_DEPENDENCY_STACK_HOST": host,
    }
    if stack.network_name:
        env["PROJECT_DEPENDENCY_STACK_NETWORK"] = str(stack.network_name)

    token_values: dict[str, str] = {
        "PROJECT_DEPENDENCY_STACK_ID": str(stack.id),
        "PROJECT_DEPENDENCY_STACK_HOST": host,
        "PROJECT_DEPENDENCY_STACK_NETWORK": str(stack.network_name or ""),
    }
    for service_name, ports in (stack.exposed_ports or {}).items():
        if not isinstance(ports, list):
            continue
        service_key = _safe_env_segment(str(service_name))
        env[f"PROJECT_DEPENDENCY_{service_key}_HOST"] = host
        token_values[f"{service_name}.host"] = host
        for port in ports:
            if not isinstance(port, dict):
                continue
            container_port = str(port.get("container_port") or "").strip()
            host_port = str(port.get("host_port") or "").strip()
            if not container_port or not host_port:
                continue
            port_key = _safe_env_segment(container_port)
            env[f"PROJECT_DEPENDENCY_{service_key}_{port_key}_PORT"] = host_port
            token_values[f"{service_name}.{container_port}"] = host_port

    for key, value in (spec.env or {}).items():
        rendered = str(value)
        for token, token_value in token_values.items():
            rendered = rendered.replace("{{" + token + "}}", token_value)
            rendered = rendered.replace("${" + token + "}", token_value)
        env[str(key)] = rendered
    return env


def _serialize(instance: ProjectDependencyStackInstance, stack: DockerStack | None = None) -> dict[str, Any]:
    payload = {
        "id": str(instance.id),
        "project_id": str(instance.project_id),
        "project_instance_id": str(instance.project_instance_id) if instance.project_instance_id else None,
        "task_id": str(instance.task_id) if instance.task_id else None,
        "docker_stack_id": str(instance.docker_stack_id) if instance.docker_stack_id else None,
        "scope": instance.scope,
        "source_path": instance.source_path,
        "status": instance.status,
        "env": dict(instance.env or {}),
        "commands": dict(instance.commands or {}),
        "last_action": instance.last_action,
        "last_result": dict(instance.last_result or {}),
        "error_message": instance.error_message,
        "expires_at": instance.expires_at.isoformat() if instance.expires_at else None,
        "created_at": instance.created_at.isoformat() if instance.created_at else None,
        "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
    }
    if stack is not None:
        payload["stack"] = {
            "id": str(stack.id),
            "name": stack.name,
            "status": stack.status,
            "project_name": stack.project_name,
            "network_name": stack.network_name,
            "container_ids": stack.container_ids or {},
            "exposed_ports": stack.exposed_ports or {},
        }
    return payload


async def _existing_instance(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    project_instance_id: uuid.UUID | None = None,
    scope: str,
) -> ProjectDependencyStackInstance | None:
    if task_id is not None:
        stmt = select(ProjectDependencyStackInstance).where(
            ProjectDependencyStackInstance.task_id == task_id,
            ProjectDependencyStackInstance.deleted_at.is_(None),
        )
    elif scope == "project_instance" and project_instance_id is not None:
        stmt = select(ProjectDependencyStackInstance).where(
            ProjectDependencyStackInstance.project_id == project_id,
            ProjectDependencyStackInstance.project_instance_id == project_instance_id,
            ProjectDependencyStackInstance.scope == scope,
            ProjectDependencyStackInstance.deleted_at.is_(None),
        )
    else:
        stmt = select(ProjectDependencyStackInstance).where(
            ProjectDependencyStackInstance.project_id == project_id,
            ProjectDependencyStackInstance.scope == scope,
            ProjectDependencyStackInstance.deleted_at.is_(None),
        )
    return (await db.execute(stmt.order_by(ProjectDependencyStackInstance.created_at.desc()).limit(1))).scalar_one_or_none()


async def get_project_dependency_stack(
    db: AsyncSession,
    project: Project,
    *,
    task_id: uuid.UUID | None = None,
    project_instance: ProjectInstance | None = None,
    scope: str = "project",
) -> dict[str, Any]:
    spec = project_dependency_stack_spec(project)
    instance = await _existing_instance(
        db,
        project_id=project.id,
        task_id=task_id,
        project_instance_id=project_instance.id if project_instance is not None else None,
        scope=scope,
    )
    stack = await db.get(DockerStack, instance.docker_stack_id) if instance and instance.docker_stack_id else None
    return {
        "configured": spec.configured,
        "spec": {
            "source_path": spec.source_path,
            "env": spec.env or {},
            "commands": spec.commands or {},
        },
        "instance": _serialize(instance, stack) if instance else None,
    }


async def ensure_project_dependency_stack_instance(
    db: AsyncSession,
    project: Project,
    *,
    task: Task | None = None,
    project_instance: ProjectInstance | None = None,
    scope: str | None = None,
) -> ProjectDependencyStackInstance:
    resolved_scope = scope or ("task" if task is not None else "project")
    existing = await _existing_instance(
        db,
        project_id=project.id,
        task_id=task.id if task is not None else None,
        project_instance_id=project_instance.id if project_instance is not None else None,
        scope=resolved_scope,
    )
    if existing is not None:
        return existing
    instance = ProjectDependencyStackInstance(
        project_id=project.id,
        project_instance_id=project_instance.id if project_instance is not None else None,
        task_id=task.id if task is not None else None,
        scope=resolved_scope,
        status="not_prepared",
        expires_at=_utcnow() + timedelta(seconds=DEFAULT_DEPENDENCY_STACK_TTL_SECONDS),
    )
    db.add(instance)
    await db.flush()
    return instance


def _safe_preflight_payload(payload: dict[str, Any]) -> dict[str, Any]:
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else payload
    env = instance.get("env") if isinstance(instance, dict) else {}
    return {
        "configured": True,
        "status": instance.get("status") if isinstance(instance, dict) else payload.get("status"),
        "instance_id": instance.get("id") if isinstance(instance, dict) else payload.get("id"),
        "scope": instance.get("scope") if isinstance(instance, dict) else payload.get("scope"),
        "source_path": instance.get("source_path") if isinstance(instance, dict) else payload.get("source_path"),
        "env_keys": sorted(str(key) for key in env) if isinstance(env, dict) else [],
        "command_keys": sorted(str(key) for key in (instance.get("commands") or {})) if isinstance(instance, dict) else [],
    }


async def preflight_task_dependency_stack(
    db: AsyncSession,
    *,
    task: Task,
    project: Project,
    project_instance: ProjectInstance | None = None,
) -> dict[str, Any]:
    """Prepare a task-scoped dependency stack before the agent receives env."""
    spec = project_dependency_stack_spec(project)
    if not spec.configured:
        return {"configured": False, "status": "not_configured", "env_keys": [], "command_keys": []}

    runtime = await ensure_project_dependency_stack_instance(
        db,
        project,
        task=task,
        project_instance=project_instance,
        scope="task",
    )
    try:
        payload = await prepare_project_dependency_stack(db, project, runtime=runtime)
        return {**_safe_preflight_payload(payload), "ok": True}
    except Exception as exc:
        await db.refresh(runtime)
        return {
            "configured": True,
            "ok": False,
            "status": runtime.status,
            "instance_id": str(runtime.id),
            "scope": runtime.scope,
            "source_path": runtime.source_path or spec.source_path,
            "env_keys": [],
            "command_keys": sorted((spec.commands or {}).keys()),
            "error": redact(str(exc))[:1000],
        }


async def _project_dir_for_dependency(project: Project, runtime: ProjectDependencyStackInstance) -> ProjectDirectory:
    if runtime.project_instance_id is not None:
        # The caller's session may have a stale project object. Load the instance
        # from a short-lived DB session owned by the stack action.
        from app.db.engine import async_session

        async with async_session() as lookup_db:
            instance = await lookup_db.get(ProjectInstance, runtime.project_instance_id)
            if instance is None:
                raise ValueError("Project dependency stack instance points at a missing Project Instance")
            return project_directory_from_instance(instance, project)
    return project_directory_from_project(project)


async def prepare_project_dependency_stack(
    db: AsyncSession,
    project: Project,
    *,
    runtime: ProjectDependencyStackInstance,
    force_recreate: bool = False,
) -> dict[str, Any]:
    spec = project_dependency_stack_spec(project)
    if not spec.configured:
        raise ValueError("Project has no dependency stack configured")
    project_dir = await _project_dir_for_dependency(project, runtime)
    compose, source_path = _compose_for_spec(spec, project_dir)
    rendered = _render_compose_vars(compose, project=project, project_dir=project_dir, instance_id=runtime.id)
    _validate_project_mounts(rendered, project_dir=project_dir, stack_id=runtime.id)
    validate_compose(rendered)

    runtime.status = "preparing"
    runtime.source_path = source_path
    runtime.commands = spec.commands or {}
    runtime.last_action = "prepare"
    runtime.error_message = None
    runtime.updated_at = _utcnow()
    await db.commit()
    await db.refresh(runtime)

    try:
        stack = await stack_service.get_by_id(runtime.docker_stack_id) if runtime.docker_stack_id else None
        if stack is None:
            stack = await stack_service.create(
                bot_id=PROJECT_DEPENDENCY_STACK_BOT_ID,
                name=f"{project.slug or project.name} deps {str(runtime.id)[:8]}",
                compose_definition=rendered,
                description=f"Project dependency stack for {project.name}",
                max_stacks=10_000,
            )
            runtime.docker_stack_id = stack.id
            stack_row = await db.get(DockerStack, stack.id)
            if stack_row is not None:
                stack_row.source = "project_dependency"
            # stack_service.start() uses its own short-lived DB sessions to
            # update the DockerStack row. Commit the link/source metadata first
            # so the caller's ORM transaction cannot hold that row lock while
            # compose starts the dependency services.
            await db.commit()
            await db.refresh(runtime)
        else:
            if stack.status == "running":
                stack = await stack_service.stop(stack)
            stack = await stack_service.update_definition(stack, rendered)
        stack = await stack_service.start(stack, force_recreate=force_recreate)
        connection_env = _dependency_connection_env(stack, spec)
        runtime.status = "running"
        runtime.env = connection_env
        runtime.last_result = {"ok": True, "stack_id": str(stack.id), "env_keys": sorted(connection_env)}
        runtime.error_message = None
        runtime.updated_at = _utcnow()
        await db.commit()
        await db.refresh(runtime)
        return _serialize(runtime, stack)
    except Exception as exc:
        runtime.status = "failed"
        runtime.error_message = redact(str(exc))[:2000]
        runtime.last_result = {"ok": False, "error": runtime.error_message}
        runtime.updated_at = _utcnow()
        await db.commit()
        await db.refresh(runtime)
        raise


async def project_dependency_stack_status(db: AsyncSession, runtime: ProjectDependencyStackInstance) -> dict[str, Any]:
    stack = await db.get(DockerStack, runtime.docker_stack_id) if runtime.docker_stack_id else None
    if stack is None:
        return _serialize(runtime)
    services = await stack_service.get_status(stack)
    return {**_serialize(runtime, stack), "services": [service.__dict__ for service in services]}


async def restart_project_dependency_stack(db: AsyncSession, runtime: ProjectDependencyStackInstance) -> dict[str, Any]:
    stack = await db.get(DockerStack, runtime.docker_stack_id) if runtime.docker_stack_id else None
    if stack is None:
        raise ValueError("Project dependency stack has not been prepared")
    stack = await stack_service.restart(stack)
    runtime.status = "running"
    runtime.last_action = "restart"
    runtime.last_result = {"ok": True, "stack_id": str(stack.id)}
    runtime.error_message = None
    runtime.updated_at = _utcnow()
    await db.commit()
    await db.refresh(runtime)
    return _serialize(runtime, stack)


async def stop_project_dependency_stack(db: AsyncSession, runtime: ProjectDependencyStackInstance) -> dict[str, Any]:
    stack = await db.get(DockerStack, runtime.docker_stack_id) if runtime.docker_stack_id else None
    if stack is None:
        raise ValueError("Project dependency stack has not been prepared")
    stack = await stack_service.stop(stack)
    runtime.status = "stopped"
    runtime.last_action = "stop"
    runtime.last_result = {"ok": True, "stack_id": str(stack.id)}
    runtime.updated_at = _utcnow()
    await db.commit()
    await db.refresh(runtime)
    return _serialize(runtime, stack)


async def project_dependency_stack_logs(
    db: AsyncSession,
    runtime: ProjectDependencyStackInstance,
    *,
    service: str | None = None,
    tail: int | None = None,
) -> dict[str, Any]:
    stack = await db.get(DockerStack, runtime.docker_stack_id) if runtime.docker_stack_id else None
    if stack is None:
        raise ValueError("Project dependency stack has not been prepared")
    logs = await stack_service.get_logs(stack, service=service, tail=tail)
    return {"ok": True, "dependency_stack": _serialize(runtime, stack), "service": service, "logs": logs}


async def exec_project_dependency_stack_command(
    db: AsyncSession,
    runtime: ProjectDependencyStackInstance,
    *,
    service: str,
    command: str,
) -> dict[str, Any]:
    stack = await db.get(DockerStack, runtime.docker_stack_id) if runtime.docker_stack_id else None
    if stack is None:
        raise ValueError("Project dependency stack has not been prepared")
    result = await stack_service.exec_in_service(stack, service, command)
    runtime.last_action = "exec"
    runtime.last_result = {
        "ok": result.exit_code == 0,
        "service": service,
        "command": command,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "truncated": result.truncated,
    }
    runtime.updated_at = _utcnow()
    await db.commit()
    await db.refresh(runtime)
    return {**runtime.last_result, "dependency_stack": _serialize(runtime, stack)}


async def health_project_dependency_stack(db: AsyncSession, runtime: ProjectDependencyStackInstance) -> dict[str, Any]:
    stack = await db.get(DockerStack, runtime.docker_stack_id) if runtime.docker_stack_id else None
    if stack is None:
        raise ValueError("Project dependency stack has not been prepared")
    services = await stack_service.get_status(stack)
    service_payloads = [service.__dict__ for service in services]
    ok = bool(services) and all(
        (service.state or "").lower() in {"running", "restarting"}
        and ((service.health or "").lower() in {"", "healthy"} or service.health is None)
        for service in services
    )
    result = {"ok": ok, "services": service_payloads}
    runtime.last_action = "health"
    runtime.last_result = result
    runtime.updated_at = _utcnow()
    await db.commit()
    await db.refresh(runtime)
    return {**result, "dependency_stack": _serialize(runtime, stack)}


async def destroy_project_dependency_stack(db: AsyncSession, runtime: ProjectDependencyStackInstance, *, keep_volumes: bool = False) -> dict[str, Any]:
    stack = await db.get(DockerStack, runtime.docker_stack_id) if runtime.docker_stack_id else None
    if stack is not None:
        try:
            await stack_service.destroy(stack, remove_volumes=not keep_volumes)
        except StackError as exc:
            runtime.error_message = redact(str(exc))[:2000]
            await db.commit()
            raise
    runtime.status = "deleted"
    runtime.deleted_at = _utcnow()
    runtime.last_action = "destroy"
    runtime.last_result = {"ok": True, "volumes_preserved": keep_volumes}
    runtime.updated_at = _utcnow()
    await db.commit()
    await db.refresh(runtime)
    return _serialize(runtime)
