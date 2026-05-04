"""Reaction-driven intents.

Native Slack bot affordance: users can drive server actions by reacting
to messages. The bot's own messages carry structured context (approval
buttons, pinned-widget envelopes, …) that make intent inference cheap —
we parse the message's existing blocks rather than maintain a
reaction→resource map out-of-band.

Current mapping (extend as new intents land):

  :+1: / :thumbsup:      → (a) approve a pending tool / capability
                           approval if the message *is* an approval block,
                           else (b) record turn feedback (vote=up).
  :-1: / :thumbsdown:    → record turn feedback (vote=down).

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
DOWN_REACTIONS = frozenset({"-1", "thumbsdown"})

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
        # Try the approval path first — only when the message *is* an
        # approval block does the approve semantics apply. If not, fall
        # through and treat the :+1: as a turn-feedback vote.
        approval_id = await _extract_approval_id(client, channel, ts)
        if approval_id:
            await _handle_approve_reaction(
                client, channel, ts, user_id, approval_id=approval_id,
            )
            return
        await _handle_feedback_reaction(channel, ts, user_id, vote="up")
        return

    if reaction in DOWN_REACTIONS:
        await _handle_feedback_reaction(channel, ts, user_id, vote="down")
        return

    logger.debug("reaction_added unmapped: %s on %s/%s", reaction, channel, ts)


async def on_reaction_removed_for_tests(event: dict, client) -> None:
    """The reaction_removed dispatch — clears a Slack-side feedback vote."""
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

    if reaction in APPROVE_REACTIONS or reaction in DOWN_REACTIONS:
        await _clear_feedback_reaction(channel, ts, user_id)
        return


def register_reaction_handlers(app) -> None:
    """Register Bolt reaction handlers."""

    @app.event("reaction_added")
    async def on_reaction_added(event, client):
        await on_reaction_added_for_tests(event, client)

    @app.event("reaction_removed")
    async def on_reaction_removed(event, client):
        await on_reaction_removed_for_tests(event, client)

    @app.action("turn_feedback_up")
    async def on_turn_feedback_up(ack, body):
        await ack()
        await _handle_feedback_button(body, vote="up")

    @app.action("turn_feedback_down")
    async def on_turn_feedback_down(ack, body):
        await ack()
        await _handle_feedback_button(body, vote="down")

    @app.action("turn_feedback_menu")
    async def on_turn_feedback_menu(ack, body, client):
        await ack()
        await _handle_feedback_menu(body, client)


async def _handle_feedback_button(body: dict, *, vote: str) -> None:
    channel = (body.get("channel") or {}).get("id")
    message = body.get("message") or {}
    ts = message.get("ts")
    user_id = (body.get("user") or {}).get("id") or "unknown"
    if not channel or not ts:
        return
    await _handle_feedback_reaction(channel, ts, user_id, vote=vote)


async def _handle_feedback_menu(body: dict, client) -> None:
    action = (body.get("actions") or [{}])[0]
    selected = action.get("selected_option") or {}
    vote = selected.get("value")
    if vote not in {"up", "down"}:
        return

    channel = (body.get("channel") or {}).get("id")
    message = body.get("message") or {}
    ts = message.get("ts")
    user_id = (body.get("user") or {}).get("id") or "unknown"
    if not channel or not ts:
        return

    recorded = await _handle_feedback_reaction(channel, ts, user_id, vote=vote)
    if recorded:
        await _mark_feedback_on_message(client, channel, ts, message, vote=vote)


async def _mark_feedback_on_message(
    client, channel: str, ts: str, message: dict, *, vote: str,
) -> None:
    blocks = [
        block for block in (message.get("blocks") or [])
        if block.get("block_id") != "turn_feedback_status"
    ]
    label = ":thumbsup:" if vote == "up" else ":thumbsdown:"
    blocks.append({
        "type": "context",
        "block_id": "turn_feedback_status",
        "elements": [
            {"type": "mrkdwn", "text": f"Feedback recorded: {label}"},
        ],
    })
    try:
        await client.chat_update(
            channel=channel,
            ts=ts,
            text=message.get("text") or "",
            blocks=blocks,
        )
    except Exception:
        logger.debug("failed to mark Slack feedback state", exc_info=True)


async def _handle_approve_reaction(
    client, channel: str, ts: str, user_id: str, *, approval_id: str,
) -> None:
    """Approve a pending approval that this message represents."""
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

    Approval messages are posted by ``SlackApprovalDelivery``
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


async def _handle_feedback_reaction(
    channel: str, ts: str, user_id: str, *, vote: str,
) -> bool:
    """POST a feedback vote keyed by the slack ``(channel, ts)`` ref.

    The server resolves the ref to the owning Spindrel turn and persists
    an anonymous ``turn_feedback`` row (``user_id=NULL`` because there is
    no Slack→Spindrel user mapping yet). 404 is silent — reactions on
    non-bot messages and uncatalogued history get dropped at debug level.
    """
    from slack_settings import AGENT_BASE_URL, API_KEY

    url = f"{AGENT_BASE_URL}/api/v1/messages/feedback/by-slack-reaction"
    payload = {
        "slack_ts": ts,
        "slack_channel": channel,
        "slack_user_id": user_id,
        "vote": vote,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
    except Exception:
        logger.exception("feedback reaction post failed")
        return False

    if r.status_code == 404:
        logger.debug(
            "feedback reaction unmapped channel=%s ts=%s vote=%s",
            channel, ts, vote,
        )
        return False
    if r.status_code >= 400:
        logger.warning(
            "feedback reaction returned %d: %s",
            r.status_code, r.text,
        )
        return False
    return True


async def _clear_feedback_reaction(
    channel: str, ts: str, user_id: str,
) -> None:
    """Mirror of `_handle_feedback_reaction` for ``reaction_removed``."""
    from slack_settings import AGENT_BASE_URL, API_KEY

    url = f"{AGENT_BASE_URL}/api/v1/messages/feedback/by-slack-reaction/clear"
    payload = {
        "slack_ts": ts,
        "slack_channel": channel,
        "slack_user_id": user_id,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
    except Exception:
        logger.exception("clear feedback reaction post failed")
        return

    if r.status_code >= 400 and r.status_code != 204:
        logger.debug(
            "clear feedback reaction returned %d for channel=%s ts=%s",
            r.status_code, channel, ts,
        )
