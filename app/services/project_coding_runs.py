"""Project coding-run launch and review summaries."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Project, ProjectRunReceipt, Task
from app.services.agent_activity import list_agent_activity
from app.services.project_run_receipts import serialize_project_run_receipt
from app.services.project_runtime import load_project_runtime_environment, project_snapshot
from app.services.run_presets import get_run_preset

PROJECT_CODING_RUN_PRESET_ID = "project_coding_run"


@dataclass(frozen=True)
class ProjectCodingRunCreate:
    channel_id: uuid.UUID
    request: str = ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slug(text: str, *, fallback: str = "coding-run", max_len: int = 40) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return (value or fallback)[:max_len].strip("-") or fallback


def _first_repo(snapshot: dict[str, Any]) -> dict[str, Any]:
    repos = snapshot.get("repos")
    if isinstance(repos, list):
        for repo in repos:
            if isinstance(repo, dict):
                return repo
    return {}


def project_coding_run_defaults(project: Project, *, request: str = "", task_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Return deterministic, secret-safe handoff defaults for a Project run."""
    snapshot = project_snapshot(project)
    repo = _first_repo(snapshot)
    base_branch = str(repo.get("branch") or "").strip() or None
    task_uuid = task_id or uuid.uuid4()
    branch = f"spindrel/project-{str(task_uuid)[:8]}-{_slug(request or project.name)}"
    return {
        "branch": branch[:96],
        "base_branch": base_branch,
        "repo": {
            "name": str(repo.get("name") or "").strip() or None,
            "path": str(repo.get("path") or "").strip() or None,
            "url": str(repo.get("url") or "").strip() or None,
        },
    }


def _safe_runtime_target(runtime_payload: dict[str, Any]) -> dict[str, Any]:
    keys = set(runtime_payload.get("env_default_keys") or []) | set(runtime_payload.get("secret_keys") or [])
    target_keys = [
        key for key in (
            "SPINDREL_E2E_URL",
            "E2E_BASE_URL",
            "E2E_HOST",
            "E2E_PORT",
            "E2E_API_KEY",
            "SPINDREL_UI_URL",
            "GITHUB_TOKEN",
        )
        if key in keys
    ]
    return {
        "ready": bool(runtime_payload.get("ready")),
        "configured_keys": target_keys,
        "missing_secrets": list(runtime_payload.get("missing_secrets") or []),
    }


def _project_coding_run_prompt(
    *,
    base_prompt: str,
    project: Project,
    request: str,
    defaults: dict[str, Any],
    runtime_target: dict[str, Any],
) -> str:
    base_branch = defaults.get("base_branch") or "the repository default branch"
    branch = defaults.get("branch")
    repo = defaults.get("repo") or {}
    repo_path = repo.get("path") or "the Project root"
    configured_keys = ", ".join(runtime_target.get("configured_keys") or []) or "none"
    missing_secrets = ", ".join(runtime_target.get("missing_secrets") or []) or "none"
    request_text = request.strip() or "Use the Project task request from the run title and Project context."
    return (
        f"{base_prompt}\n\n"
        "Project coding-run handoff configuration:\n"
        f"- Project: {project.name} (/{project.root_path})\n"
        f"- Repository path: {repo_path}\n"
        f"- Base branch: {base_branch}\n"
        f"- Work branch: {branch}\n"
        f"- E2E/runtime configured keys: {configured_keys}\n"
        f"- Missing runtime secret bindings: {missing_secrets}\n\n"
        "Guided handoff requirements:\n"
        "1. Before editing, inspect git status and update from the base branch when safe.\n"
        f"2. Create or switch to the work branch `{branch}` before making changes.\n"
        "3. Use the Project runtime env and run_e2e_tests(status) before UI/e2e work.\n"
        "4. If GitHub credentials and gh are available, push the branch and open a draft PR. "
        "If not, publish a blocked or needs_review receipt with the exact blocker.\n"
        "5. publish_project_run_receipt must include branch, base_branch, changed files, tests, screenshots, and handoff URL when available.\n\n"
        f"Project task request:\n{request_text}"
    )


def _execution_config_from_preset(defaults: Any, *, project_id: uuid.UUID, run_defaults: dict[str, Any], runtime_target: dict[str, Any], request: str) -> dict[str, Any]:
    return {
        "run_preset_id": PROJECT_CODING_RUN_PRESET_ID,
        "skills": list(defaults.skills),
        "tools": list(defaults.tools),
        "post_final_to_channel": defaults.post_final_to_channel,
        "history_mode": defaults.history_mode,
        "history_recent_count": defaults.history_recent_count,
        "skip_tool_approval": defaults.skip_tool_approval,
        "session_target": dict(defaults.session_target or {}),
        "project_instance": dict(defaults.project_instance or {}),
        "allow_issue_reporting": defaults.allow_issue_reporting,
        "harness_effort": defaults.harness_effort,
        "project_coding_run": {
            "project_id": str(project_id),
            "request": request.strip(),
            "branch": run_defaults.get("branch"),
            "base_branch": run_defaults.get("base_branch"),
            "repo": run_defaults.get("repo") or {},
            "runtime_target": runtime_target,
        },
    }


