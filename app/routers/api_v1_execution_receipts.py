"""Execution receipt API."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.execution_receipts import (
    create_execution_receipt,
    list_execution_receipts,
    serialize_execution_receipt,
)

router = APIRouter(prefix="/execution-receipts", tags=["execution-receipts"])


class ExecutionReceiptWrite(BaseModel):
    scope: str = "general"
    action_type: str
    status: str = "reported"
    summary: str
    actor: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)
    before_summary: str | None = None
    after_summary: str | None = None
    approval_required: bool = False
    approval_ref: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    rollback_hint: str | None = None
    bot_id: str | None = None
    channel_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionReceiptOut(BaseModel):
    schema_version: str
    id: str
    scope: str
    action_type: str
    status: str
    summary: str
    actor: dict[str, Any]
    target: dict[str, Any]
    before_summary: str | None = None
    after_summary: str | None = None
    approval_required: bool
    approval_ref: str | None = None
    result: dict[str, Any]
    rollback_hint: str | None = None
    bot_id: str | None = None
    channel_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any]
    created_at: str | None = None


@router.get("", response_model=list[ExecutionReceiptOut])
async def get_execution_receipts(
    scope: str | None = Query(None),
    bot_id: str | None = Query(None),
    channel_id: uuid.UUID | None = Query(None),
    session_id: uuid.UUID | None = Query(None),
    task_id: uuid.UUID | None = Query(None),
    correlation_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _auth=Depends(require_scopes("logs:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = await list_execution_receipts(
        db,
        scope=scope,
        bot_id=bot_id,
        channel_id=channel_id,
        session_id=session_id,
        task_id=task_id,
        correlation_id=correlation_id,
        limit=limit,
    )
    return [serialize_execution_receipt(row) for row in rows]


@router.post("", response_model=ExecutionReceiptOut, status_code=201)
async def post_execution_receipt(
    body: ExecutionReceiptWrite,
    _auth=Depends(require_scopes("logs:write")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        receipt = await create_execution_receipt(
            db,
            scope=body.scope,
            action_type=body.action_type,
            status=body.status,
            summary=body.summary,
            actor=body.actor,
            target=body.target,
            before_summary=body.before_summary,
            after_summary=body.after_summary,
            approval_required=body.approval_required,
            approval_ref=body.approval_ref,
            result=body.result,
            rollback_hint=body.rollback_hint,
            bot_id=body.bot_id,
            channel_id=body.channel_id,
            session_id=body.session_id,
            task_id=body.task_id,
            correlation_id=body.correlation_id,
            idempotency_key=body.idempotency_key,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_execution_receipt(receipt)
