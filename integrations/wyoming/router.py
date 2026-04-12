"""Wyoming integration router -- serves config and binding suggestions."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Bot as BotRow, Channel, ChannelIntegration

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/config")
async def wyoming_config(request: Request):
    """Returns device->bot mapping for the Wyoming pipeline orchestrator.

    Merges legacy Channel-level bindings and modern ChannelIntegration bindings.
    Each device entry includes satellite_uri so the orchestrator knows where to connect.
    """
    from app.config import settings

    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        api_key = api_key or auth_header[7:]

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
        # Legacy channels
        channel_rows = (await db.execute(
            select(Channel).where(Channel.integration == "wyoming")
        )).scalars().all()

        # Modern bindings
        binding_rows = (await db.execute(
            select(Channel, ChannelIntegration)
            .join(ChannelIntegration, ChannelIntegration.channel_id == Channel.id)
            .where(ChannelIntegration.integration_type == "wyoming")
        )).tuples().all()

        bot_rows = (await db.execute(select(BotRow))).scalars().all()

    bots = {str(b.id): b for b in bot_rows}
    devices: dict[str, dict] = {}

    # Legacy
    for row in channel_rows:
        if not row.client_id:
            continue
        device_id = row.client_id.removeprefix("wyoming:")
        bot = bots.get(str(row.bot_id))
        devices[device_id] = {
            "bot_id": str(row.bot_id),
            "bot_name": bot.name if bot else "unknown",
            "channel_id": str(row.id),
            "channel_name": row.name,
        }

    # Modern bindings
    for channel, binding in binding_rows:
        device_id = (binding.client_id or "").removeprefix("wyoming:")
        if not device_id:
            continue
        bot = bots.get(str(channel.bot_id))
        config = binding.activation_config or {}
        devices[device_id] = {
            "bot_id": str(channel.bot_id),
            "bot_name": bot.name if bot else "unknown",
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "satellite_uri": config.get("satellite_uri"),
            "voice": config.get("voice"),
            "wake_words": config.get("wake_words"),
        }

    return {"devices": devices}


@router.get("/binding-suggestions")
async def binding_suggestions():
    """Return suggested device bindings for the admin UI."""
    return [
        {
            "client_id": "wyoming:living-room",
            "display_name": "Living Room",
            "description": "Example: Raspberry Pi satellite in the living room",
        },
        {
            "client_id": "wyoming:bedroom",
            "display_name": "Bedroom",
            "description": "Example: Raspberry Pi satellite in the bedroom",
        },
        {
            "client_id": "wyoming:kitchen",
            "display_name": "Kitchen",
            "description": "Example: Raspberry Pi satellite in the kitchen",
        },
    ]
