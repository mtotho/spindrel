"""Review receipts produced by Project coding runs."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectInstance, ProjectRunReceipt, Task

VALID_PROJECT_RUN_RECEIPT_STATUSES = {"reported", "completed", "blocked", "failed", "needs_review"}


def _coerce_uuid(value: uuid.UUID | str | None, *, field: str) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid UUID") from exc


def _clip_text(value: Any, *, max_chars: int = 12_000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("summary is required")
    if len(text) > max_chars:
        return text[: max_chars - 18].rstrip() + "\n\n[...truncated]"
    return text


def _normalize_list(value: Any, *, max_items: int = 100) -> list[Any]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [item for item in items[:max_items]]


def _normalize_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def serialize_project_run_receipt(receipt: ProjectRunReceipt) -> dict[str, Any]:
    return {
        "id": str(receipt.id),
        "project_id": str(receipt.project_id),
        "project_instance_id": str(receipt.project_instance_id) if receipt.project_instance_id else None,
        "task_id": str(receipt.task_id) if receipt.task_id else None,
        "session_id": str(receipt.session_id) if receipt.session_id else None,
        "bot_id": receipt.bot_id,
        "status": receipt.status,
        "summary": receipt.summary,
        "handoff_type": receipt.handoff_type,
        "handoff_url": receipt.handoff_url,
        "branch": receipt.branch,
        "base_branch": receipt.base_branch,
        "commit_sha": receipt.commit_sha,
        "changed_files": list(receipt.changed_files or []),
        "tests": list(receipt.tests or []),
        "screenshots": list(receipt.screenshots or []),
        "metadata": dict(receipt.metadata_ or {}),
        "created_at": receipt.created_at.isoformat() if receipt.created_at else None,
    }


async def list_project_run_receipts(
    db: AsyncSession,
    project_id: uuid.UUID | str,
    *,
    limit: int = 25,
) -> list[ProjectRunReceipt]:
    project_uuid = _coerce_uuid(project_id, field="project_id")
    if project_uuid is None:
        raise ValueError("project_id is required")
    rows = (await db.execute(
        select(ProjectRunReceipt)
        .where(ProjectRunReceipt.project_id == project_uuid)
        .order_by(ProjectRunReceipt.created_at.desc())
        .limit(max(1, min(limit, 100)))
    )).scalars().all()
    return list(rows)


async def create_project_run_receipt(
    db: AsyncSession,
    *,
    project_id: uuid.UUID | str,
    summary: str,
    status: str = "reported",
    project_instance_id: uuid.UUID | str | None = None,
    task_id: uuid.UUID | str | None = None,
    session_id: uuid.UUID | str | None = None,
    bot_id: str | None = None,
    handoff_type: str | None = None,
    handoff_url: str | None = None,
    branch: str | None = None,
    base_branch: str | None = None,
    commit_sha: str | None = None,
    changed_files: Any = None,
    tests: Any = None,
    screenshots: Any = None,
    metadata: Any = None,
) -> ProjectRunReceipt:
    project_uuid = _coerce_uuid(project_id, field="project_id")
    if project_uuid is None:
        raise ValueError("project_id is required")
    if await db.get(Project, project_uuid) is None:
        raise ValueError("project not found")

    instance_uuid = _coerce_uuid(project_instance_id, field="project_instance_id")
    if instance_uuid is not None:
        instance = await db.get(ProjectInstance, instance_uuid)
        if instance is None or instance.project_id != project_uuid:
            raise ValueError("project_instance_id does not belong to this Project")

    task_uuid = _coerce_uuid(task_id, field="task_id")
    if task_uuid is not None:
        task = await db.get(Task, task_uuid)
        if task is None:
            raise ValueError("task_id does not reference an existing task")

    session_uuid = _coerce_uuid(session_id, field="session_id")
    normalized_status = (status or "reported").strip()
    if normalized_status not in VALID_PROJECT_RUN_RECEIPT_STATUSES:
        raise ValueError(f"status must be one of {', '.join(sorted(VALID_PROJECT_RUN_RECEIPT_STATUSES))}")

    receipt = ProjectRunReceipt(
        project_id=project_uuid,
        project_instance_id=instance_uuid,
        task_id=task_uuid,
        session_id=session_uuid,
        bot_id=(bot_id or None),
        status=normalized_status,
        summary=_clip_text(summary),
        handoff_type=(handoff_type or None),
        handoff_url=(handoff_url or None),
        branch=(branch or None),
        base_branch=(base_branch or None),
        commit_sha=(commit_sha or None),
        changed_files=_normalize_list(changed_files),
        tests=_normalize_list(tests),
        screenshots=_normalize_list(screenshots),
        metadata_=_normalize_dict(metadata),
    )
    db.add(receipt)
    await db.commit()
    await db.refresh(receipt)
    return receipt
