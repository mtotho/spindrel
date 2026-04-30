"""Executable setup plans for Project Blueprint snapshots."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Project, ProjectSecretBinding, ProjectSetupRun
from app.services.projects import normalize_project_path, project_directory_from_project
from app.services.project_runtime import (
    build_project_runtime_environment,
    project_snapshot,
    redact_known_values,
    required_secret_names,
)
from app.services.secret_registry import redact


SETUP_SOURCE = "blueprint_snapshot"
RUN_STATUS_PENDING = "pending"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_FAILED = "failed"
DEFAULT_SETUP_COMMAND_TIMEOUT_SECONDS = 600
MAX_SETUP_COMMAND_TIMEOUT_SECONDS = 3600
SETUP_COMMAND_OUTPUT_LIMIT = 12000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _repo_name_from_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail or "repo"


def _validate_repo_url(url: str) -> str | None:
    if (
        url.startswith("https://")
        or url.startswith("ssh://")
        or url.startswith("file://")
        or url.startswith("git@")
        or url.startswith("/")
    ):
        return None
    return "repo url must be https, ssh, git@, file, or an absolute local path"


def _normalize_repo(raw: Any, index: int) -> dict[str, Any]:
    errors: list[str] = []
    data = raw if isinstance(raw, dict) else {}
    url = str(data.get("url") or data.get("repo") or "").strip()
    if not url:
        errors.append("repo url is required")
    else:
        url_error = _validate_repo_url(url)
        if url_error:
            errors.append(url_error)

    name = str(data.get("name") or _repo_name_from_url(url) or f"repo-{index + 1}").strip()
    branch = str(data.get("branch") or "").strip() or None
    raw_path = data.get("path") or data.get("target") or name
    try:
        path = normalize_project_path(str(raw_path))
        if not path:
            errors.append("repo path must not target the Project root")
            path = ""
    except ValueError as exc:
        path = ""
        errors.append(str(exc).replace("project_path", "repo path"))

    return {
        "name": name,
        "url": url,
        "path": path,
        "branch": branch,
        "status": "invalid" if errors else "pending",
        "errors": errors,
    }


def _normalize_setup_command(raw: Any, index: int) -> dict[str, Any]:
    errors: list[str] = []
    data = raw if isinstance(raw, dict) else {"command": "" if raw is None else raw}

    name = str(data.get("name") or data.get("label") or f"Command {index + 1}").strip()
    command = str(data.get("command") or data.get("cmd") or "").strip()
    if not command:
        errors.append("command is required")

    raw_cwd = data.get("cwd") or data.get("workdir") or ""
    try:
        cwd = normalize_project_path(str(raw_cwd)) if str(raw_cwd).strip() else ""
    except ValueError as exc:
        cwd = ""
        errors.append(str(exc).replace("project_path", "command cwd"))

    raw_timeout = data.get("timeout_seconds") or data.get("timeout") or DEFAULT_SETUP_COMMAND_TIMEOUT_SECONDS
    try:
        timeout_seconds = int(raw_timeout)
    except (TypeError, ValueError):
        timeout_seconds = DEFAULT_SETUP_COMMAND_TIMEOUT_SECONDS
        errors.append("timeout_seconds must be an integer")
    if timeout_seconds < 1 or timeout_seconds > MAX_SETUP_COMMAND_TIMEOUT_SECONDS:
        errors.append(f"timeout_seconds must be between 1 and {MAX_SETUP_COMMAND_TIMEOUT_SECONDS}")

    return {
        "name": name or f"Command {index + 1}",
        "command": command,
        "cwd": cwd,
        "timeout_seconds": timeout_seconds,
        "status": "invalid" if errors else "pending",
        "errors": errors,
    }


def build_project_setup_plan(
    project: Project,
    *,
    bindings: list[ProjectSecretBinding],
) -> dict[str, Any]:
    """Return a secret-safe setup plan derived from the applied snapshot."""
    snapshot = project_snapshot(project)
    return build_project_setup_plan_from_snapshot(
        project_id=project.id,
        snapshot=snapshot,
        bindings=bindings,
    )


def build_project_setup_plan_from_snapshot(
    *,
    project_id: uuid.UUID | str,
    snapshot: dict[str, Any],
    bindings: list[ProjectSecretBinding],
) -> dict[str, Any]:
    """Return a setup plan from a frozen Project blueprint snapshot."""
    repos = [_normalize_repo(repo, index) for index, repo in enumerate(snapshot.get("repos") or [])]
    commands = [
        _normalize_setup_command(command, index)
        for index, command in enumerate(snapshot.get("setup_commands") or [])
    ]
    runtime_project = SimpleNamespace(id=project_id, metadata_={"blueprint_snapshot": snapshot})
    runtime_env = build_project_runtime_environment(runtime_project, bindings=bindings)

    bindings_by_name = {binding.logical_name: binding for binding in bindings}
    secret_slots: list[dict[str, Any]] = []
    missing_secrets: list[str] = []
    for name in required_secret_names(snapshot):
        binding = bindings_by_name.get(name)
        bound = bool(binding and binding.secret_value_id)
        if not bound:
            missing_secrets.append(name)
        secret_slots.append(
            {
                "logical_name": name,
                "bound": bound,
                "secret_value_id": str(binding.secret_value_id) if binding and binding.secret_value_id else None,
                "secret_value_name": binding.secret_value.name if binding and binding.secret_value else None,
            }
        )

    invalid_repos = [repo for repo in repos if repo["status"] == "invalid"]
    invalid_commands = [command for command in commands if command["status"] == "invalid"]
    has_setup_work = bool(repos) or bool(commands)
    ready = has_setup_work and not missing_secrets and not invalid_repos and not invalid_commands
    reasons: list[str] = []
    if not has_setup_work:
        reasons.append("empty_setup")
    if missing_secrets:
        reasons.append("missing_secrets")
    if invalid_repos:
        reasons.append("invalid_repos")
    if invalid_commands:
        reasons.append("invalid_commands")

    return {
        "source": SETUP_SOURCE,
        "ready": ready,
        "reasons": reasons,
        "repos": repos,
        "commands": commands,
        "env": {key: str(runtime_env.env[key]) for key in runtime_env.env_default_keys if key in runtime_env.env},
        "secret_slots": secret_slots,
        "missing_secrets": missing_secrets,
        "runtime": runtime_env.safe_payload(),
    }


async def load_project_setup_plan(db: AsyncSession, project: Project) -> dict[str, Any]:
    bindings = (await db.execute(
        select(ProjectSecretBinding)
        .options(selectinload(ProjectSecretBinding.secret_value))
        .where(ProjectSecretBinding.project_id == project.id)
        .order_by(ProjectSecretBinding.logical_name)
    )).scalars().all()
    return build_project_setup_plan(project, bindings=list(bindings))


def _safe_repo_target(project_root: str, repo_path: str) -> Path:
    root = Path(project_root).resolve()
    target = (root / repo_path).resolve()
    if target == root or root not in target.parents:
        raise ValueError("repo path must stay inside the Project root")
    return target


def _safe_command_cwd(project_root: str, cwd: str) -> Path:
    root = Path(project_root).resolve()
    target = (root / cwd).resolve() if cwd else root
    if target != root and root not in target.parents:
        raise ValueError("command cwd must stay inside the Project root")
    return target


def _redact_with_values(text: str, values: dict[str, str]) -> str:
    return redact_known_values(redact(text), values)


def _truncate_output(text: str) -> str:
    if len(text) <= SETUP_COMMAND_OUTPUT_LIMIT:
        return text
    return text[:SETUP_COMMAND_OUTPUT_LIMIT] + "\n[output truncated]"


async def _run_git_clone(
    repo: dict[str, Any],
    *,
    target: Path,
    env: dict[str, str],
    secret_env: dict[str, str],
) -> dict[str, Any]:
    if target.exists():
        return {**repo, "status": "already_present", "message": "Target path already exists; setup did not modify it."}

    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1"]
    if repo.get("branch"):
        cmd.extend(["--branch", str(repo["branch"])])
    cmd.extend([str(repo["url"]), str(target)])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **env},
    )
    stdout, stderr = await proc.communicate()
    output = "\n".join(part for part in [stdout.decode(errors="replace"), stderr.decode(errors="replace")] if part).strip()
    redacted_output = _redact_with_values(output, secret_env)
    if proc.returncode != 0:
        return {
            **repo,
            "status": "failed",
            "message": redacted_output or f"git clone exited with {proc.returncode}",
            "returncode": proc.returncode,
        }
    return {
        **repo,
        "status": "cloned",
        "message": redacted_output or "Repository cloned.",
        "returncode": proc.returncode,
    }


async def _run_setup_command(
    command: dict[str, Any],
    *,
    cwd: Path,
    env: dict[str, str],
    secret_env: dict[str, str],
) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-lc",
        str(command["command"]),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
        env={**os.environ, **env},
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=int(command.get("timeout_seconds") or DEFAULT_SETUP_COMMAND_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError:
        proc.kill()
        stdout, stderr = await proc.communicate()
        output = "\n".join(part for part in [stdout.decode(errors="replace"), stderr.decode(errors="replace")] if part).strip()
        redacted_output = _truncate_output(_redact_with_values(output, secret_env))
        return {
            **command,
            "status": "failed",
            "message": redacted_output or "Command timed out.",
            "returncode": None,
            "timed_out": True,
        }

    output = "\n".join(part for part in [stdout.decode(errors="replace"), stderr.decode(errors="replace")] if part).strip()
    redacted_output = _truncate_output(_redact_with_values(output, secret_env))
    if proc.returncode != 0:
        return {
            **command,
            "status": "failed",
            "message": redacted_output or f"Command exited with {proc.returncode}",
            "returncode": proc.returncode,
        }
    return {
        **command,
        "status": "succeeded",
        "message": redacted_output or "Command completed.",
        "returncode": proc.returncode,
    }


async def execute_project_setup_plan(
    plan: dict[str, Any],
    *,
    project_root: str,
    secret_env: dict[str, str],
) -> dict[str, Any]:
    """Execute the Project setup plan."""
    if not plan.get("ready"):
        return {"status": RUN_STATUS_FAILED, "repos": [], "logs": ["Setup plan is not ready."]}
    env = {**{str(k): str(v) for k, v in (plan.get("env") or {}).items()}, **secret_env}
    repo_results: list[dict[str, Any]] = []
    command_results: list[dict[str, Any]] = []
    logs: list[str] = []
    for repo in plan.get("repos") or []:
        target = _safe_repo_target(project_root, str(repo.get("path") or ""))
        result = await _run_git_clone(repo, target=target, env=env, secret_env=secret_env)
        repo_results.append(result)
        logs.append(_redact_with_values(f"{result['status']}: {repo.get('path')} {result.get('message', '')}".strip(), secret_env))
    if any(repo.get("status") == "failed" for repo in repo_results):
        for command in plan.get("commands") or []:
            command_results.append({**command, "status": "skipped", "message": "Skipped because repository setup failed."})
        return {"status": RUN_STATUS_FAILED, "repos": repo_results, "commands": command_results, "logs": logs}

    for command in plan.get("commands") or []:
        cwd = _safe_command_cwd(project_root, str(command.get("cwd") or ""))
        if command.get("cwd") and not cwd.exists():
            result = {
                **command,
                "status": "failed",
                "message": "Command cwd does not exist.",
                "returncode": None,
            }
        else:
            cwd.mkdir(parents=True, exist_ok=True)
            result = await _run_setup_command(command, cwd=cwd, env=env, secret_env=secret_env)
        command_results.append(result)
        logs.append(_redact_with_values(f"{result['status']}: {command.get('name')} {result.get('message', '')}".strip(), secret_env))
        if result.get("status") == "failed":
            for skipped in (plan.get("commands") or [])[len(command_results):]:
                command_results.append({**skipped, "status": "skipped", "message": "Skipped because an earlier command failed."})
            return {"status": RUN_STATUS_FAILED, "repos": repo_results, "commands": command_results, "logs": logs}

    return {"status": RUN_STATUS_SUCCEEDED, "repos": repo_results, "commands": command_results, "logs": logs}


async def resolve_project_secret_env(db: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    from app.services.project_runtime import load_project_runtime_environment_for_id

    runtime_env = await load_project_runtime_environment_for_id(db, project_id)
    if runtime_env is None:
        return {}
    return {key: str(runtime_env.env[key]) for key in runtime_env.secret_keys if key in runtime_env.env}


async def list_project_setup_runs(db: AsyncSession, project_id: uuid.UUID, *, limit: int = 5) -> list[ProjectSetupRun]:
    return list((await db.execute(
        select(ProjectSetupRun)
        .where(ProjectSetupRun.project_id == project_id)
        .order_by(ProjectSetupRun.created_at.desc())
        .limit(limit)
    )).scalars().all())


async def run_project_setup(db: AsyncSession, project: Project) -> ProjectSetupRun:
    plan = await load_project_setup_plan(db, project)
    run = ProjectSetupRun(
        project_id=project.id,
        status=RUN_STATUS_RUNNING,
        source=SETUP_SOURCE,
        plan=plan,
        logs=[],
        started_at=_utcnow(),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    try:
        project_root = project_directory_from_project(project).host_path
        secret_env = await resolve_project_secret_env(db, project.id)
        result = await execute_project_setup_plan(plan, project_root=project_root, secret_env=secret_env)
        run.status = result["status"]
        run.result = result
        run.logs = result["logs"]
        run.completed_at = _utcnow()
    except Exception as exc:
        run.status = RUN_STATUS_FAILED
        run.result = {"status": RUN_STATUS_FAILED, "error": redact(str(exc))}
        run.logs = [redact(str(exc))]
        run.completed_at = _utcnow()
    await db.commit()
    await db.refresh(run)
    return run
