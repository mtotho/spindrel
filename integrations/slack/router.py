"""Slack integration router — serves config to the Slack bot process."""
from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Bot as BotRow, Channel, ChannelIntegration
from app.dependencies import verify_admin_auth
from app.schemas.binding_suggestions import BindingSuggestion

logger = logging.getLogger(__name__)

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
        # Legacy channels: integration="slack" with client_id set directly
        channel_rows = (await db.execute(
            select(Channel).where(Channel.integration == "slack")
        )).scalars().all()

        # Modern bindings: channels bound via ChannelIntegration table (UI flow)
        binding_rows = (await db.execute(
            select(Channel, ChannelIntegration)
            .join(ChannelIntegration, ChannelIntegration.channel_id == Channel.id)
            .where(ChannelIntegration.integration_type == "slack")
        )).tuples().all()

        bot_rows = (await db.execute(select(BotRow))).scalars().all()

    channels = {}
    # Legacy channels (Channel.client_id set directly)
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
            "tool_output_display": row.tool_output_display,
        }

    # Modern bindings (ChannelIntegration.client_id) — don't overwrite legacy
    for ch, binding in binding_rows:
        slack_id = binding.client_id.removeprefix("slack:")
        if slack_id not in channels:
            channels[slack_id] = {
                "bot_id": ch.bot_id,
                "require_mention": ch.require_mention,
                "passive_memory": ch.passive_memory,
                "allow_bot_messages": ch.allow_bot_messages,
                "thinking_display": ch.thinking_display,
                "tool_output_display": ch.tool_output_display,
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


# ---------------------------------------------------------------------------
# Binding suggestions — cached, configurable
# ---------------------------------------------------------------------------

_suggestions_cache: dict[str, object] = {"data": [], "ts": 0.0}
_SUGGESTIONS_CACHE_TTL = 300  # 5 minutes


def _get_slack_setting(key: str, default: str = "") -> str:
    """Get a Slack setting: DB cache > env var > default."""
    try:
        from app.services.integration_settings import get_value
        return get_value("slack", key, default)
    except ImportError:
        return os.environ.get(key, default)


@router.get("/binding-suggestions", response_model=list[BindingSuggestion])
async def binding_suggestions(_auth=Depends(verify_admin_auth)) -> list[BindingSuggestion]:
    """Return Slack channels the bot can see, formatted as binding suggestions.

    Controlled by:
    - ``SLACK_SUGGEST_CHANNELS`` — enable/disable (default true)
    - ``SLACK_SUGGEST_COUNT`` — how many to return (default 20, max 100)

    Results are cached server-side for 5 minutes.
    Requires ``channels:read`` scope (already standard).
    """
    enabled = _get_slack_setting("SLACK_SUGGEST_CHANNELS", "true").lower() in ("true", "1", "yes")
    if not enabled:
        return []

    try:
        count = max(1, min(100, int(_get_slack_setting("SLACK_SUGGEST_COUNT", "20"))))
    except ValueError:
        count = 20

    # Return cached results if fresh
    now = time.monotonic()
    if _suggestions_cache["data"] and (now - _suggestions_cache["ts"]) < _SUGGESTIONS_CACHE_TTL:
        return _suggestions_cache["data"][:count]

    # Get bot token
    token = _get_slack_setting("SLACK_BOT_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="SLACK_BOT_TOKEN not configured")

    from integrations.slack.client import list_conversations

    channels = await list_conversations(token, limit=200)
    if channels is None:
        raise HTTPException(status_code=502, detail="Failed to fetch Slack channels (check channels:read scope)")

    # Sort: channels with more recent activity first (Slack doesn't guarantee order).
    # Use 'updated' timestamp if available, else 'created'.
    channels.sort(key=lambda c: c.get("updated", c.get("created", 0)), reverse=True)

    all_suggestions: list[BindingSuggestion] = []
    for ch in channels:
        ch_id = ch.get("id", "")
        if not ch_id:
            continue
        name = ch.get("name_normalized") or ch.get("name") or ch_id
        is_private = ch.get("is_private", False)
        prefix = "" if is_private else "#"
        topic = (ch.get("topic") or {}).get("value", "")
        purpose = (ch.get("purpose") or {}).get("value", "")
        description = topic or purpose

        all_suggestions.append(BindingSuggestion(
            client_id=f"slack:{ch_id}",
            display_name=f"{prefix}{name}",
            description=description[:80] if description else "",
        ))

    _suggestions_cache["data"] = all_suggestions
    _suggestions_cache["ts"] = now

    return all_suggestions[:count]
