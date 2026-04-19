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
from app.dependencies import ApiKeyAuth, get_db, require_scopes, verify_auth_or_user
from app.services.auth import (
    WIDGET_TOKEN_TTL_SECONDS,
    create_widget_token,
)

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


async def _caller_may_use_bot(auth: object, bot: Bot) -> bool:
    """Admin bypass, otherwise the user that owns the bot."""
    if _is_admin(auth):
        return True
    if isinstance(auth, User):
        return bot.user_id is not None and bot.user_id == auth.id
    return False


@router.post(
    "/mint",
    response_model=MintResponse,
    dependencies=[Depends(require_scopes("chat"))],
)
async def mint_widget_token(
    body: MintRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_auth_or_user),
):
    bot = await db.get(Bot, body.source_bot_id)
    if bot is None:
        raise HTTPException(404, f"Bot {body.source_bot_id} not found")

    if not await _caller_may_use_bot(auth, bot):
        raise HTTPException(403, "Not allowed to mint a token for this bot")

    if bot.api_key_id is None:
        raise HTTPException(
            400,
            f"Bot {bot.id} has no API key configured — no scopes to grant the "
            "widget. Provision one via the admin UI first.",
        )

    api_key = await db.get(ApiKey, bot.api_key_id)
    if api_key is None or not api_key.is_active:
        raise HTTPException(400, f"Bot {bot.id}'s API key is missing or inactive")

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
