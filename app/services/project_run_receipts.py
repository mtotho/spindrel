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


def _clip_optional_text(value: Any, *, max_chars: int = 512) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:max_chars]


def _normalize_list(value: Any, *, max_items: int = 100) -> list[Any]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [item for item in items[:max_items]]


def _normalize_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _derive_idempotency_key(
    *,
    explicit: str | None = None,
    task_id: uuid.UUID | None = None,
    handoff_url: str | None = None,
    branch: str | None = None,
    base_branch: str | None = None,
    commit_sha: str | None = None,
    session_id: uuid.UUID | None = None,
) -> str | None:
    explicit_key = _clip_optional_text(explicit)
    if explicit_key:
        return explicit_key
    if task_id is not None:
        return f"task:{task_id}"
    if handoff_url:
        return _clip_optional_text(f"handoff:{handoff_url}")
    if branch and base_branch and commit_sha:
        return _clip_optional_text(f"git:{base_branch}:{branch}:{commit_sha}")
    if session_id is not None and branch:
        return _clip_optional_text(f"session-branch:{session_id}:{branch}")
    return None


def _apply_receipt_values(
    receipt: ProjectRunReceipt,
    *,
    project_instance_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    bot_id: str | None,
    status: str,
    summary: str,
    handoff_type: str | None,
    handoff_url: str | None,
    branch: str | None,
    base_branch: str | None,
    commit_sha: str | None,
    changed_files: Any,
    tests: Any,
    screenshots: Any,
    dev_targets: Any,
    metadata: Any,
) -> None:
    receipt.project_instance_id = project_instance_id
    receipt.task_id = task_id
    receipt.session_id = session_id
    receipt.bot_id = bot_id
    receipt.status = status
    receipt.summary = _clip_text(summary)
    receipt.handoff_type = handoff_type
    receipt.handoff_url = handoff_url
    receipt.branch = branch
    receipt.base_branch = base_branch
    receipt.commit_sha = commit_sha
    receipt.changed_files = _normalize_list(changed_files)
    receipt.tests = _normalize_list(tests)
    receipt.screenshots = _normalize_list(screenshots)
    normalized_metadata = _normalize_dict(metadata)
    if dev_targets is not None:
        normalized_metadata["dev_targets"] = _normalize_list(dev_targets, max_items=20)
    receipt.metadata_ = normalized_metadata


def serialize_project_run_receipt(receipt: ProjectRunReceipt) -> dict[str, Any]:
    metadata = dict(receipt.metadata_ or {})
    return {
        "id": str(receipt.id),
        "project_id": str(receipt.project_id),
        "project_instance_id": str(receipt.project_instance_id) if receipt.project_instance_id else None,
        "task_id": str(receipt.task_id) if receipt.task_id else None,
        "session_id": str(receipt.session_id) if receipt.session_id else None,
        "bot_id": receipt.bot_id,
        "idempotency_key": receipt.idempotency_key,
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
        "dev_targets": list(metadata.get("dev_targets") or []),
        "metadata": metadata,
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
    dev_targets: Any = None,
    metadata: Any = None,
    idempotency_key: str | None = None,
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

    normalized_handoff_url = _clip_optional_text(handoff_url)
    normalized_branch = _clip_optional_text(branch)
    normalized_base_branch = _clip_optional_text(base_branch)
    normalized_commit_sha = _clip_optional_text(commit_sha)
    normalized_idempotency_key = _derive_idempotency_key(
        explicit=idempotency_key,
        task_id=task_uuid,
        handoff_url=normalized_handoff_url,
        branch=normalized_branch,
        base_branch=normalized_base_branch,
        commit_sha=normalized_commit_sha,
        session_id=session_uuid,
    )

    receipt: ProjectRunReceipt | None = None
    if normalized_idempotency_key:
        receipt = (await db.execute(
            select(ProjectRunReceipt).where(
                ProjectRunReceipt.project_id == project_uuid,
                ProjectRunReceipt.idempotency_key == normalized_idempotency_key,
            )
        )).scalar_one_or_none()

    if receipt is None:
        receipt = ProjectRunReceipt(project_id=project_uuid, idempotency_key=normalized_idempotency_key)
        db.add(receipt)
        setattr(receipt, "_spindrel_created", True)
    else:
        setattr(receipt, "_spindrel_created", False)

    _apply_receipt_values(
        receipt,
        project_instance_id=instance_uuid,
        task_id=task_uuid,
        session_id=session_uuid,
        bot_id=(bot_id or None),
        status=normalized_status,
        summary=summary,
        handoff_type=_clip_optional_text(handoff_type),
        handoff_url=normalized_handoff_url,
        branch=normalized_branch,
        base_branch=normalized_base_branch,
        commit_sha=normalized_commit_sha,
        changed_files=changed_files,
        tests=tests,
        screenshots=screenshots,
        dev_targets=dev_targets,
        metadata=metadata,
    )
    db.add(receipt)
    await db.commit()
    await db.refresh(receipt)
    return receipt
