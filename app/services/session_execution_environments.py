"""Per-session execution environment lifecycle.

The session remains the product primitive; this module attaches optional
filesystem and Docker isolation to a normal Session row.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectInstance, Session, SessionExecutionEnvironment
from app.services.project_instances import project_directory_from_instance
from app.services.projects import (
    project_canonical_repo_host_path,
    project_canonical_repo_relative_path,
    project_directory_from_project,
)


MODE_SHARED = "shared"
MODE_ISOLATED = "isolated"
STATUS_PREPARING = "preparing"
STATUS_READY = "ready"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"
STATUS_DELETED = "deleted"

DEFAULT_ISOLATED_TTL_SECONDS = 24 * 60 * 60
DEFAULT_MAX_ACTIVE_ISOLATED = 4


@dataclass(frozen=True)
class SessionExecutionRuntime:
    mode: str
    status: str
    cwd: str | None
    env: dict[str, str]
    hint: str | None
    record: SessionExecutionEnvironment | None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _max_active_isolated() -> int:
    raw = os.environ.get("SPINDREL_SESSION_DOCKER_MAX_ACTIVE")
    try:
        return max(1, int(raw)) if raw else DEFAULT_MAX_ACTIVE_ISOLATED
    except ValueError:
        return DEFAULT_MAX_ACTIVE_ISOLATED


def _docker_image() -> str:
    return os.environ.get("SPINDREL_SESSION_DOCKER_IMAGE") or "docker:29-dind"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _container_name(session_id: uuid.UUID) -> str:
    short = str(session_id).replace("-", "")[:12]
    return f"spindrel-session-docker-{short}"


def _state_volume_name(session_id: uuid.UUID) -> str:
    return f"{_container_name(session_id)}-state"


async def get_session_execution_environment(
    db: AsyncSession,
    session_id: uuid.UUID | str,
) -> SessionExecutionEnvironment | None:
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError:
        return None
    return (await db.execute(
        select(SessionExecutionEnvironment)
        .where(
            SessionExecutionEnvironment.session_id == sid,
            SessionExecutionEnvironment.deleted_at.is_(None),
        )
        .order_by(SessionExecutionEnvironment.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()


async def list_session_execution_environments(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    stmt = (
        select(SessionExecutionEnvironment)
        .where(SessionExecutionEnvironment.deleted_at.is_(None))
        .order_by(SessionExecutionEnvironment.updated_at.desc())
        .limit(max(1, min(int(limit or 100), 500)))
    )
    if status:
        stmt = stmt.where(SessionExecutionEnvironment.status == status)
    rows = list((await db.execute(stmt)).scalars().all())
    return {
        "capacity": {
            "active": await _active_isolated_count(db),
            "max_active": _max_active_isolated(),
        },
        "environments": [session_execution_environment_out(row, session_id=row.session_id) for row in rows],
    }


async def _active_isolated_count(db: AsyncSession) -> int:
    return int((await db.execute(
        select(func.count(SessionExecutionEnvironment.id)).where(
            SessionExecutionEnvironment.mode == MODE_ISOLATED,
            SessionExecutionEnvironment.status.in_((STATUS_PREPARING, STATUS_READY)),
            SessionExecutionEnvironment.deleted_at.is_(None),
        )
    )).scalar_one() or 0)


def _session_project_cwd(instance: ProjectInstance | None, project: Project | None) -> str | None:
    if instance is None or project is None:
        return None
    project_dir = project_directory_from_instance(instance, project)
    return str(Path(project_dir.host_path).resolve())


def _slug(value: str | None, *, fallback: str = "session", max_len: int = 48) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").lower()).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return (text or fallback)[:max_len].strip("-") or fallback


def _project_workspace_host_root(project: Project) -> Path:
    project_dir = Path(project_directory_from_project(project).host_path).resolve()
    root_parts = tuple(part for part in str(project.root_path or "").replace("\\", "/").split("/") if part)
    if root_parts and tuple(project_dir.parts[-len(root_parts):]) == root_parts:
        return Path(*project_dir.parts[:-len(root_parts)])
    for parent in project_dir.parents:
        if parent.name == "shared":
            return parent
    return project_dir.parent


def _session_worktree_path(
    project: Project,
    *,
    source_repo: Path,
    session_id: uuid.UUID,
) -> Path:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    snapshot = metadata.get("blueprint_snapshot") if isinstance(metadata, dict) else None
    repo_rel = project_canonical_repo_relative_path(snapshot)
    rel = Path(repo_rel) if repo_rel else Path(source_repo.name)
    short = str(session_id).replace("-", "")[:12]
    return (
        _project_workspace_host_root(project)
        / "common"
        / "session-worktrees"
        / _slug(project.slug or project.name or str(project.id), fallback="project")
        / short
        / rel
    ).resolve()


def _git(cwd: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(cwd), *args], timeout=timeout)


def _default_branch_name(session_id: uuid.UUID) -> str:
    return f"spindrel/session-{str(session_id).replace('-', '')[:12]}"


def _prepare_session_worktree(
    project: Project | None,
    *,
    session_id: uuid.UUID,
    branch: str | None = None,
    base_branch: str | None = None,
) -> dict[str, Any] | None:
    if project is None:
        return None
    raw_source = project_canonical_repo_host_path(project)
    if not raw_source:
        return None
    source = Path(raw_source).resolve()
    if not source.exists():
        return None
    top = _git(source, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return None
    source = Path(top.stdout.strip() or source).resolve()
    target = _session_worktree_path(project, source_repo=source, session_id=session_id)
    resolved_branch = (branch or "").strip() or _default_branch_name(session_id)
    base_ref = (base_branch or "").strip() or "HEAD"

    if target.exists() and (target / ".git").exists():
        sha = _git(target, "rev-parse", "HEAD")
        return {
            "kind": "git_worktree",
            "source_repo": str(source),
            "worktree_path": str(target),
            "branch": resolved_branch,
            "base_ref": base_ref,
            "created_sha": sha.stdout.strip() if sha.returncode == 0 else None,
            "reused": True,
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    if base_branch:
        _git(source, "fetch", "--quiet", "origin", base_branch, timeout=180)
    branch_exists = _git(source, "show-ref", "--verify", f"refs/heads/{resolved_branch}")
    if branch_exists.returncode == 0:
        add = _git(source, "worktree", "add", str(target), resolved_branch, timeout=180)
    else:
        add = _git(source, "worktree", "add", "-b", resolved_branch, str(target), base_ref, timeout=180)
        if add.returncode != 0 and base_ref != "HEAD":
            add = _git(source, "worktree", "add", "-b", resolved_branch, str(target), "HEAD", timeout=180)
            base_ref = "HEAD"
    if add.returncode != 0:
        detail = (add.stderr or add.stdout or "").strip()
        raise RuntimeError(detail or f"git worktree add exited with {add.returncode}")
    sha = _git(target, "rev-parse", "HEAD")
    return {
        "kind": "git_worktree",
        "source_repo": str(source),
        "worktree_path": str(target),
        "branch": resolved_branch,
        "base_ref": base_ref,
        "created_sha": sha.stdout.strip() if sha.returncode == 0 else None,
        "reused": False,
    }


def _inspect_container(name: str) -> dict[str, Any] | None:
    proc = _run(["docker", "inspect", name], timeout=30)
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return None


def _docker_payload_from_inspect(session_id: uuid.UUID, info: dict[str, Any]) -> dict[str, Any]:
    state = info.get("State") if isinstance(info.get("State"), dict) else {}
    network = info.get("NetworkSettings") if isinstance(info.get("NetworkSettings"), dict) else {}
    ports = network.get("Ports") if isinstance(network.get("Ports"), dict) else {}
    binding = None
    for candidate in (ports.get("2375/tcp"), ports.get("2375")):
        if isinstance(candidate, list) and candidate:
            binding = candidate[0]
            break
    port = None
    if isinstance(binding, dict) and binding.get("HostPort"):
        try:
            port = int(str(binding["HostPort"]))
        except ValueError:
            port = None
    mounts = info.get("Mounts") if isinstance(info.get("Mounts"), list) else []
    volume = _state_volume_name(session_id)
    for mount in mounts:
        if isinstance(mount, dict) and mount.get("Destination") == "/var/lib/docker" and mount.get("Name"):
            volume = str(mount["Name"])
            break
    return {
        "endpoint": f"tcp://127.0.0.1:{port}" if port else None,
        "container_id": str(info.get("Id") or ""),
        "container_name": _container_name(session_id),
        "state_volume": volume,
        "port": port,
        "state": "running" if state.get("Running") else (state.get("Status") or "unknown"),
    }


def _run_new_docker_daemon(session_id: uuid.UUID) -> dict[str, Any]:
    if os.environ.get("SPINDREL_SESSION_DOCKER_DISABLED") == "1":
        raise RuntimeError("per-session Docker daemon is disabled by SPINDREL_SESSION_DOCKER_DISABLED")

    name = _container_name(session_id)
    volume = _state_volume_name(session_id)
    port = _find_free_port()
    endpoint = f"tcp://127.0.0.1:{port}"
    args = [
        "docker",
        "run",
        "-d",
        "--privileged",
        "--name",
        name,
        "--label",
        f"spindrel.session_id={session_id}",
        "--label",
        "spindrel.kind=session-docker-daemon",
        "-e",
        "DOCKER_TLS_CERTDIR=",
        "-p",
        f"127.0.0.1:{port}:2375",
        "-v",
        f"{volume}:/var/lib/docker",
        _docker_image(),
        "dockerd",
        "--host=tcp://0.0.0.0:2375",
        "--host=unix:///var/run/docker.sock",
    ]
    proc = _run(args, timeout=120)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"docker daemon container exited with {proc.returncode}")
    return {
        "endpoint": endpoint,
        "container_id": proc.stdout.strip(),
        "container_name": name,
        "state_volume": volume,
        "port": port,
        "state": "running",
    }


def _start_docker_daemon(session_id: uuid.UUID) -> dict[str, Any]:
    name = _container_name(session_id)
    info = _inspect_container(name)
    if info is not None:
        payload = _docker_payload_from_inspect(session_id, info)
        if payload.get("state") == "running" and payload.get("endpoint"):
            return payload
        proc = _run(["docker", "start", name], timeout=120)
        if proc.returncode == 0:
            refreshed = _inspect_container(name)
            if refreshed is not None:
                payload = _docker_payload_from_inspect(session_id, refreshed)
                if payload.get("endpoint"):
                    return payload
        _run(["docker", "rm", "-f", name], timeout=60)
    return _run_new_docker_daemon(session_id)


def _apply_docker_payload(env: SessionExecutionEnvironment, docker: dict[str, Any], *, status: str = STATUS_READY) -> None:
    env.status = status
    env.docker_endpoint = docker.get("endpoint")
    env.docker_container_id = docker.get("container_id")
    env.docker_container_name = docker.get("container_name")
    env.docker_state_volume = docker.get("state_volume")
    env.docker_status = str(docker.get("state") or "running")
    metadata = dict(env.metadata_ or {})
    metadata["docker"] = docker
    env.metadata_ = metadata
    env.updated_at = _utcnow()


async def ensure_isolated_session_environment(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    project: Project | None = None,
    project_instance: ProjectInstance | None = None,
    branch: str | None = None,
    base_branch: str | None = None,
    ttl_seconds: int = DEFAULT_ISOLATED_TTL_SECONDS,
) -> SessionExecutionEnvironment:
    existing = await get_session_execution_environment(db, session_id)
    if existing is not None and existing.mode == MODE_ISOLATED and existing.status == STATUS_READY:
        return existing
    if existing is not None and existing.mode != MODE_ISOLATED:
        raise ValueError("session already has a non-isolated execution environment")

    active_count = await _active_isolated_count(db)
    if existing is None and active_count >= _max_active_isolated():
        raise RuntimeError(f"isolated session capacity reached ({active_count}/{_max_active_isolated()})")

    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError("session not found")
    if project_instance is None and session.project_instance_id is not None:
        project_instance = await db.get(ProjectInstance, session.project_instance_id)
    if project is None and project_instance is not None:
        project = await db.get(Project, project_instance.project_id)
    worktree = _prepare_session_worktree(
        project,
        session_id=session_id,
        branch=branch,
        base_branch=base_branch,
    )
    cwd = str(worktree["worktree_path"]) if worktree is not None else _session_project_cwd(project_instance, project)
    if not cwd:
        raise ValueError("isolated session environment requires a canonical git repo or ready Project instance")

    now = _utcnow()
    env = existing or SessionExecutionEnvironment(
        session_id=session_id,
        project_id=project.id if project is not None else None,
        project_instance_id=project_instance.id if project_instance is not None else None,
        mode=MODE_ISOLATED,
        status=STATUS_PREPARING,
        cwd=cwd,
        expires_at=now + timedelta(seconds=max(60, int(ttl_seconds))),
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    db.add(env)
    await db.flush()

    try:
        docker = _start_docker_daemon(session_id)
        env.cwd = cwd
        env.metadata_ = {
            **dict(env.metadata_ or {}),
            "worktree": worktree,
            "isolation": "git_worktree_per_session_docker_daemon" if worktree else "project_instance_per_session_docker_daemon",
        }
        _apply_docker_payload(env, docker)
    except Exception as exc:
        env.status = STATUS_FAILED
        env.docker_status = "failed"
        env.metadata_ = {**dict(env.metadata_ or {}), "error": str(exc)}
        env.updated_at = _utcnow()
        await db.commit()
        raise
    env.updated_at = _utcnow()
    await db.commit()
    await db.refresh(env)
    return env


async def stop_session_execution_environment(db: AsyncSession, session_id: uuid.UUID | str) -> SessionExecutionEnvironment | None:
    env = await get_session_execution_environment(db, session_id)
    if env is None:
        return None
    if env.docker_container_name:
        _run(["docker", "stop", env.docker_container_name], timeout=120)
    env.status = STATUS_STOPPED
    env.docker_status = "stopped"
    env.updated_at = _utcnow()
    await db.commit()
    await db.refresh(env)
    return env


async def start_session_execution_environment(db: AsyncSession, session_id: uuid.UUID | str) -> SessionExecutionEnvironment | None:
    env = await get_session_execution_environment(db, session_id)
    if env is None:
        return None
    if env.mode != MODE_ISOLATED:
        raise ValueError("only isolated session environments have a Docker daemon")
    active_count = await _active_isolated_count(db)
    if env.status != STATUS_READY and active_count >= _max_active_isolated():
        raise RuntimeError(f"isolated session capacity reached ({active_count}/{_max_active_isolated()})")
    docker = _start_docker_daemon(env.session_id)
    _apply_docker_payload(env, docker)
    await db.commit()
    await db.refresh(env)
    return env


async def restart_session_execution_environment(db: AsyncSession, session_id: uuid.UUID | str) -> SessionExecutionEnvironment | None:
    env = await get_session_execution_environment(db, session_id)
    if env is None:
        return None
    if env.docker_container_name and _inspect_container(env.docker_container_name) is not None:
        proc = _run(["docker", "restart", env.docker_container_name], timeout=180)
        if proc.returncode == 0:
            info = _inspect_container(env.docker_container_name)
            if info is not None:
                docker = _docker_payload_from_inspect(env.session_id, info)
                if docker.get("endpoint"):
                    _apply_docker_payload(env, docker)
                    await db.commit()
                    await db.refresh(env)
                    return env
    return await start_session_execution_environment(db, session_id)


async def pin_session_execution_environment(
    db: AsyncSession,
    session_id: uuid.UUID | str,
    *,
    pinned: bool,
    ttl_seconds: int | None = None,
) -> SessionExecutionEnvironment | None:
    env = await get_session_execution_environment(db, session_id)
    if env is None:
        return None
    env.pinned = bool(pinned)
    if pinned:
        env.expires_at = None
    elif ttl_seconds is not None:
        env.expires_at = _utcnow() + timedelta(seconds=max(60, int(ttl_seconds)))
    elif env.expires_at is None:
        env.expires_at = _utcnow() + timedelta(seconds=DEFAULT_ISOLATED_TTL_SECONDS)
    env.updated_at = _utcnow()
    await db.commit()
    await db.refresh(env)
    return env


async def doctor_session_execution_environment(db: AsyncSession, session_id: uuid.UUID | str) -> dict[str, Any]:
    env = await get_session_execution_environment(db, session_id)
    if env is None:
        return {
            "ok": True,
            "mode": MODE_SHARED,
            "status": STATUS_READY,
            "checks": [{"name": "environment", "status": "not_configured"}],
            "findings": [],
            "next_actions": ["create_isolated"],
        }
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    cwd_exists = bool(env.cwd and Path(env.cwd).exists())
    checks.append({"name": "cwd", "status": "ok" if cwd_exists else "missing", "path": env.cwd})
    if not cwd_exists:
        findings.append({"severity": "error", "code": "session_env_cwd_missing", "message": "Execution cwd is missing."})
    container = _inspect_container(env.docker_container_name) if env.docker_container_name else None
    if env.mode == MODE_ISOLATED:
        docker_status = "missing"
        endpoint = env.docker_endpoint
        if container is not None:
            docker = _docker_payload_from_inspect(env.session_id, container)
            docker_status = str(docker.get("state") or "unknown")
            endpoint = docker.get("endpoint") or endpoint
        checks.append({
            "name": "docker_daemon",
            "status": "ok" if docker_status == "running" and endpoint else docker_status,
            "container": env.docker_container_name,
            "endpoint": endpoint,
        })
        if docker_status != "running":
            findings.append({"severity": "warning", "code": "session_docker_not_running", "message": "The private Docker daemon is not running."})
    ok = not any(item.get("severity") == "error" for item in findings)
    next_actions: list[str] = []
    if any(item.get("code") == "session_docker_not_running" for item in findings):
        next_actions.append("start")
    if any(item.get("code") == "session_env_cwd_missing" for item in findings):
        next_actions.append("cleanup")
    if not next_actions:
        next_actions.append("none")
    return {
        "ok": ok,
        "environment": session_execution_environment_out(env, session_id=env.session_id),
        "checks": checks,
        "findings": findings,
        "next_actions": next_actions,
        "capacity": {
            "active": await _active_isolated_count(db),
            "max_active": _max_active_isolated(),
        },
    }


async def load_session_execution_runtime(
    db: AsyncSession,
    session_id: uuid.UUID | str,
) -> SessionExecutionRuntime:
    env = await get_session_execution_environment(db, session_id)
    if env is None:
        return SessionExecutionRuntime(mode=MODE_SHARED, status=STATUS_READY, cwd=None, env={}, hint=None, record=None)
    runtime_env: dict[str, str] = {
        "SPINDREL_SESSION_ID": str(env.session_id),
        "SPINDREL_EXECUTION_ENVIRONMENT": env.mode,
    }
    if env.cwd:
        runtime_env["SPINDREL_SESSION_WORKTREE"] = env.cwd
    if env.mode == MODE_ISOLATED and env.status == STATUS_READY and env.docker_endpoint:
        runtime_env["DOCKER_HOST"] = env.docker_endpoint
        runtime_env["COMPOSE_PROJECT_NAME"] = f"spindrel_{str(env.session_id).replace('-', '')[:12]}"
    hint = None
    if env.mode == MODE_ISOLATED:
        worktree = (env.metadata_ or {}).get("worktree") if isinstance(env.metadata_, dict) else None
        worktree_kind = "git worktree" if isinstance(worktree, dict) and worktree.get("kind") == "git_worktree" else "isolated work surface"
        hint = (
            "This session is running in an isolated execution environment. "
            f"Use the current working directory as the session {worktree_kind}. "
            "Docker commands are routed to this session's private Docker daemon."
        )
    return SessionExecutionRuntime(
        mode=env.mode,
        status=env.status,
        cwd=env.cwd,
        env=runtime_env,
        hint=hint,
        record=env,
    )


async def cleanup_session_execution_environment(
    db: AsyncSession,
    session_id: uuid.UUID | str,
    *,
    remove_state: bool = True,
) -> SessionExecutionEnvironment | None:
    env = await get_session_execution_environment(db, session_id)
    if env is None:
        return None
    if env.docker_container_name:
        _run(["docker", "rm", "-f", env.docker_container_name], timeout=60)
    if remove_state and env.docker_state_volume:
        _run(["docker", "volume", "rm", "-f", env.docker_state_volume], timeout=60)
    metadata = dict(env.metadata_ or {})
    worktree = metadata.get("worktree")
    if isinstance(worktree, dict) and worktree.get("worktree_path"):
        worktree_path = Path(str(worktree["worktree_path"])).resolve()
        source_repo = Path(str(worktree.get("source_repo") or "")).resolve() if worktree.get("source_repo") else None
        removed = False
        if source_repo and source_repo.exists():
            proc = _git(source_repo, "worktree", "remove", "--force", str(worktree_path), timeout=120)
            removed = proc.returncode == 0
        if not removed:
            parts = set(worktree_path.parts)
            if "session-worktrees" in parts:
                shutil.rmtree(worktree_path, ignore_errors=True)
                removed = True
        metadata["worktree"] = {**worktree, "removed": removed, "removed_at": _utcnow().isoformat()}
        env.metadata_ = metadata
    env.status = STATUS_DELETED
    env.docker_status = "deleted"
    env.deleted_at = _utcnow()
    env.updated_at = _utcnow()
    await db.commit()
    await db.refresh(env)
    return env


async def cleanup_expired_session_execution_environments(db: AsyncSession, *, limit: int = 25) -> dict[str, Any]:
    now = _utcnow()
    rows = list((await db.execute(
        select(SessionExecutionEnvironment)
        .where(
            SessionExecutionEnvironment.deleted_at.is_(None),
            SessionExecutionEnvironment.pinned.is_(False),
            SessionExecutionEnvironment.expires_at.is_not(None),
            SessionExecutionEnvironment.expires_at <= now,
        )
        .order_by(SessionExecutionEnvironment.expires_at.asc())
        .limit(max(1, min(int(limit or 25), 100)))
    )).scalars().all())
    cleaned: list[str] = []
    for env in rows:
        await cleanup_session_execution_environment(db, env.session_id)
        cleaned.append(str(env.session_id))
    return {"ok": True, "cleaned": cleaned, "count": len(cleaned)}


async def manage_session_execution_environment(
    db: AsyncSession,
    session_id: uuid.UUID | str,
    *,
    action: str,
    project: Project | None = None,
    project_instance: ProjectInstance | None = None,
    pinned: bool | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    action = (action or "").strip().lower()
    sid = uuid.UUID(str(session_id))
    if action in {"status", "get"}:
        env = await get_session_execution_environment(db, sid)
        return {"ok": True, "environment": session_execution_environment_out(env, session_id=sid)}
    if action in {"doctor", "check"}:
        return await doctor_session_execution_environment(db, sid)
    if action in {"ensure_isolated", "create_isolated"}:
        env = await ensure_isolated_session_environment(
            db,
            session_id=sid,
            project=project,
            project_instance=project_instance,
            ttl_seconds=ttl_seconds or DEFAULT_ISOLATED_TTL_SECONDS,
        )
        return {"ok": True, "environment": session_execution_environment_out(env, session_id=env.session_id)}
    if action == "start":
        env = await start_session_execution_environment(db, sid)
    elif action == "stop":
        env = await stop_session_execution_environment(db, sid)
    elif action == "restart":
        env = await restart_session_execution_environment(db, sid)
    elif action == "cleanup":
        env = await cleanup_session_execution_environment(db, sid)
    elif action == "pin":
        env = await pin_session_execution_environment(db, sid, pinned=True)
    elif action == "unpin":
        env = await pin_session_execution_environment(db, sid, pinned=False, ttl_seconds=ttl_seconds)
    elif action == "set_pin":
        env = await pin_session_execution_environment(db, sid, pinned=bool(pinned), ttl_seconds=ttl_seconds)
    else:
        raise ValueError(f"unknown session execution environment action: {action}")
    if env is None:
        return {"ok": False, "error": "session execution environment not found", "error_code": "session_environment_not_found"}
    return {"ok": True, "environment": session_execution_environment_out(env, session_id=env.session_id)}


def session_execution_environment_out(env: SessionExecutionEnvironment | None, *, session_id: uuid.UUID) -> dict[str, Any]:
    if env is None:
        return {
            "session_id": session_id,
            "mode": MODE_SHARED,
            "status": STATUS_READY,
            "cwd": None,
            "docker_status": None,
            "docker_endpoint": None,
            "project_id": None,
            "project_instance_id": None,
            "pinned": False,
            "expires_at": None,
            "created_at": None,
            "updated_at": None,
            "metadata": {},
            "worktree": None,
            "docker": None,
            "runtime_env": {},
        }
    metadata = dict(env.metadata_ or {})
    worktree = metadata.get("worktree") if isinstance(metadata.get("worktree"), dict) else None
    docker = metadata.get("docker") if isinstance(metadata.get("docker"), dict) else None
    runtime_env = {
        "SPINDREL_SESSION_ID": str(env.session_id),
        "SPINDREL_EXECUTION_ENVIRONMENT": env.mode,
    }
    if env.cwd:
        runtime_env["SPINDREL_SESSION_WORKTREE"] = env.cwd
    if env.mode == MODE_ISOLATED and env.status == STATUS_READY and env.docker_endpoint:
        runtime_env["DOCKER_HOST"] = env.docker_endpoint
        runtime_env["COMPOSE_PROJECT_NAME"] = f"spindrel_{str(env.session_id).replace('-', '')[:12]}"
    return {
        "session_id": env.session_id,
        "mode": env.mode,
        "status": env.status,
        "cwd": env.cwd,
        "docker_status": env.docker_status,
        "docker_endpoint": env.docker_endpoint,
        "project_id": env.project_id,
        "project_instance_id": env.project_instance_id,
        "pinned": env.pinned,
        "expires_at": env.expires_at,
        "created_at": env.created_at,
        "updated_at": env.updated_at,
        "metadata": metadata,
        "worktree": worktree,
        "docker": docker,
        "runtime_env": runtime_env,
    }
