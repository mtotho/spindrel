"""Slack integration router — serves config to the Slack bot process."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from integrations.sdk import (
    BindingSuggestion,
    BotRow,
    Channel,
    ChannelIntegration,
    app_settings,
    async_session,
    get_setting,
    has_scope,
    validate_api_key,
    verify_admin_auth,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_CONFIG_CACHE_TTL = 5.0
_AUTH_CACHE_TTL = 5.0
_config_cache: dict[str, object] = {"data": None, "ts": 0.0}
_auth_cache: dict[str, float] = {}
_config_lock: asyncio.Lock | None = None
_auth_lock: asyncio.Lock | None = None


def _cache_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _get_config_lock() -> asyncio.Lock:
    global _config_lock
    if _config_lock is None:
        _config_lock = asyncio.Lock()
    return _config_lock


def _get_auth_lock() -> asyncio.Lock:
    global _auth_lock
    if _auth_lock is None:
        _auth_lock = asyncio.Lock()
    return _auth_lock


def _clear_slack_config_cache_for_tests() -> None:
    _config_cache["data"] = None
    _config_cache["ts"] = 0.0
    _auth_cache.clear()


async def _is_config_request_authorized(api_key: str | None) -> bool:
    expected = getattr(app_settings, "API_KEY", None)
    if expected and api_key == expected:
        return True

    if not api_key or not api_key.startswith("ask_"):
        return False

    now = time.monotonic()
    auth_cache_key = _cache_key(api_key)
    if _auth_cache.get(auth_cache_key, 0.0) > now:
        return True

    async with _get_auth_lock():
        now = time.monotonic()
        if _auth_cache.get(auth_cache_key, 0.0) > now:
            return True

        async with async_session() as key_db:
            key_row = await validate_api_key(key_db, api_key)
            authed = bool(key_row and has_scope(key_row.scopes or [], "admin"))

        if authed:
            _auth_cache[auth_cache_key] = now + _AUTH_CACHE_TTL
        return authed


async def _load_config_payload() -> dict:
    now = time.monotonic()
    cached = _config_cache.get("data")
    if isinstance(cached, dict) and now - float(_config_cache["ts"]) < _CONFIG_CACHE_TTL:
        return cached

    async with _get_config_lock():
        now = time.monotonic()
        cached = _config_cache.get("data")
        if isinstance(cached, dict) and now - float(_config_cache["ts"]) < _CONFIG_CACHE_TTL:
            return cached

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

        payload = {
            "default_bot": os.environ.get("SLACK_DEFAULT_BOT", "default"),
            "channels": channels,
            "bots": bots,
        }
        _config_cache["data"] = payload
        _config_cache["ts"] = time.monotonic()
        return payload


@router.get("/config")
async def slack_config(request: Request):
    """Returns Slack channel->bot mapping for the Slack bot process."""
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not await _is_config_request_authorized(api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")

    return JSONResponse(await _load_config_payload())


# ---------------------------------------------------------------------------
# Binding suggestions — cached, configurable
# ---------------------------------------------------------------------------

_suggestions_cache: dict[str, object] = {"data": [], "ts": 0.0}
_SUGGESTIONS_CACHE_TTL = 300  # 5 minutes


def _get_slack_setting(key: str, default: str = "") -> str:
    """Get a Slack setting: DB cache > env var > default."""
    try:
        return get_setting("slack", key, default)
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
