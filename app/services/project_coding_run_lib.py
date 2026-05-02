"""Shared types, helpers, and read-side endpoints for Project coding runs.

The three Project coding-run lifecycles — orchestration (`project_coding_run_orchestration.py`),
review (`project_coding_run_review.py`), and schedule (`project_run_schedule.py`) — all
consume this lib. The lib must NOT import any of the three lifecycle modules.

The original `project_coding_runs.py` re-exports every public name from here, so
existing callers (routers, workspace_attention, tools, tests) keep working.
"""
from __future__ import annotations

import os
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, ExecutionReceipt, IssueWorkPack, Project, ProjectInstance, ProjectRunReceipt, Task
from app.services.agent_activity import list_agent_activity
from app.services.project_dependency_stacks import project_dependency_stack_spec
from app.services.project_run_handoff import prepare_project_run_handoff
from app.services.project_run_receipts import serialize_project_run_receipt
from app.services.project_runtime import project_snapshot
from app.services.project_task_execution_context import ProjectTaskExecutionContext
from app.services.projects import normalize_project_path, project_directory_from_project

PROJECT_CODING_RUN_PRESET_ID = "project_coding_run"
PROJECT_CODING_RUN_REVIEW_PRESET_ID = "project_coding_run_review"
PROJECT_CODING_RUN_SCHEDULE_PRESET_ID = "project_coding_run_schedule"
PROJECT_REVIEW_TEMPLATE_MARKER = "SPINDREL_REVIEW_CMD_"
DEFAULT_DEV_TARGET_PORT_RANGE = (31_000, 32_999)


@dataclass(frozen=True)
class ProjectMachineTargetGrant:
    provider_id: str
    target_id: str
    capabilities: list[str] | None = None
    allow_agent_tools: bool = True
    expires_at: str | datetime | None = None


@dataclass(frozen=True)
class ProjectCodingRunCreate:
    channel_id: uuid.UUID
    request: str = ""
    repo_path: str | None = None
    machine_target_grant: ProjectMachineTargetGrant | None = None
    granted_by_user_id: uuid.UUID | None = None
    source_work_pack_id: uuid.UUID | None = None
    schedule_task_id: uuid.UUID | None = None
    schedule_run_number: int | None = None


@dataclass(frozen=True)
class ProjectCodingRunScheduleCreate:
    channel_id: uuid.UUID
    title: str = "Scheduled Project coding run"
    request: str = ""
    repo_path: str | None = None
    scheduled_at: datetime | None = None
    recurrence: str = "+1w"
    machine_target_grant: ProjectMachineTargetGrant | None = None
    granted_by_user_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ProjectCodingRunScheduleUpdate:
    title: str | None = None
    request: str | None = None
    repo_path: str | None = None
    scheduled_at: datetime | None = None
    recurrence: str | None = None
    enabled: bool | None = None
    channel_id: uuid.UUID | None = None
    machine_target_grant: ProjectMachineTargetGrant | None = None
    granted_by_user_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ProjectCodingRunContinue:
    feedback: str = ""


@dataclass(frozen=True)
class ProjectCodingRunReviewCreate:
    channel_id: uuid.UUID
    task_ids: list[uuid.UUID]
    prompt: str = ""
    merge_method: str = "squash"
    machine_target_grant: ProjectMachineTargetGrant | None = None
    granted_by_user_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ProjectCodingRunReviewFinalize:
    review_task_id: uuid.UUID
    run_task_id: uuid.UUID
    outcome: str = "accepted"
    summary: str = ""
    details: dict[str, Any] | None = None
    merge: bool = False
    merge_method: str = "squash"


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


def _project_repo_cwd(project: Project, repo_path: str | None = None) -> str:
    root = os.path.realpath(project_directory_from_project(project).host_path)
    rel = normalize_project_path(repo_path)
    cwd = os.path.realpath(os.path.join(root, rel)) if rel else root
    prefix = root.rstrip(os.sep) + os.sep
    if cwd != root and not cwd.startswith(prefix):
        raise ValueError("repo_path must stay inside the Project work surface")
    return cwd


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


def _safe_dependency_stack_target(project: Project) -> dict[str, Any]:
    spec = project_dependency_stack_spec(project)
    return {
        "configured": spec.configured,
        "source_path": spec.source_path,
        "env_keys": sorted((spec.env or {}).keys()),
        "commands": sorted((spec.commands or {}).keys()),
    }


