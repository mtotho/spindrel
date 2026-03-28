"""Slack Block Kit action handlers for tool approval buttons.

Handles approve_tool_call, deny_tool_call, and allow_always_tool_call
button clicks from Block Kit messages sent by SlackDispatcher.request_approval().
"""
import json
import logging

import httpx

logger = logging.getLogger(__name__)


def register_approval_handlers(app) -> None:
    """Register Slack Bolt action handlers for approval buttons."""

    @app.action("approve_tool_call")
    async def handle_approve(ack, body, respond):
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

    @app.action("allow_always_tool_call")
    async def handle_allow_always(ack, body, respond):
        await ack()
        raw = body["actions"][0]["value"]
        data = json.loads(raw)
        approval_id = data["approval_id"]
        bot_id = data["bot_id"]
        tool_name = data["tool_name"]
        user_id = body.get("user", {}).get("id", "unknown")

        # Approve this call
        ok = await _decide(approval_id, approved=True, decided_by=f"slack:{user_id}")
        if ok:
            # Create an allow rule so it never asks again
            await _create_allow_rule(bot_id, tool_name, decided_by=f"slack:{user_id}")
            await _update_message(
                respond, body,
                f":white_check_mark: *Approved* and *always allowed* for `{tool_name}` on `{bot_id}` by <@{user_id}>",
            )
        else:
            await _update_message(respond, body, f":warning: Approval already resolved.")


async def _decide_and_update(
    approval_id: str, *, approved: bool, decided_by: str, respond, body,
) -> None:
    """Decide and update the Slack message to remove buttons."""
    user_id = decided_by.split(":")[-1]
    verdict = "Approved" if approved else "Denied"
    emoji = ":white_check_mark:" if approved else ":no_entry_sign:"

    ok = await _decide(approval_id, approved=approved, decided_by=decided_by)
    if ok:
        await _update_message(respond, body, f"{emoji} *{verdict}* by <@{user_id}>")
    elif ok is None:
        await _update_message(respond, body, f":warning: Approval already resolved.")
    else:
        await _update_message(respond, body, f":x: Failed to process approval.")


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


async def _create_allow_rule(bot_id: str, tool_name: str, *, decided_by: str) -> None:
    """Create an allow policy rule for this bot+tool so it's auto-approved going forward."""
    from slack_settings import AGENT_BASE_URL, API_KEY

    url = f"{AGENT_BASE_URL}/api/v1/tool-policies"
    payload = {
        "bot_id": bot_id,
        "tool_name": tool_name,
        "action": "allow",
        "priority": 50,
        "reason": f"Allowed via Slack by {decided_by}",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            if r.status_code == 201:
                logger.info("Created allow rule for %s/%s via Slack", bot_id, tool_name)
            else:
                logger.error("Failed to create allow rule: %d %s", r.status_code, r.text)
    except Exception:
        logger.exception("Failed to create allow rule for %s/%s", bot_id, tool_name)


async def _update_message(respond, body, text: str) -> None:
    """Replace the original approval message with a resolved status (no buttons)."""
    # Preserve the original context blocks (bot, tool, args) but replace actions
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
