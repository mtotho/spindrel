"""Admin endpoints driving the ChatGPT subscription OAuth flow.

Three endpoints plus a status read so the admin UI can:

  1. ``POST /start/{provider_id}``  — open a device-code session.
  2. ``POST /poll/{provider_id}``   — wait until the user approves the
     code, then persist tokens onto the provider row.
  3. ``POST /disconnect/{provider_id}``  — clear OAuth tokens.
  4. ``GET  /status/{provider_id}``  — quick read of connection state.

Tokens themselves live on ``ProviderConfig.config['oauth']``; secrets are
encrypted. See ``app/services/openai_oauth.py`` for the wire details.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProviderConfig as ProviderConfigRow
from app.dependencies import get_db, require_scopes
from app.services.openai_oauth import (
    cancel_device_flow,
    disconnect_provider,
    poll_once,
    start_device_flow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers/openai-oauth", tags=["OpenAI subscription OAuth"])


class DeviceStartOut(BaseModel):
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class PollOut(BaseModel):
    status: str
    email: str = ""
    plan: str = ""


class StatusOut(BaseModel):
    connected: bool
    email: str = ""
    plan: str = ""
    expires_at: str = ""


async def _require_subscription_provider(
    provider_id: str, db: AsyncSession
) -> ProviderConfigRow:
    row = await db.get(ProviderConfigRow, provider_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if row.provider_type != "openai-subscription":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider {provider_id!r} is type {row.provider_type!r}; "
                "OAuth flow is only valid for openai-subscription providers."
            ),
        )
    return row


@router.post("/start/{provider_id}", response_model=DeviceStartOut)
async def start(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _scope=Depends(require_scopes("admin")),
):
    await _require_subscription_provider(provider_id, db)
    try:
        data = await start_device_flow(provider_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return DeviceStartOut(**data)


@router.post("/poll/{provider_id}", response_model=PollOut)
async def poll(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _scope=Depends(require_scopes("admin")),
):
    """One poll cycle — returns quickly with ``pending`` or ``success``.

    Clients call this on the interval returned by ``/start`` until the
    status is no longer ``pending``.
    """
    await _require_subscription_provider(provider_id, db)
    try:
        return PollOut(**await poll_once(provider_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/disconnect/{provider_id}")
async def disconnect(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _scope=Depends(require_scopes("admin")),
):
    await _require_subscription_provider(provider_id, db)
    await cancel_device_flow(provider_id)
    await disconnect_provider(provider_id)
    return {"ok": True}


@router.get("/status/{provider_id}", response_model=StatusOut)
async def status(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _scope=Depends(require_scopes("admin")),
):
    row = await _require_subscription_provider(provider_id, db)
    oauth = (row.config or {}).get("oauth") or {}
    connected = bool(oauth.get("access_token"))
    return StatusOut(
        connected=connected,
        email=oauth.get("account_email", ""),
        plan=oauth.get("plan", ""),
        expires_at=oauth.get("expires_at", ""),
    )
