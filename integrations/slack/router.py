"""Slack integration router — serves config to the Slack bot process."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Bot as BotRow, Channel

router = APIRouter()


@router.get("/config")
async def slack_config(request: Request):
    """Returns Slack channel->bot mapping for the Slack bot process."""
    from app.config import settings

    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    expected = getattr(settings, "API_KEY", None)

    authed = bool(expected and api_key == expected)

    if not authed and api_key and api_key.startswith("ask_"):
        from app.services.api_keys import validate_api_key, has_scope
        async with async_session() as key_db:
            key_row = await validate_api_key(key_db, api_key)
            if key_row and has_scope(key_row.scopes or [], "admin"):
                authed = True

    if not authed:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with async_session() as db:
        channel_rows = (await db.execute(
            select(Channel).where(Channel.integration == "slack")
        )).scalars().all()
        bot_rows = (await db.execute(select(BotRow))).scalars().all()

    channels = {}
    for row in channel_rows:
        if not row.client_id:
            continue
        slack_id = row.client_id.removeprefix("slack:")
        channels[slack_id] = {
            "bot_id": row.bot_id,
            "require_mention": row.require_mention,
            "passive_memory": row.passive_memory,
            "allow_bot_messages": row.allow_bot_messages,
            "thinking_display": row.thinking_display,
        }

    bots = {
        row.id: {
            "display_name": row.display_name or row.name,
            "icon_emoji": (row.integration_config or {}).get("slack", {}).get("icon_emoji") or None,
            "icon_url": row.avatar_url or None,
        }
        for row in bot_rows
    }

    return JSONResponse({
        "default_bot": os.environ.get("SLACK_DEFAULT_BOT", "default"),
        "channels": channels,
        "bots": bots,
    })