def _dev_target_specs(project: Project) -> list[dict[str, Any]]:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    raw = metadata.get("dev_targets")
    snapshot = project_snapshot(project)
    if not isinstance(raw, list):
        raw = snapshot.get("dev_targets")
    if not isinstance(raw, list) and isinstance(snapshot.get("metadata"), dict):
        raw = snapshot["metadata"].get("dev_targets")
    if not isinstance(raw, list):
        return []
    specs: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        key = _slug(str(item.get("key") or item.get("name") or f"target-{index + 1}"), fallback=f"target-{index + 1}", max_len=32)
        env_segment = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").upper() or f"TARGET_{index + 1}"
        range_value = item.get("port_range")
        port_range = DEFAULT_DEV_TARGET_PORT_RANGE
        if isinstance(range_value, str) and "-" in range_value:
            start, end = range_value.split("-", 1)
            try:
                port_range = (int(start), int(end))
            except ValueError:
                port_range = DEFAULT_DEV_TARGET_PORT_RANGE
        elif isinstance(range_value, list) and len(range_value) == 2:
            try:
                port_range = (int(range_value[0]), int(range_value[1]))
            except (TypeError, ValueError):
                port_range = DEFAULT_DEV_TARGET_PORT_RANGE
        if port_range[0] <= 0 or port_range[1] > 65_535 or port_range[0] > port_range[1]:
            port_range = DEFAULT_DEV_TARGET_PORT_RANGE
        specs.append({
            "key": key,
            "label": str(item.get("label") or item.get("name") or key),
            "port_env": str(item.get("port_env") or f"SPINDREL_DEV_{env_segment}_PORT"),
            "url_env": str(item.get("url_env") or f"SPINDREL_DEV_{env_segment}_URL"),
            "url_template": str(item.get("url_template") or "http://127.0.0.1:{port}"),
            "port_range": port_range,
        })
    return specs


def _is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.05)
        return sock.connect_ex((host, port)) == 0


def _dev_target_env(dev_targets: list[dict[str, Any]]) -> dict[str, str]:
    env: dict[str, str] = {}
    for target in dev_targets:
        port_env = str(target.get("port_env") or "").strip()
        url_env = str(target.get("url_env") or "").strip()
        if port_env and target.get("port") is not None:
            env[port_env] = str(target["port"])
        if url_env and target.get("url"):
            env[url_env] = str(target["url"])
    return env


async def allocate_project_run_dev_targets(
    db: AsyncSession,
    project: Project,
    *,
    task_id: uuid.UUID,
) -> list[dict[str, Any]]:
    specs = _dev_target_specs(project)
    if not specs:
        return []
    channel_ids = list((await db.execute(
        select(Channel.id).where(Channel.project_id == project.id)
    )).scalars().all())
    assigned_ports: set[int] = set()
    if channel_ids:
        tasks = list((await db.execute(
            select(Task).where(Task.channel_id.in_(channel_ids), Task.id != task_id)
        )).scalars().all())
        for task in tasks:
            if task.status in {"complete", "completed", "failed", "cancelled"}:
                continue
            cfg = _task_run_config(task)
            for target in cfg.get("dev_targets") or []:
                if isinstance(target, dict):
                    try:
                        assigned_ports.add(int(target.get("port")))
                    except (TypeError, ValueError):
                        continue
    allocated: list[dict[str, Any]] = []
    for spec in specs:
        start, end = spec["port_range"]
        port = None
        for candidate in range(start, end + 1):
            if candidate in assigned_ports or _is_port_listening(candidate):
                continue
            port = candidate
            assigned_ports.add(candidate)
            break
        if port is None:
            raise ValueError(f"no available dev target port for {spec['key']} in {start}-{end}")
        url = spec["url_template"].replace("{host}", "127.0.0.1").replace("{port}", str(port))
        allocated.append({
            "key": spec["key"],
            "label": spec["label"],
            "port": port,
            "port_env": spec["port_env"],
            "url": url,
            "url_env": spec["url_env"],
        })
    return allocated


async def _attach_task_machine_grant(
    db: AsyncSession,
    *,
    task: Task,
    grant: ProjectMachineTargetGrant | None,
    granted_by_user_id: uuid.UUID | None,
) -> None:
    if grant is None:
        return
    from app.services.machine_task_grants import upsert_task_machine_grant

    await upsert_task_machine_grant(
        db,
        task=task,
        provider_id=grant.provider_id,
        target_id=grant.target_id,
        granted_by_user_id=granted_by_user_id,
        capabilities=grant.capabilities,
        allow_agent_tools=grant.allow_agent_tools,
        expires_at=grant.expires_at,
    )


