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
    ColumnCreateRequest,
    ColumnRenameRequest,
    ColumnReorderRequest,
)
from integrations.mission_control.services import (
    create_card,
    create_column,
    delete_column,
    export_kanban_json,
    export_kanban_md,
    get_card_history,
    move_card,
    rename_column,
    reorder_columns,
    update_card,
)

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
    column_ids: dict[str, str | None] = {}  # col_name -> id (from first channel)
    for ch, columns_data in zip(channels, all_columns):
        for col in columns_data:
            col_name = col["name"]
            if col_name not in merged:
                merged[col_name] = []
                column_order.append(col_name)
                column_ids[col_name] = col.get("id")
            for card in col.get("cards", []):
                merged[col_name].append(KanbanCard(
                    title=card["title"],
                    meta=card.get("meta", {}),
                    description=card.get("description", ""),
                    channel_id=str(ch.id),
                    channel_name=ch.name,
                    plan_id=card.get("plan_id"),
                    plan_step_position=card.get("plan_step_position"),
                ))

    result_columns = [
        KanbanColumn(name=name, cards=merged[name], id=column_ids.get(name))
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


@router.get("/kanban/cards/{card_id}/history")
async def card_history(
    card_id: str,
    channel_id: str,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Get change history for a card (timeline events mentioning its ID)."""
    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    events = await get_card_history(str(channel.id), card_id, limit=limit)
    return {"events": events}


@router.post("/kanban/columns")
async def create_column_endpoint(
    body: ColumnCreateRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Create a new kanban column."""
    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(body.channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    result = await create_column(str(channel.id), body.name, position=body.position)
    return {"ok": True, **result}


@router.patch("/kanban/columns/{column_id}")
async def rename_column_endpoint(
    column_id: str,
    body: ColumnRenameRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Rename a kanban column."""
    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(body.channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    try:
        result = await rename_column(str(channel.id), column_id, body.name)
    except ValueError as e:
        raise HTTPException(409, str(e))

    return {"ok": True, **result}


@router.delete("/kanban/columns/{column_id}")
async def delete_column_endpoint(
    column_id: str,
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Delete a kanban column (must be empty)."""
    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    try:
        await delete_column(str(channel.id), column_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(404, msg)
        raise HTTPException(409, msg)

    return {"ok": True}


@router.post("/kanban/columns/reorder")
async def reorder_columns_endpoint(
    body: ColumnReorderRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Reorder kanban columns."""
    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(body.channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)
    if not channel.channel_workspace_enabled:
        raise HTTPException(400, "Channel workspace not enabled")

    try:
        await reorder_columns(str(channel.id), body.column_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"ok": True}


@router.get("/kanban/export")
async def export_kanban(
    channel_id: str,
    format: Literal["markdown", "json"] = "json",
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    """Export kanban board as markdown or JSON."""
    from fastapi.responses import PlainTextResponse

    user = get_user(auth)
    channel = await db.get(Channel, uuid.UUID(channel_id))
    if not channel:
        raise HTTPException(404, "Channel not found")
    require_channel_access(channel, user)

    if format == "markdown":
        content = await export_kanban_md(str(channel.id))
        return PlainTextResponse(
            content,
            headers={"Content-Disposition": f'attachment; filename="kanban-{channel.name}.md"'},
        )
    else:
        data = await export_kanban_json(str(channel.id))
        return {"columns": data}
