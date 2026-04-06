"""Slack Block Kit action handlers for tool approval buttons.

Handles button clicks from Block Kit messages sent by
SlackDispatcher.request_approval().

Button actions:
  - approve_tool_call: Approve once + session-scoped allow for this conversation
  - deny_tool_call: Deny the request
  - allow_rule_always: Approve + create permanent bot-scoped allow rule
  - allow_rule_N: Approve + create rule from suggestion (bot or global scope)
"""
import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)


def register_approval_handlers(app) -> None:
    """Register Slack Bolt action handlers for approval buttons."""

    @app.action("approve_tool_call")
    async def handle_approve(ack, body, respond):
        """Approve once — also grants session-scoped allow for this conversation."""
        await ack()
        approval_id = body["actions"][0]["value"]
        user_id = body.get("user", {}).get("id", "unknown")
        await _decide_and_update(
            approval_id, approved=True, decided_by=f"slack:{user_id}",
            respond=respond, body=body,
        )

    @app.action("deny_tool_call")
    async def handle_deny(ack, body, respond):
        await ack()
        approval_id = body["actions"][0]["value"]
        user_id = body.get("user", {}).get("id", "unknown")
        await _decide_and_update(
            approval_id, approved=False, decided_by=f"slack:{user_id}",
            respond=respond, body=body,
        )

    @app.action("allow_rule_always")
    async def handle_allow_always(ack, body, respond):
        """Approve + create a permanent bot-scoped allow rule (no conditions)."""
        await ack()
        raw = body["actions"][0]["value"]
        data = json.loads(raw)
        approval_id = data["approval_id"]
        bot_id = data["bot_id"]
        tool_name = data["tool_name"]
        scope = data.get("scope", "bot")
        label = data.get("label", f"Allow {tool_name}")
        user_id = body.get("user", {}).get("id", "unknown")

        ok = await _decide_with_rule(
            approval_id,
            decided_by=f"slack:{user_id}",
            create_rule={
                "tool_name": tool_name,
                "conditions": {},
                "scope": scope,
            },
        )
        scope_text = " (all bots)" if scope == "global" else f" for `{bot_id}`"
        if ok:
            await _update_message(
                respond, body,
                f":white_check_mark: *Allowed* `{tool_name}`{scope_text} by <@{user_id}>",
            )
        elif ok is None:
            await _update_message(respond, body, ":warning: Approval already resolved.")
        else:
            await _update_message(respond, body, ":x: Failed to process approval.")

    @app.action("pin_capability")
    async def handle_pin_capability(ack, body, respond):
        """Allow + permanently pin the capability to the bot's carapace list."""
        await ack()
        raw = body["actions"][0]["value"]
        data = json.loads(raw)
        approval_id = data["approval_id"]
        capability_id = data["capability_id"]
        capability_name = data.get("capability_name", capability_id)
        user_id = body.get("user", {}).get("id", "unknown")

        ok = await _decide_with_pin(
            approval_id,
            decided_by=f"slack:{user_id}",
            capability_id=capability_id,
        )
        if ok:
            await _update_message(
                respond, body,
                f":white_check_mark: *Allowed & pinned* _{capability_name}_ by <@{user_id}>",
            )
        elif ok is None:
            await _update_message(respond, body, ":warning: Approval already resolved.")
        else:
            await _update_message(respond, body, ":x: Failed to process approval.")

    # Dynamic rule suggestion buttons: allow_rule_0, allow_rule_1, ...
    @app.action(re.compile(r"^allow_rule_\d+$"))
    async def handle_allow_rule(ack, body, respond):
        await ack()
        raw = body["actions"][0]["value"]
        data = json.loads(raw)
        approval_id = data["approval_id"]
        bot_id = data["bot_id"]
        tool_name = data["tool_name"]
        conditions = data.get("conditions", {})
        scope = data.get("scope", "bot")
        label = data.get("label", tool_name)
        user_id = body.get("user", {}).get("id", "unknown")

        ok = await _decide_with_rule(
            approval_id,
            decided_by=f"slack:{user_id}",
            create_rule={
                "tool_name": tool_name,
                "conditions": conditions,
                "scope": scope,
            },
        )
        scope_text = " (all bots)" if scope == "global" else f" for `{bot_id}`"
        if ok:
            await _update_message(
                respond, body,
                f":white_check_mark: *Approved* + rule created: *{label}*{scope_text} by <@{user_id}>",
            )
        elif ok is None:
            await _update_message(respond, body, ":warning: Approval already resolved.")
        else:
            await _update_message(respond, body, ":x: Failed to process approval.")


