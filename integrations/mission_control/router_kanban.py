"""Mission Control — Kanban CRUD endpoints."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel
from app.dependencies import get_db, verify_auth_or_user
from integrations.mission_control.helpers import (
    get_bot,
    get_mc_prefs,
    get_user,
    read_tasks_for_channel,
    require_channel_access,
    tracked_channels,
)
from integrations.mission_control.schemas import (
    KanbanCard,
    KanbanColumn,
    KanbanCreateRequest,
    KanbanMoveRequest,
    KanbanUpdateRequest,
)
from integrations.mission_control.services import create_card, move_card, update_card

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/kanban")
async def kanban(
    scope: Literal["fleet", "personal"] = "fleet",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Aggregated kanban: reads tasks.md from all tracked channels, merges columns."""
    user = get_user(auth)
    prefs = await get_mc_prefs(db, user)
    channels = await tracked_channels(db, user, prefs, scope=scope)

    merged: dict[str, list[KanbanCard]] = {}
    column_order: list[str] = []

    all_columns = await asyncio.gather(
        *(read_tasks_for_channel(ch) for ch in channels)
    )
    for ch, columns_data in zip(channels, all_columns):
        for col in columns_data:
            col_name = col["name"]
            if col_name not in merged:
                merged[col_name] = []
                column_order.append(col_name)
            for card in col.get("cards", []):
                merged[col_name].append(KanbanCard(
                    title=card["title"],
                    meta=card.get("meta", {}),
                    description=card.get("description", ""),
                    channel_id=str(ch.id),
                    channel_name=ch.name,
                ))

    result_columns = [
        KanbanColumn(name=name, cards=merged[name])
        for name in column_order
    ]

    return {"columns": [c.model_dump() for c in result_columns]}


@router.post("/kanban/move")
async def kanban_move(
    body: KanbanMoveRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Move a card between columns."""
    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(body.channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    try:
        result = await move_card(
            str(channel.id), body.card_id, body.to_column, from_column=body.from_column,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(404, msg)
        raise HTTPException(409, msg)

    return {"ok": True, "card": result["card"]}


@router.post("/kanban/create")
async def kanban_create(
    body: KanbanCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Create a new card in a specific channel's tasks.md."""
    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(body.channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    result = await create_card(
        str(channel.id),
        body.title,
        column=body.column,
        priority=body.priority,
        assigned=body.assigned,
        tags=body.tags,
        due=body.due,
        description=body.description,
    )

    return {"ok": True, "card": result["card"], "column": result["column"]}


@router.patch("/kanban/update")
async def kanban_update(
    body: KanbanUpdateRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Update card fields (title, description, priority, assigned, due, tags)."""
    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(body.channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    try:
        result = await update_card(
            str(channel.id),
            body.card_id,
            title=body.title,
            description=body.description,
            priority=body.priority,
            assigned=body.assigned,
            due=body.due,
            tags=body.tags,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {"ok": True, "card": result["card"], "changes": result["changes"]}
