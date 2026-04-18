"""Reaction-driven intents.

Native Slack bot affordance: users can drive server actions by reacting
to messages. The bot's own messages carry structured context (approval
buttons, pinned-widget envelopes, …) that make intent inference cheap —
we parse the message's existing blocks rather than maintain a
reaction→resource map out-of-band.

Current mapping (extend as new intents land):

  :+1: / :thumbsup:      → approve a pending tool / capability approval

Unknown reactions are ignored silently; logging stays at ``debug`` so
noisy channels don't flood the bot log.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

APPROVE_REACTIONS = frozenset({"+1", "thumbsup"})

# Resolved once via auth.test; we skip reactions the bot itself posts
# (hourglass on turn start, tool-type emojis, checkmark on completion).
_own_bot_user_id: str | None = None


async def _resolve_own_bot_user_id(client) -> str | None:
    global _own_bot_user_id
    if _own_bot_user_id is not None:
        return _own_bot_user_id
    try:
        resp = await client.auth_test()
    except Exception:
        logger.debug("auth.test failed in reaction handler", exc_info=True)
        return None
    if resp and resp.get("ok"):
        _own_bot_user_id = resp.get("user_id") or ""
    return _own_bot_user_id or None


async def on_reaction_added_for_tests(event: dict, client) -> None:
    """The reaction_added dispatch logic, exposed for direct unit-testing.

    Bolt registers ``register_reaction_handlers`` which wraps this function
    as an event listener; the body lives here so tests can call it without
    a live Bolt app.
    """
    reaction = (event.get("reaction") or "").lower()
    item = event.get("item") or {}
    if item.get("type") != "message":
        return

    channel = item.get("channel")
    ts = item.get("ts")
    user_id = event.get("user") or "unknown"
    if not channel or not ts:
        return

    own = await _resolve_own_bot_user_id(client)
    if own and user_id == own:
        return

    if reaction in APPROVE_REACTIONS:
        await _handle_approve_reaction(client, channel, ts, user_id)
        return

    logger.debug("reaction_added unmapped: %s on %s/%s", reaction, channel, ts)


def register_reaction_handlers(app) -> None:
    """Register Bolt reaction handlers."""

    @app.event("reaction_added")
    async def on_reaction_added(event, client):
        await on_reaction_added_for_tests(event, client)


async def _handle_approve_reaction(
    client, channel: str, ts: str, user_id: str,
) -> None:
    """Approve a pending approval that this message represents."""
    approval_id = await _extract_approval_id(client, channel, ts)
    if not approval_id:
        logger.debug(
            "approve reaction on non-approval message channel=%s ts=%s",
            channel, ts,
        )
        return

    ok = await _decide_approval(approval_id, user_id)
    if not ok:
        return

    try:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=(
                f":white_check_mark: Approved by <@{user_id}> via reaction."
            ),
        )
    except Exception:
        logger.debug("failed to post approval-by-reaction confirmation", exc_info=True)


async def _extract_approval_id(client, channel: str, ts: str) -> str | None:
    """Look up the approval_id embedded in an approval message's buttons.

    Approval messages are posted by ``SlackRenderer._handle_approval_requested``
    and their action buttons carry ``value`` = either the bare approval_id
    (approve / deny buttons) or a JSON blob containing ``approval_id`` (rule
    / pin buttons). We fetch the message, scan the action blocks, and return
    the first approval_id we find.
    """
    try:
        resp = await client.conversations_history(
            channel=channel, latest=ts, inclusive=True, limit=1,
        )
    except Exception:
        logger.debug("conversations_history failed", exc_info=True)
        return None
    if not resp or not resp.get("ok"):
        return None

    messages = resp.get("messages") or []
    if not messages:
        return None

    for block in messages[0].get("blocks") or []:
        if block.get("type") != "actions":
            continue
        for element in block.get("elements") or []:
            if element.get("type") != "button":
                continue
            value = element.get("value") or ""
            approval_id = _approval_id_from_button_value(value)
            if approval_id:
                return approval_id
    return None


def _approval_id_from_button_value(value: str) -> str | None:
    """Return the approval_id from a button's value field, or None."""
    if not value:
        return None
    # Bare UUID form used by approve_tool_call / deny_tool_call.
    if "{" not in value:
        return value
    try:
        data: Any = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        approval_id = data.get("approval_id")
        if isinstance(approval_id, str):
            return approval_id
    return None


async def _decide_approval(approval_id: str, user_id: str) -> bool:
    """POST /approvals/{id}/decide with approved=True.

    Returns True on 200. 409 (already resolved) is silent — user reacted
    to a stale message. 4xx/5xx log and return False.
    """
    from slack_settings import AGENT_BASE_URL, API_KEY

    url = f"{AGENT_BASE_URL}/api/v1/approvals/{approval_id}/decide"
    payload = {"approved": True, "decided_by": f"slack:{user_id}"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
    except Exception:
        logger.exception("decide approval %s failed", approval_id)
        return False

    if r.status_code == 200:
        return True
    if r.status_code == 409:
        return False
    logger.warning(
        "decide approval %s returned %d: %s",
        approval_id, r.status_code, r.text,
    )
    return False
