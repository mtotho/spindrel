"""Durable execution receipts for agent-important actions."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, ExecutionReceipt, Task


VALID_EXECUTION_RECEIPT_STATUSES = {"reported", "succeeded", "failed", "blocked", "needs_review"}


def _coerce_uuid(value: uuid.UUID | str | None, *, field: str) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid UUID") from exc


def _clip_text(value: Any, *, field: str, max_chars: int = 2_000, required: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if len(text) > max_chars:
        return text[: max_chars - 18].rstrip() + "\n\n[...truncated]"
    return text


def _normalize_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def serialize_execution_receipt(row: ExecutionReceipt) -> dict[str, Any]:
    return {
        "schema_version": "execution-receipt.v1",
        "id": str(row.id),
        "scope": row.scope,
        "action_type": row.action_type,
        "status": row.status,
        "summary": row.summary,
        "actor": dict(row.actor or {}),
        "target": dict(row.target or {}),
        "before_summary": row.before_summary,
        "after_summary": row.after_summary,
        "approval_required": bool(row.approval_required),
        "approval_ref": row.approval_ref,
        "result": dict(row.result or {}),
        "rollback_hint": row.rollback_hint,
        "bot_id": row.bot_id,
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "session_id": str(row.session_id) if row.session_id else None,
        "task_id": str(row.task_id) if row.task_id else None,
        "correlation_id": str(row.correlation_id) if row.correlation_id else None,
        "idempotency_key": row.idempotency_key,
        "metadata": dict(row.metadata_ or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def create_execution_receipt(
    db: AsyncSession,
    *,
    scope: str = "general",
    action_type: str,
    summary: str,
    status: str = "reported",
    actor: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    before_summary: str | None = None,
    after_summary: str | None = None,
    approval_required: bool = False,
    approval_ref: str | None = None,
    result: dict[str, Any] | None = None,
    rollback_hint: str | None = None,
    bot_id: str | None = None,
    channel_id: uuid.UUID | str | None = None,
    session_id: uuid.UUID | str | None = None,
    task_id: uuid.UUID | str | None = None,
    correlation_id: uuid.UUID | str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionReceipt:
    normalized_scope = _clip_text(scope, field="scope", max_chars=120, required=True) or "general"
    normalized_action = _clip_text(action_type, field="action_type", max_chars=160, required=True)
    normalized_status = (status or "reported").strip()
    if normalized_status not in VALID_EXECUTION_RECEIPT_STATUSES:
        raise ValueError(f"status must be one of {', '.join(sorted(VALID_EXECUTION_RECEIPT_STATUSES))}")

    channel_uuid = _coerce_uuid(channel_id, field="channel_id")
    if channel_uuid is not None and await db.get(Channel, channel_uuid) is None:
        raise ValueError("channel_id does not reference an existing channel")
    task_uuid = _coerce_uuid(task_id, field="task_id")
    if task_uuid is not None and await db.get(Task, task_uuid) is None:
        raise ValueError("task_id does not reference an existing task")

    session_uuid = _coerce_uuid(session_id, field="session_id")
    correlation_uuid = _coerce_uuid(correlation_id, field="correlation_id")
    normalized_idempotency = _clip_text(idempotency_key, field="idempotency_key", max_chars=512)

    receipt: ExecutionReceipt | None = None
    if normalized_idempotency:
        receipt = (await db.execute(
            select(ExecutionReceipt).where(
                ExecutionReceipt.scope == normalized_scope,
                ExecutionReceipt.idempotency_key == normalized_idempotency,
            )
        )).scalar_one_or_none()

    if receipt is None:
        receipt = ExecutionReceipt(scope=normalized_scope, idempotency_key=normalized_idempotency)
        db.add(receipt)
        setattr(receipt, "_spindrel_created", True)
    else:
        setattr(receipt, "_spindrel_created", False)

    receipt.action_type = normalized_action or "action"
    receipt.status = normalized_status
    receipt.summary = _clip_text(summary, field="summary", max_chars=2_000, required=True) or normalized_action or "action"
    receipt.actor = _normalize_dict(actor)
    receipt.target = _normalize_dict(target)
    receipt.before_summary = _clip_text(before_summary, field="before_summary", max_chars=2_000)
    receipt.after_summary = _clip_text(after_summary, field="after_summary", max_chars=2_000)
    receipt.approval_required = bool(approval_required)
    receipt.approval_ref = _clip_text(approval_ref, field="approval_ref", max_chars=512)
    receipt.result = _normalize_dict(result)
    receipt.rollback_hint = _clip_text(rollback_hint, field="rollback_hint", max_chars=2_000)
    receipt.bot_id = _clip_text(bot_id, field="bot_id", max_chars=200)
    receipt.channel_id = channel_uuid
    receipt.session_id = session_uuid
    receipt.task_id = task_uuid
    receipt.correlation_id = correlation_uuid
    receipt.metadata_ = _normalize_dict(metadata)

    db.add(receipt)
    await db.commit()
    await db.refresh(receipt)
    return receipt


async def list_execution_receipts(
    db: AsyncSession,
    *,
    scope: str | None = None,
    bot_id: str | None = None,
    channel_id: uuid.UUID | str | None = None,
    session_id: uuid.UUID | str | None = None,
    task_id: uuid.UUID | str | None = None,
    correlation_id: uuid.UUID | str | None = None,
    limit: int = 50,
) -> list[ExecutionReceipt]:
    bounded = max(1, min(int(limit or 50), 200))
    stmt = select(ExecutionReceipt).order_by(ExecutionReceipt.created_at.desc()).limit(bounded)
    if scope:
        stmt = stmt.where(ExecutionReceipt.scope == scope)
    if bot_id:
        stmt = stmt.where(ExecutionReceipt.bot_id == bot_id)
    channel_uuid = _coerce_uuid(channel_id, field="channel_id")
    if channel_uuid:
        stmt = stmt.where(ExecutionReceipt.channel_id == channel_uuid)
    session_uuid = _coerce_uuid(session_id, field="session_id")
    if session_uuid:
        stmt = stmt.where(ExecutionReceipt.session_id == session_uuid)
    task_uuid = _coerce_uuid(task_id, field="task_id")
    if task_uuid:
        stmt = stmt.where(ExecutionReceipt.task_id == task_uuid)
    correlation_uuid = _coerce_uuid(correlation_id, field="correlation_id")
    if correlation_uuid:
        stmt = stmt.where(ExecutionReceipt.correlation_id == correlation_uuid)
    return list((await db.execute(stmt)).scalars().all())
