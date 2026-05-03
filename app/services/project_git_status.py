"""Local Git status/diff summaries for Project work surfaces."""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Project, Session, Task
from app.services.projects import (
    normalize_project_path,
    project_directory_from_project,
    project_repo_host_path,
)
from app.services.session_execution_environments import get_session_execution_environment


GIT_TIMEOUT_SECONDS = 8
MAX_OUTPUT_CHARS = 80_000
MAX_PATCH_CHARS = 48_000
MAX_REPOS = 12


def _run_git(cwd: Path, *args: str, max_chars: int = MAX_OUTPUT_CHARS) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": "git executable not found"}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "returncode": 124, "stdout": (exc.stdout or "")[:max_chars], "stderr": "git command timed out"}
    stdout = (proc.stdout or "")[:max_chars]
    stderr = (proc.stderr or "")[:max_chars]
    return {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": stdout, "stderr": stderr}


def _git_toplevel(path: Path) -> Path | None:
    result = _run_git(path, "rev-parse", "--show-toplevel")
    if not result["ok"]:
        return None
    value = str(result["stdout"] or "").strip()
    return Path(value).resolve() if value else None


def _discover_repo_roots(root: Path) -> list[Path]:
    root = root.resolve()
    top = _git_toplevel(root)
    if top is not None:
        return [top]
    repos: list[Path] = []
    if not root.exists():
        return repos
    for parent, dirs, _files in os.walk(root):
        parent_path = Path(parent)
        depth = len(parent_path.relative_to(root).parts)
        if depth > 3:
            dirs[:] = []
            continue
        skip = {".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache", "__pycache__"}
        dirs[:] = [item for item in dirs if item not in skip]
        if ".git" in dirs or (parent_path / ".git").is_file():
            repos.append(parent_path.resolve())
            dirs[:] = []
        if len(repos) >= MAX_REPOS:
            break
    return repos


def _project_repo_roots(project: Project, repo_path: str | None = None) -> list[Path]:
    roots: list[Path] = []
    explicit = project_repo_host_path(project, repo_path=repo_path)
    if explicit:
        roots.extend(_discover_repo_roots(Path(explicit)))
    if not roots and repo_path:
        project_root = Path(project_directory_from_project(project).host_path).resolve()
        rel = normalize_project_path(repo_path)
        if rel:
            roots.extend(_discover_repo_roots(project_root / rel))
    if not roots:
        metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
        snapshot = metadata.get("blueprint_snapshot") if isinstance(metadata, dict) else {}
        repos = snapshot.get("repos") if isinstance(snapshot, dict) else None
        if isinstance(repos, list):
            for repo in repos:
                if not isinstance(repo, dict):
                    continue
                path = normalize_project_path(str(repo.get("path") or ""))
                if not path:
                    continue
                host = project_repo_host_path(project, repo_path=path, snapshot=snapshot)
                if host:
                    roots.extend(_discover_repo_roots(Path(host)))
                if len(roots) >= MAX_REPOS:
                    break
    if not roots:
        roots.extend(_discover_repo_roots(Path(project_directory_from_project(project).host_path)))
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(root.resolve())
    return unique[:MAX_REPOS]


def _repo_summary(root: Path, *, include_patch: bool = False) -> dict[str, Any]:
    branch = _run_git(root, "status", "--short", "--branch")
    porcelain = _run_git(root, "status", "--porcelain=v1", "-uall")
    stat = _run_git(root, "diff", "--stat")
    staged_stat = _run_git(root, "diff", "--cached", "--stat")
    name_status = _run_git(root, "diff", "--name-status")
    staged_name_status = _run_git(root, "diff", "--cached", "--name-status")
    log = _run_git(root, "log", "--oneline", "--decorate", "-20")
    files = [
        line
        for line in str(porcelain.get("stdout") or "").splitlines()
        if line.strip()
    ][:200]
    payload: dict[str, Any] = {
        "path": str(root),
        "branch": str(branch.get("stdout") or "").splitlines()[0] if branch.get("stdout") else "",
        "clean": len(files) == 0,
        "changed_count": len(files),
        "files": files,
        "diff_stat": str(stat.get("stdout") or "").strip(),
        "staged_diff_stat": str(staged_stat.get("stdout") or "").strip(),
        "name_status": str(name_status.get("stdout") or "").strip(),
        "staged_name_status": str(staged_name_status.get("stdout") or "").strip(),
        "recent_commits": [
            line for line in str(log.get("stdout") or "").splitlines() if line.strip()
        ],
        "errors": [
            item.get("stderr")
            for item in [branch, porcelain, stat, staged_stat, name_status, staged_name_status, log]
            if item.get("stderr") and not item.get("ok")
        ],
    }
    if include_patch:
        patch = _run_git(root, "diff", "--patch", max_chars=MAX_PATCH_CHARS)
        staged_patch = _run_git(root, "diff", "--cached", "--patch", max_chars=MAX_PATCH_CHARS)
        payload["patch"] = str(patch.get("stdout") or "")
        payload["staged_patch"] = str(staged_patch.get("stdout") or "")
        payload["patch_truncated"] = len(str(patch.get("stdout") or "")) >= MAX_PATCH_CHARS
        payload["staged_patch_truncated"] = len(str(staged_patch.get("stdout") or "")) >= MAX_PATCH_CHARS
    return payload


def git_status_for_roots(roots: list[Path], *, include_patch: bool = False, scope: dict[str, Any] | None = None) -> dict[str, Any]:
    repos = [_repo_summary(root, include_patch=include_patch) for root in roots]
    return {
        "scope": scope or {},
        "repo_count": len(repos),
        "dirty_count": sum(0 if repo.get("clean") else 1 for repo in repos),
        "repos": repos,
    }


async def project_git_status(
    db: AsyncSession,
    project: Project,
    *,
    repo_path: str | None = None,
    include_patch: bool = False,
) -> dict[str, Any]:
    roots = _project_repo_roots(project, repo_path=repo_path)
    return git_status_for_roots(
        roots,
        include_patch=include_patch,
        scope={"kind": "project", "project_id": str(project.id), "repo_path": repo_path},
    )


async def session_git_status(db: AsyncSession, session_id: uuid.UUID, *, include_patch: bool = False) -> dict[str, Any]:
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError("session not found")
    env = await get_session_execution_environment(db, session_id)
    if env is not None and env.cwd:
        roots = _discover_repo_roots(Path(env.cwd))
        return git_status_for_roots(
            roots,
            include_patch=include_patch,
            scope={"kind": "session", "session_id": str(session_id), "cwd": env.cwd},
        )
    channel = await db.get(Channel, session.channel_id) if session.channel_id else None
    project = await db.get(Project, channel.project_id) if channel is not None and channel.project_id else None
    if project is not None:
        return await project_git_status(db, project, include_patch=include_patch)
    return git_status_for_roots([], include_patch=include_patch, scope={"kind": "session", "session_id": str(session_id)})


async def project_run_git_status(
    db: AsyncSession,
    project: Project,
    task_id: uuid.UUID,
    *,
    include_patch: bool = False,
) -> dict[str, Any]:
    task = await db.get(Task, task_id)
    if task is None:
        raise ValueError("coding run not found")
    if task.session_id is not None:
        status = await session_git_status(db, task.session_id, include_patch=include_patch)
        status["scope"] = {**dict(status.get("scope") or {}), "kind": "project_run", "task_id": str(task.id), "project_id": str(project.id)}
        return status
    cfg = task.execution_config if isinstance(task.execution_config, dict) else {}
    run = cfg.get("project_coding_run") if isinstance(cfg.get("project_coding_run"), dict) else {}
    return await project_git_status(db, project, repo_path=run.get("repo", {}).get("path") if isinstance(run.get("repo"), dict) else None, include_patch=include_patch)


def receipt_git_summary(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "repo_count": status.get("repo_count", 0),
        "dirty_count": status.get("dirty_count", 0),
        "repos": [
            {
                "path": repo.get("path"),
                "branch": repo.get("branch"),
                "clean": repo.get("clean"),
                "changed_count": repo.get("changed_count"),
                "files": list(repo.get("files") or [])[:100],
                "diff_stat": repo.get("diff_stat"),
                "staged_diff_stat": repo.get("staged_diff_stat"),
            }
            for repo in list(status.get("repos") or [])[:MAX_REPOS]
            if isinstance(repo, dict)
        ],
    }
