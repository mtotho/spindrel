"""Slack integration hooks — metadata + lifecycle.

Metadata (registered at import):
  - user_attribution, resolve_display_names, client_id_prefix

Lifecycle hooks:
  - after_tool_call: emoji reactions + audit channel logging
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
    """Return Slack payload fields for user identity (username, icon_emoji, icon_url).

    Same pattern as bot_attribution() — uses chat:write.customize scope.
    Accepts a User ORM object (or any object with display_name, integration_config, avatar_url).
    """
    attrs: dict = {}
    if user.display_name:
        attrs["username"] = user.display_name
    slack_cfg = (user.integration_config or {}).get("slack", {})
    if slack_cfg.get("icon_emoji"):
        attrs["icon_emoji"] = slack_cfg["icon_emoji"]
    elif user.avatar_url:
        attrs["icon_url"] = user.avatar_url
    return attrs


# ---------------------------------------------------------------------------
# Display name resolution (moved from api_v1_admin/channels.py)
# ---------------------------------------------------------------------------

_slack_name_cache: dict[str, tuple[str, float]] = {}
_SLACK_NAME_CACHE_TTL = 600  # 10 minutes


async def _fetch_slack_name(client: httpx.AsyncClient, token: str, slack_id: str) -> str | None:
    """Fetch a single Slack channel name, using TTL cache."""
    cached = _slack_name_cache.get(slack_id)
    if cached and (_time.monotonic() - cached[1]) < _SLACK_NAME_CACHE_TTL:
        return cached[0]
    try:
        r = await client.get(
            "https://slack.com/api/conversations.info",
            params={"channel": slack_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        data = r.json()
        if data.get("ok"):
            info = data.get("channel") or {}
            name = info.get("name_normalized") or info.get("name")
            if name:
                _slack_name_cache[slack_id] = (name, _time.monotonic())
                return name
    except Exception:
        pass
    return None


async def _resolve_display_names(channels: list) -> dict:
    """Resolve display names for Slack channels. Returns {channel.id: '#name'}."""
    import asyncio
    import os

    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return {}

    slack_channels = [ch for ch in channels if ch.integration == "slack"]
    if not slack_channels:
        return {}

    result: dict = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        async def _resolve_one(ch):
            if not ch.client_id:
                return
            slack_id = ch.client_id.removeprefix("slack:")
            name = await _fetch_slack_name(client, token, slack_id)
            if name:
                result[ch.id] = f"#{name}"

        await asyncio.gather(*[_resolve_one(ch) for ch in slack_channels])
    return result


# ---------------------------------------------------------------------------
# Lifecycle hooks: Slack emoji reactions as tool indicators
# ---------------------------------------------------------------------------

# Map tool name patterns to emoji reactions
_TOOL_EMOJI: list[tuple[str, str]] = [
    ("web_search", "mag"),
    ("search", "mag"),
    ("exec", "computer"),
    ("shell", "computer"),
    ("sandbox", "computer"),
    ("save_memory", "brain"),
    ("memory", "brain"),
    ("read_", "eyes"),
    ("write_", "pencil2"),
    ("edit_", "pencil2"),
    ("delegate", "speech_balloon"),
]
_DEFAULT_TOOL_EMOJI = "gear"
_WORKING_EMOJI = "hourglass_flowing_sand"
_DONE_EMOJI = "white_check_mark"

# Track which reactions we've added per correlation_id so we can clean up.
# Each entry is (reactions_set, created_timestamp) — stale entries are evicted.
_active_reactions: dict[str, tuple[set[str], float]] = {}
_REACTION_TTL = 600  # 10 minutes — evict stale entries from cancelled/errored turns


def _evict_stale_reactions() -> None:
    """Remove entries older than _REACTION_TTL to prevent unbounded growth."""
    now = _time.monotonic()
    stale = [k for k, (_, ts) in _active_reactions.items() if now - ts > _REACTION_TTL]
    for k in stale:
        _active_reactions.pop(k, None)


def _get_slack_ref() -> tuple[str | None, str | None, str | None]:
    """Read Slack channel_id, message_ts, token from current dispatch context.

    Returns the user's message timestamp (for reactions) — falls back to
    thread_ts if message_ts isn't available.
    """
    if current_dispatch_type.get() != "slack":
        return None, None, None
    cfg = current_dispatch_config.get() or {}
    ts = cfg.get("message_ts") or cfg.get("thread_ts")
    return cfg.get("channel_id"), ts, cfg.get("token")


def _emoji_for_tool(tool_name: str) -> str:
    """Pick an emoji based on tool name."""
    lower = tool_name.lower()
    for pattern, emoji in _TOOL_EMOJI:
        if pattern in lower:
            return emoji
    return _DEFAULT_TOOL_EMOJI


_react_http = httpx.AsyncClient(timeout=5.0)


async def _slack_react(token: str, channel: str, timestamp: str, emoji: str, *, remove: bool = False) -> None:
    """Add or remove a Slack reaction. Fire-and-forget, errors swallowed."""
    method = "reactions.remove" if remove else "reactions.add"
    try:
        r = await _react_http.post(
            f"https://slack.com/api/{method}",
            json={"channel": channel, "timestamp": timestamp, "name": emoji},
            headers={"Authorization": f"Bearer {token}"},
        )
        data = r.json()
        # already_reacted / no_reaction are expected races, not errors
        if not data.get("ok") and data.get("error") not in ("already_reacted", "no_reaction"):
            level = logging.WARNING if data.get("error") == "missing_scope" else logging.DEBUG
            logger.log(level, "Slack %s failed: %s", method, data.get("error"))
    except Exception:
        logger.debug("Slack %s request failed", method, exc_info=True)


async def _on_after_tool_call(ctx: HookContext, **kwargs) -> None:
    """Add emoji reaction for the tool that just ran."""
    channel_id, thread_ts, token = _get_slack_ref()
    if not all((channel_id, thread_ts, token)):
        return

    corr_key = str(ctx.correlation_id) if ctx.correlation_id else None
    if not corr_key:
        return

    _evict_stale_reactions()

    tool_name = ctx.extra.get("tool_name", "")
    emoji = _emoji_for_tool(tool_name)

    # Track reactions for cleanup
    if corr_key not in _active_reactions:
        _active_reactions[corr_key] = (set(), _time.monotonic())
        # Add working indicator on first tool call
        await _slack_react(token, channel_id, thread_ts, _WORKING_EMOJI)
        _active_reactions[corr_key][0].add(_WORKING_EMOJI)

    if emoji not in _active_reactions[corr_key][0]:
        await _slack_react(token, channel_id, thread_ts, emoji)
        _active_reactions[corr_key][0].add(emoji)


async def _on_after_response(ctx: HookContext, **kwargs) -> None:
    """Remove working indicator and add done checkmark."""
    channel_id, thread_ts, token = _get_slack_ref()
    if not all((channel_id, thread_ts, token)):
        return

    corr_key = str(ctx.correlation_id) if ctx.correlation_id else None
    if not corr_key:
        return

    entry = _active_reactions.pop(corr_key, None)
    if not entry:
        return  # no tool calls were made, skip reactions entirely
    reactions = entry[0]

    # Remove working indicator
    if _WORKING_EMOJI in reactions:
        await _slack_react(token, channel_id, thread_ts, _WORKING_EMOJI, remove=True)

    # Add done checkmark
    await _slack_react(token, channel_id, thread_ts, _DONE_EMOJI)


# ---------------------------------------------------------------------------
# Lifecycle hooks: Audit channel logging
# ---------------------------------------------------------------------------

_STATE_FILE = Path(__file__).parent / "slack_state.json"
_audit_channel_cache: tuple[str | None, float] = (None, 0.0)
_AUDIT_CACHE_TTL = 30.0  # re-read file every 30s


def _get_audit_channel() -> str | None:
    """Read audit_channel from slack_state.json. Cached with TTL."""
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
    """Post tool usage to the configured audit Slack channel."""
    audit_channel = _get_audit_channel()
    if not audit_channel:
        return
    # Get token from dispatch context or env
    _, _, token = _get_slack_ref()
    if not token:
        import os
        token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return

    tool = ctx.extra.get("tool_name", "?")
    ms = ctx.extra.get("duration_ms") or 0
    bot = ctx.bot_id or "?"
    text = f"`{tool}` by `{bot}` ({ms}ms)"

    try:
        await _react_http.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": audit_channel, "text": text},
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception:
        logger.debug("Audit post failed", exc_info=True)


# ---------------------------------------------------------------------------
# Register at import time
# ---------------------------------------------------------------------------

def _resolve_dispatch_config(client_id: str) -> dict | None:
    """Build Slack dispatch_config from a slack: client_id.

    Extracts the Slack channel ID and looks up the bot token from
    IntegrationSetting DB cache or environment variables.
    """
    import os

    if not client_id.startswith("slack:"):
        return None
    channel_id = client_id.removeprefix("slack:")
    if not channel_id:
        return None

    token = None
    try:
        token = get_setting("slack", "SLACK_BOT_TOKEN")
    except Exception:
        pass
    if not token:
        token = os.environ.get("SLACK_BOT_TOKEN")

    if not token:
        logger.debug("Cannot resolve Slack dispatch_config: missing SLACK_BOT_TOKEN")
        return None

    return {"channel_id": channel_id, "token": token}


# ---------------------------------------------------------------------------
# Thread mirroring hooks
# ---------------------------------------------------------------------------


def _apply_thread_ref(target, ref: dict):
    """Rewrite a SlackTarget so outbound posts land in the Slack thread.

    ``ref`` shape — ``{"channel": "C123", "thread_ts": "1700000000.001"}``.
    Matches ``Session.integration_thread_refs["slack"]`` stored by
    ``POST /messages/{id}/thread`` and the inbound-thread resolver.
    """
    from dataclasses import replace
    from integrations.slack.target import SlackTarget

    if not isinstance(target, SlackTarget):
        return target
    thread_ts = ref.get("thread_ts")
    if not thread_ts:
        return target
    return replace(target, thread_ts=thread_ts, reply_in_thread=True)


def _build_thread_ref_from_message(metadata: dict) -> dict | None:
    """Return a Slack thread ref dict if ``metadata`` identifies a Slack msg.

    The persistence path stamps ``slack_ts`` + ``slack_channel`` onto the
    Message on both inbound (``message_handlers.dispatch``) and outbound
    (``outbox_drainer`` → ``DeliveryReceipt.external_id``). When threading
    off an assistant Message that itself is a reply inside an existing
    Slack thread, fall back to the message's own ``slack_thread_ts`` so the
    new Spindrel thread binds to the SAME Slack thread (Slack threads are
    flat — no nested threads).
    """
    channel = metadata.get("slack_channel") or metadata.get("channel_external_id")
    if not channel:
        return None
    thread_ts = metadata.get("slack_thread_ts") or metadata.get("slack_ts")
    if not thread_ts:
        return None
    return {"channel": channel, "thread_ts": thread_ts}


def _extract_thread_ref_from_dispatch(dispatch_config: dict) -> dict | None:
    """Inbound: return the Slack thread ref if ``dispatch_config`` is a reply."""
    thread_ts = dispatch_config.get("thread_ts")
    channel = dispatch_config.get("channel_id")
    if not (thread_ts and channel):
        return None
    return {"channel": channel, "thread_ts": thread_ts}


def _persist_delivery_metadata(metadata: dict, external_id: str, target) -> None:
    """Stamp Slack-side identifiers onto a delivered Message's metadata.

    Called by the outbox drainer after a successful ``chat.postMessage`` so
    that ``_build_thread_ref_from_message`` can reconstruct the thread ref
    when a user later clicks "Reply in thread" on the outbound Message.
    The drainer owns the deep-copy → ``flag_modified`` dance; we just
    mutate the supplied dict in place.
    """
    from integrations.slack.target import SlackTarget

    if not isinstance(target, SlackTarget):
        return
    if not external_id:
        return
    metadata["slack_ts"] = external_id
    metadata["slack_channel"] = target.channel_id
    if target.thread_ts:
        metadata["slack_thread_ts"] = target.thread_ts


def _claims_user_id(recipient_user_id: str) -> bool:
    """Slack user ids start with ``U`` (regular) or ``W`` (enterprise) and are alphanumeric."""
    return recipient_user_id[:1] in ("U", "W") and recipient_user_id.isalnum()


register_integration(IntegrationMeta(
    integration_type="slack",
    client_id_prefix="slack:",
    user_attribution=_user_attribution,
    resolve_display_names=_resolve_display_names,
    resolve_dispatch_config=_resolve_dispatch_config,
    apply_thread_ref=_apply_thread_ref,
    build_thread_ref_from_message=_build_thread_ref_from_message,
    extract_thread_ref_from_dispatch=_extract_thread_ref_from_dispatch,
    persist_delivery_metadata=_persist_delivery_metadata,
    claims_user_id=_claims_user_id,
    attachment_file_id_key="slack_file_id",
))

register_hook("after_tool_call", _on_after_tool_call)
register_hook("after_tool_call", _on_audit_tool_call)
register_hook("after_response", _on_after_response)
