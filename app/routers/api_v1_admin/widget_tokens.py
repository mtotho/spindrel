"""POST /api/v1/admin/widgets/tokens/revoke — kill a widget JWT before
its 15-min TTL expires. Authenticated as admin (the parent router pins
``verify_admin_auth``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import jwt as _jwt
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db, require_scopes
from app.services.widget_token_revocations import revoke

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/widgets/tokens/revoke")
async def revoke_widget_token(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    """Revoke a widget token by ``(api_key_id, jti)`` or by raw token.

    Either pass ``{token: "<jwt>"}`` and we extract the fields, or
    ``{api_key_id, jti, expires_at}`` directly. ``expires_at`` is
    stored so the purge sweep can drop the row once the underlying
    token is dead anyway.
    """
    api_key_id_raw = payload.get("api_key_id")
    jti = payload.get("jti")
    expires_at_raw = payload.get("expires_at")

    if "token" in payload and payload["token"]:
        try:
            decoded = _jwt.decode(
                payload["token"],
                settings.JWT_SECRET or "",
                algorithms=["HS256"],
                # We don't care if it's expired — we still want to record
                # the revocation. (A purge sweep cleans up later.)
                options={"verify_exp": False, "verify_signature": True}
                if settings.JWT_SECRET
                else {"verify_signature": False, "verify_exp": False},
            )
        except _jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid token: {exc}")
        if decoded.get("kind") != "widget":
            raise HTTPException(status_code=400, detail="Not a widget token")
        api_key_id_raw = decoded.get("api_key_id")
        jti = decoded.get("jti")
        expires_at_raw = decoded.get("exp")

    if not api_key_id_raw or not jti:
        raise HTTPException(
            status_code=400,
            detail="Provide either {token} or {api_key_id, jti, expires_at}",
        )

    try:
        api_key_id = UUID(str(api_key_id_raw))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid api_key_id")

    expires_at: datetime
    if isinstance(expires_at_raw, (int, float)):
        expires_at = datetime.fromtimestamp(int(expires_at_raw), tz=timezone.utc)
    elif isinstance(expires_at_raw, str):
        try:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expires_at")
    else:
        # Default — 15 minutes (matches WIDGET_TOKEN_TTL_SECONDS). The
        # purge sweep will pick this up on schedule even if the original
        # token had a longer TTL.
        from datetime import timedelta

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    await revoke(db, api_key_id=api_key_id, jti=str(jti), expires_at=expires_at)
    await db.commit()
    logger.info("Widget token revoked: api_key_id=%s jti=%s", api_key_id, jti)
    return {"revoked": True, "api_key_id": str(api_key_id), "jti": str(jti)}
