"""Discord integration hooks -- metadata + lifecycle.

Metadata (registered at import):
  - user_attribution, resolve_display_names, client_id_prefix

Lifecycle hooks:
  - after_tool_call: Unicode emoji reactions + audit channel logging
  - after_response: remove working reaction, add checkmark
"""
from __future__ import annotations

import json
import logging
import time as _time
from pathlib import Path

import httpx

from integrations.sdk import (
    HookContext,
    IntegrationMeta,
    current_dispatch_config,
    current_dispatch_type,
    get_setting,
    register_hook,
    register_integration,
)

logger = logging.getLogger(__name__)


def _user_attribution(user) -> dict:
    """Return display info for user identity.

    Accepts a User ORM object (or any object with display_name, avatar_url).
    """
    attrs: dict = {}
    if user.display_name:
        attrs["username"] = user.display_name
    if user.avatar_url:
        attrs["avatar_url"] = user.avatar_url
    return attrs


# ---------------------------------------------------------------------------
# Display name resolution
# ---------------------------------------------------------------------------

_discord_name_cache: dict[str, tuple[str, float]] = {}
_DISCORD_NAME_CACHE_TTL = 600  # 10 minutes


async def _fetch_discord_channel_name(client: httpx.AsyncClient, token: str, channel_id: str) -> str | None:
    """Fetch a single Discord channel name, using TTL cache."""
    cached = _discord_name_cache.get(channel_id)
    if cached and (_time.monotonic() - cached[1]) < _DISCORD_NAME_CACHE_TTL:
        return cached[0]
    try:
        r = await client.get(
            f"https://discord.com/api/v10/channels/{channel_id}",
            headers={"Authorization": f"Bot {token}"},
        )
        data = r.json()
        name = data.get("name")
        if name:
            _discord_name_cache[channel_id] = (name, _time.monotonic())
            return name
    except Exception:
        pass
    return None


async def _resolve_display_names(channels: list) -> dict:
    """Resolve display names for Discord channels. Returns {channel.id: '#name'}."""
    import asyncio
    import os

    token = os.environ.get("DISCORD_TOKEN", "")
    if not token:
        return {}

    discord_channels = [ch for ch in channels if ch.integration == "discord"]
    if not discord_channels:
        return {}

    result: dict = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        async def _resolve_one(ch):
            if not ch.client_id:
                return
            discord_id = ch.client_id.removeprefix("discord:")
            name = await _fetch_discord_channel_name(client, token, discord_id)
            if name:
                result[ch.id] = f"#{name}"

        await asyncio.gather(*[_resolve_one(ch) for ch in discord_channels])
    return result


# ---------------------------------------------------------------------------
# Lifecycle hooks: Unicode emoji reactions as tool indicators
# ---------------------------------------------------------------------------

# Map tool name patterns to Unicode emoji for reactions
_TOOL_EMOJI: list[tuple[str, str]] = [
    ("web_search", "\U0001f50d"),  # mag
    ("search", "\U0001f50d"),
    ("exec", "\U0001f4bb"),  # computer
    ("shell", "\U0001f4bb"),
    ("sandbox", "\U0001f4bb"),
    ("save_memory", "\U0001f9e0"),  # brain
    ("memory", "\U0001f9e0"),
    ("read_", "\U0001f440"),  # eyes
    ("write_", "\u270f\ufe0f"),  # pencil2
    ("edit_", "\u270f\ufe0f"),
    ("delegate", "\U0001f4ac"),  # speech_balloon
]
_DEFAULT_TOOL_EMOJI = "\u2699\ufe0f"  # gear
_WORKING_EMOJI = "\u23f3"  # hourglass_flowing_sand
_DONE_EMOJI = "\u2705"  # white_check_mark

# Track which reactions we've added per correlation_id so we can clean up.
_active_reactions: dict[str, tuple[set[str], float]] = {}
_REACTION_TTL = 600


def _evict_stale_reactions() -> None:
    """Remove entries older than _REACTION_TTL to prevent unbounded growth."""
    now = _time.monotonic()
    stale = [k for k, (_, ts) in _active_reactions.items() if now - ts > _REACTION_TTL]
    for k in stale:
        _active_reactions.pop(k, None)


def _get_discord_ref() -> tuple[str | None, str | None, str | None]:
    """Read Discord channel_id, message_id, token from current dispatch context."""
    if current_dispatch_type.get() != "discord":
        return None, None, None
    cfg = current_dispatch_config.get() or {}
    msg_id = cfg.get("user_message_id")
    return cfg.get("channel_id"), msg_id, cfg.get("token")


def _emoji_for_tool(tool_name: str) -> str:
    """Pick a Unicode emoji based on tool name."""
    lower = tool_name.lower()
    for pattern, emoji in _TOOL_EMOJI:
        if pattern in lower:
            return emoji
    return _DEFAULT_TOOL_EMOJI


_react_http = httpx.AsyncClient(timeout=5.0)


