"""Shared Slack HTTP helpers — single source of truth for chat.postMessage.

All Slack API calls from the server (dispatcher, delegation, fan-out) go through
this module.  The Slack Bolt integration uses its own AsyncWebClient for interactive
events; this module covers the non-Bolt code paths.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)


def bot_attribution(bot_id: str) -> dict:
    """Return Slack payload fields for bot identity (username, icon_emoji, icon_url).

    Requires chat:write.customize scope on the Slack app.
    """
    from app.agent.bots import get_bot

    try:
        bot = get_bot(bot_id)
    except Exception:
        logger.warning("bot_attribution: failed to resolve bot_id=%s", bot_id, exc_info=True)
        return {}

    attrs: dict = {}
    username = bot.display_name or bot.name
    if username:
        attrs["username"] = username
    slack_cfg = bot.integration_config.get("slack", {})
    if slack_cfg.get("icon_emoji"):
        attrs["icon_emoji"] = slack_cfg["icon_emoji"]
    elif bot.avatar_url:
        attrs["icon_url"] = bot.avatar_url
    return attrs


def user_attribution(user) -> dict:
    """Return Slack payload fields for user identity (username, icon_emoji, icon_url).

    Delegates to integrations/slack/hooks.py — kept here for backward compat
    within the Slack integration.
    """
    from integrations.slack.hooks import _user_attribution
    return _user_attribution(user)


async def post_message(
    token: str,
    channel_id: str,
    text: str,
    *,
    thread_ts: str | None = None,
    reply_in_thread: bool = True,
    username: str | None = None,
    icon_emoji: str | None = None,
    icon_url: str | None = None,
) -> bool:
    """Post a message to a Slack channel via chat.postMessage.

    Returns True on success, False on failure.
    """
    payload: dict = {"channel": channel_id, "text": text}
    if thread_ts and reply_in_thread:
        payload["thread_ts"] = thread_ts
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji
    elif icon_url:
        payload["icon_url"] = icon_url

    try:
        r = await _http.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            logger.error("Slack chat.postMessage error: %s", data.get("error"))
            return False
        return True
    except Exception:
        logger.exception("Failed to post to Slack channel %s", channel_id)
        return False


async def post_message_raw(
    token: str,
    channel_id: str,
    text: str,
    *,
    thread_ts: str | None = None,
    reply_in_thread: bool = True,
    username: str | None = None,
    icon_emoji: str | None = None,
    icon_url: str | None = None,
) -> dict | None:
    """Post a message and return the full Slack API response (with ts, channel, etc).

    Returns None on failure.
    """
    payload: dict = {"channel": channel_id, "text": text}
    if thread_ts and reply_in_thread:
        payload["thread_ts"] = thread_ts
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji
    elif icon_url:
        payload["icon_url"] = icon_url

    try:
        r = await _http.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            logger.error("Slack chat.postMessage error: %s", data.get("error"))
            return None
        return data
    except Exception:
        logger.exception("Failed to post to Slack channel %s", channel_id)
        return None


async def update_message(
    token: str,
    channel_id: str,
    ts: str,
    text: str,
    *,
    username: str | None = None,
    icon_emoji: str | None = None,
    icon_url: str | None = None,
) -> bool:
    """Update an existing Slack message via chat.update. Returns True on success."""
    payload: dict = {"channel": channel_id, "ts": ts, "text": text}
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji
    elif icon_url:
        payload["icon_url"] = icon_url

    try:
        r = await _http.post(
            "https://slack.com/api/chat.update",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            logger.error("Slack chat.update error: %s", data.get("error"))
            return False
        return True
    except Exception:
        logger.exception("Failed to update Slack message %s in %s", ts, channel_id)
        return False