async def _decide_and_update(
    approval_id: str, *, approved: bool, decided_by: str, respond, body,
) -> None:
    """Decide and update the Slack message to remove buttons."""
    user_id = decided_by.split(":")[-1]
    verdict = "Approved" if approved else "Denied"
    emoji = ":white_check_mark:" if approved else ":no_entry_sign:"

    ok = await _decide(approval_id, approved=approved, decided_by=decided_by)
    if ok:
        suffix = " (this run)" if approved else ""
        await _update_message(respond, body, f"{emoji} *{verdict}{suffix}* by <@{user_id}>")
    elif ok is None:
        await _update_message(respond, body, ":warning: Approval already resolved.")
    else:
        await _update_message(respond, body, ":x: Failed to process approval.")


async def _decide(approval_id: str, *, approved: bool, decided_by: str) -> bool | None:
    """Call the agent server's approval decide endpoint.
    Returns True on success, None on 409 (already resolved), False on error.
    """
    from slack_settings import AGENT_BASE_URL, API_KEY

    url = f"{AGENT_BASE_URL}/api/v1/approvals/{approval_id}/decide"
    payload = {"approved": approved, "decided_by": decided_by}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            if r.status_code == 200:
                return True
            elif r.status_code == 409:
                return None
            else:
                logger.error("Approval decide failed: %d %s", r.status_code, r.text)
                return False
    except Exception:
        logger.exception("Failed to decide approval %s", approval_id)
        return False


async def _decide_with_pin(
    approval_id: str, *, decided_by: str, capability_id: str,
) -> bool | None:
    """Approve + pin the capability to the bot's carapace list."""
    from slack_settings import AGENT_BASE_URL, API_KEY

    url = f"{AGENT_BASE_URL}/api/v1/approvals/{approval_id}/decide"
    payload = {
        "approved": True,
        "decided_by": decided_by,
        "pin_capability": capability_id,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            if r.status_code == 200:
                return True
            elif r.status_code == 409:
                return None
            else:
                logger.error("Approval decide+pin failed: %d %s", r.status_code, r.text)
                return False
    except Exception:
        logger.exception("Failed to decide+pin approval %s", approval_id)
        return False


async def _decide_with_rule(
    approval_id: str, *, decided_by: str, create_rule: dict,
) -> bool | None:
    """Approve + create an allow rule in a single call."""
    from slack_settings import AGENT_BASE_URL, API_KEY

    url = f"{AGENT_BASE_URL}/api/v1/approvals/{approval_id}/decide"
    payload = {
        "approved": True,
        "decided_by": decided_by,
        "create_rule": create_rule,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            if r.status_code == 200:
                return True
            elif r.status_code == 409:
                return None
            else:
                logger.error("Approval decide+rule failed: %d %s", r.status_code, r.text)
                return False
    except Exception:
        logger.exception("Failed to decide+rule approval %s", approval_id)
        return False


async def _update_message(respond, body, text: str) -> None:
    """Replace the original approval message with a resolved status (no buttons)."""
    original_blocks = body.get("message", {}).get("blocks", [])
    updated_blocks = [b for b in original_blocks if b.get("type") != "actions"]
    updated_blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
    })

    try:
        await respond(blocks=updated_blocks, text=text, replace_original=True)
    except Exception:
        logger.exception("Failed to update approval message")
