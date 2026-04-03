"""Channel creation approval gate for Slack.

When SLACK_REQUIRE_CHANNEL_APPROVAL is enabled, messages from unknown Slack
channels trigger a Block Kit approval prompt instead of auto-creating a channel.
"""
import json
import logging

from state import get_global_setting, set_global_setting

logger = logging.getLogger(__name__)


def _get_approvals() -> dict[str, str]:
    """Return the channel_approvals dict from global settings."""
    return get_global_setting("channel_approvals") or {}


def _set_approval(channel_id: str, status: str) -> None:
    """Set the approval status for a Slack channel."""
    approvals = _get_approvals()
    approvals[channel_id] = status
    set_global_setting("channel_approvals", approvals)


async def check_or_prompt_approval(
    channel: str,
    bot_id: str,
    client,
    mentioned: bool,
) -> bool:
    """Check approval state and prompt if needed. Returns True if allowed to proceed.

    States:
      - "approved" → return True
      - "denied" + not mentioned → return False (silent)
      - "denied" + mentioned → re-post prompt, set "pending", return False
      - "pending" → return False (already waiting)
      - unknown → post prompt, set "pending", return False
    """
    approvals = _get_approvals()
    status = approvals.get(channel)

    if status == "approved":
        return True

    if status == "denied":
        if not mentioned:
            return False
        # @mention in a denied channel → re-prompt
        await _post_approval_prompt(channel, bot_id, client)
        _set_approval(channel, "pending")
        return False

    if status == "pending":
        return False

    # Unknown channel → post prompt
    await _post_approval_prompt(channel, bot_id, client)
    _set_approval(channel, "pending")
    return False


async def _post_approval_prompt(channel: str, bot_id: str, client) -> None:
    """Post a Block Kit approval prompt to the Slack channel."""
    value = json.dumps({"channel": channel, "bot_id": bot_id})
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*New channel detected* — `{channel}`\n\n"
                    f"A message was received from this channel, which isn't currently "
                    f"connected. Approve to create a channel with bot `{bot_id}`, "
                    f"or deny to ignore messages from this channel."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "approve_channel_create",
                    "value": value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deny"},
                    "style": "danger",
                    "action_id": "deny_channel_create",
                    "value": value,
                },
            ],
        },
    ]
    try:
        await client.chat_postMessage(
            channel=channel,
            text=f"New channel detected — approve or deny connection for bot `{bot_id}`.",
            blocks=blocks,
        )
    except Exception:
        logger.exception("Failed to post channel approval prompt to %s", channel)
