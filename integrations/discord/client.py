"""Shared Discord REST API helpers — single source of truth for message posting.

All Discord API calls from the server (dispatcher, delegation, fan-out) go through
this module. The Discord bot process uses discord.py for interactive events;
this module covers the non-bot code paths (task dispatcher, etc.).
"""
from __future__ import annotations

import logging
from urllib.parse import quote as urlquote

import httpx

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
_http = httpx.AsyncClient(timeout=30.0)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bot {token}"}


def bot_attribution(bot_id: str) -> dict:
    """Return display name and avatar URL for bot identity.

    Discord webhooks support username + avatar_url overrides.
    Regular bot messages use the bot's own identity, but we return
    display info for use in embeds, thread naming, etc.
    """
    from integrations.sdk import get_bot

    try:
        bot = get_bot(bot_id)
    except Exception:
        logger.warning("bot_attribution: failed to resolve bot_id=%s", bot_id, exc_info=True)
        return {}

    attrs: dict = {}
    username = bot.display_name or bot.name
    if username:
        attrs["username"] = username
    if bot.avatar_url:
        attrs["avatar_url"] = bot.avatar_url
    return attrs


async def post_message(
    token: str,
    channel_id: str,
    text: str,
) -> dict | None:
    """Post a message to a Discord channel. Returns the message object or None on failure."""
    payload: dict = {"content": text}
    try:
        r = await _http.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            json=payload,
            headers=_headers(token),
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        logger.exception("Failed to post to Discord channel %s", channel_id)
        return None


async def edit_message(
    token: str,
    channel_id: str,
    message_id: str,
    text: str,
) -> bool:
    """Edit an existing Discord message. Returns True on success."""
    payload: dict = {"content": text}
    try:
        r = await _http.patch(
            f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}",
            json=payload,
            headers=_headers(token),
        )
        r.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to edit Discord message %s in %s", message_id, channel_id)
        return False


async def add_reaction(
    token: str,
    channel_id: str,
    message_id: str,
    emoji: str,
) -> bool:
    """Add a Unicode emoji reaction to a message. Returns True on success."""
    encoded = urlquote(emoji)
    try:
        r = await _http.put(
            f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
            headers=_headers(token),
        )
        # 204 No Content = success, 400 = already reacted (ok)
        return r.status_code in (204, 200, 400)
    except Exception:
        logger.debug("Failed to add reaction %s to %s/%s", emoji, channel_id, message_id, exc_info=True)
        return False


async def remove_reaction(
    token: str,
    channel_id: str,
    message_id: str,
    emoji: str,
) -> bool:
    """Remove our own reaction from a message. Returns True on success."""
    encoded = urlquote(emoji)
    try:
        r = await _http.delete(
            f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
            headers=_headers(token),
        )
        return r.status_code in (204, 200, 404)  # 404 = already removed
    except Exception:
        logger.debug("Failed to remove reaction %s from %s/%s", emoji, channel_id, message_id, exc_info=True)
        return False


async def upload_file(
    token: str,
    channel_id: str,
    file_bytes: bytes,
    filename: str,
    *,
    content: str | None = None,
) -> dict | None:
    """Upload a file to a Discord channel. Returns message object or None."""
    try:
        files = {"file": (filename, file_bytes)}
        data: dict = {}
        if content:
            data["content"] = content
        r = await _http.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            data=data,
            files=files,
            headers=_headers(token),
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        logger.exception("Failed to upload file to Discord channel %s", channel_id)
        return None