def _machine_target_grant_summary(grant: ProjectMachineTargetGrant | None) -> dict[str, Any] | None:
    if grant is None:
        return None
    return {
        "provider_id": grant.provider_id,
        "target_id": grant.target_id,
        "capabilities": list(grant.capabilities or []),
        "allow_agent_tools": bool(grant.allow_agent_tools),
        "expires_at": grant.expires_at.isoformat() if isinstance(grant.expires_at, datetime) else grant.expires_at,
    }


def _machine_access_prompt_block(grant: ProjectMachineTargetGrant | None) -> str:
    if grant is None:
        return (
            "Machine/e2e access:\n"
            "- No task-scoped machine target grant was attached to this run.\n"
            "- Use the Project workspace, runtime env, and normal tools only; do not assume host, SSH, browser-live, or e2e target access.\n"
        )
    capabilities = ", ".join(grant.capabilities or ["provider default"])
    tool_line = (
        "machine_status, machine_inspect_command, and machine_exec_command may be used within this task grant."
        if grant.allow_agent_tools
        else "LLM machine tools are disabled; only deterministic machine pipeline steps may consume this grant."
    )
    return (
        "Machine/e2e access:\n"
        f"- Task-scoped grant: {grant.provider_id}/{grant.target_id}\n"
        f"- Capabilities: {capabilities}\n"
        f"- Agent tools: {tool_line}\n"
        "- Use this target for e2e/browser/server checks when the task requires external execution access, and report any target-readiness blocker in the run receipt.\n"
    )


def _execution_config_from_preset(
    defaults: Any,
    *,
    project: Project,
    project_id: uuid.UUID,
    run_defaults: dict[str, Any],
    runtime_target: dict[str, Any],
    dev_targets: list[dict[str, Any]],
    request: str,
    machine_target_grant: ProjectMachineTargetGrant | None = None,
    source_work_pack_id: uuid.UUID | None = None,
) -> dict[str, Any]:
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
            "dev_targets": dev_targets,
            "dev_target_env": _dev_target_env(dev_targets),
            "dependency_stack": _safe_dependency_stack_target(project),
            "machine_target_grant": _machine_target_grant_summary(machine_target_grant),
            "source_work_pack_id": str(source_work_pack_id) if source_work_pack_id else None,
            "schedule_task_id": None,
            "schedule_run_number": None,
            "continuation_index": 0,
        },
    }


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


def _task_run_config(task: Task) -> dict[str, Any]:
    ecfg = task.execution_config if isinstance(task.execution_config, dict) else {}
    run = ecfg.get("project_coding_run")
    return dict(run) if isinstance(run, dict) else {}


