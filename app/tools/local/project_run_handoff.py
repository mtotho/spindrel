"""Project coding-run branch and PR handoff tool."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_correlation_id,
    current_session_id,
    current_task_id,
)
from app.tools.registry import register


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "status": {"type": "string"},
        "action": {"type": "string"},
        "branch": {"type": "string"},
        "base_branch": {"type": "string"},
        "repo_root": {"type": "string"},
        "dirty": {"type": "boolean"},
        "remote_url": {"type": "string"},
        "pr_url": {"type": "string"},
        "handoff": {"type": "object"},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "receipts": {"type": "array", "items": {"type": "object"}},
        "commands": {"type": "array", "items": {"type": "object"}},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}


_FINALIZE_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "status": {"type": "string"},
        "run_task_id": {"type": "string"},
        "merge": {"type": "object"},
        "run": {"type": "object"},
        "error": {"type": "string"},
        "error_code": {"type": "string"},
        "error_kind": {"type": "string"},
        "retryable": {"type": "boolean"},
        "details": {"type": "object"},
    },
    "required": ["ok"],
}


_REVIEW_CONTEXT_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "project": {"type": "object"},
        "review_task": {"type": "object"},
        "operator_prompt": {"type": "string"},
        "selected_task_ids": {"type": "array", "items": {"type": "string"}},
        "selected_runs": {"type": "array", "items": {"type": "object"}},
        "readiness": {"type": "object"},
        "finalization": {"type": "object"},
        "error": {"type": "string"},
        "error_code": {"type": "string"},
        "error_kind": {"type": "string"},
        "retryable": {"type": "boolean"},
    },
    "required": ["ok"],
}


_SCHEDULE_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "schedule": {"type": "object"},
        "error": {"type": "string"},
        "error_code": {"type": "string"},
    },
    "required": ["ok"],
}


def _tool_error(error: str, error_code: str, *, error_kind: str = "validation", retryable: bool = False, **extra: Any) -> str:
    payload = {
        "ok": False,
        "status": "blocked",
        "error": error,
        "error_code": error_code,
        "error_kind": error_kind,
        "retryable": retryable,
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    return json.dumps(payload, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "prepare_project_run_handoff",
        "description": (
            "Prepare the configured Project coding-run git branch, optionally push it and open a draft PR, "
            "and write durable Project run progress receipts. Use prepare_branch before editing and open_pr "
            "near handoff when credentials are available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "prepare_branch", "push", "open_pr"],
                    "description": "Which handoff phase to run. Defaults to prepare_branch.",
                },
                "project_id": {"type": "string", "description": "Optional Project UUID; inferred from task/channel when omitted."},
                "task_id": {"type": "string", "description": "Optional Task UUID; inferred from the current task run when omitted."},
                "branch": {"type": "string", "description": "Optional work branch override."},
                "base_branch": {"type": "string", "description": "Optional base branch override."},
                "repo_path": {"type": "string", "description": "Optional Project-relative repository path override."},
                "title": {"type": "string", "description": "Draft PR title for action=open_pr."},
                "body": {"type": "string", "description": "Draft PR body for action=open_pr."},
                "draft": {"type": "boolean", "description": "Create a draft PR when action=open_pr. Defaults true."},
                "remote": {"type": "string", "description": "Git remote name. Defaults origin."},
            },
        },
    },
}, safety_tier="exec_capable", requires_bot_context=True, requires_channel_context=True, returns=_RETURNS)
async def prepare_project_run_handoff(
    action: str = "prepare_branch",
    project_id: str | None = None,
    task_id: str | None = None,
    branch: str | None = None,
    base_branch: str | None = None,
    repo_path: str | None = None,
    title: str | None = None,
    body: str | None = None,
    draft: bool = True,
    remote: str = "origin",
) -> str:
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()
    if not bot_id:
        return _tool_error("No bot context available.", "missing_bot_context")
    if not channel_id:
        return _tool_error("No channel context available.", "missing_channel_context")

    try:
        from app.db.engine import async_session
        from app.services.project_run_handoff import prepare_project_run_handoff as prepare_handoff

        async with async_session() as db:
            payload: dict[str, Any] = await prepare_handoff(
                db,
                action=action,
                project_id=project_id,
                task_id=task_id or current_task_id.get(),
                channel_id=channel_id,
                bot_id=bot_id,
                session_id=current_session_id.get(),
                correlation_id=current_correlation_id.get(),
                branch=branch,
                base_branch=base_branch,
                repo_path=repo_path,
                title=title,
                body=body,
                draft=draft,
                remote=remote or "origin",
            )
    except Exception as exc:
        return _tool_error(str(exc), "project_run_handoff_failed", error_kind="execution")
    return json.dumps(payload, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "schedule_project_coding_run",
        "description": (
            "Create a recurring Project coding-run schedule for the current Project-bound channel. "
            "Use when the user asks for a nightly/weekly Project review, maintenance sweep, or recurring implementation run."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Human-readable schedule title."},
                "request": {"type": "string", "description": "Prompt for each concrete Project coding run."},
                "scheduled_at": {"type": "string", "description": "Optional ISO start time. Defaults to now."},
                "recurrence": {"type": "string", "description": "Relative recurrence like +1d or +1w. Defaults to +1w."},
            },
            "required": ["title", "request"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True, returns=_SCHEDULE_RETURNS)
async def schedule_project_coding_run(
    title: str,
    request: str,
    scheduled_at: str | None = None,
    recurrence: str = "+1w",
) -> str:
    channel_id = current_channel_id.get()
    if not channel_id:
        return _tool_error("No channel context available.", "missing_channel_context")
    try:
        from datetime import datetime

        from app.db.engine import async_session
        from app.db.models import Channel, Project
        from app.services.project_coding_runs import (
            ProjectCodingRunScheduleCreate,
            create_project_coding_run_schedule,
            list_project_coding_run_schedules,
        )

        start = datetime.fromisoformat(scheduled_at) if scheduled_at else None
        async with async_session() as db:
            channel = await db.get(Channel, channel_id)
            if channel is None or channel.project_id is None:
                return _tool_error("Current channel is not Project-bound.", "project_channel_required")
            project = await db.get(Project, channel.project_id)
            if project is None:
                return _tool_error("Project not found.", "project_not_found")
            schedule = await create_project_coding_run_schedule(
                db,
                project,
                ProjectCodingRunScheduleCreate(
                    channel_id=channel.id,
                    title=title,
                    request=request,
                    scheduled_at=start,
                    recurrence=recurrence or "+1w",
                ),
            )
            rows = await list_project_coding_run_schedules(db, project)
            row = next((item for item in rows if item["id"] == str(schedule.id)), None)
    except ValueError as exc:
        return _tool_error(str(exc), "project_schedule_invalid_request")
    except Exception as exc:
        return _tool_error(str(exc), "project_schedule_failed", error_kind="execution")
    return json.dumps({"ok": True, "schedule": row}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "get_project_coding_run_review_context",
        "description": (
            "Return the selected runs, evidence, handoff links, runtime/e2e/GitHub readiness, "
            "and finalization rules for the current Project coding-run review task. "
            "Call this before finalizing or merging selected Project coding runs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "review_task_id": {
                    "type": "string",
                    "description": "Optional Project coding-run review task UUID; inferred from the current task when omitted.",
                },
            },
        },
    },
}, safety_tier="readonly", requires_bot_context=True, requires_channel_context=True, returns=_REVIEW_CONTEXT_RETURNS)
async def get_project_coding_run_review_context(review_task_id: str | None = None) -> str:
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()
    resolved_review_task_id = review_task_id or current_task_id.get()
    if not bot_id:
        return _tool_error("No bot context available.", "missing_bot_context")
    if not channel_id:
        return _tool_error("No channel context available.", "missing_channel_context")
    if not resolved_review_task_id:
        return _tool_error("No review task context available.", "missing_review_task_context")

    try:
        from app.db.engine import async_session
        from app.db.models import Channel, Project
        from app.services.project_coding_runs import get_project_coding_run_review_context as review_context

        async with async_session() as db:
            channel = await db.get(Channel, channel_id)
            if channel is None or channel.project_id is None:
                return _tool_error("Current channel is not Project-bound.", "project_channel_required")
            project = await db.get(Project, channel.project_id)
            if project is None:
                return _tool_error("Project not found.", "project_not_found")
            payload: dict[str, Any] = await review_context(
                db,
                project,
                uuid.UUID(str(resolved_review_task_id)),
            )
    except ValueError as exc:
        return _tool_error(str(exc), "project_review_invalid_request")
    except Exception as exc:
        return _tool_error(str(exc), "project_review_context_failed", error_kind="execution")
    return json.dumps(payload, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "finalize_project_coding_run_review",
        "description": (
            "Finalize one selected Project coding run from a Project coding-run review session. "
            "Accepted outcomes mark the run reviewed; rejected or blocked outcomes record review details "
            "without marking it reviewed. Use merge=true only when the operator asked this review session to merge accepted PRs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "run_task_id": {"type": "string", "description": "The selected Project coding-run task UUID being finalized."},
                "outcome": {"type": "string", "enum": ["accepted", "rejected", "blocked"], "description": "Review decision for this run."},
                "summary": {"type": "string", "description": "Concise reviewer summary."},
                "details": {"type": "object", "description": "Evidence, issues, links, and decision details."},
                "merge": {"type": "boolean", "description": "Merge the accepted run's PR now. Only set true when explicitly requested."},
                "merge_method": {"type": "string", "enum": ["squash", "merge", "rebase"], "description": "GitHub merge method. Defaults to squash."},
            },
            "required": ["run_task_id", "outcome", "summary"],
        },
    },
}, safety_tier="exec_capable", requires_bot_context=True, requires_channel_context=True, returns=_FINALIZE_RETURNS)
async def finalize_project_coding_run_review(
    run_task_id: str,
    outcome: str = "accepted",
    summary: str = "",
    details: dict[str, Any] | None = None,
    merge: bool = False,
    merge_method: str = "squash",
) -> str:
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()
    review_task_id = current_task_id.get()
    if not bot_id:
        return _tool_error("No bot context available.", "missing_bot_context")
    if not channel_id:
        return _tool_error("No channel context available.", "missing_channel_context")
    if not review_task_id:
        return _tool_error("No review task context available.", "missing_review_task_context")

    try:
        from app.db.engine import async_session
        from app.db.models import Channel, Project
        from app.services.project_coding_runs import (
            ProjectCodingRunReviewFinalize,
            finalize_project_coding_run_review as finalize_review,
        )

        async with async_session() as db:
            channel = await db.get(Channel, channel_id)
            if channel is None or channel.project_id is None:
                return _tool_error("Current channel is not Project-bound.", "project_channel_required")
            project = await db.get(Project, channel.project_id)
            if project is None:
                return _tool_error("Project not found.", "project_not_found")
            payload: dict[str, Any] = await finalize_review(
                db,
                project,
                ProjectCodingRunReviewFinalize(
                    review_task_id=review_task_id,
                    run_task_id=uuid.UUID(str(run_task_id)),
                    outcome=outcome,
                    summary=summary,
                    details=details or {},
                    merge=merge,
                    merge_method=merge_method,
                ),
            )
    except Exception as exc:
        return _tool_error(str(exc), "project_review_finalize_failed", error_kind="execution")
    return json.dumps(payload, ensure_ascii=False)
