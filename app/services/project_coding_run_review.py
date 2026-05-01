"""Project coding-run review lifecycle.

Owns review session creation, finalization, mark-reviewed flows, instance
cleanup, and the read-side review-context endpoint plus the review prompt
template machinery.

Imports go: review → lib. Never the reverse, and never to orchestration or
schedule. The cross-lifecycle entry point is ``project_coding_runs`` re-exports.
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Channel, IssueWorkPack, Project, ProjectInstance, Task
from app.services.execution_receipts import create_execution_receipt
from app.services.project_instances import cleanup_project_instance
from app.services.project_run_handoff import (
    CommandRunner,
    _clip,
    _default_command_runner,
    merge_project_run_handoff,
)
from app.services.project_runtime import load_project_runtime_environment, project_snapshot
from app.services.run_presets import get_run_preset

from app.services.project_coding_run_lib import (
    PROJECT_CODING_RUN_REVIEW_PRESET_ID,
    PROJECT_REVIEW_TEMPLATE_MARKER,
    ProjectCodingRunReviewCreate,
    ProjectCodingRunReviewFinalize,
    ProjectTaskExecutionContext,
    _attach_task_machine_grant,
    _coding_run_row,
    _first_repo,
    _latest_run_receipts_by_task,
    _load_project_coding_task,
    _machine_access_prompt_block,
    _project_repo_cwd,
    _safe_runtime_target,
    _task_run_config,
    _utcnow,
    get_project_coding_run,
)


def _review_error_payload(
    *,
    error: str,
    error_code: str,
    status: str = "blocked",
    run_task_id: uuid.UUID | None = None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "status": status,
        "error": error,
        "error_code": error_code,
        "error_kind": "validation",
        "retryable": retryable,
    }
    if run_task_id is not None:
        payload["run_task_id"] = str(run_task_id)
    if details:
        payload["details"] = details
    return payload


def _substitute_review_template_variables(text: str, variables: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        value = variables.get(key, "")
        if isinstance(value, (dict, list)):
            return str(value)
        return str(value)

    return re.sub(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}", repl, text)


async def expand_project_review_prompt_template(
    template: str,
    *,
    variables: dict[str, Any],
    cwd: str,
    env: dict[str, str] | None = None,
    command_runner: CommandRunner | None = None,
) -> str:
    """Expand Project review templates, including raw Sandcastle-style ! shell lines."""
    commands: list[str] = []

    def mark(match: re.Match[str]) -> str:
        index = len(commands)
        command = (match.group(1) or match.group(2) or "").strip()
        commands.append(command)
        return f"{PROJECT_REVIEW_TEMPLATE_MARKER}{index}"

    marked = re.sub(r"(?m)^!\s*(?:`([^`\n]+)`|(.+?))\s*$", mark, template)
    substituted = _substitute_review_template_variables(marked, variables)
    runner = command_runner or _default_command_runner
    resolved_env = dict(env or {})

    for index, command in enumerate(commands):
        expanded_command = _substitute_review_template_variables(command, variables)
        result = await runner(cwd, ("bash", "-lc", expanded_command), resolved_env, 30)
        if not result.ok:
            detail = _clip(result.stderr or result.stdout or f"command failed: {expanded_command}", limit=600)
            raise ValueError(f"Project review prompt command failed: {detail}")
        output = _clip(result.stdout, limit=4_000) or "(no output)"
        block = f"```console\n$ {expanded_command}\n{output}\n```"
        substituted = substituted.replace(f"{PROJECT_REVIEW_TEMPLATE_MARKER}{index}", block)
    return substituted


def _normal_merge_method(value: str | None) -> str:
    method = (value or "squash").strip().lower()
    if method not in {"squash", "merge", "rebase"}:
        raise ValueError("merge_method must be one of squash, merge, rebase")
    return method


def _normal_review_outcome(value: str | None) -> str:
    outcome = (value or "accepted").strip().lower()
    aliases = {"accept": "accepted", "approve": "accepted", "approved": "accepted", "reject": "rejected"}
    outcome = aliases.get(outcome, outcome)
    if outcome not in {"accepted", "rejected", "blocked"}:
        raise ValueError("outcome must be one of accepted, rejected, blocked")
    return outcome


def _review_session_config(task: Task | None) -> dict[str, Any]:
    if task is None or not isinstance(task.execution_config, dict):
        return {}
    raw = task.execution_config.get("project_coding_run_review")
    return dict(raw) if isinstance(raw, dict) else {}


async def _load_project_review_task(db: AsyncSession, project: Project, task_id: uuid.UUID) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise ValueError("review session not found")
    channel = await db.get(Channel, task.channel_id) if task.channel_id else None
    if channel is None or channel.project_id != project.id:
        raise ValueError("review session not found")
    if not isinstance(task.execution_config, dict) or task.execution_config.get("run_preset_id") != PROJECT_CODING_RUN_REVIEW_PRESET_ID:
        raise ValueError("review session not found")
    return task


def _selected_runs_prompt_block(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in rows:
        review = row.get("review") or {}
        receipt = row.get("receipt") or {}
        lines.append(
            "\n".join([
                f"- Run task: {row['task']['id']}",
                f"  Request: {row.get('request') or row['task'].get('title') or 'Project coding run'}",
                f"  Branch: {row.get('branch') or 'not recorded'}",
                f"  Base: {row.get('base_branch') or 'repository default'}",
                f"  Review state: {review.get('status') or row.get('status')}",
                f"  Handoff: {review.get('handoff_url') or receipt.get('handoff_url') or 'not recorded'}",
                f"  Evidence: {_evidence_summary_for_prompt(review, receipt)}",
            ])
        )
    return "\n".join(lines)


def _evidence_summary_for_prompt(review: dict[str, Any], receipt: dict[str, Any]) -> str:
    evidence = review.get("evidence") if isinstance(review, dict) else None
    if isinstance(evidence, dict):
        return (
            f"{evidence.get('tests_count', 0)} tests, "
            f"{evidence.get('screenshots_count', 0)} screenshots, "
            f"{evidence.get('changed_files_count', 0)} files, "
            f"{evidence.get('dev_targets_count', 0)} dev targets"
        )
    return (
        f"{len(receipt.get('tests') or [])} tests, "
        f"{len(receipt.get('screenshots') or [])} screenshots, "
        f"{len(receipt.get('changed_files') or [])} files, "
        f"{len((receipt.get('metadata') or {}).get('dev_targets') or [])} dev targets"
    )


def _review_context_row(row: dict[str, Any]) -> dict[str, Any]:
    review = row.get("review") or {}
    receipt = row.get("receipt") or {}
    task = row.get("task") or {}
    return {
        "id": row.get("id"),
        "task_id": task.get("id"),
        "title": task.get("title"),
        "request": row.get("request") or task.get("title"),
        "status": row.get("status"),
        "review_status": review.get("status") or row.get("status"),
        "branch": row.get("branch"),
        "base_branch": row.get("base_branch"),
        "repo": row.get("repo") or {},
        "dev_targets": row.get("dev_targets") or [],
        "source_work_pack_id": row.get("source_work_pack_id"),
        "launch_batch_id": row.get("launch_batch_id"),
        "handoff_url": review.get("handoff_url") or receipt.get("handoff_url"),
        "review": {
            "reviewed": bool(review.get("reviewed")),
            "blocker": review.get("blocker"),
            "pr": review.get("pr") or {},
            "steps": review.get("steps") or {},
            "evidence": review.get("evidence") or {
                "changed_files_count": len(receipt.get("changed_files") or []),
                "tests_count": len(receipt.get("tests") or []),
                "screenshots_count": len(receipt.get("screenshots") or []),
                "has_tests": bool(receipt.get("tests")),
                "has_screenshots": bool(receipt.get("screenshots")),
            },
            "actions": review.get("actions") or {},
        },
        "receipt": {
            "id": receipt.get("id"),
            "status": receipt.get("status"),
            "summary": receipt.get("summary"),
            "handoff_url": receipt.get("handoff_url"),
            "changed_files": receipt.get("changed_files") or [],
            "tests": receipt.get("tests") or [],
            "screenshots": receipt.get("screenshots") or [],
            "dev_targets": (receipt.get("metadata") or {}).get("dev_targets") or [],
        } if receipt else None,
    }


def _review_context_readiness(
    *,
    rows: list[dict[str, Any]],
    runtime_payload: dict[str, Any],
    review_cfg: dict[str, Any],
    machine_target_grant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_target = _safe_runtime_target(runtime_payload)
    keys = set(runtime_target.get("configured_keys") or [])
    blockers: list[str] = []
    warnings: list[str] = []
    if not rows:
        blockers.append("No selected coding runs were resolved for this review session.")
    if not runtime_target.get("ready", True):
        warnings.append("Project runtime environment has missing, invalid, or reserved variables.")
    if not any((row.get("review") or {}).get("handoff_url") or (row.get("receipt") or {}).get("handoff_url") for row in rows):
        warnings.append("No selected run has a recorded handoff URL.")
    if not any((row.get("review") or {}).get("evidence", {}).get("has_tests") or (row.get("receipt") or {}).get("tests") for row in rows):
        warnings.append("No selected run has recorded test evidence.")
    if not any((row.get("review") or {}).get("evidence", {}).get("has_screenshots") or (row.get("receipt") or {}).get("screenshots") for row in rows):
        warnings.append("No selected run has recorded screenshot evidence.")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "merge_method": _normal_merge_method(review_cfg.get("merge_method")),
        "runtime_env": runtime_target,
        "e2e": {
            "configured": bool(keys & {"SPINDREL_E2E_URL", "E2E_BASE_URL", "E2E_HOST", "E2E_PORT", "SPINDREL_UI_URL"}),
            "configured_keys": [key for key in runtime_target.get("configured_keys") or [] if key.startswith("E2E") or key.startswith("SPINDREL")],
        },
        "github": {
            "token_configured": "GITHUB_TOKEN" in keys,
            "configured_keys": [key for key in runtime_target.get("configured_keys") or [] if key == "GITHUB_TOKEN"],
        },
        "machine_target": {
            "granted": machine_target_grant is not None,
            "provider_id": machine_target_grant.get("provider_id") if machine_target_grant else None,
            "target_id": machine_target_grant.get("target_id") if machine_target_grant else None,
            "capabilities": list(machine_target_grant.get("capabilities") or []) if machine_target_grant else [],
            "allow_agent_tools": bool(machine_target_grant.get("allow_agent_tools")) if machine_target_grant else False,
        },
    }


async def get_project_coding_run_review_context(
    db: AsyncSession,
    project: Project,
    review_task_id: uuid.UUID,
) -> dict[str, Any]:
    """Return a compact, secret-safe manifest for a Project coding-run review task."""
    review_task = await _load_project_review_task(db, project, review_task_id)
    review_cfg = _review_session_config(review_task)
    selected_ids: list[uuid.UUID] = []
    for raw in review_cfg.get("selected_task_ids") or []:
        try:
            selected_ids.append(uuid.UUID(str(raw)))
        except ValueError:
            continue

    selected_tasks = [await _load_project_coding_task(db, project, task_id) for task_id in selected_ids]
    receipts_by_task = await _latest_run_receipts_by_task(db, project.id, [task.id for task in selected_tasks])
    rows = [
        await _coding_run_row(db, project, task, receipts_by_task.get(task.id))
        for task in selected_tasks
    ]
    runtime = await load_project_runtime_environment(db, project)
    runtime_payload = runtime.safe_payload()
    repo_path = str(review_cfg.get("repo_path") or "").strip() or None
    from app.services.machine_task_grants import task_machine_grant_payload

    machine_target_grant = await task_machine_grant_payload(db, review_task)
    return {
        "ok": True,
        "project": {
            "id": str(project.id),
            "name": project.name,
            "root_path": project.root_path,
            "repo_path": repo_path,
        },
        "review_task": {
            "id": str(review_task.id),
            "status": review_task.status,
            "title": review_task.title,
            "bot_id": review_task.bot_id,
            "channel_id": str(review_task.channel_id) if review_task.channel_id else None,
            "session_id": str(review_task.session_id) if review_task.session_id else None,
        },
        "operator_prompt": review_cfg.get("operator_prompt") or "",
        "selected_task_ids": [str(task_id) for task_id in selected_ids],
        "selected_runs": [_review_context_row(row) for row in rows],
        "readiness": _review_context_readiness(
            rows=rows,
            runtime_payload=runtime_payload,
            review_cfg=review_cfg,
            machine_target_grant=machine_target_grant,
        ),
        "finalization": {
            "tool": "finalize_project_coding_run_review",
            "required_per_run": True,
            "accepted_marks_reviewed": True,
            "rejected_or_blocked_stays_open": True,
            "merge_requires_explicit_operator_request": True,
        },
    }


async def create_project_coding_run_review_session(
    db: AsyncSession,
    project: Project,
    body: ProjectCodingRunReviewCreate,
) -> Task:
    channel = await db.get(Channel, body.channel_id)
    if channel is None:
        raise ValueError("channel not found")
    if channel.project_id != project.id:
        raise ValueError("channel does not belong to this Project")
    if not body.task_ids:
        raise ValueError("at least one coding run is required")
    preset = get_run_preset(PROJECT_CODING_RUN_REVIEW_PRESET_ID)
    if preset is None:
        raise ValueError("Project coding-run review preset is not registered")

    selected_tasks: list[Task] = []
    seen: set[uuid.UUID] = set()
    for task_id in body.task_ids:
        if task_id in seen:
            continue
        selected_tasks.append(await _load_project_coding_task(db, project, task_id))
        seen.add(task_id)
    if not selected_tasks:
        raise ValueError("at least one coding run is required")

    rows: list[dict[str, Any]] = []
    receipts_by_task = await _latest_run_receipts_by_task(db, project.id, [task.id for task in selected_tasks])
    for task in selected_tasks:
        rows.append(await _coding_run_row(db, project, task, receipts_by_task.get(task.id)))

    first_ctx = ProjectTaskExecutionContext.from_task(selected_tasks[0])
    repo_path = str(first_ctx.repo.get("path") or "").strip() or None
    if repo_path is None:
        repo_path = str(_first_repo(project_snapshot(project)).get("path") or "").strip() or None
    cwd = _project_repo_cwd(project, repo_path)
    operator_prompt = body.prompt.strip() or "Review the selected runs and report decisions. Do not merge unless this prompt explicitly asks you to merge."

    new_task_id = uuid.uuid4()
    ctx = await ProjectTaskExecutionContext.review(
        db,
        project,
        task_id=new_task_id,
        selected_task_ids=[task.id for task in selected_tasks],
        operator_prompt=operator_prompt,
        merge_method=_normal_merge_method(body.merge_method),
        repo_path=repo_path,
        machine_grant=body.machine_target_grant,
        granted_by_user_id=body.granted_by_user_id,
    )
    env = os.environ.copy()
    env.update(ctx.env_for_subprocess())

    template = (
        f"{preset.task_defaults.prompt}\n\n"
        "Operator review request:\n{{operator_prompt}}\n\n"
        "Project:\n"
        f"- Name: {project.name}\n"
        f"- Root: /{project.root_path}\n"
        f"- Repository path: {repo_path or 'Project root'}\n"
        f"- Merge method default: {_normal_merge_method(body.merge_method)}\n\n"
        f"{_machine_access_prompt_block(body.machine_target_grant)}\n"
        "Selected coding runs:\n{{selected_runs}}\n\n"
        "Project workspace snapshot:\n"
        "! `git status --short || true`\n"
        "! `git log --oneline -5 || true`\n\n"
        "When you finish each selected run, call finalize_project_coding_run_review with the run task id, outcome, summary, details, and merge settings."
    )
    prompt = await expand_project_review_prompt_template(
        template,
        variables={
            "operator_prompt": operator_prompt,
            "selected_runs": _selected_runs_prompt_block(rows),
        },
        cwd=cwd,
        env=env,
    )
    task = Task(
        id=new_task_id,
        prompt=prompt,
        scheduled_at=None,
        status="pending",
        recurrence=None,
        created_at=_utcnow(),
    )
    ctx.apply_to_task(task, channel=channel)
    db.add(task)
    await db.flush()
    await _attach_task_machine_grant(
        db,
        task=task,
        grant=body.machine_target_grant,
        granted_by_user_id=body.granted_by_user_id,
    )
    await db.commit()
    await db.refresh(task)
    return task


async def mark_project_coding_runs_reviewed(
    db: AsyncSession,
    project: Project,
    task_ids: list[uuid.UUID],
    *,
    note: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[uuid.UUID] = set()
    for task_id in task_ids:
        if task_id in seen:
            continue
        seen.add(task_id)
        task = await _load_project_coding_task(db, project, task_id)
        await _record_review_marked(
            db,
            project=project,
            run_task=task,
            actor={"kind": "operator"},
            summary=note.strip() or "Project coding run marked reviewed.",
            result={"outcome": "accepted", "reviewed_by": "operator", "note": note.strip()},
        )
        rows.append(await get_project_coding_run(db, project, task.id))
    return rows


async def _record_review_marked(
    db: AsyncSession,
    *,
    project: Project,
    run_task: Task,
    actor: dict[str, Any],
    summary: str,
    result: dict[str, Any],
) -> None:
    await create_execution_receipt(
        db,
        scope="project_coding_run",
        action_type="review.marked",
        status="succeeded",
        summary=summary,
        actor=actor,
        target={"project_id": str(project.id), "task_id": str(run_task.id)},
        result=result,
        bot_id=run_task.bot_id,
        channel_id=run_task.channel_id,
        session_id=run_task.session_id,
        task_id=run_task.id,
        correlation_id=run_task.correlation_id,
        idempotency_key=f"{run_task.id}:review.marked",
    )
    await _record_source_work_pack_reviewed(
        db,
        run_task=run_task,
        actor=actor,
        summary=summary,
        result=result,
    )


async def _record_source_work_pack_reviewed(
    db: AsyncSession,
    *,
    run_task: Task,
    actor: dict[str, Any],
    summary: str,
    result: dict[str, Any],
) -> None:
    run_cfg = _task_run_config(run_task)
    raw_pack_id = run_cfg.get("source_work_pack_id")
    if not raw_pack_id:
        return
    try:
        pack_id = uuid.UUID(str(raw_pack_id))
    except (TypeError, ValueError):
        return
    pack = await db.get(IssueWorkPack, pack_id)
    if pack is None:
        return
    now = _utcnow()
    metadata = dict(pack.metadata_ or {})
    review_actions = list(metadata.get("review_actions") or [])
    action = {
        "action": "reviewed",
        "actor": actor,
        "at": now.isoformat(),
        "note": summary,
        "prior_status": pack.status,
        "task_id": str(run_task.id),
        "review_task_id": result.get("review_task_id"),
        "review_session_id": result.get("review_session_id"),
        "launch_batch_id": run_cfg.get("launch_batch_id") or metadata.get("launch_batch_id"),
        "outcome": result.get("outcome"),
        "merge": result.get("merge"),
        "merge_method": result.get("merge_method"),
    }
    review_actions.append(action)
    metadata["review_actions"] = review_actions
    metadata["latest_review_action"] = action
    metadata["reviewed_at"] = now.isoformat()
    metadata["review_task_id"] = result.get("review_task_id")
    metadata["review_session_id"] = result.get("review_session_id")
    metadata["review_summary"] = summary
    pack.metadata_ = metadata
    pack.updated_at = now
    flag_modified(pack, "metadata_")
    await db.commit()


async def finalize_project_coding_run_review(
    db: AsyncSession,
    project: Project,
    body: ProjectCodingRunReviewFinalize,
    *,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    try:
        review_task = await _load_project_review_task(db, project, body.review_task_id)
        review_cfg = _review_session_config(review_task)
        selected = {str(value) for value in review_cfg.get("selected_task_ids") or []}
        if str(body.run_task_id) not in selected:
            return _review_error_payload(
                error="coding run was not selected for this review session",
                error_code="project_review_run_not_selected",
                run_task_id=body.run_task_id,
            )
        run_task = await _load_project_coding_task(db, project, body.run_task_id)
        outcome = _normal_review_outcome(body.outcome)
        method = _normal_merge_method(body.merge_method or review_cfg.get("merge_method"))
    except ValueError as exc:
        return _review_error_payload(
            error=str(exc),
            error_code="project_review_invalid_request",
            run_task_id=body.run_task_id,
        )
    details = dict(body.details or {})
    summary = body.summary.strip() or f"Project coding run review {outcome}."
    merge_payload: dict[str, Any] | None = None
    if outcome == "accepted" and body.merge:
        merge_payload = await merge_project_run_handoff(
            db,
            project_id=project.id,
            task_id=run_task.id,
            review_task_id=review_task.id,
            review_session_id=review_task.session_id,
            bot_id=review_task.bot_id,
            channel_id=run_task.channel_id,
            session_id=run_task.session_id,
            correlation_id=run_task.correlation_id,
            merge_method=method,
            command_runner=command_runner,
        )
        if not merge_payload.get("ok"):
            await _record_review_result(db, project=project, review_task=review_task, run_task=run_task, outcome="blocked", summary=summary, details=details, merge_payload=merge_payload, merge_method=method)
            return {
                "ok": False,
                "status": "blocked",
                "run_task_id": str(run_task.id),
                "error": str(merge_payload.get("error") or "Merge failed."),
                "error_code": str(merge_payload.get("error_code") or "project_review_merge_failed"),
                "error_kind": str(merge_payload.get("error_kind") or "execution"),
                "retryable": bool(merge_payload.get("retryable", False)),
                "merge": merge_payload,
            }

    if outcome == "accepted":
        result = {
            "outcome": outcome,
            "summary": summary,
            "details": details,
            "review_task_id": str(review_task.id),
            "review_session_id": str(review_task.session_id) if review_task.session_id else None,
            "reviewed_by": "agent",
            "merge": bool(body.merge),
            "merge_method": method if body.merge else None,
            "merge_result": merge_payload,
        }
        await _record_review_marked(
            db,
            project=project,
            run_task=run_task,
            actor={"kind": "bot", "bot_id": review_task.bot_id, "task_id": str(review_task.id)},
            summary=summary,
            result=result,
        )
        return {"ok": True, "status": "reviewed", "run": await get_project_coding_run(db, project, run_task.id)}

    await _record_review_result(db, project=project, review_task=review_task, run_task=run_task, outcome=outcome, summary=summary, details=details, merge_payload=None, merge_method=method)
    return {"ok": True, "status": outcome, "run": await get_project_coding_run(db, project, run_task.id)}


async def _record_review_result(
    db: AsyncSession,
    *,
    project: Project,
    review_task: Task,
    run_task: Task,
    outcome: str,
    summary: str,
    details: dict[str, Any],
    merge_payload: dict[str, Any] | None,
    merge_method: str,
) -> None:
    status = "blocked" if outcome == "blocked" else "needs_review"
    await create_execution_receipt(
        db,
        scope="project_coding_run",
        action_type="review.result",
        status=status,
        summary=summary,
        actor={"kind": "bot", "bot_id": review_task.bot_id, "task_id": str(review_task.id)},
        target={"project_id": str(project.id), "task_id": str(run_task.id)},
        result={
            "outcome": outcome,
            "summary": summary,
            "details": details,
            "review_task_id": str(review_task.id),
            "review_session_id": str(review_task.session_id) if review_task.session_id else None,
            "merge_method": merge_method,
            "merge_result": merge_payload,
        },
        rollback_hint=summary,
        bot_id=run_task.bot_id,
        channel_id=run_task.channel_id,
        session_id=run_task.session_id,
        task_id=run_task.id,
        correlation_id=run_task.correlation_id,
        idempotency_key=f"{run_task.id}:review.result:{review_task.id}",
    )


async def mark_project_coding_run_reviewed(db: AsyncSession, project: Project, task_id: uuid.UUID) -> dict[str, Any]:
    task = await _load_project_coding_task(db, project, task_id)
    await _record_review_marked(
        db,
        project=project,
        run_task=task,
        actor={"kind": "operator"},
        summary="Project coding run marked reviewed.",
        result={"outcome": "accepted", "reviewed_by": "operator"},
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
            from app.db.models import ProjectDependencyStackInstance
            from app.services.project_dependency_stacks import destroy_project_dependency_stack

            dependency_stack = (await db.execute(
                select(ProjectDependencyStackInstance).where(
                    ProjectDependencyStackInstance.task_id == task.id,
                    ProjectDependencyStackInstance.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            runtime_result: dict[str, Any] | None = None
            if dependency_stack is not None:
                runtime_result = await destroy_project_dependency_stack(db, dependency_stack, keep_volumes=False)
            cleaned = await cleanup_project_instance(db, instance)
            status = "succeeded"
            summary = "Project coding run fresh instance and dependency stack cleaned up."
            result = {
                "cleaned": True,
                "project_instance_id": str(cleaned.id),
                "status": cleaned.status,
                "dependency_stack": runtime_result,
            }
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