def _task_summary(task: Task, *, machine_target_grant: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
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
    if machine_target_grant is not None:
        payload["machine_target_grant"] = machine_target_grant
    return payload


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
    metadata = dict(receipt.metadata_ or {}) if receipt is not None and isinstance(receipt.metadata_, dict) else {}
    dev_targets = metadata.get("dev_targets") if isinstance(metadata.get("dev_targets"), list) else []
    return {
        "changed_files_count": len(changed_files),
        "tests_count": len(tests),
        "screenshots_count": len(screenshots),
        "dev_targets_count": len(dev_targets),
        "has_tests": bool(tests),
        "has_screenshots": bool(screenshots),
        "has_dev_targets": bool(dev_targets),
    }


def _task_project_instance_policy(task: Task) -> str:
    ecfg = task.execution_config if isinstance(task.execution_config, dict) else {}
    raw = ecfg.get("project_instance")
    if isinstance(raw, dict) and raw.get("mode") == "fresh":
        return "fresh"
    if ecfg.get("fresh_project_instance"):
        return "fresh"
    return "shared"


def _work_surface_summary(
    *,
    project: Project,
    task: Task,
    instance: ProjectInstance | None,
) -> dict[str, Any]:
    policy = _task_project_instance_policy(task)
    expected = "fresh_project_instance" if policy == "fresh" else "shared_project_root"
    if instance is not None:
        active = instance.status == "ready" and instance.deleted_at is None
        return {
            "kind": "project_instance",
            "isolation": "isolated",
            "expected": expected,
            "active": active,
            "status": instance.status,
            "display_path": f"/workspace/{instance.root_path.strip('/')}",
            "root_path": instance.root_path,
            "project_id": str(project.id),
            "project_instance_id": str(instance.id),
            "owner_kind": instance.owner_kind,
            "owner_id": str(instance.owner_id) if instance.owner_id else None,
            "expires_at": instance.expires_at.isoformat() if instance.expires_at else None,
            "deleted_at": instance.deleted_at.isoformat() if instance.deleted_at else None,
            "blocker": None if active else "Project instance is not ready for this run.",
        }
    if policy == "fresh":
        return {
            "kind": "project_instance",
            "isolation": "pending",
            "expected": expected,
            "active": False,
            "status": "pending",
            "display_path": None,
            "root_path": None,
            "project_id": str(project.id),
            "project_instance_id": None,
            "blocker": "Fresh Project instance has not been created for this run yet.",
        }
    return {
        "kind": "project",
        "isolation": "shared",
        "expected": expected,
        "active": True,
        "status": "ready",
        "display_path": f"/workspace/{project.root_path.strip('/')}",
        "root_path": project.root_path,
        "project_id": str(project.id),
        "project_instance_id": None,
        "blocker": None,
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
    merge_step = _latest_action(activity, "handoff.merge")
    reviewed_step = _latest_action(activity, "review.marked")
    review_result_step = _latest_action(activity, "review.result")
    cleanup_step = _latest_action(activity, "instance.cleanup")

    pr_result = _step_result(pr_step)
    status_result = _step_result(status_step)
    review_result = _step_result(review_result_step)
    merge_result = _step_result(merge_step)
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
    if blocker is None and review_result_step is not None and _step_status(review_result_step) in {"blocked", "needs_review"}:
        blocker = review_result.get("summary") or review_result_step.get("summary")
    if blocker is None and task.error:
        blocker = task.error

    evidence = _evidence_summary(receipt)
    reviewed = _step_status(reviewed_step) == "succeeded"
    reviewed_result = _step_result(reviewed_step)
    if reviewed:
        review_status = "reviewed"
    elif review_result.get("outcome") == "rejected":
        review_status = "changes_requested"
    elif review_result.get("outcome") == "blocked":
        review_status = "blocked"
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
        and task.status not in {"pending", "running"}
    )
    can_continue = task.status not in {"pending", "running"} and not reviewed
    recovery_blocker = None
    if task.status in {"pending", "running"}:
        recovery_blocker = "Run is still active."
    elif reviewed:
        recovery_blocker = "Run is already reviewed."
    return {
        "status": review_status,
        "blocker": blocker,
        "reviewed": reviewed,
        "reviewed_at": reviewed_step.get("created_at") if reviewed_step else None,
        "reviewed_by": reviewed_result.get("reviewed_by"),
        "review_task_id": reviewed_result.get("review_task_id") or review_result.get("review_task_id") or merge_result.get("review_task_id"),
        "review_session_id": reviewed_result.get("review_session_id") or review_result.get("review_session_id") or merge_result.get("review_session_id"),
        "review_summary": reviewed_result.get("summary") or review_result.get("summary"),
        "review_details": reviewed_result.get("details") or review_result.get("details") or {},
        "merge_method": reviewed_result.get("merge_method") or review_result.get("merge_method") or merge_result.get("merge_method"),
        "merged_at": merge_result.get("merged_at"),
        "merge_commit_sha": merge_result.get("merge_commit_sha"),
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
            "merge": {"status": _step_status(merge_step), "summary": merge_step.get("summary") if merge_step else None},
            "review": {"status": _step_status(review_result_step), "summary": review_result_step.get("summary") if review_result_step else None},
            "cleanup": {"status": _step_status(cleanup_step), "summary": cleanup_step.get("summary") if cleanup_step else None},
        },
        "evidence": evidence,
        "instance": instance_payload,
        "recovery": {
            "can_continue": can_continue,
            "blocker": recovery_blocker,
            "suggested_feedback": blocker or review_result.get("summary") or reviewed_result.get("summary") or "",
            "latest_continuation_id": task.execution_config.get("latest_continuation_task_id") if isinstance(task.execution_config, dict) else None,
        },
        "actions": {
            "can_refresh": True,
            "can_mark_reviewed": not reviewed and bool(pr_url or receipt is not None),
            "can_cleanup_instance": can_cleanup,
            "can_request_changes": bool(pr_url or receipt is not None),
            "can_continue": can_continue,
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
    from app.services.machine_task_grants import task_machine_grant_payload
    from app.services.project_dependency_stacks import get_project_dependency_stack

    machine_target_grant = await task_machine_grant_payload(db, task)
    dependency_stack = await get_project_dependency_stack(db, project, task_id=task.id, scope="task")
    ctx = ProjectTaskExecutionContext.from_task(task)
    cfg = _task_run_config(task)
    work_surface = _work_surface_summary(project=project, task=task, instance=instance)
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
        "request": ctx.request or "",
        "branch": ctx.branch,
        "base_branch": ctx.base_branch,
        "repo": dict(ctx.repo),
        "runtime_target": ctx.runtime_target.to_persisted(),
        "dev_targets": [t.to_persisted() for t in ctx.dev_targets],
        "dependency_stack": dependency_stack,
        "dependency_stack_preflight": cfg.get("dependency_stack_preflight") or {},
        "readiness": ctx.readiness_summary(dependency_stack_status=dependency_stack),
        "work_surface": work_surface,
        "source_work_pack_id": ctx.source_work_pack_id,
        "launch_batch_id": cfg.get("launch_batch_id"),
        "parent_task_id": ctx.lineage.parent_task_id,
        "root_task_id": ctx.lineage.root_task_id,
        "continuation_index": ctx.lineage.continuation_index,
        "continuation_feedback": ctx.lineage.continuation_feedback,
        "continuations": [],
        "task": _task_summary(task, machine_target_grant=machine_target_grant),
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


def _review_task_config(task: Task) -> dict[str, Any]:
    ecfg = task.execution_config if isinstance(task.execution_config, dict) else {}
    review = ecfg.get("project_coding_run_review")
    return dict(review) if isinstance(review, dict) else {}


def _review_batch_status(status_counts: dict[str, int], review_sessions: list[dict[str, Any]]) -> str:
    total = sum(status_counts.values())
    active_review = any(session.get("active") for session in review_sessions)
    if total > 0 and status_counts.get("reviewed", 0) == total:
        return "reviewed"
    if active_review:
        return "reviewing"
    if any(status_counts.get(status, 0) for status in ("blocked", "failed", "changes_requested")):
        return "blocked"
    if any(status_counts.get(status, 0) for status in ("ready_for_review", "completed", "needs_review")):
        return "ready_for_review"
    if any(status_counts.get(status, 0) for status in ("running", "pending")):
        return "running"
    return "pending"


def _review_session_row(task: Task) -> dict[str, Any]:
    status = task.status or "unknown"
    return {
        "task_id": str(task.id),
        "status": status,
        "title": task.title,
        "session_id": str(task.session_id) if task.session_id else None,
        "channel_id": str(task.channel_id) if task.channel_id else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "active": status in {"pending", "running"},
    }


def _work_pack_row(pack: IssueWorkPack) -> dict[str, Any]:
    metadata = dict(pack.metadata_ or {}) if isinstance(pack.metadata_, dict) else {}
    latest = metadata.get("latest_review_action")
    return {
        "id": str(pack.id),
        "title": pack.title,
        "summary": pack.summary,
        "status": pack.status,
        "category": pack.category,
        "confidence": pack.confidence,
        "launched_task_id": str(pack.launched_task_id) if pack.launched_task_id else None,
        "latest_review_action": dict(latest) if isinstance(latest, dict) else None,
    }


def _review_receipt_row(receipt: ExecutionReceipt) -> dict[str, Any]:
    result = dict(receipt.result or {}) if isinstance(receipt.result, dict) else {}
    outcome = str(result.get("outcome") or "").strip() or (
        "accepted" if receipt.action_type == "review.marked" and receipt.status == "succeeded" else receipt.status
    )
    merge_result = result.get("merge_result") if isinstance(result.get("merge_result"), dict) else {}
    return {
        "id": str(receipt.id),
        "task_id": str(receipt.task_id) if receipt.task_id else None,
        "action_type": receipt.action_type,
        "status": receipt.status,
        "outcome": outcome,
        "summary": receipt.summary,
        "details": dict(result.get("details") or {}) if isinstance(result.get("details"), dict) else {},
        "merge": bool(result.get("merge")),
        "merge_method": result.get("merge_method"),
        "merge_result": merge_result,
        "created_at": receipt.created_at.isoformat() if receipt.created_at else None,
    }


def _review_session_ledger_status(
    task: Task,
    *,
    run_count: int,
    outcome_counts: dict[str, int],
) -> str:
    if outcome_counts.get("blocked", 0) > 0:
        return "blocked"
    reviewed_count = sum(outcome_counts.values())
    if run_count > 0 and reviewed_count >= run_count:
        return "finalized"
    if task.status in {"pending", "running"}:
        return "active"
    if reviewed_count > 0:
        return "partially_reviewed"
    return task.status or "unknown"


def _compact_review_run_row(run: dict[str, Any]) -> dict[str, Any]:
    review = run.get("review") if isinstance(run.get("review"), dict) else {}
    receipt = run.get("receipt") if isinstance(run.get("receipt"), dict) else None
    evidence = review.get("evidence") if isinstance(review.get("evidence"), dict) else {}
    task = run.get("task") if isinstance(run.get("task"), dict) else {}
    pr = review.get("pr") if isinstance(review.get("pr"), dict) else {}
    return {
        "id": run.get("id"),
        "task_id": task.get("id") or run.get("id"),
        "title": task.get("title"),
        "status": run.get("status"),
        "review_status": review.get("status"),
        "branch": run.get("branch"),
        "launch_batch_id": run.get("launch_batch_id"),
        "source_work_pack_id": run.get("source_work_pack_id"),
        "handoff_url": review.get("handoff_url") or (receipt or {}).get("handoff_url") or pr.get("url"),
        "receipt_summary": (receipt or {}).get("summary"),
        "evidence": {
            "tests_count": evidence.get("tests_count", 0),
            "screenshots_count": evidence.get("screenshots_count", 0),
            "changed_files_count": evidence.get("changed_files_count", 0),
            "dev_targets_count": evidence.get("dev_targets_count", 0),
        },
        "updated_at": run.get("updated_at"),
    }


async def list_project_coding_run_review_sessions(
    db: AsyncSession,
    project: Project,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return review-session ledger rows derived from review tasks and receipts."""
    channel_ids = list((await db.execute(
        select(Channel.id).where(Channel.project_id == project.id)
    )).scalars().all())
    if not channel_ids:
        return []

    candidates = list((await db.execute(
        select(Task)
        .where(Task.channel_id.in_(channel_ids))
        .order_by(Task.created_at.desc())
        .limit(max(1, min(limit * 4, 250)))
    )).scalars().all())
    review_tasks = [
        task for task in candidates
        if isinstance(task.execution_config, dict)
        and task.execution_config.get("run_preset_id") == PROJECT_CODING_RUN_REVIEW_PRESET_ID
    ][: max(1, min(limit, 100))]
    if not review_tasks:
        return []

    selected_ids: set[uuid.UUID] = set()
    selected_by_review: dict[uuid.UUID, list[uuid.UUID]] = {}
    for task in review_tasks:
        cfg = _review_task_config(task)
        ids: list[uuid.UUID] = []
        for item in cfg.get("selected_task_ids") or []:
            parsed = _uuid_from_config(item)
            if parsed is not None:
                ids.append(parsed)
                selected_ids.add(parsed)
        selected_by_review[task.id] = ids

    selected_tasks_by_id: dict[uuid.UUID, Task] = {}
    if selected_ids:
        selected_tasks = list((await db.execute(
            select(Task).where(Task.id.in_(selected_ids))
        )).scalars().all())
        selected_tasks_by_id = {
            task.id: task
            for task in selected_tasks
            if isinstance(task.execution_config, dict)
            and task.execution_config.get("run_preset_id") == PROJECT_CODING_RUN_PRESET_ID
        }

    receipts_by_task = await _latest_run_receipts_by_task(db, project.id, list(selected_tasks_by_id))
    run_rows_by_task: dict[uuid.UUID, dict[str, Any]] = {}
    for task_id, task in selected_tasks_by_id.items():
        run_rows_by_task[task_id] = await _coding_run_row(db, project, task, receipts_by_task.get(task_id))

    review_receipts_by_review: dict[uuid.UUID, list[ExecutionReceipt]] = {task.id: [] for task in review_tasks}
    if selected_tasks_by_id:
        review_receipts = list((await db.execute(
            select(ExecutionReceipt)
            .where(
                ExecutionReceipt.scope == "project_coding_run",
                ExecutionReceipt.action_type.in_(["review.marked", "review.result"]),
                ExecutionReceipt.task_id.in_(list(selected_tasks_by_id)),
            )
            .order_by(ExecutionReceipt.created_at.desc())
            .limit(500)
        )).scalars().all())
        review_task_ids = set(review_receipts_by_review)
        for receipt in review_receipts:
            result = dict(receipt.result or {}) if isinstance(receipt.result, dict) else {}
            review_task_id = _uuid_from_config(result.get("review_task_id"))
            if review_task_id in review_task_ids:
                review_receipts_by_review.setdefault(review_task_id, []).append(receipt)

    pack_ids: set[uuid.UUID] = set()
    for run in run_rows_by_task.values():
        source_id = _uuid_from_config(run.get("source_work_pack_id"))
        if source_id is not None:
            pack_ids.add(source_id)
    packs_by_id: dict[uuid.UUID, IssueWorkPack] = {}
    if pack_ids:
        packs_by_id = {
            pack.id: pack for pack in list((await db.execute(
                select(IssueWorkPack).where(IssueWorkPack.id.in_(pack_ids), IssueWorkPack.project_id == project.id)
            )).scalars().all())
        }

    rows: list[dict[str, Any]] = []
    for task in review_tasks:
        cfg = _review_task_config(task)
        selected_task_ids = selected_by_review.get(task.id, [])
        selected_runs = [
            run_rows_by_task[run_task_id]
            for run_task_id in selected_task_ids
            if run_task_id in run_rows_by_task
        ]
        compact_runs = [_compact_review_run_row(run) for run in selected_runs]
        evidence = {"tests_count": 0, "screenshots_count": 0, "changed_files_count": 0, "dev_targets_count": 0}
        launch_batch_ids: set[str] = set()
        source_pack_ids: set[uuid.UUID] = set()
        updated_values: list[str] = []
        for run in compact_runs:
            if run.get("launch_batch_id"):
                launch_batch_ids.add(str(run["launch_batch_id"]))
            source_id = _uuid_from_config(run.get("source_work_pack_id"))
            if source_id is not None:
                source_pack_ids.add(source_id)
            run_evidence = run.get("evidence") if isinstance(run.get("evidence"), dict) else {}
            for key in evidence:
                try:
                    evidence[key] += int(run_evidence.get(key) or 0)
                except (TypeError, ValueError):
                    continue
            if run.get("updated_at"):
                updated_values.append(str(run["updated_at"]))

        receipt_rows = [_review_receipt_row(receipt) for receipt in review_receipts_by_review.get(task.id, [])]
        outcome_counts: dict[str, int] = {}
        for receipt in receipt_rows:
            outcome = str(receipt.get("outcome") or "unknown")
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        status = _review_session_ledger_status(task, run_count=len(compact_runs), outcome_counts=outcome_counts)
        source_packs = sorted(
            [_work_pack_row(packs_by_id[pack_id]) for pack_id in source_pack_ids if pack_id in packs_by_id],
            key=lambda item: item["title"].lower(),
        )
        latest_summary = receipt_rows[0]["summary"] if receipt_rows else task.result
        latest_activity = max(
            [value for value in [
                task.completed_at.isoformat() if task.completed_at else None,
                task.created_at.isoformat() if task.created_at else None,
                *(row.get("created_at") for row in receipt_rows),
                *updated_values,
            ] if value],
            default=None,
        )
        merge_requested = [row for row in receipt_rows if row.get("merge")]
        merge_completed = [
            row for row in merge_requested
            if isinstance(row.get("merge_result"), dict)
            and row["merge_result"].get("ok") is not False
            and row["merge_result"]
        ]
        rows.append({
            "id": str(task.id),
            "task_id": str(task.id),
            "project_id": str(project.id),
            "status": status,
            "task_status": task.status or "unknown",
            "title": task.title,
            "session_id": str(task.session_id) if task.session_id else None,
            "channel_id": str(task.channel_id) if task.channel_id else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "latest_activity_at": latest_activity,
            "selected_task_ids": [str(item) for item in selected_task_ids],
            "selected_run_ids": [str(run["id"]) for run in compact_runs if run.get("id")],
            "run_count": len(compact_runs),
            "launch_batch_ids": sorted(launch_batch_ids),
            "outcome_counts": outcome_counts,
            "evidence": evidence,
            "source_work_packs": source_packs,
            "selected_runs": compact_runs,
            "summaries": receipt_rows[:10],
            "latest_summary": latest_summary,
            "merge": {
                "method": cfg.get("merge_method"),
                "requested_count": len(merge_requested),
                "completed_count": len(merge_completed),
            },
            "actions": {
                "can_open_task": True,
                "can_select_runs": bool(compact_runs),
                "active": task.status in {"pending", "running"},
                "finalized": status == "finalized",
            },
        })

    return sorted(
        rows,
        key=lambda row: str(row.get("latest_activity_at") or row.get("created_at") or ""),
        reverse=True,
    )[: max(1, min(limit, 100))]


async def list_project_coding_run_review_batches(
    db: AsyncSession,
    project: Project,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return launch-batch review inbox rows derived from existing Project run state."""
    runs = await list_project_coding_runs(db, project, limit=max(25, min(limit * 4, 100)))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        batch_id = run.get("launch_batch_id")
        if not batch_id:
            continue
        grouped.setdefault(str(batch_id), []).append(run)
    if not grouped:
        return []

    batch_ids = set(grouped)
    packs = list((await db.execute(
        select(IssueWorkPack)
        .where(IssueWorkPack.project_id == project.id)
        .order_by(IssueWorkPack.updated_at.desc(), IssueWorkPack.created_at.desc())
        .limit(250)
    )).scalars().all())
    packs_by_batch: dict[str, list[IssueWorkPack]] = {batch_id: [] for batch_id in batch_ids}
    for pack in packs:
        metadata = pack.metadata_ if isinstance(pack.metadata_, dict) else {}
        batch_id = metadata.get("launch_batch_id")
        if batch_id in packs_by_batch:
            packs_by_batch[str(batch_id)].append(pack)

    channel_ids = list((await db.execute(
        select(Channel.id).where(Channel.project_id == project.id)
    )).scalars().all())
    review_tasks: list[Task] = []
    if channel_ids:
        candidates = list((await db.execute(
            select(Task)
            .where(Task.channel_id.in_(channel_ids))
            .order_by(Task.created_at.desc())
            .limit(250)
        )).scalars().all())
        review_tasks = [
            task for task in candidates
            if isinstance(task.execution_config, dict)
            and task.execution_config.get("run_preset_id") == PROJECT_CODING_RUN_REVIEW_PRESET_ID
        ]

    review_sessions_by_run: dict[str, list[dict[str, Any]]] = {}
    for task in review_tasks:
        cfg = _review_task_config(task)
        selected = [str(item) for item in cfg.get("selected_task_ids") or []]
        if not selected:
            continue
        row = _review_session_row(task)
        for run_task_id in selected:
            review_sessions_by_run.setdefault(run_task_id, []).append(row)

    inbox: list[dict[str, Any]] = []
    for batch_id, batch_runs in grouped.items():
        status_counts: dict[str, int] = {}
        evidence = {"tests_count": 0, "screenshots_count": 0, "changed_files_count": 0, "dev_targets_count": 0}
        review_sessions_by_id: dict[str, dict[str, Any]] = {}
        updated_values: list[str] = []
        ready_run_ids: list[str] = []
        unreviewed_run_ids: list[str] = []

        for run in batch_runs:
            review = run.get("review") if isinstance(run.get("review"), dict) else {}
            status = str(review.get("status") or run.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            if status in {"ready_for_review", "completed", "needs_review"}:
                ready_run_ids.append(str(run["id"]))
            if status != "reviewed":
                unreviewed_run_ids.append(str(run["id"]))
            run_evidence = review.get("evidence") if isinstance(review.get("evidence"), dict) else {}
            for key in evidence:
                try:
                    evidence[key] += int(run_evidence.get(key) or 0)
                except (TypeError, ValueError):
                    continue
            if run.get("updated_at"):
                updated_values.append(str(run["updated_at"]))
            for session in review_sessions_by_run.get(str(run["task"]["id"]), []):
                review_sessions_by_id[session["task_id"]] = session

        review_sessions = sorted(
            review_sessions_by_id.values(),
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )
        source_packs = sorted(
            [_work_pack_row(pack) for pack in packs_by_batch.get(batch_id, [])],
            key=lambda item: item["title"].lower(),
        )
        status = _review_batch_status(status_counts, review_sessions)
        active_review = next((session for session in review_sessions if session.get("active")), None)
        latest_review = review_sessions[0] if review_sessions else None
        latest_run = max(batch_runs, key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""))
        inbox.append({
            "id": batch_id,
            "project_id": str(project.id),
            "status": status,
            "run_count": len(batch_runs),
            "status_counts": status_counts,
            "evidence": evidence,
            "run_ids": [str(run["id"]) for run in batch_runs],
            "task_ids": [str(run["task"]["id"]) for run in batch_runs],
            "ready_run_ids": ready_run_ids,
            "unreviewed_run_ids": unreviewed_run_ids,
            "source_work_packs": source_packs,
            "review_sessions": review_sessions,
            "active_review_task": active_review,
            "latest_review_task": latest_review,
            "latest_activity_at": max(updated_values) if updated_values else latest_run.get("updated_at") or latest_run.get("created_at"),
            "summary": {
                "title": source_packs[0]["title"] if source_packs else f"Launch batch {batch_id}",
                "source_work_pack_count": len(source_packs),
                "ready_count": len(ready_run_ids),
                "unreviewed_count": len(unreviewed_run_ids),
            },
            "actions": {
                "can_select": True,
                "can_start_review": bool(batch_runs) and status != "reviewed",
                "can_resume_review": active_review is not None,
                "can_mark_reviewed": bool(unreviewed_run_ids),
            },
        })

    return sorted(
        inbox,
        key=lambda row: str(row.get("latest_activity_at") or ""),
        reverse=True,
    )[: max(1, min(limit, 100))]
