"""Workspace Attention API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.domain.errors import NotFoundError, ValidationError
from app.services.workspace_attention import (
    acknowledge_attention_item,
    acknowledge_attention_items_bulk,
    assign_attention_item,
    actor_label,
    create_attention_triage_run,
    create_user_attention_item,
    get_attention_brief,
    get_attention_triage_run,
    get_attention_item,
    list_attention_triage_runs,
    list_attention_items,
    mark_attention_responded,
    record_attention_triage_feedback,
    resolve_attention_item,
    serialize_attention_item,
    serialize_attention_items,
    unassign_attention_item,
)


router = APIRouter(prefix="/workspace/attention", tags=["workspace-attention"])


class AttentionStatusRequest(BaseModel):
    message_id: uuid.UUID | None = None


class AttentionCreateRequest(BaseModel):
    channel_id: uuid.UUID | None = None
    target_kind: str = "channel"
    target_id: str | None = None
    title: str
    message: str = ""
    severity: str = "warning"
    requires_response: bool = True
    next_steps: list[str] = Field(default_factory=list)


class AttentionAssignRequest(BaseModel):
    bot_id: str
    mode: str = "next_heartbeat"
    instructions: str | None = None


class AttentionBulkAcknowledgeRequest(BaseModel):
    scope: str = "workspace_visible"
    target_kind: str | None = None
    target_id: str | None = None
    channel_id: uuid.UUID | None = None


class AttentionTriageRunRequest(BaseModel):
    scope: str = "all_active"
    model_override: str | None = None
    model_provider_id_override: str | None = None


class AttentionTriageFeedbackRequest(BaseModel):
    verdict: str
    note: str | None = None
    route: str | None = None


class AttentionTriageRunsResponse(BaseModel):
    runs: list[dict]


@router.post("")
async def create_attention_item_route(
    body: AttentionCreateRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        target_id = body.target_id or (str(body.channel_id) if body.channel_id and body.target_kind == "channel" else None)
        if not target_id:
            raise ValidationError("target_id is required unless target_kind is channel and channel_id is set.")
        item = await create_user_attention_item(
            db,
            actor=actor_label(auth) or "user",
            channel_id=body.channel_id,
            target_kind=body.target_kind,
            target_id=target_id,
            title=body.title,
            message=body.message,
            severity=body.severity,
            requires_response=body.requires_response,
            next_steps=body.next_steps,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/acknowledge-bulk")
async def acknowledge_attention_bulk(
    body: AttentionBulkAcknowledgeRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        items = await acknowledge_attention_items_bulk(
            db,
            auth=auth,
            scope=body.scope,
            target_kind=body.target_kind,
            target_id=body.target_id,
            channel_id=body.channel_id,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    serialized = await serialize_attention_items(db, items)
    return {
        "count": len(items),
        "item_ids": [item["id"] for item in serialized],
        "items": serialized,
    }


@router.post("/triage-runs")
async def create_attention_triage_run_route(
    body: AttentionTriageRunRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    if body.scope != "all_active":
        raise HTTPException(400, "scope must be all_active.")
    try:
        return await create_attention_triage_run(
            db,
            auth=auth,
            actor=actor_label(auth),
            model_override=body.model_override,
            model_provider_id_override=body.model_provider_id_override,
        )
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/triage-runs", response_model=AttentionTriageRunsResponse)
async def list_attention_triage_runs_route(
    limit: int = 20,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return {"runs": await list_attention_triage_runs(db, auth=auth, limit=limit)}


@router.get("/triage-runs/{task_id}")
async def get_attention_triage_run_route(
    task_id: uuid.UUID,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_attention_triage_run(db, auth=auth, task_id=task_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e


@router.get("")
async def get_attention_items(
    status: str | None = None,
    channel_id: uuid.UUID | None = None,
    include_resolved: bool = False,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    items = await list_attention_items(
        db,
        auth=auth,
        status=status,
        channel_id=channel_id,
        include_resolved=include_resolved,
    )
    return {"items": await serialize_attention_items(db, items)}


@router.get("/brief")
async def get_attention_brief_route(
    channel_id: uuid.UUID | None = None,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    return await get_attention_brief(db, auth=auth, channel_id=channel_id)


@router.get("/{item_id}")
async def get_attention_item_route(
    item_id: uuid.UUID,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await get_attention_item(db, item_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    if item.source_type == "system" and "admin" not in getattr(auth, "scopes", []) and not getattr(auth, "is_admin", False):
        raise HTTPException(404, "Attention item not found.")
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/acknowledge")
async def acknowledge_attention(
    item_id: uuid.UUID,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await acknowledge_attention_item(db, item_id)
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/triage-feedback")
async def attention_triage_feedback(
    item_id: uuid.UUID,
    body: AttentionTriageFeedbackRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await record_attention_triage_feedback(
            db,
            item_id,
            verdict=body.verdict,
            actor=actor_label(auth),
            note=body.note,
            route=body.route,
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/responded")
async def responded_attention(
    item_id: uuid.UUID,
    body: AttentionStatusRequest | None = None,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await mark_attention_responded(
            db,
            item_id,
            response_message_id=body.message_id if body else None,
            responded_by=actor_label(auth),
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/resolve")
async def resolve_attention(
    item_id: uuid.UUID,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await resolve_attention_item(db, item_id, resolved_by=actor_label(auth))
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/assign")
async def assign_attention(
    item_id: uuid.UUID,
    body: AttentionAssignRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await assign_attention_item(
            db,
            item_id,
            bot_id=body.bot_id,
            mode=body.mode,
            instructions=body.instructions,
            assigned_by=actor_label(auth),
        )
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValidationError as e:
        raise HTTPException(400, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}


@router.post("/{item_id}/unassign")
async def unassign_attention(
    item_id: uuid.UUID,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await unassign_attention_item(db, item_id, actor=actor_label(auth))
    except NotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"item": await serialize_attention_item(db, item)}
