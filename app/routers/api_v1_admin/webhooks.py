"""Webhook endpoint CRUD + delivery log: /webhooks."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WebhookDelivery, WebhookEndpoint
from app.dependencies import get_db, require_scopes
from app.services.encryption import decrypt, encrypt
from app.services.webhooks import (
    EVENT_REGISTRY,
    generate_secret,
    invalidate_cache,
    send_test_event,
    validate_webhook_url,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WebhookEndpointOut(BaseModel):
    id: str
    name: str
    url: str
    events: list[str]
    is_active: bool
    description: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookEndpointCreateIn(BaseModel):
    name: str
    url: str
    events: list[str] = []
    is_active: bool = True
    description: str = ""


class WebhookEndpointCreateOut(BaseModel):
    endpoint: WebhookEndpointOut
    secret: str  # returned ONCE on creation


class WebhookEndpointUpdateIn(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[list[str]] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class WebhookDeliveryOut(BaseModel):
    id: str
    endpoint_id: str
    event: str
    payload: dict
    attempt: int
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookEventOut(BaseModel):
    event: str
    description: str


class TestResultOut(BaseModel):
    success: bool
    status_code: Optional[int] = None
    duration_ms: int
    response_body: Optional[str] = None
    error: Optional[str] = None


class RotateSecretOut(BaseModel):
    secret: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_out(row: WebhookEndpoint) -> WebhookEndpointOut:
    return WebhookEndpointOut(
        id=str(row.id),
        name=row.name,
        url=row.url,
        events=row.events or [],
        is_active=row.is_active,
        description=row.description or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _delivery_to_out(row: WebhookDelivery) -> WebhookDeliveryOut:
    return WebhookDeliveryOut(
        id=str(row.id),
        endpoint_id=str(row.endpoint_id),
        event=row.event,
        payload=row.payload,
        attempt=row.attempt,
        status_code=row.status_code,
        response_body=row.response_body,
        error=row.error,
        duration_ms=row.duration_ms,
        created_at=row.created_at,
    )


async def _get_endpoint(db: AsyncSession, endpoint_id: str) -> WebhookEndpoint:
    try:
        pk = uuid.UUID(endpoint_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    row = await db.get(WebhookEndpoint, pk)
    if not row:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/webhooks/events", response_model=list[WebhookEventOut])
async def admin_webhook_events(
    _auth=Depends(require_scopes("webhooks:read")),
):
    """List available webhook event types."""
    return [WebhookEventOut(event=k, description=v) for k, v in EVENT_REGISTRY.items()]


@router.get("/webhooks", response_model=list[WebhookEndpointOut])
async def admin_list_webhooks(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("webhooks:read")),
):
    """List all webhook endpoints."""
    rows = (await db.execute(
        select(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc())
    )).scalars().all()
    return [_row_to_out(r) for r in rows]


@router.post("/webhooks", response_model=WebhookEndpointCreateOut, status_code=201)
async def admin_create_webhook(
    body: WebhookEndpointCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("webhooks:write")),
):
    """Create a new webhook endpoint. Returns the signing secret ONCE."""
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    if not body.url or not body.url.strip():
        raise HTTPException(status_code=422, detail="url is required")

    try:
        await validate_webhook_url(body.url.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Validate event names
    invalid = [e for e in body.events if e not in EVENT_REGISTRY]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid events: {invalid}")

    raw_secret = generate_secret()
    row = WebhookEndpoint(
        id=uuid.uuid4(),
        name=body.name.strip(),
        url=body.url.strip(),
        secret=encrypt(raw_secret),
        events=body.events,
        is_active=body.is_active,
        description=body.description.strip() if body.description else "",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    invalidate_cache()

    return WebhookEndpointCreateOut(
        endpoint=_row_to_out(row),
        secret=raw_secret,
    )


@router.get("/webhooks/{endpoint_id}", response_model=WebhookEndpointOut)
async def admin_get_webhook(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("webhooks:read")),
):
    """Get webhook endpoint details (secret is never returned)."""
    row = await _get_endpoint(db, endpoint_id)
    return _row_to_out(row)


@router.put("/webhooks/{endpoint_id}", response_model=WebhookEndpointOut)
async def admin_update_webhook(
    endpoint_id: str,
    body: WebhookEndpointUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("webhooks:write")),
):
    """Update a webhook endpoint."""
    row = await _get_endpoint(db, endpoint_id)

    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="name cannot be empty")
        row.name = body.name.strip()

    if body.url is not None:
        if not body.url.strip():
            raise HTTPException(status_code=422, detail="url cannot be empty")
        try:
            await validate_webhook_url(body.url.strip())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        row.url = body.url.strip()

    if body.events is not None:
        invalid = [e for e in body.events if e not in EVENT_REGISTRY]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid events: {invalid}")
        row.events = body.events

    if body.is_active is not None:
        row.is_active = body.is_active

    if body.description is not None:
        row.description = body.description.strip()

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    invalidate_cache()

    return _row_to_out(row)


@router.delete("/webhooks/{endpoint_id}")
async def admin_delete_webhook(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("webhooks:write")),
):
    """Delete a webhook endpoint and all its deliveries."""
    row = await _get_endpoint(db, endpoint_id)
    await db.delete(row)
    await db.commit()
    invalidate_cache()
    return {"ok": True}


@router.post("/webhooks/{endpoint_id}/rotate-secret", response_model=RotateSecretOut)
async def admin_rotate_webhook_secret(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("webhooks:write")),
):
    """Generate a new signing secret for an endpoint. Returns the new secret ONCE."""
    row = await _get_endpoint(db, endpoint_id)
    raw_secret = generate_secret()
    row.secret = encrypt(raw_secret)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    invalidate_cache()
    return RotateSecretOut(secret=raw_secret)


@router.post("/webhooks/{endpoint_id}/test", response_model=TestResultOut)
async def admin_test_webhook(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("webhooks:write")),
):
    """Send a test event to a webhook endpoint."""
    try:
        pk = uuid.UUID(endpoint_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    try:
        result = await send_test_event(pk, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return TestResultOut(**result)


@router.get("/webhooks/{endpoint_id}/deliveries", response_model=list[WebhookDeliveryOut])
async def admin_webhook_deliveries(
    endpoint_id: str,
    event: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("webhooks:read")),
):
    """Get delivery log for a webhook endpoint."""
    # Verify endpoint exists
    await _get_endpoint(db, endpoint_id)
    pk = uuid.UUID(endpoint_id)

    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.endpoint_id == pk)
        .order_by(WebhookDelivery.created_at.desc())
    )
    if event:
        stmt = stmt.where(WebhookDelivery.event == event)
    stmt = stmt.offset(offset).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return [_delivery_to_out(r) for r in rows]
