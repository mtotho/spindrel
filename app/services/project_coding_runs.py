"""Project coding-run launch and review summaries."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Project, ProjectInstance, ProjectRunReceipt, Task
from app.services.agent_activity import list_agent_activity
from app.services.execution_receipts import create_execution_receipt
from app.services.project_instances import cleanup_project_instance
from app.services.project_run_handoff import prepare_project_run_handoff
from app.services.project_run_receipts import serialize_project_run_receipt
from app.services.project_runtime import load_project_runtime_environment, project_snapshot
from app.services.run_presets import get_run_preset

PROJECT_CODING_RUN_PRESET_ID = "project_coding_run"


@dataclass(frozen=True)
class ProjectCodingRunCreate:
    channel_id: uuid.UUID
    request: str = ""


@dataclass(frozen=True)
class ProjectCodingRunContinue:
    feedback: str = ""


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
    continuation: dict[str, Any] | None = None,
) -> str:
    base_branch = defaults.get("base_branch") or "the repository default branch"
    branch = defaults.get("branch")
    repo = defaults.get("repo") or {}
    repo_path = repo.get("path") or "the Project root"
    configured_keys = ", ".join(runtime_target.get("configured_keys") or []) or "none"
    missing_secrets = ", ".join(runtime_target.get("missing_secrets") or []) or "none"
    request_text = request.strip() or "Use the Project task request from the run title and Project context."
    continuation_block = ""
    if continuation:
        feedback = str(continuation.get("feedback") or "").strip() or "Continue from the reviewer feedback on the existing PR."
        parent_task_id = continuation.get("parent_task_id") or "unknown"
        root_task_id = continuation.get("root_task_id") or parent_task_id
        handoff_url = continuation.get("handoff_url") or "not recorded"
        prior_evidence = continuation.get("prior_evidence") or {}
        evidence_line = (
            f"{prior_evidence.get('tests_count', 0)} tests, "
            f"{prior_evidence.get('screenshots_count', 0)} screenshots, "
            f"{prior_evidence.get('changed_files_count', 0)} files"
        )
        continuation_block = (
            "\n\nReview continuation context:\n"
            "- This is a follow-up run for an existing Project coding run, not a fresh branch.\n"
            f"- Parent task: {parent_task_id}\n"
            f"- Root task: {root_task_id}\n"
            f"- Existing handoff/PR: {handoff_url}\n"
            f"- Prior evidence: {evidence_line}\n"
            "- Update the same work branch and existing PR. Do not create a replacement PR unless the handoff tool reports that reuse is impossible.\n"
            "- Address the reviewer feedback, rerun relevant tests/screenshots, and publish a new Project run receipt.\n\n"
            f"Reviewer feedback:\n{feedback}"
        )
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
        f"{continuation_block}"
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
            "continuation_index": 0,
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
    ecfg["project_coding_run"]["root_task_id"] = str(task_id)
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


def _uuid_from_config(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _lineage_config(task: Task, cfg: dict[str, Any]) -> dict[str, Any]:
    parent_task_id = _uuid_from_config(cfg.get("parent_task_id"))
    root_task_id = _uuid_from_config(cfg.get("root_task_id")) or task.id
    try:
        continuation_index = int(cfg.get("continuation_index") or 0)
    except (TypeError, ValueError):
        continuation_index = 0
    return {
        "parent_task_id": str(parent_task_id) if parent_task_id else None,
        "root_task_id": str(root_task_id),
        "continuation_index": max(0, continuation_index),
        "continuation_feedback": str(cfg.get("continuation_feedback") or "").strip() or None,
    }


def _prior_evidence_context(receipt: ProjectRunReceipt | None) -> dict[str, Any]:
    evidence = _evidence_summary(receipt)
    if receipt is None:
        return {**evidence, "summary": None, "handoff_url": None}
    return {
        **evidence,
        "summary": receipt.summary,
        "handoff_url": receipt.handoff_url,
        "changed_files": list(receipt.changed_files or [])[:12],
        "tests": list(receipt.tests or [])[:8],
        "screenshots": list(receipt.screenshots or [])[:8],
    }


async def _next_continuation_index(db: AsyncSession, project: Project, root_task_id: uuid.UUID) -> int:
    channel_ids = list((await db.execute(
        select(Channel.id).where(Channel.project_id == project.id)
    )).scalars().all())
    if not channel_ids:
        return 1
    candidates = list((await db.execute(
        select(Task).where(Task.channel_id.in_(channel_ids))
    )).scalars().all())
    max_index = 0
    for task in candidates:
        if not isinstance(task.execution_config, dict):
            continue
        cfg = task.execution_config.get("project_coding_run")
        if not isinstance(cfg, dict):
            continue
        lineage = _lineage_config(task, cfg)
        if lineage["root_task_id"] == str(root_task_id):
            max_index = max(max_index, int(lineage["continuation_index"] or 0))
    return max_index + 1


async def continue_project_coding_run(
    db: AsyncSession,
    project: Project,
    task_id: uuid.UUID,
    body: ProjectCodingRunContinue,
) -> Task:
    parent = await _load_project_coding_task(db, project, task_id)
    parent_cfg = _task_run_config(parent)
    parent_lineage = _lineage_config(parent, parent_cfg)
    root_task_id = uuid.UUID(parent_lineage["root_task_id"])
    continuation_index = await _next_continuation_index(db, project, root_task_id)
    receipt = (await _latest_run_receipts_by_task(db, project.id, [parent.id])).get(parent.id)
    prior_evidence = _prior_evidence_context(receipt)

    preset = get_run_preset(PROJECT_CODING_RUN_PRESET_ID)
    if preset is None:
        raise ValueError("Project coding-run preset is not registered")
    channel = await db.get(Channel, parent.channel_id) if parent.channel_id else None
    if channel is None or channel.project_id != project.id:
        raise ValueError("coding run not found")

    new_task_id = uuid.uuid4()
    fallback_defaults = project_coding_run_defaults(
        project,
        request=str(parent_cfg.get("request") or project.name),
        task_id=root_task_id,
    )
    run_defaults = {
        "branch": parent_cfg.get("branch") or fallback_defaults.get("branch"),
        "base_branch": parent_cfg.get("base_branch") or fallback_defaults.get("base_branch"),
        "repo": parent_cfg.get("repo") or fallback_defaults.get("repo") or {},
    }
    runtime_target = dict(parent_cfg.get("runtime_target") or {})
    if not runtime_target:
        runtime = await load_project_runtime_environment(db, project)
        runtime_target = _safe_runtime_target(runtime.safe_payload())
    feedback = body.feedback.strip()
    continuation_context = {
        "feedback": feedback,
        "parent_task_id": str(parent.id),
        "root_task_id": str(root_task_id),
        "handoff_url": prior_evidence.get("handoff_url"),
        "prior_evidence": prior_evidence,
    }
    prompt = _project_coding_run_prompt(
        base_prompt=preset.task_defaults.prompt,
        project=project,
        request=str(parent_cfg.get("request") or ""),
        defaults=run_defaults,
        runtime_target=runtime_target,
        continuation=continuation_context,
    )
    ecfg = _execution_config_from_preset(
        preset.task_defaults,
        project_id=project.id,
        run_defaults=run_defaults,
        runtime_target=runtime_target,
        request=str(parent_cfg.get("request") or ""),
    )
    parent_ecfg = parent.execution_config if isinstance(parent.execution_config, dict) else {}
    ecfg["session_target"] = dict(parent_ecfg.get("session_target") or ecfg["session_target"])
    ecfg["project_instance"] = dict(parent_ecfg.get("project_instance") or ecfg["project_instance"])
    ecfg["project_coding_run"].update({
        "parent_task_id": str(parent.id),
        "root_task_id": str(root_task_id),
        "continuation_index": continuation_index,
        "continuation_feedback": feedback,
        "continued_from_handoff_url": prior_evidence.get("handoff_url"),
        "prior_evidence": prior_evidence,
    })
    task = Task(
        id=new_task_id,
        bot_id=channel.bot_id,
        client_id=channel.client_id,
        session_id=channel.active_session_id,
        channel_id=channel.id,
        prompt=prompt,
        title=f"{preset.task_defaults.title} follow-up {continuation_index}",
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


def _activity_receipts(activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item for item in activity
        if item.get("kind") == "execution_receipt"
        and isinstance(item.get("source"), dict)
        and item["source"].get("scope") == "project_coding_run"
    ]


def _latest_action(activity: list[dict[str, Any]], action_type: str) -> dict[str, Any] | None:
    for item in _activity_receipts(activity):
        if item.get("source", {}).get("action_type") == action_type:
            return item
    return None


def _step_status(item: dict[str, Any] | None) -> str:
    if not item:
        return "missing"
    status = str(item.get("status") or "reported")
    if status == "unknown" and "ready" in str(item.get("summary") or "").lower():
        return "succeeded"
    return status


def _step_result(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    source = item.get("source")
    if not isinstance(source, dict):
        return {}
    result = source.get("result")
    return dict(result) if isinstance(result, dict) else {}


def _evidence_summary(receipt: ProjectRunReceipt | None) -> dict[str, Any]:
    changed_files = list(receipt.changed_files or []) if receipt is not None else []
    tests = list(receipt.tests or []) if receipt is not None else []
    screenshots = list(receipt.screenshots or []) if receipt is not None else []
    return {
        "changed_files_count": len(changed_files),
        "tests_count": len(tests),
        "screenshots_count": len(screenshots),
        "has_tests": bool(tests),
        "has_screenshots": bool(screenshots),
    }


def _summarize_checks(checks: Any) -> str | None:
    if not isinstance(checks, list) or not checks:
        return None
    labels = [
        str((check or {}).get("conclusion") or (check or {}).get("status") or "").lower()
        for check in checks
        if isinstance(check, dict)
    ]
    if any(label in {"failure", "failed", "error", "cancelled", "timed_out"} for label in labels):
        return "failed"
    if labels and all(label in {"success", "completed", "passed", "neutral", "skipped"} for label in labels):
        return "passed"
    return "pending"


def _review_summary(
    *,
    task: Task,
    receipt: ProjectRunReceipt | None,
    activity: list[dict[str, Any]],
    instance: ProjectInstance | None,
) -> dict[str, Any]:
    branch_step = _latest_action(activity, "handoff.prepare_branch")
    push_step = _latest_action(activity, "handoff.push")
    pr_step = _latest_action(activity, "handoff.open_pr")
    status_step = _latest_action(activity, "handoff.status")
    reviewed_step = _latest_action(activity, "review.marked")
    cleanup_step = _latest_action(activity, "instance.cleanup")

    pr_result = _step_result(pr_step)
    status_result = _step_result(status_step)
    pr_status = status_result.get("pr_status") if isinstance(status_result.get("pr_status"), dict) else {}
    pr_url = (
        (receipt.handoff_url if receipt is not None else None)
        or pr_result.get("pr_url")
        or pr_status.get("url")
    )
    blocker = None
    for item in _activity_receipts(activity):
        if _step_status(item) in {"blocked", "failed"}:
            result = _step_result(item)
            blocker = result.get("blocker") or item.get("next_action") or item.get("summary")
            break
    if blocker is None and receipt is not None and receipt.status in {"blocked", "failed"}:
        blocker = receipt.summary
    if blocker is None and task.error:
        blocker = task.error

    evidence = _evidence_summary(receipt)
    reviewed = _step_status(reviewed_step) == "succeeded"
    if reviewed:
        review_status = "reviewed"
    elif blocker and (receipt is None or receipt.status != "needs_review"):
        review_status = "blocked"
    elif receipt is not None and receipt.status in {"completed", "needs_review"}:
        review_status = "ready_for_review"
    elif pr_url:
        review_status = "ready_for_review"
    elif task.status in {"pending", "running"}:
        review_status = task.status
    elif task.status == "complete":
        review_status = "pending_evidence"
    else:
        review_status = _run_status(task, receipt)

    instance_payload: dict[str, Any] | None = None
    if instance is not None:
        instance_payload = {
            "id": str(instance.id),
            "status": instance.status,
            "root_path": instance.root_path,
            "owner_kind": instance.owner_kind,
            "owner_id": str(instance.owner_id) if instance.owner_id else None,
            "expires_at": instance.expires_at.isoformat() if instance.expires_at else None,
            "deleted_at": instance.deleted_at.isoformat() if instance.deleted_at else None,
        }

    can_cleanup = (
        instance is not None
        and instance.status != "deleted"
        and instance.owner_kind == "task"
        and instance.owner_id == task.id
    )
    return {
        "status": review_status,
        "blocker": blocker,
        "reviewed": reviewed,
        "reviewed_at": reviewed_step.get("created_at") if reviewed_step else None,
        "handoff_url": pr_url,
        "pr": {
            "url": pr_url,
            "state": pr_status.get("state"),
            "draft": pr_status.get("draft"),
            "merge_state": pr_status.get("merge_state"),
            "review_decision": pr_status.get("review_decision"),
            "checks_status": _summarize_checks(pr_status.get("checks")),
        },
        "steps": {
            "branch": {"status": _step_status(branch_step), "summary": branch_step.get("summary") if branch_step else None},
            "push": {"status": _step_status(push_step), "summary": push_step.get("summary") if push_step else None},
            "pr": {"status": _step_status(pr_step), "summary": pr_step.get("summary") if pr_step else None},
            "status": {"status": _step_status(status_step), "summary": status_step.get("summary") if status_step else None},
            "cleanup": {"status": _step_status(cleanup_step), "summary": cleanup_step.get("summary") if cleanup_step else None},
        },
        "evidence": evidence,
        "instance": instance_payload,
        "actions": {
            "can_refresh": True,
            "can_mark_reviewed": not reviewed and bool(pr_url or receipt is not None),
            "can_cleanup_instance": can_cleanup,
            "can_request_changes": bool(pr_url or receipt is not None),
        },
    }


async def _latest_run_receipts_by_task(
    db: AsyncSession,
    project_id: uuid.UUID,
    task_ids: list[uuid.UUID],
) -> dict[uuid.UUID, ProjectRunReceipt]:
    receipts = list((await db.execute(
        select(ProjectRunReceipt)
        .where(ProjectRunReceipt.project_id == project_id, ProjectRunReceipt.task_id.in_(task_ids))
        .order_by(ProjectRunReceipt.created_at.desc())
    )).scalars().all())
    receipts_by_task: dict[uuid.UUID, ProjectRunReceipt] = {}
    for receipt in receipts:
        if receipt.task_id is not None and receipt.task_id not in receipts_by_task:
            receipts_by_task[receipt.task_id] = receipt
    return receipts_by_task


async def _coding_run_row(
    db: AsyncSession,
    project: Project,
    task: Task,
    receipt: ProjectRunReceipt | None,
) -> dict[str, Any]:
    activity = await list_agent_activity(
        db,
        bot_id=task.bot_id,
        channel_id=task.channel_id,
        session_id=task.session_id,
        task_id=task.id,
        correlation_id=task.correlation_id,
        limit=20,
    )
    instance = await db.get(ProjectInstance, task.project_instance_id) if task.project_instance_id else None
    cfg = _task_run_config(task)
    lineage = _lineage_config(task, cfg)
    updated_at = (
        receipt.created_at.isoformat()
        if receipt is not None and receipt.created_at is not None
        else task.completed_at.isoformat() if task.completed_at is not None
        else task.run_at.isoformat() if task.run_at is not None
        else task.created_at.isoformat() if task.created_at is not None
        else None
    )
    return {
        "id": str(task.id),
        "project_id": str(project.id),
        "status": _run_status(task, receipt),
        "request": cfg.get("request") or "",
        "branch": cfg.get("branch"),
        "base_branch": cfg.get("base_branch"),
        "repo": cfg.get("repo") or {},
        "runtime_target": cfg.get("runtime_target") or {},
        "parent_task_id": lineage["parent_task_id"],
        "root_task_id": lineage["root_task_id"],
        "continuation_index": lineage["continuation_index"],
        "continuation_feedback": lineage["continuation_feedback"],
        "continuations": [],
        "task": _task_summary(task),
        "receipt": _receipt_summary(receipt),
        "activity": activity,
        "review": _review_summary(task=task, receipt=receipt, activity=activity, instance=instance),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": updated_at,
    }


async def _load_project_coding_task(db: AsyncSession, project: Project, task_id: uuid.UUID) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise ValueError("coding run not found")
    channel = await db.get(Channel, task.channel_id) if task.channel_id else None
    if channel is None or channel.project_id != project.id:
        raise ValueError("coding run not found")
    if not isinstance(task.execution_config, dict) or task.execution_config.get("run_preset_id") != PROJECT_CODING_RUN_PRESET_ID:
        raise ValueError("coding run not found")
    return task


async def get_project_coding_run(db: AsyncSession, project: Project, task_id: uuid.UUID) -> dict[str, Any]:
    task = await _load_project_coding_task(db, project, task_id)
    receipt = (await _latest_run_receipts_by_task(db, project.id, [task.id])).get(task.id)
    return await _coding_run_row(db, project, task, receipt)


async def refresh_project_coding_run_status(db: AsyncSession, project: Project, task_id: uuid.UUID) -> dict[str, Any]:
    task = await _load_project_coding_task(db, project, task_id)
    await prepare_project_run_handoff(db, action="status", project_id=project.id, task_id=task.id)
    return await get_project_coding_run(db, project, task.id)


async def mark_project_coding_run_reviewed(db: AsyncSession, project: Project, task_id: uuid.UUID) -> dict[str, Any]:
    task = await _load_project_coding_task(db, project, task_id)
    await create_execution_receipt(
        db,
        scope="project_coding_run",
        action_type="review.marked",
        status="succeeded",
        summary="Project coding run marked reviewed.",
        actor={"kind": "operator"},
        target={"project_id": str(project.id), "task_id": str(task.id)},
        bot_id=task.bot_id,
        channel_id=task.channel_id,
        session_id=task.session_id,
        task_id=task.id,
        correlation_id=task.correlation_id,
        idempotency_key=f"{task.id}:review.marked",
    )
    return await get_project_coding_run(db, project, task.id)


async def cleanup_project_coding_run_instance(db: AsyncSession, project: Project, task_id: uuid.UUID) -> dict[str, Any]:
    task = await _load_project_coding_task(db, project, task_id)
    instance = await db.get(ProjectInstance, task.project_instance_id) if task.project_instance_id else None
    status = "reported"
    summary = "Project coding run has no fresh instance to clean up."
    result: dict[str, Any] = {"cleaned": False}
    if instance is not None:
        if instance.owner_kind == "task" and instance.owner_id == task.id:
            cleaned = await cleanup_project_instance(db, instance)
            status = "succeeded"
            summary = "Project coding run fresh instance cleaned up."
            result = {"cleaned": True, "project_instance_id": str(cleaned.id), "status": cleaned.status}
        else:
            status = "blocked"
            summary = "Project coding run instance cleanup blocked: instance is not task-owned."
            result = {"cleaned": False, "project_instance_id": str(instance.id), "owner_kind": instance.owner_kind}
    await create_execution_receipt(
        db,
        scope="project_coding_run",
        action_type="instance.cleanup",
        status=status,
        summary=summary,
        actor={"kind": "operator"},
        target={"project_id": str(project.id), "task_id": str(task.id)},
        result=result,
        rollback_hint=summary if status == "blocked" else None,
        bot_id=task.bot_id,
        channel_id=task.channel_id,
        session_id=task.session_id,
        task_id=task.id,
        correlation_id=task.correlation_id,
        idempotency_key=f"{task.id}:instance.cleanup",
    )
    return await get_project_coding_run(db, project, task.id)


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

    receipts_by_task = await _latest_run_receipts_by_task(db, project.id, [task.id for task in tasks])

    rows: list[dict[str, Any]] = []
    for task in tasks:
        receipt = receipts_by_task.get(task.id)
        rows.append(await _coding_run_row(db, project, task, receipt))
    rows_by_id = {row["id"]: row for row in rows}
    children_by_root: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        parent_task_id = row.get("parent_task_id")
        if parent_task_id and parent_task_id in rows_by_id:
            children_by_root.setdefault(str(row.get("root_task_id") or parent_task_id), []).append({
                "id": row["id"],
                "task_id": row["task"]["id"],
                "status": row["status"],
                "review_status": row.get("review", {}).get("status"),
                "continuation_index": row.get("continuation_index") or 0,
                "feedback": row.get("continuation_feedback"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            })
    for row in rows:
        root_id = str(row.get("root_task_id") or row["id"])
        continuations = sorted(
            children_by_root.get(root_id, []),
            key=lambda child: int(child.get("continuation_index") or 0),
        )
        row["continuations"] = continuations
        row["continuation_count"] = len(continuations)
        latest = continuations[-1] if continuations else None
        row["latest_continuation"] = latest
    return rows
