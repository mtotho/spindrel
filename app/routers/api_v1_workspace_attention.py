"""Workspace Attention API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.domain.errors import NotFoundError, ValidationError
from app.services.workspace_attention import (
    acknowledge_attention_item,
    actor_label,
    get_attention_item,
    list_attention_items,
    mark_attention_responded,
    resolve_attention_item,
    serialize_attention_item,
    serialize_attention_items,
)


router = APIRouter(prefix="/workspace/attention", tags=["workspace-attention"])


class AttentionStatusRequest(BaseModel):
    message_id: uuid.UUID | None = None


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
