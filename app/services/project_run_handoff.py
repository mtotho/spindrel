"""Branch and pull-request handoff helpers for Project coding runs."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.db.models import Channel, Project, Task
from app.services.execution_receipts import create_execution_receipt, serialize_execution_receipt
from app.services.github_git_auth import prepare_github_git_env
from app.services.project_runtime import load_project_runtime_environment_for_id
from app.services.projects import (
    normalize_project_path,
    project_directory_from_project,
    resolve_channel_work_surface_by_id,
    work_surface_from_project_directory,
)

PROJECT_CODING_RUN_SCOPE = "project_coding_run"

HandoffAction = str


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    cwd: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


CommandRunner = Callable[[str, tuple[str, ...], dict[str, str], int], Awaitable[CommandResult]]


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _clip(value: Any, *, limit: int = 2_000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 18].rstrip() + "\n\n[...truncated]"


def _command_payload(result: CommandResult) -> dict[str, Any]:
    return {
        "command": " ".join(result.args),
        "cwd": result.cwd,
        "exit_code": result.exit_code,
        "stdout": _clip(result.stdout, limit=800),
        "stderr": _clip(result.stderr, limit=800),
        "timed_out": result.timed_out,
    }


def _task_project_run_config(task: Task | None) -> dict[str, Any]:
    if task is None or not isinstance(task.execution_config, dict):
        return {}
    raw = task.execution_config.get("project_coding_run")
    return dict(raw) if isinstance(raw, dict) else {}


def _repo_path_from_config(config: dict[str, Any]) -> str | None:
    repo = config.get("repo")
    if isinstance(repo, dict):
        value = repo.get("path")
        if value:
            return str(value)
    return None


def _resolve_repo_cwd(surface_root: str, repo_path: str | None) -> str:
    root = os.path.realpath(surface_root)
    rel = normalize_project_path(repo_path)
    cwd = os.path.realpath(os.path.join(root, rel)) if rel else root
    prefix = root.rstrip(os.sep) + os.sep
    if cwd != root and not cwd.startswith(prefix):
        raise ValueError("repo_path must stay inside the Project work surface")
    return cwd


async def _default_command_runner(
    cwd: str,
    args: tuple[str, ...],
    env: dict[str, str],
    timeout: int,
) -> CommandResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return CommandResult(args=args, cwd=cwd, exit_code=127, stderr=str(exc))

    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=max(1, timeout))
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        stdout, stderr = await proc.communicate()
    return CommandResult(
        args=args,
        cwd=cwd,
        exit_code=124 if timed_out else int(proc.returncode or 0),
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
        timed_out=timed_out,
    )


def _normal_action(action: str | None) -> HandoffAction:
    value = (action or "prepare_branch").strip().lower()
    aliases = {
        "prepare": "prepare_branch",
        "branch": "prepare_branch",
        "pr": "open_pr",
        "pull_request": "open_pr",
        "full": "open_pr",
    }
    value = aliases.get(value, value)
    if value not in {"status", "prepare_branch", "push", "open_pr"}:
        raise ValueError("action must be one of status, prepare_branch, push, open_pr")
    return value


def _normal_merge_method(method: str | None) -> str:
    value = (method or "squash").strip().lower()
    if value not in {"squash", "merge", "rebase"}:
        raise ValueError("merge_method must be one of squash, merge, rebase")
    return value


def _extract_pr_url(stdout: str) -> str | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and payload.get("url"):
            return str(payload["url"])
    except json.JSONDecodeError:
        pass
    for token in text.replace("\n", " ").split():
        if token.startswith("http://") or token.startswith("https://"):
            return token
    return None


def _safe_json_object(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


async def _record_progress(
    db: AsyncSession,
    *,
    action_type: str,
    status: str,
    summary: str,
    project_id: uuid.UUID | str | None,
    branch: str | None,
    base_branch: str | None,
    repo_path: str | None,
    result: dict[str, Any],
    bot_id: str | None,
    channel_id: uuid.UUID | str | None,
    session_id: uuid.UUID | str | None,
    task_id: uuid.UUID | str | None,
    correlation_id: uuid.UUID | str | None,
) -> dict[str, Any]:
    stable_target = str(task_id or branch or project_id or "adhoc")
    receipt = await create_execution_receipt(
        db,
        scope=PROJECT_CODING_RUN_SCOPE,
        action_type=action_type,
        status=status,
        summary=summary,
        actor={"kind": "bot", "bot_id": bot_id},
        target={
            "project_id": str(project_id) if project_id else None,
            "branch": branch,
            "base_branch": base_branch,
            "repo_path": repo_path,
        },
        result=result,
        rollback_hint=result.get("blocker") if status in {"blocked", "failed", "needs_review"} else None,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        task_id=task_id,
        correlation_id=correlation_id,
        idempotency_key=f"{stable_target}:{action_type}",
    )
    return serialize_execution_receipt(receipt)


async def _run(
    runner: CommandRunner,
    commands: list[dict[str, Any]],
    cwd: str,
    args: tuple[str, ...],
    env: dict[str, str],
    *,
    timeout: int = 60,
) -> CommandResult:
    result = await runner(cwd, args, env, timeout)
    commands.append(_command_payload(result))
    return result


async def prepare_project_run_handoff(
    db: AsyncSession,
    *,
    action: str = "prepare_branch",
    project_id: uuid.UUID | str | None = None,
    task_id: uuid.UUID | str | None = None,
    channel_id: uuid.UUID | str | None = None,
    bot_id: str | None = None,
    session_id: uuid.UUID | str | None = None,
    correlation_id: uuid.UUID | str | None = None,
    branch: str | None = None,
    base_branch: str | None = None,
    repo_path: str | None = None,
    title: str | None = None,
    body: str | None = None,
    draft: bool = True,
    remote: str = "origin",
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Prepare a Project coding-run branch and optional draft pull request."""
    normalized_action = _normal_action(action)
    task_uuid = _coerce_uuid(task_id)
    task = await db.get(Task, task_uuid) if task_uuid else None
    run_config = _task_project_run_config(task)
    channel_uuid = _coerce_uuid(channel_id) or (task.channel_id if task is not None else None)
    project_uuid = _coerce_uuid(project_id) or _coerce_uuid(run_config.get("project_id"))
    resolved_bot_id = bot_id or (task.bot_id if task is not None else None)
    resolved_session_id = session_id or (str(task.session_id) if task is not None and task.session_id else None)
    resolved_correlation_id = correlation_id or (str(task.correlation_id) if task is not None and task.correlation_id else None)

    channel = await db.get(Channel, channel_uuid) if channel_uuid else None
    if channel is not None:
        resolved_bot_id = resolved_bot_id or channel.bot_id
        project_uuid = project_uuid or channel.project_id

    resolved_branch = (branch or run_config.get("branch") or "").strip()
    resolved_base = (base_branch or run_config.get("base_branch") or "").strip() or None
    resolved_repo_path = repo_path or _repo_path_from_config(run_config)
    commands: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    blockers: list[str] = []

    if not resolved_bot_id:
        raise ValueError("bot_id is required")
    if not project_uuid:
        raise ValueError("project_id is required")

    bot = get_bot(resolved_bot_id)
    surface = await resolve_channel_work_surface_by_id(db, channel_uuid, bot) if channel_uuid else None
    if surface is None:
        project = await db.get(Project, project_uuid)
        if project is None:
            raise ValueError("Project not found")
        surface = work_surface_from_project_directory(project_directory_from_project(project))

    cwd = _resolve_repo_cwd(surface.root_host_path, resolved_repo_path)
    runtime = await load_project_runtime_environment_for_id(db, project_uuid, task_id=task_uuid)
    env = os.environ.copy()
    if runtime is not None:
        env.update({str(key): str(value) for key, value in runtime.env.items()})
    env = prepare_github_git_env(env)

    runner = command_runner or _default_command_runner
    repo_root_result = await _run(runner, commands, cwd, ("git", "rev-parse", "--show-toplevel"), env)
    if not repo_root_result.ok:
        blocker = _clip(repo_root_result.stderr or repo_root_result.stdout or "Not a git repository.", limit=500)
        blockers.append(blocker)
        receipts.append(await _record_progress(
            db,
            action_type="handoff.status",
            status="blocked",
            summary="Project run handoff blocked: repository state could not be inspected.",
            project_id=project_uuid,
            branch=resolved_branch or None,
            base_branch=resolved_base,
            repo_path=resolved_repo_path,
            result={"blocker": blocker, "commands": commands},
            bot_id=resolved_bot_id,
            channel_id=channel_uuid,
            session_id=resolved_session_id,
            task_id=task_uuid,
            correlation_id=resolved_correlation_id,
        ))
        return {
            "ok": False,
            "status": "blocked",
            "action": normalized_action,
            "blockers": blockers,
            "commands": commands,
            "receipts": receipts,
        }

    repo_root = os.path.realpath(repo_root_result.stdout.strip() or cwd)
    if Path(surface.root_host_path).resolve() not in {Path(repo_root).resolve(), *Path(repo_root).resolve().parents}:
        blocker = "Resolved git repository is outside the Project work surface."
        blockers.append(blocker)
        receipts.append(await _record_progress(
            db,
            action_type="handoff.status",
            status="blocked",
            summary="Project run handoff blocked: repository escaped the Project work surface.",
            project_id=project_uuid,
            branch=resolved_branch or None,
            base_branch=resolved_base,
            repo_path=resolved_repo_path,
            result={"blocker": blocker, "repo_root": repo_root},
            bot_id=resolved_bot_id,
            channel_id=channel_uuid,
            session_id=resolved_session_id,
            task_id=task_uuid,
            correlation_id=resolved_correlation_id,
        ))
        return {"ok": False, "status": "blocked", "action": normalized_action, "blockers": blockers, "receipts": receipts}

    cwd = repo_root
    status_result = await _run(runner, commands, cwd, ("git", "status", "--short"), env)
    branch_result = await _run(runner, commands, cwd, ("git", "rev-parse", "--abbrev-ref", "HEAD"), env)
    remote_result = await _run(runner, commands, cwd, ("git", "remote", "get-url", remote), env)
    dirty = bool((status_result.stdout or "").strip())
    current_branch = (branch_result.stdout or "").strip() if branch_result.ok else None
    remote_url = (remote_result.stdout or "").strip() if remote_result.ok else None

    base_payload = {
        "repo_root": repo_root,
        "current_branch": current_branch,
        "dirty": dirty,
        "remote_url": remote_url,
    }
    if normalized_action == "status":
        pr_status: dict[str, Any] | None = None
        if resolved_branch:
            pr_result = await _run(
                runner,
                commands,
                cwd,
                (
                    "gh",
                    "pr",
                    "view",
                    resolved_branch,
                    "--json",
                    "url,state,isDraft,mergeStateStatus,reviewDecision,headRefName,baseRefName,statusCheckRollup",
                ),
                env,
            )
            if pr_result.ok:
                pr_payload = _safe_json_object(pr_result.stdout)
                pr_status = {
                    "available": True,
                    "url": pr_payload.get("url"),
                    "state": pr_payload.get("state"),
                    "draft": pr_payload.get("isDraft"),
                    "merge_state": pr_payload.get("mergeStateStatus"),
                    "review_decision": pr_payload.get("reviewDecision"),
                    "head_ref": pr_payload.get("headRefName"),
                    "base_ref": pr_payload.get("baseRefName"),
                    "checks": pr_payload.get("statusCheckRollup") or [],
                }
            else:
                pr_status = {
                    "available": False,
                    "blocker": _clip(pr_result.stderr or pr_result.stdout or "gh pr view failed", limit=500),
                }
        receipts.append(await _record_progress(
            db,
            action_type="handoff.status",
            status="succeeded",
            summary="Project run repository state inspected.",
            project_id=project_uuid,
            branch=resolved_branch or current_branch,
            base_branch=resolved_base,
            repo_path=resolved_repo_path,
            result={**base_payload, "pr_status": pr_status, "commands": commands},
            bot_id=resolved_bot_id,
            channel_id=channel_uuid,
            session_id=resolved_session_id,
            task_id=task_uuid,
            correlation_id=resolved_correlation_id,
        ))
        return {
            "ok": True,
            "status": "succeeded",
            "action": normalized_action,
            "branch": resolved_branch or current_branch,
            "base_branch": resolved_base,
            "cwd": cwd,
            "repo_root": repo_root,
            "dirty": dirty,
            "remote_url": remote_url,
            "pr_status": pr_status,
            "commands": commands,
            "receipts": receipts,
        }

    if not resolved_branch:
        blocker = "No work branch was provided by the Project coding-run configuration."
        blockers.append(blocker)
        receipts.append(await _record_progress(
            db,
            action_type="handoff.prepare_branch",
            status="blocked",
            summary="Project run branch preparation blocked: missing branch.",
            project_id=project_uuid,
            branch=None,
            base_branch=resolved_base,
            repo_path=resolved_repo_path,
            result={**base_payload, "blocker": blocker},
            bot_id=resolved_bot_id,
            channel_id=channel_uuid,
            session_id=resolved_session_id,
            task_id=task_uuid,
            correlation_id=resolved_correlation_id,
        ))
        return {"ok": False, "status": "blocked", "action": normalized_action, "blockers": blockers, "receipts": receipts}

    if current_branch != resolved_branch:
        if dirty:
            blocker = f"Working tree has uncommitted changes on {current_branch}; branch switch was not attempted."
            blockers.append(blocker)
            receipts.append(await _record_progress(
                db,
                action_type="handoff.prepare_branch",
                status="blocked",
                summary="Project run branch preparation blocked by existing working-tree changes.",
                project_id=project_uuid,
                branch=resolved_branch,
                base_branch=resolved_base,
                repo_path=resolved_repo_path,
                result={**base_payload, "blocker": blocker},
                bot_id=resolved_bot_id,
                channel_id=channel_uuid,
                session_id=resolved_session_id,
                task_id=task_uuid,
                correlation_id=resolved_correlation_id,
            ))
            return {
                "ok": False,
                "status": "blocked",
                "action": normalized_action,
                "branch": resolved_branch,
                "base_branch": resolved_base,
                "cwd": cwd,
                "repo_root": repo_root,
                "dirty": dirty,
                "blockers": blockers,
                "commands": commands,
                "receipts": receipts,
            }

        exists_result = await _run(runner, commands, cwd, ("git", "rev-parse", "--verify", resolved_branch), env)
        if exists_result.ok:
            switch_result = await _run(runner, commands, cwd, ("git", "switch", resolved_branch), env)
        else:
            start_ref = None
            if resolved_base:
                await _run(runner, commands, cwd, ("git", "fetch", remote, resolved_base), env, timeout=120)
                start_ref = f"{remote}/{resolved_base}"
            switch_args = ("git", "switch", "-c", resolved_branch, start_ref) if start_ref else ("git", "switch", "-c", resolved_branch)
            switch_result = await _run(runner, commands, cwd, switch_args, env)
            if not switch_result.ok and start_ref:
                switch_result = await _run(runner, commands, cwd, ("git", "switch", "-c", resolved_branch), env)
        if not switch_result.ok:
            blocker = _clip(switch_result.stderr or switch_result.stdout or "git switch failed", limit=500)
            blockers.append(blocker)
            receipts.append(await _record_progress(
                db,
                action_type="handoff.prepare_branch",
                status="blocked",
                summary="Project run branch preparation blocked by git switch failure.",
                project_id=project_uuid,
                branch=resolved_branch,
                base_branch=resolved_base,
                repo_path=resolved_repo_path,
                result={**base_payload, "blocker": blocker, "commands": commands},
                bot_id=resolved_bot_id,
                channel_id=channel_uuid,
                session_id=resolved_session_id,
                task_id=task_uuid,
                correlation_id=resolved_correlation_id,
            ))
            return {
                "ok": False,
                "status": "blocked",
                "action": normalized_action,
                "branch": resolved_branch,
                "base_branch": resolved_base,
                "cwd": cwd,
                "repo_root": repo_root,
                "dirty": dirty,
                "blockers": blockers,
                "commands": commands,
                "receipts": receipts,
            }
        current_branch = resolved_branch

    receipts.append(await _record_progress(
        db,
        action_type="handoff.prepare_branch",
        status="succeeded",
        summary=f"Project run branch ready: {resolved_branch}.",
        project_id=project_uuid,
        branch=resolved_branch,
        base_branch=resolved_base,
        repo_path=resolved_repo_path,
        result={**base_payload, "current_branch": current_branch, "commands": commands},
        bot_id=resolved_bot_id,
        channel_id=channel_uuid,
        session_id=resolved_session_id,
        task_id=task_uuid,
        correlation_id=resolved_correlation_id,
    ))
    if normalized_action == "prepare_branch":
        return {
            "ok": True,
            "status": "succeeded",
            "action": normalized_action,
            "branch": resolved_branch,
            "base_branch": resolved_base,
            "cwd": cwd,
            "repo_root": repo_root,
            "dirty": dirty,
            "remote_url": remote_url,
            "commands": commands,
            "receipts": receipts,
        }

    push_result = await _run(runner, commands, cwd, ("git", "push", "-u", remote, resolved_branch), env, timeout=180)
    if not push_result.ok:
        blocker = _clip(push_result.stderr or push_result.stdout or "git push failed", limit=500)
        blockers.append(blocker)
        receipts.append(await _record_progress(
            db,
            action_type="handoff.push",
            status="blocked",
            summary="Project run branch push blocked.",
            project_id=project_uuid,
            branch=resolved_branch,
            base_branch=resolved_base,
            repo_path=resolved_repo_path,
            result={**base_payload, "blocker": blocker, "commands": commands},
            bot_id=resolved_bot_id,
            channel_id=channel_uuid,
            session_id=resolved_session_id,
            task_id=task_uuid,
            correlation_id=resolved_correlation_id,
        ))
        return {
            "ok": False,
            "status": "blocked",
            "action": normalized_action,
            "branch": resolved_branch,
            "base_branch": resolved_base,
            "cwd": cwd,
            "repo_root": repo_root,
            "dirty": dirty,
            "blockers": blockers,
            "commands": commands,
            "receipts": receipts,
        }

    receipts.append(await _record_progress(
        db,
        action_type="handoff.push",
        status="succeeded",
        summary=f"Project run branch pushed: {resolved_branch}.",
        project_id=project_uuid,
        branch=resolved_branch,
        base_branch=resolved_base,
        repo_path=resolved_repo_path,
        result={**base_payload, "commands": commands},
        bot_id=resolved_bot_id,
        channel_id=channel_uuid,
        session_id=resolved_session_id,
        task_id=task_uuid,
        correlation_id=resolved_correlation_id,
    ))
    if normalized_action == "push":
        return {
            "ok": True,
            "status": "succeeded",
            "action": normalized_action,
            "branch": resolved_branch,
            "base_branch": resolved_base,
            "cwd": cwd,
            "repo_root": repo_root,
            "dirty": dirty,
            "remote_url": remote_url,
            "commands": commands,
            "receipts": receipts,
        }

    view_result = await _run(runner, commands, cwd, ("gh", "pr", "view", resolved_branch, "--json", "url,state,title"), env)
    pr_url = _extract_pr_url(view_result.stdout) if view_result.ok else None
    if pr_url is None:
        pr_title = (title or f"Project coding run: {resolved_branch}").strip()
        pr_body = (body or "Automated Project coding-run handoff. Review tests, screenshots, and run receipts before merge.").strip()
        create_args = ["gh", "pr", "create", "--base", resolved_base or "HEAD", "--head", resolved_branch, "--title", pr_title, "--body", pr_body]
        if draft:
            create_args.insert(3, "--draft")
        create_result = await _run(runner, commands, cwd, tuple(create_args), env)
        pr_url = _extract_pr_url(create_result.stdout) if create_result.ok else None
        if pr_url is None:
            blocker = _clip(create_result.stderr or create_result.stdout or view_result.stderr or "gh pr create failed", limit=500)
            blockers.append(blocker)
            receipts.append(await _record_progress(
                db,
                action_type="handoff.open_pr",
                status="blocked",
                summary="Project run draft PR handoff blocked.",
                project_id=project_uuid,
                branch=resolved_branch,
                base_branch=resolved_base,
                repo_path=resolved_repo_path,
                result={**base_payload, "blocker": blocker, "commands": commands},
                bot_id=resolved_bot_id,
                channel_id=channel_uuid,
                session_id=resolved_session_id,
                task_id=task_uuid,
                correlation_id=resolved_correlation_id,
            ))
            return {
                "ok": False,
                "status": "blocked",
                "action": normalized_action,
                "branch": resolved_branch,
                "base_branch": resolved_base,
                "cwd": cwd,
                "repo_root": repo_root,
                "dirty": dirty,
                "blockers": blockers,
                "commands": commands,
                "receipts": receipts,
                "handoff": {"type": "pull_request", "branch": resolved_branch, "base_branch": resolved_base},
            }

    receipts.append(await _record_progress(
        db,
        action_type="handoff.open_pr",
        status="succeeded",
        summary=f"Project run draft PR ready: {pr_url}.",
        project_id=project_uuid,
        branch=resolved_branch,
        base_branch=resolved_base,
        repo_path=resolved_repo_path,
        result={**base_payload, "pr_url": pr_url, "commands": commands},
        bot_id=resolved_bot_id,
        channel_id=channel_uuid,
        session_id=resolved_session_id,
        task_id=task_uuid,
        correlation_id=resolved_correlation_id,
    ))
    return {
        "ok": True,
        "status": "succeeded",
        "action": normalized_action,
        "branch": resolved_branch,
        "base_branch": resolved_base,
        "cwd": cwd,
        "repo_root": repo_root,
        "dirty": dirty,
        "remote_url": remote_url,
        "pr_url": pr_url,
        "commands": commands,
        "receipts": receipts,
        "handoff": {
            "type": "pull_request",
            "url": pr_url,
            "branch": resolved_branch,
            "base_branch": resolved_base,
        },
    }


