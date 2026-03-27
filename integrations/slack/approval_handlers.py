"""Slack Block Kit action handlers for tool approval buttons.

Handles approve_tool_call and deny_tool_call button clicks from Block Kit
messages sent by SlackDispatcher.request_approval().
"""
import logging

import httpx

logger = logging.getLogger(__name__)


def register_approval_handlers(app) -> None:
    """Register Slack Bolt action handlers for approval buttons."""

    @app.action("approve_tool_call")
    async def handle_approve(ack, body, say):
        await ack()
        approval_id = body["actions"][0]["value"]
        user_id = body.get("user", {}).get("id", "unknown")
        await _decide(approval_id, approved=True, decided_by=f"slack:{user_id}", say=say)

    @app.action("deny_tool_call")
    async def handle_deny(ack, body, say):
        await ack()
        approval_id = body["actions"][0]["value"]
        user_id = body.get("user", {}).get("id", "unknown")
        await _decide(approval_id, approved=False, decided_by=f"slack:{user_id}", say=say)


async def _decide(approval_id: str, *, approved: bool, decided_by: str, say) -> None:
    """Call the agent server's approval decide endpoint."""
    from slack_settings import AGENT_SERVER_URL, API_KEY

    url = f"{AGENT_SERVER_URL}/api/v1/approvals/{approval_id}/decide"
    payload = {"approved": approved, "decided_by": decided_by}
    verdict = "approved" if approved else "denied"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            if r.status_code == 200:
                await say(f":white_check_mark: Tool call *{verdict}* by <@{decided_by.split(':')[-1]}>")
            elif r.status_code == 409:
                await say(f":warning: Approval already resolved.")
            else:
                logger.error("Approval decide failed: %d %s", r.status_code, r.text)
                await say(f":x: Failed to {verdict} tool call: {r.text[:200]}")
    except Exception:
        logger.exception("Failed to decide approval %s", approval_id)
        await say(f":x: Error processing approval decision.")
