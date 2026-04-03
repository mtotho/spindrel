"""Block Kit action handlers for channel creation approval buttons.

Handles Approve/Deny button clicks from the prompts posted by channel_approval.py.
"""
import json
import logging

logger = logging.getLogger(__name__)


def register_channel_approval_handlers(app) -> None:
    """Register Slack Bolt action handlers for channel approval buttons."""

    @app.action("approve_channel_create")
    async def handle_approve(ack, body, respond):
        await ack()
        raw = body["actions"][0]["value"]
        data = json.loads(raw)
        channel = data["channel"]
        bot_id = data["bot_id"]
        user_id = body.get("user", {}).get("id", "unknown")

        from channel_approval import _set_approval
        from agent_client import ensure_channel
        from session_helpers import slack_client_id

        # Create the channel on the agent server
        client_id = slack_client_id(channel)
        result = await ensure_channel(client_id, bot_id)
        if result:
            _set_approval(channel, "approved")
            await _update_message(
                respond, body,
                f":white_check_mark: *Channel approved* by <@{user_id}> — now connected with bot `{bot_id}`.",
            )
        else:
            await _update_message(
                respond, body,
                ":x: Failed to create channel on the agent server. Try again or check server logs.",
            )

    @app.action("deny_channel_create")
    async def handle_deny(ack, body, respond):
        await ack()
        raw = body["actions"][0]["value"]
        data = json.loads(raw)
        channel = data["channel"]
        user_id = body.get("user", {}).get("id", "unknown")

        from channel_approval import _set_approval
        _set_approval(channel, "denied")
        await _update_message(
            respond, body,
            f":no_entry_sign: *Channel denied* by <@{user_id}> — messages will be ignored. @mention the bot to re-prompt.",
        )


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
        logger.exception("Failed to update channel approval message")