async def merge_project_run_handoff(
    db: AsyncSession,
    *,
    project_id: uuid.UUID | str | None = None,
    task_id: uuid.UUID | str | None = None,
    review_task_id: uuid.UUID | str | None = None,
    review_session_id: uuid.UUID | str | None = None,
    bot_id: str | None = None,
    channel_id: uuid.UUID | str | None = None,
    session_id: uuid.UUID | str | None = None,
    correlation_id: uuid.UUID | str | None = None,
    branch: str | None = None,
    repo_path: str | None = None,
    merge_method: str = "squash",
    remote: str = "origin",
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Merge the configured Project coding-run PR and record handoff.merge."""
    method = _normal_merge_method(merge_method)
    task_uuid = _coerce_uuid(task_id)
    task = await db.get(Task, task_uuid) if task_uuid else None
    run_config = _task_project_run_config(task)
    channel_uuid = _coerce_uuid(channel_id) or (task.channel_id if task is not None else None)
    project_uuid = _coerce_uuid(project_id) or _coerce_uuid(run_config.get("project_id"))
    resolved_bot_id = bot_id or (task.bot_id if task is not None else None)
    resolved_session_id = session_id or (str(task.session_id) if task is not None and task.session_id else None)
    resolved_correlation_id = correlation_id or (str(task.correlation_id) if task is not None and task.correlation_id else None)
    resolved_branch = (branch or run_config.get("branch") or "").strip()
    resolved_repo_path = repo_path or _repo_path_from_config(run_config)
    commands: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []

    if not resolved_bot_id:
        raise ValueError("bot_id is required")
    if not project_uuid:
        raise ValueError("project_id is required")
    if not resolved_branch:
        raise ValueError("branch is required")

    channel = await db.get(Channel, channel_uuid) if channel_uuid else None
    if channel is not None:
        project_uuid = project_uuid or channel.project_id

    bot = get_bot(resolved_bot_id)
    surface = await resolve_channel_work_surface_by_id(db, channel_uuid, bot) if channel_uuid else None
    if surface is None:
        project = await db.get(Project, project_uuid)
        if project is None:
            raise ValueError("Project not found")
        surface = work_surface_from_project_directory(project_directory_from_project(project))

    cwd = _resolve_repo_cwd(surface.root_host_path, resolved_repo_path)
    runtime = await load_project_runtime_environment_for_id(db, project_uuid)
    env = os.environ.copy()
    if runtime is not None:
        env.update({str(key): str(value) for key, value in runtime.env.items()})
    runner = command_runner or _default_command_runner

    repo_root_result = await _run(runner, commands, cwd, ("git", "rev-parse", "--show-toplevel"), env)
    if not repo_root_result.ok:
        blocker = _clip(repo_root_result.stderr or repo_root_result.stdout or "Not a git repository.", limit=500)
        receipts.append(await _record_progress(
            db,
            action_type="handoff.merge",
            status="blocked",
            summary="Project run merge blocked: repository state could not be inspected.",
            project_id=project_uuid,
            branch=resolved_branch,
            base_branch=run_config.get("base_branch"),
            repo_path=resolved_repo_path,
            result={"blocker": blocker, "commands": commands, "review_task_id": str(review_task_id) if review_task_id else None},
            bot_id=resolved_bot_id,
            channel_id=channel_uuid,
            session_id=resolved_session_id,
            task_id=task_uuid,
            correlation_id=resolved_correlation_id,
        ))
        return {"ok": False, "status": "blocked", "blocker": blocker, "commands": commands, "receipts": receipts}

    cwd = os.path.realpath(repo_root_result.stdout.strip() or cwd)
    pr_result = await _run(
        runner,
        commands,
        cwd,
        ("gh", "pr", "view", resolved_branch, "--json", "url,state,isDraft,mergeStateStatus,headRefName,baseRefName"),
        env,
    )
    pr_payload = _safe_json_object(pr_result.stdout) if pr_result.ok else {}
    pr_url = pr_payload.get("url")
    merge_target = str(pr_url or resolved_branch)
    merge_args = ("gh", "pr", "merge", merge_target, f"--{method}", "--delete-branch")
    merge_result = await _run(runner, commands, cwd, merge_args, env, timeout=180)
    if not merge_result.ok:
        blocker = _clip(merge_result.stderr or merge_result.stdout or "gh pr merge failed", limit=500)
        receipts.append(await _record_progress(
            db,
            action_type="handoff.merge",
            status="blocked",
            summary="Project run PR merge blocked.",
            project_id=project_uuid,
            branch=resolved_branch,
            base_branch=run_config.get("base_branch"),
            repo_path=resolved_repo_path,
            result={
                "blocker": blocker,
                "merge_method": method,
                "pr_url": pr_url,
                "pr_status": pr_payload,
                "commands": commands,
                "review_task_id": str(review_task_id) if review_task_id else None,
                "review_session_id": str(review_session_id) if review_session_id else None,
            },
            bot_id=resolved_bot_id,
            channel_id=channel_uuid,
            session_id=resolved_session_id,
            task_id=task_uuid,
            correlation_id=resolved_correlation_id,
        ))
        return {"ok": False, "status": "blocked", "blocker": blocker, "pr_url": pr_url, "commands": commands, "receipts": receipts}

    merged_view = await _run(
        runner,
        commands,
        cwd,
        ("gh", "pr", "view", merge_target, "--json", "url,state,mergedAt,mergeCommit"),
        env,
    )
    merged_payload = _safe_json_object(merged_view.stdout) if merged_view.ok else {}
    merge_commit = merged_payload.get("mergeCommit") if isinstance(merged_payload.get("mergeCommit"), dict) else {}
    receipts.append(await _record_progress(
        db,
        action_type="handoff.merge",
        status="succeeded",
        summary=f"Project run PR merged with {method}.",
        project_id=project_uuid,
        branch=resolved_branch,
        base_branch=run_config.get("base_branch"),
        repo_path=resolved_repo_path,
        result={
            "merge_method": method,
            "pr_url": pr_url or merged_payload.get("url"),
            "merged_at": merged_payload.get("mergedAt"),
            "merge_commit_sha": merge_commit.get("oid") or merge_commit.get("sha"),
            "commands": commands,
            "review_task_id": str(review_task_id) if review_task_id else None,
            "review_session_id": str(review_session_id) if review_session_id else None,
        },
        bot_id=resolved_bot_id,
        channel_id=channel_uuid,
        session_id=resolved_session_id,
        task_id=task_uuid,
        correlation_id=resolved_correlation_id,
    ))
    return {
        "ok": True,
        "status": "succeeded",
        "branch": resolved_branch,
        "pr_url": pr_url or merged_payload.get("url"),
        "merge_method": method,
        "merged_at": merged_payload.get("mergedAt"),
        "merge_commit_sha": merge_commit.get("oid") or merge_commit.get("sha"),
        "commands": commands,
        "receipts": receipts,
    }
