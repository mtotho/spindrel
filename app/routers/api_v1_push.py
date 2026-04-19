"""API endpoints for /api/v1/push.

Public surface:

  GET  /api/v1/push/vapid-public-key   authenticated user  → {publicKey}
  POST /api/v1/push/subscribe          authenticated user  → {id}
  POST /api/v1/push/unsubscribe        authenticated user  → {deleted}
  POST /api/v1/push/send               push:send scope     → {sent,pruned,failed,skippedActive}
  POST /api/v1/presence/heartbeat      authenticated user  → {ok:true}

The subscribe endpoint upserts on `endpoint` — re-subscribing from the
same browser replaces the old keys instead of inserting a duplicate. The
send endpoint is the external-API hook; the same delivery path is also
wrapped by the `send_push_notification` bot tool, which routes through
`app.services.push.send_push` directly.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import PushSubscription, User
from app.dependencies import get_db, require_scopes, verify_user
from app.services import presence
from app.services.push import PushDisabledError, send_push

router = APIRouter(prefix="/push", tags=["Push"])
presence_router = APIRouter(prefix="/presence", tags=["Presence"])


# ---------------------------------------------------------------------------
# VAPID public key (needed by the browser to subscribe)
# ---------------------------------------------------------------------------


class VapidKeyOut(BaseModel):
    publicKey: str


@router.get("/vapid-public-key", response_model=VapidKeyOut)
async def get_vapid_public_key(
    _user: User = Depends(verify_user),
):
    if not settings.VAPID_PUBLIC_KEY:
        raise HTTPException(
            status_code=503,
            detail="Web Push is not configured on this server.",
        )
    return VapidKeyOut(publicKey=settings.VAPID_PUBLIC_KEY)


# ---------------------------------------------------------------------------
# Subscribe / unsubscribe — user scope
# ---------------------------------------------------------------------------


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: SubscriptionKeys
    userAgent: Optional[str] = Field(default=None, max_length=500)


class SubscriptionOut(BaseModel):
    id: uuid.UUID


@router.post("/subscribe", response_model=SubscriptionOut)
async def subscribe(
    payload: SubscriptionIn,
    user: User = Depends(verify_user),
    db: AsyncSession = Depends(get_db),
):
    # Upsert on endpoint — re-subscribing replaces old keys.
    existing = (
        await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
        )
    ).scalar_one_or_none()
    if existing:
        await db.execute(
            update(PushSubscription)
            .where(PushSubscription.id == existing.id)
            .values(
                user_id=user.id,
                p256dh=payload.keys.p256dh,
                auth=payload.keys.auth,
                user_agent=payload.userAgent,
            )
        )
        await db.commit()
        return SubscriptionOut(id=existing.id)

    row = PushSubscription(
        user_id=user.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=payload.userAgent,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return SubscriptionOut(id=row.id)


class UnsubscribeIn(BaseModel):
    endpoint: str


class UnsubscribeOut(BaseModel):
    deleted: int


@router.post("/unsubscribe", response_model=UnsubscribeOut)
async def unsubscribe(
    payload: UnsubscribeIn,
    user: User = Depends(verify_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        delete(PushSubscription)
        .where(PushSubscription.endpoint == payload.endpoint)
        .where(PushSubscription.user_id == user.id)
    )
    await db.commit()
    return UnsubscribeOut(deleted=result.rowcount or 0)


# ---------------------------------------------------------------------------
# Send — requires push:send scope. Same path as the bot tool.
# ---------------------------------------------------------------------------


class PushSendIn(BaseModel):
    """Push payload. Either `user_id` or `user_email` identifies the target."""
    user_id: Optional[uuid.UUID] = None
    user_email: Optional[str] = None
    title: str = Field(..., max_length=200)
    body: str = Field(..., max_length=2000)
    url: Optional[str] = None
    tag: Optional[str] = None
    icon: Optional[str] = None
    badge: Optional[str] = None
    data: Optional[dict] = None
    only_if_inactive: bool = True


class PushSendOut(BaseModel):
    sent: int
    pruned: int
    failed: int
    skippedActive: bool


@router.post("/send", response_model=PushSendOut)
async def send(
    payload: PushSendIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("push:send")),
):
    if not payload.user_id and not payload.user_email:
        raise HTTPException(status_code=400, detail="user_id or user_email required")

    user_id = payload.user_id
    if user_id is None:
        u = (
            await db.execute(select(User).where(User.email == payload.user_email))
        ).scalar_one_or_none()
        if u is None:
            raise HTTPException(status_code=404, detail="user not found")
        user_id = u.id

    try:
        result = await send_push(
            db, user_id,
            payload.title, payload.body,
            url=payload.url, tag=payload.tag,
            icon=payload.icon, badge=payload.badge, data=payload.data,
            only_if_inactive=payload.only_if_inactive,
        )
    except PushDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return PushSendOut(
        sent=result.sent,
        pruned=result.pruned,
        failed=result.failed,
        skippedActive=result.skipped_active,
    )


# ---------------------------------------------------------------------------
# Presence heartbeat — called by the frontend every ~60s while visible.
# Lives here so it's co-located with its consumer (`only_if_inactive`
# check in the push service).
# ---------------------------------------------------------------------------


class HeartbeatOut(BaseModel):
    ok: bool = True


@presence_router.post("/heartbeat", response_model=HeartbeatOut)
async def presence_heartbeat(
    user: User = Depends(verify_user),
):
    presence.mark_active(user.id)
    return HeartbeatOut()
