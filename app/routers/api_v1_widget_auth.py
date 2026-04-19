"""Widget auth — short-lived bearer tokens for interactive HTML widgets.

``POST /api/v1/widget-auth/mint`` mints a 15-minute JWT scoped to a bot's
own API key. Injected by ``InteractiveHtmlRenderer`` into the iframe's
``window.spindrel.api()`` so bot-authored JS authenticates as the bot —
NOT as the viewing user. Without this, an admin viewing a pinned widget
would be lending their admin credentials to whatever fetch() calls the
bot chose to write.

Authorization for the mint itself:
- Must be an authenticated user (or admin-scoped API key).
- Caller must own the bot (``bot.user_id == user.id``) OR be admin.
- Bot must have a configured API key; otherwise the widget has no bot
  identity to authenticate as and the mint 400s with a clear message.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, Bot, User
from app.dependencies import ApiKeyAuth, get_db, verify_auth_or_user
from app.services.auth import (
    WIDGET_TOKEN_TTL_SECONDS,
    create_widget_token,
)
from app.services.bots_visibility import can_user_use_bot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widget-auth", tags=["widget-auth"])


class MintRequest(BaseModel):
    source_bot_id: str
    pin_id: str | None = None


class MintResponse(BaseModel):
    token: str
    expires_at: str
    expires_in: int
    bot_id: str
    bot_name: str
    bot_avatar_url: str | None = None
    scopes: list[str]


def _is_admin(auth: object) -> bool:
    if isinstance(auth, ApiKeyAuth):
        return "admin" in (auth.scopes or [])
    # User with admin flag
    return bool(getattr(auth, "is_admin", False))


async def _caller_may_use_bot(db: AsyncSession, auth: object, bot: Bot) -> bool:
    """Admin bypass, bot owner bypass, else a ``bot_grants`` row is required."""
    if _is_admin(auth):
        return True
    if isinstance(auth, User):
        return await can_user_use_bot(db, auth, bot)
    return False


@router.post("/mint", response_model=MintResponse)
async def mint_widget_token(
    body: MintRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    bot = await db.get(Bot, body.source_bot_id)
    if bot is None:
        raise HTTPException(404, f"Bot {body.source_bot_id} not found")

    bot_label = bot.display_name or bot.name or str(bot.id)

    if not await _caller_may_use_bot(db, auth, bot):
        raise HTTPException(
            status_code=403,
            detail={
                "message": (
                    f"You don't have access to bot '{bot_label}'. "
                    "Ask an admin to grant you access under "
                    f"Admin → Bots → {bot_label} → Grants."
                ),
                "reason": "bot_access_denied",
                "bot_id": bot.id,
                "bot_name": bot_label,
                "pin_id": body.pin_id,
            },
        )

    if bot.api_key_id is None:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    f"Bot '{bot_label}' has no API permissions yet. "
                    "Grant the widget the scopes it needs (e.g. attachments:read) "
                    f"under Admin → Bots → {bot_label} → Permissions, then retry."
                ),
                "reason": "bot_missing_api_key",
                "bot_id": bot.id,
                "pin_id": body.pin_id,
            },
        )

    api_key = await db.get(ApiKey, bot.api_key_id)
    if api_key is None or not api_key.is_active:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    f"Bot '{bot_label}' has an inactive API key. "
                    "Re-enable it under Admin → Bots → Permissions, then retry."
                ),
                "reason": "bot_api_key_inactive",
                "bot_id": bot.id,
                "pin_id": body.pin_id,
            },
        )

    scopes = list(api_key.scopes or [])
    token, expires_at = create_widget_token(
        bot_id=bot.id,
        scopes=scopes,
        api_key_id=api_key.id,
        pin_id=body.pin_id,
    )
    return MintResponse(
        token=token,
        expires_at=expires_at.isoformat(),
        expires_in=WIDGET_TOKEN_TTL_SECONDS,
        bot_id=bot.id,
        bot_name=bot.display_name or bot.name,
        bot_avatar_url=bot.avatar_url,
        scopes=scopes,
    )
