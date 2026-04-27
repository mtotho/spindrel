"""Read receipt and unread notification endpoints."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, NotificationTarget, Session, SessionReadState, UnreadNotificationRule
from app.dependencies import get_db, verify_user
from app.services import unread, user_events

router = APIRouter(prefix="/unread", tags=["Unread"])


class MarkReadBody(BaseModel):
    session_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    source: str = "web"
    surface: str | None = None


class VisibleBody(BaseModel):
    session_id: uuid.UUID
    surface: str | None = None
    mark_read: bool = True


class RuleBody(BaseModel):
    channel_id: uuid.UUID | None = None
    enabled: bool = True
    target_mode: str = "inherit"
    target_ids: list[uuid.UUID] = []
    immediate_enabled: bool = True
    reminder_enabled: bool = True
    reminder_delay_minutes: int = 5
    preview_policy: str = "short"


def _serialize_rule(row: UnreadNotificationRule) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "enabled": row.enabled,
        "target_mode": row.target_mode,
        "target_ids": [str(item) for item in (row.target_ids or [])],
        "immediate_enabled": row.immediate_enabled,
        "reminder_enabled": row.reminder_enabled,
        "reminder_delay_minutes": row.reminder_delay_minutes,
        "preview_policy": row.preview_policy,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _validate_rule(body: RuleBody) -> None:
    if body.target_mode not in {"inherit", "replace"}:
        raise HTTPException(400, "target_mode must be inherit or replace")
    if body.preview_policy not in {"none", "short", "full"}:
        raise HTTPException(400, "preview_policy must be none, short, or full")
    if body.reminder_delay_minutes < 1:
        raise HTTPException(400, "reminder_delay_minutes must be at least 1")


@router.get("/state")
async def get_unread_state(
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    rows = (await db.execute(
        select(SessionReadState)
        .where(SessionReadState.user_id == user.id)
        .order_by(SessionReadState.latest_unread_at.desc().nullslast(), SessionReadState.updated_at.desc())
    )).scalars().all()
    channel_rows = (await db.execute(
        select(
            SessionReadState.channel_id,
            func.coalesce(func.sum(SessionReadState.unread_agent_reply_count), 0),
            func.max(SessionReadState.latest_unread_at),
        )
        .where(SessionReadState.user_id == user.id)
        .group_by(SessionReadState.channel_id)
    )).all()
    return {
        "states": [unread.serialize_read_state(row) for row in rows],
        "channels": [
            {
                "channel_id": str(channel_id) if channel_id else None,
                "unread_agent_reply_count": int(count or 0),
                "latest_unread_at": latest.isoformat() if latest else None,
            }
            for channel_id, count, latest in channel_rows
        ],
    }


@router.post("/visible")
async def set_session_visible(
    body: VisibleBody,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    session = await db.get(Session, body.session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    if body.mark_read:
        state = await unread.mark_session_visible_and_read(
            db,
            user_id=user.id,
            session_id=body.session_id,
            source="web_visible",
            surface=body.surface,
        )
        await db.commit()
        return {"state": unread.serialize_read_state(state)}
    unread.mark_session_visible(user.id, body.session_id)
    return {"ok": True}


@router.post("/read")
async def mark_read(
    body: MarkReadBody,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    if body.session_id:
        state = await unread.mark_session_read(
            db,
            user_id=user.id,
            session_id=body.session_id,
            message_id=body.message_id,
            source=body.source,
            surface=body.surface,
        )
        await db.commit()
        return {"states": [unread.serialize_read_state(state)]}
    if body.channel_id:
        channel = await db.get(Channel, body.channel_id)
        if channel is None:
            raise HTTPException(404, "channel not found")
        states = await unread.mark_channel_read(
            db,
            user_id=user.id,
            channel_id=body.channel_id,
            source=body.source or "web_channel_read",
        )
        await db.commit()
        return {"states": [unread.serialize_read_state(row) for row in states]}
    count = await unread.mark_all_read(db, user_id=user.id, source=body.source or "web_all_read")
    await db.commit()
    return {"updated": count}


@router.get("/rules")
async def list_rules(
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    rows = (await db.execute(
        select(UnreadNotificationRule)
        .where(UnreadNotificationRule.user_id == user.id)
        .order_by(UnreadNotificationRule.channel_id.nullsfirst())
    )).scalars().all()
    targets = (await db.execute(
        select(NotificationTarget)
        .where(NotificationTarget.enabled.is_(True))
        .order_by(NotificationTarget.label)
    )).scalars().all()
    return {
        "rules": [_serialize_rule(row) for row in rows],
        "targets": [
            {
                "id": str(target.id),
                "label": target.label,
                "kind": target.kind,
                "config": target.config or {},
            }
            for target in targets
        ],
    }


@router.put("/rules")
async def upsert_rule(
    body: RuleBody,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    _validate_rule(body)
    if body.channel_id and await db.get(Channel, body.channel_id) is None:
        raise HTTPException(404, "channel not found")
    for target_id in body.target_ids:
        if await db.get(NotificationTarget, target_id) is None:
            raise HTTPException(404, f"notification target not found: {target_id}")
    channel_condition = (
        UnreadNotificationRule.channel_id == body.channel_id
        if body.channel_id
        else UnreadNotificationRule.channel_id.is_(None)
    )
    row = (await db.execute(
        select(UnreadNotificationRule).where(
            UnreadNotificationRule.user_id == user.id,
            channel_condition,
        )
    )).scalar_one_or_none()
    if row is None:
        row = UnreadNotificationRule(
            id=uuid.uuid4(),
            user_id=user.id,
            channel_id=body.channel_id,
        )
        db.add(row)
    row.enabled = body.enabled
    row.target_mode = body.target_mode
    row.target_ids = [str(item) for item in body.target_ids]
    row.immediate_enabled = body.immediate_enabled
    row.reminder_enabled = body.reminder_enabled
    row.reminder_delay_minutes = body.reminder_delay_minutes
    row.preview_policy = body.preview_policy
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _serialize_rule(row)


@router.get("/events")
async def unread_events(
    since: int | None = Query(None),
    user=Depends(verify_user),
):
    async def _event_stream():
        shutdown = user_events.get_shutdown_event()
        async_gen = user_events.subscribe(user.id, since=since)
        pending = asyncio.ensure_future(async_gen.__anext__())
        try:
            while not shutdown.is_set():
                try:
                    event = await asyncio.wait_for(asyncio.shield(pending), timeout=15.0)
                    if event.kind == "shutdown":
                        break
                    yield f"data: {json.dumps(user_events.event_to_sse_dict(event))}\n\n"
                    pending = asyncio.ensure_future(async_gen.__anext__())
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                except StopAsyncIteration:
                    break
        finally:
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            except Exception:
                pass
            try:
                await async_gen.aclose()
            except (RuntimeError, StopAsyncIteration):
                pass

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
