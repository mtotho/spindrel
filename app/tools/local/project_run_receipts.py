"""Project coding-run receipt tools."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_project_instance_id,
    current_session_id,
    current_task_id,
)
from app.tools.registry import register


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "receipt_id": {"type": "string"},
        "receipt": {"type": "object"},
        "created": {"type": "boolean"},
        "updated": {"type": "boolean"},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}


async def _infer_project_id(db, explicit_project_id: str | None, explicit_instance_id: str | None) -> uuid.UUID:
    from app.db.models import Channel, ProjectInstance

    if explicit_project_id:
        return uuid.UUID(str(explicit_project_id))

    instance_id = explicit_instance_id or current_project_instance_id.get()
    if instance_id:
        instance = await db.get(ProjectInstance, uuid.UUID(str(instance_id)))
        if instance is not None:
            return instance.project_id

    channel_id = current_channel_id.get()
    if channel_id is not None:
        channel = await db.get(Channel, uuid.UUID(str(channel_id)))
        if channel is not None and channel.project_id is not None:
            return channel.project_id

    raise ValueError("project_id is required when the current run is not attached to a Project")


def _handoff_value(handoff: dict[str, Any] | None, *keys: str) -> str | None:
    if not isinstance(handoff, dict):
        return None
    for key in keys:
        value = handoff.get(key)
        if value:
            return str(value)
    return None


@register({
    "type": "function",
    "function": {
        "name": "publish_project_run_receipt",
        "description": (
            "Publish a Project coding-run receipt with the summary, changed files, tests, screenshots, "
            "and handoff link for human review. Use this at the end of Project implementation tasks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Concise implementation summary and review notes."},
                "status": {
                    "type": "string",
                    "enum": ["reported", "completed", "blocked", "failed", "needs_review"],
                    "description": "Run outcome status.",
                },
                "project_id": {"type": "string", "description": "Optional Project UUID; inferred from the current run when possible."},
                "project_instance_id": {"type": "string", "description": "Optional fresh Project instance UUID."},
                "task_id": {"type": "string", "description": "Optional Task UUID; inferred for task runs when omitted."},
                "changed_files": {"type": "array", "items": {}, "description": "Repository-relative changed paths or structured file records."},
                "tests": {"type": "array", "items": {}, "description": "Commands or structured test results."},
                "screenshots": {"type": "array", "items": {}, "description": "Screenshot paths or structured screenshot records."},
                "dev_targets": {"type": "array", "items": {}, "description": "Assigned dev target URLs/ports and current status."},
                "handoff": {
                    "type": "object",
                    "description": "Optional review handoff such as pull request URL, branch, base branch, or commit SHA.",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "Optional stable key for retries. When omitted, the tool derives one from task, handoff, or git metadata.",
                },
                "metadata": {"type": "object", "description": "Optional extra machine-readable run metadata."},
            },
            "required": ["summary"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, returns=_RETURNS)
async def publish_project_run_receipt(
    summary: str,
    status: str = "completed",
    project_id: str | None = None,
    project_instance_id: str | None = None,
    task_id: str | None = None,
    changed_files: list[Any] | None = None,
    tests: list[Any] | None = None,
    screenshots: list[Any] | None = None,
    dev_targets: list[Any] | None = None,
    handoff: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    from app.db.engine import async_session
    from app.services.project_run_receipts import create_project_run_receipt, serialize_project_run_receipt

    try:
        async with async_session() as db:
            resolved_project_id = await _infer_project_id(db, project_id, project_instance_id)
            receipt = await create_project_run_receipt(
                db,
                project_id=resolved_project_id,
                project_instance_id=project_instance_id or current_project_instance_id.get(),
                task_id=task_id or current_task_id.get(),
                session_id=current_session_id.get(),
                bot_id=current_bot_id.get(),
                status=status or "completed",
                summary=summary,
                handoff_type=_handoff_value(handoff, "type", "kind", "mode"),
                handoff_url=_handoff_value(handoff, "url", "pr_url", "merge_request_url"),
                branch=_handoff_value(handoff, "branch", "head"),
                base_branch=_handoff_value(handoff, "base_branch", "base"),
                commit_sha=_handoff_value(handoff, "commit_sha", "sha"),
                changed_files=changed_files or [],
                tests=tests or [],
                screenshots=screenshots or [],
                dev_targets=dev_targets or None,
                metadata=metadata or {},
                idempotency_key=idempotency_key,
            )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    payload = serialize_project_run_receipt(receipt)
    created = bool(getattr(receipt, "_spindrel_created", True))
    return json.dumps({
        "ok": True,
        "receipt_id": payload["id"],
        "receipt": payload,
        "created": created,
        "updated": not created,
    }, ensure_ascii=False)
