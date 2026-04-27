"""Notification target admin API."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationDelivery, NotificationTarget
from app.dependencies import get_db, require_scopes
from app.services.notifications import (
    NotificationPayload,
    TARGET_KINDS,
    available_destinations,
    normalize_slug,
    send_notification,
    serialize_delivery,
    serialize_target,
)

router = APIRouter(prefix="/notification-targets", tags=["Notification Targets"])


class TargetCreate(BaseModel):
    label: str
    kind: str
    slug: str | None = None
    config: dict[str, Any] = {}
    enabled: bool = True
    allowed_bot_ids: list[str] = []


class TargetUpdate(BaseModel):
    label: str | None = None
    slug: str | None = None
    kind: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    allowed_bot_ids: list[str] | None = None


class TestSendBody(BaseModel):
    title: str = "Test notification"
    body: str = "This is a test notification from Spindrel."
    url: str | None = None
    severity: str = "info"
    tag: str | None = "notification-test"


def _validate_kind(kind: str) -> None:
    if kind not in TARGET_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(TARGET_KINDS)}")


@router.get("/available-destinations")
async def list_available_destinations(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("notifications:read")),
):
    return await available_destinations(db)


@router.get("/deliveries")
async def list_notification_deliveries(
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("notifications:read")),
):
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    total = (await db.execute(select(func.count()).select_from(NotificationDelivery))).scalar() or 0
    rows = (await db.execute(
        select(NotificationDelivery)
        .order_by(NotificationDelivery.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "deliveries": [serialize_delivery(row) for row in rows],
    }


@router.get("")
async def list_notification_targets(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("notifications:read")),
):
    rows = (await db.execute(
        select(NotificationTarget).order_by(NotificationTarget.label)
    )).scalars().all()
    return {"targets": [serialize_target(row) for row in rows]}


@router.post("")
async def create_notification_target(
    body: TargetCreate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("notifications:write")),
):
    _validate_kind(body.kind)
    slug = normalize_slug(body.slug or body.label)
    if (await db.execute(select(NotificationTarget.id).where(NotificationTarget.slug == slug))).scalar_one_or_none():
        raise HTTPException(409, "slug already exists")
    row = NotificationTarget(
        id=uuid.uuid4(),
        slug=slug,
        label=body.label.strip() or slug,
        kind=body.kind,
        config=body.config or {},
        enabled=body.enabled,
        allowed_bot_ids=body.allowed_bot_ids or [],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return serialize_target(row)


@router.put("/{target_id}")
async def update_notification_target(
    target_id: uuid.UUID,
    body: TargetUpdate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("notifications:write")),
):
    row = await db.get(NotificationTarget, target_id)
    if not row:
        raise HTTPException(404, "notification target not found")
    if body.kind is not None:
        _validate_kind(body.kind)
        row.kind = body.kind
    if body.slug is not None:
        slug = normalize_slug(body.slug)
        existing = (await db.execute(
            select(NotificationTarget.id).where(NotificationTarget.slug == slug, NotificationTarget.id != target_id)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(409, "slug already exists")
        row.slug = slug
    if body.label is not None:
        row.label = body.label.strip() or row.label
    if body.config is not None:
        row.config = body.config
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.allowed_bot_ids is not None:
        row.allowed_bot_ids = body.allowed_bot_ids
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return serialize_target(row)


@router.delete("/{target_id}")
async def delete_notification_target(
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("notifications:write")),
):
    await db.execute(delete(NotificationTarget).where(NotificationTarget.id == target_id))
    await db.commit()
    return {"ok": True}


@router.post("/{target_id}/test")
async def test_notification_target(
    target_id: uuid.UUID,
    body: TestSendBody,
    _auth=Depends(require_scopes("notifications:send")),
):
    try:
        return await send_notification(
            target_id,
            NotificationPayload(
                title=body.title,
                body=body.body,
                url=body.url,
                severity=body.severity,
                tag=body.tag,
            ),
            sender_type="admin_test",
            actor_label="Notification Test",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