async def create_project_coding_run(
    db: AsyncSession,
    project: Project,
    body: ProjectCodingRunCreate,
) -> Task:
    channel = await db.get(Channel, body.channel_id)
    if channel is None:
        raise ValueError("channel not found")
    if channel.project_id != project.id:
        raise ValueError("channel does not belong to this Project")
    preset = get_run_preset(PROJECT_CODING_RUN_PRESET_ID)
    if preset is None:
        raise ValueError("Project coding-run preset is not registered")

    task_id = uuid.uuid4()
    run_defaults = project_coding_run_defaults(project, request=body.request, task_id=task_id)
    runtime = await load_project_runtime_environment(db, project)
    runtime_target = _safe_runtime_target(runtime.safe_payload())
    prompt = _project_coding_run_prompt(
        base_prompt=preset.task_defaults.prompt,
        project=project,
        request=body.request,
        defaults=run_defaults,
        runtime_target=runtime_target,
    )
    ecfg = _execution_config_from_preset(
        preset.task_defaults,
        project_id=project.id,
        run_defaults=run_defaults,
        runtime_target=runtime_target,
        request=body.request,
    )
    task = Task(
        id=task_id,
        bot_id=channel.bot_id,
        client_id=channel.client_id,
        session_id=channel.active_session_id,
        channel_id=channel.id,
        prompt=prompt,
        title=preset.task_defaults.title,
        scheduled_at=None,
        status="pending",
        task_type=preset.task_defaults.task_type,
        dispatch_type=channel.integration if channel.integration and channel.dispatch_config else "none",
        dispatch_config=dict(channel.dispatch_config) if channel.integration and channel.dispatch_config else None,
        execution_config=ecfg,
        recurrence=None,
        max_run_seconds=preset.task_defaults.max_run_seconds,
        trigger_config=dict(preset.task_defaults.trigger_config),
        created_at=_utcnow(),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


def _task_run_config(task: Task) -> dict[str, Any]:
    ecfg = task.execution_config if isinstance(task.execution_config, dict) else {}
    run = ecfg.get("project_coding_run")
    return dict(run) if isinstance(run, dict) else {}


def _task_summary(task: Task) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "status": task.status,
        "title": task.title,
        "bot_id": task.bot_id,
        "channel_id": str(task.channel_id) if task.channel_id else None,
        "session_id": str(task.session_id) if task.session_id else None,
        "project_instance_id": str(task.project_instance_id) if task.project_instance_id else None,
        "correlation_id": str(task.correlation_id) if task.correlation_id else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "run_at": task.run_at.isoformat() if task.run_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error": task.error,
    }


def _receipt_summary(receipt: ProjectRunReceipt | None) -> dict[str, Any] | None:
    return serialize_project_run_receipt(receipt) if receipt is not None else None


def _run_status(task: Task, receipt: ProjectRunReceipt | None) -> str:
    if receipt is not None:
        if receipt.status == "completed":
            return "completed"
        if receipt.status in {"failed", "blocked", "needs_review"}:
            return receipt.status
    if task.status in {"running", "pending", "failed", "complete"}:
        return "completed" if task.status == "complete" else task.status
    return task.status or "unknown"


async def list_project_coding_runs(
    db: AsyncSession,
    project: Project,
    *,
    limit: int = 25,
) -> list[dict[str, Any]]:
    channel_ids = list((await db.execute(
        select(Channel.id).where(Channel.project_id == project.id)
    )).scalars().all())
    if not channel_ids:
        return []

    candidates = list((await db.execute(
        select(Task)
        .where(Task.channel_id.in_(channel_ids))
        .order_by(Task.created_at.desc())
        .limit(max(1, min(limit * 3, 150)))
    )).scalars().all())
    tasks = [
        task for task in candidates
        if isinstance(task.execution_config, dict)
        and task.execution_config.get("run_preset_id") == PROJECT_CODING_RUN_PRESET_ID
    ][: max(1, min(limit, 100))]
    if not tasks:
        return []

    task_ids = [task.id for task in tasks]
    receipts = list((await db.execute(
        select(ProjectRunReceipt)
        .where(ProjectRunReceipt.project_id == project.id, ProjectRunReceipt.task_id.in_(task_ids))
        .order_by(ProjectRunReceipt.created_at.desc())
    )).scalars().all())
    receipts_by_task: dict[uuid.UUID, ProjectRunReceipt] = {}
    for receipt in receipts:
        if receipt.task_id is not None and receipt.task_id not in receipts_by_task:
            receipts_by_task[receipt.task_id] = receipt

    rows: list[dict[str, Any]] = []
    for task in tasks:
        receipt = receipts_by_task.get(task.id)
        activity = await list_agent_activity(
            db,
            bot_id=task.bot_id,
            channel_id=task.channel_id,
            session_id=task.session_id,
            task_id=task.id,
            correlation_id=task.correlation_id,
            limit=8,
        )
        cfg = _task_run_config(task)
        rows.append({
            "id": str(task.id),
            "project_id": str(project.id),
            "status": _run_status(task, receipt),
            "request": cfg.get("request") or "",
            "branch": cfg.get("branch"),
            "base_branch": cfg.get("base_branch"),
            "repo": cfg.get("repo") or {},
            "runtime_target": cfg.get("runtime_target") or {},
            "task": _task_summary(task),
            "receipt": _receipt_summary(receipt),
            "activity": activity,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": (
                receipt.created_at.isoformat()
                if receipt is not None and receipt.created_at is not None
                else task.completed_at.isoformat() if task.completed_at is not None
                else task.run_at.isoformat() if task.run_at is not None
                else task.created_at.isoformat() if task.created_at is not None
                else None
            ),
        })
    return rows