async def _discord_react(token: str, channel: str, message_id: str, emoji: str, *, remove: bool = False) -> None:
    """Add or remove a Discord reaction. Fire-and-forget with single 429 retry."""
    import asyncio
    from urllib.parse import quote as urlquote
    encoded = urlquote(emoji)
    url = f"https://discord.com/api/v10/channels/{channel}/messages/{message_id}/reactions/{encoded}/@me"
    headers = {"Authorization": f"Bot {token}"}
    try:
        for _attempt in range(2):
            if remove:
                r = await _react_http.delete(url, headers=headers)
            else:
                r = await _react_http.put(url, headers=headers)
            if r.status_code == 429:
                retry_after = r.json().get("retry_after", 1.0)
                await asyncio.sleep(min(retry_after, 5.0))
                continue
            # 204 = success, 400 = already reacted/not found — both acceptable
            if r.status_code not in (200, 204, 400, 404):
                logger.debug("Discord reaction %s failed: %d", "remove" if remove else "add", r.status_code)
            break
    except Exception:
        logger.debug("Discord reaction request failed", exc_info=True)


async def _on_after_tool_call(ctx: HookContext, **kwargs) -> None:
    """Add emoji reaction for the tool that just ran."""
    channel_id, message_id, token = _get_discord_ref()
    if not all((channel_id, message_id, token)):
        return

    corr_key = str(ctx.correlation_id) if ctx.correlation_id else None
    if not corr_key:
        return

    _evict_stale_reactions()

    tool_name = ctx.extra.get("tool_name", "")
    emoji = _emoji_for_tool(tool_name)

    if corr_key not in _active_reactions:
        _active_reactions[corr_key] = (set(), _time.monotonic())
        await _discord_react(token, channel_id, message_id, _WORKING_EMOJI)
        _active_reactions[corr_key][0].add(_WORKING_EMOJI)

    if emoji not in _active_reactions[corr_key][0]:
        await _discord_react(token, channel_id, message_id, emoji)
        _active_reactions[corr_key][0].add(emoji)


async def _on_after_response(ctx: HookContext, **kwargs) -> None:
    """Remove working indicator and add done checkmark."""
    channel_id, message_id, token = _get_discord_ref()
    if not all((channel_id, message_id, token)):
        return

    corr_key = str(ctx.correlation_id) if ctx.correlation_id else None
    if not corr_key:
        return

    entry = _active_reactions.pop(corr_key, None)
    if not entry:
        return  # no tool calls were made, skip reactions entirely
    reactions = entry[0]

    if _WORKING_EMOJI in reactions:
        await _discord_react(token, channel_id, message_id, _WORKING_EMOJI, remove=True)

    await _discord_react(token, channel_id, message_id, _DONE_EMOJI)


# ---------------------------------------------------------------------------
# Lifecycle hooks: Audit channel logging
# ---------------------------------------------------------------------------

_STATE_FILE = Path(__file__).parent / "discord_state.json"
_audit_channel_cache: tuple[str | None, float] = (None, 0.0)
_AUDIT_CACHE_TTL = 30.0  # re-read file every 30s


def _get_audit_channel() -> str | None:
    """Read audit_channel from discord_state.json. Cached with TTL."""
    global _audit_channel_cache
    now = _time.monotonic()
    if now - _audit_channel_cache[1] < _AUDIT_CACHE_TTL:
        return _audit_channel_cache[0]
    try:
        data = json.loads(_STATE_FILE.read_text())
        val = data.get("__settings__", {}).get("audit_channel")
    except Exception:
        val = None
    _audit_channel_cache = (val, now)
    return val


async def _on_audit_tool_call(ctx: HookContext, **kwargs) -> None:
    """Post tool usage to the configured audit Discord channel."""
    audit_channel = _get_audit_channel()
    if not audit_channel:
        return
    # Get token from dispatch context or env
    _, _, token = _get_discord_ref()
    if not token:
        import os
        token = os.environ.get("DISCORD_TOKEN", "")
    if not token:
        return

    tool = ctx.extra.get("tool_name", "?")
    ms = ctx.extra.get("duration_ms") or 0
    bot = ctx.bot_id or "?"
    text = f"`{tool}` by `{bot}` ({ms}ms)"

    try:
        await _react_http.post(
            f"https://discord.com/api/v10/channels/{audit_channel}/messages",
            json={"content": text},
            headers={"Authorization": f"Bot {token}"},
        )
    except Exception:
        logger.debug("Audit post failed", exc_info=True)


# ---------------------------------------------------------------------------
# Register at import time
# ---------------------------------------------------------------------------

def _resolve_dispatch_config(client_id: str) -> dict | None:
    """Build Discord dispatch_config from a discord: client_id.

    Extracts the Discord channel ID and looks up the bot token from
    IntegrationSetting DB cache or environment variables.
    """
    import os

    if not client_id.startswith("discord:"):
        return None
    channel_id = client_id.removeprefix("discord:")
    if not channel_id:
        return None

    token = None
    try:
        token = get_setting("discord", "DISCORD_TOKEN")
    except Exception:
        pass
    if not token:
        token = os.environ.get("DISCORD_TOKEN")

    if not token:
        logger.debug("Cannot resolve Discord dispatch_config: missing DISCORD_TOKEN")
        return None

    return {"channel_id": channel_id, "token": token}


def _claims_user_id(recipient_user_id: str) -> bool:
    """Discord user ids are numeric snowflakes."""
    return recipient_user_id.isdigit()


register_integration(IntegrationMeta(
    integration_type="discord",
    client_id_prefix="discord:",
    user_attribution=_user_attribution,
    resolve_display_names=_resolve_display_names,
    resolve_dispatch_config=_resolve_dispatch_config,
    claims_user_id=_claims_user_id,
))

register_hook("after_tool_call", _on_after_tool_call)
register_hook("after_tool_call", _on_audit_tool_call)
register_hook("after_response", _on_after_response)
