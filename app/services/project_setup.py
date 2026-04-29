"""Executable setup plans for Project Blueprint snapshots."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Project, ProjectSecretBinding, ProjectSetupRun, SecretValue
from app.services.encryption import decrypt
from app.services.projects import normalize_project_path, project_directory_from_project
from app.services.secret_registry import redact


SETUP_SOURCE = "blueprint_snapshot"
RUN_STATUS_PENDING = "pending"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot(project: Project) -> dict[str, Any]:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    snapshot = metadata.get("blueprint_snapshot")
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def _secret_name(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("key") or "").strip()
    return ""


def _required_secret_names(snapshot: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in snapshot.get("required_secrets") or []:
        name = _secret_name(item)
        if name and name not in names:
            names.append(name)
    return names


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


def build_project_setup_plan(
    project: Project,
    *,
    bindings: list[ProjectSecretBinding],
) -> dict[str, Any]:
    """Return a secret-safe setup plan derived from the applied snapshot."""
    snapshot = _snapshot(project)
    repos = [_normalize_repo(repo, index) for index, repo in enumerate(snapshot.get("repos") or [])]
    env = snapshot.get("env") if isinstance(snapshot.get("env"), dict) else {}

    bindings_by_name = {binding.logical_name: binding for binding in bindings}
    secret_slots: list[dict[str, Any]] = []
    missing_secrets: list[str] = []
    for name in _required_secret_names(snapshot):
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
    ready = bool(repos) and not missing_secrets and not invalid_repos
    reasons: list[str] = []
    if not repos:
        reasons.append("no_repos")
    if missing_secrets:
        reasons.append("missing_secrets")
    if invalid_repos:
        reasons.append("invalid_repos")

    return {
        "source": SETUP_SOURCE,
        "ready": ready,
        "reasons": reasons,
        "repos": repos,
        "env": {str(key): str(value) for key, value in env.items()},
        "secret_slots": secret_slots,
        "missing_secrets": missing_secrets,
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


def _redact_with_values(text: str, values: dict[str, str]) -> str:
    redacted = redact(text)
    for value in sorted((v for v in values.values() if v), key=len, reverse=True):
        redacted = redacted.replace(value, "[REDACTED]")
    return redacted


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


async def execute_project_setup_plan(
    plan: dict[str, Any],
    *,
    project_root: str,
    secret_env: dict[str, str],
) -> dict[str, Any]:
    """Execute the clone-only V1 setup plan."""
    if not plan.get("ready"):
        return {"status": RUN_STATUS_FAILED, "repos": [], "logs": ["Setup plan is not ready."]}
    env = {**{str(k): str(v) for k, v in (plan.get("env") or {}).items()}, **secret_env}
    repo_results: list[dict[str, Any]] = []
    logs: list[str] = []
    for repo in plan.get("repos") or []:
        target = _safe_repo_target(project_root, str(repo.get("path") or ""))
        result = await _run_git_clone(repo, target=target, env=env, secret_env=secret_env)
        repo_results.append(result)
        logs.append(_redact_with_values(f"{result['status']}: {repo.get('path')} {result.get('message', '')}".strip(), secret_env))
    status = RUN_STATUS_FAILED if any(repo.get("status") == "failed" for repo in repo_results) else RUN_STATUS_SUCCEEDED
    return {"status": status, "repos": repo_results, "logs": logs}


async def resolve_project_secret_env(db: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    rows = (await db.execute(
        select(ProjectSecretBinding, SecretValue)
        .join(SecretValue, SecretValue.id == ProjectSecretBinding.secret_value_id)
        .where(ProjectSecretBinding.project_id == project_id)
    )).all()
    env: dict[str, str] = {}
    for binding, secret in rows:
        env[binding.logical_name] = decrypt(secret.value)
    return env


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
