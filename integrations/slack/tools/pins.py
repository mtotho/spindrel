"""Tool: slack_pin_message — pin an existing Slack message to the channel."""
from __future__ import annotations

import json

from integrations.sdk import current_channel_id, register_tool as register

from integrations.slack.web_api import (
    SlackApiError,
    resolve_slack_channel_id,
    slack_call,
)


@register({
    "type": "function",
    "function": {
        "name": "slack_pin_message",
        "description": (
            "Pin an existing Slack message to the current Slack channel. The message "
            "must have been posted to this channel — use a Slack message ts "
            "(format '1700000000.123456'). ONLY works from Slack-backed channels."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message_ts": {
                    "type": "string",
                    "description": "Slack message ts to pin, e.g. '1700000000.123456'.",
                },
            },
            "required": ["message_ts"],
        },
    },
}, required_integrations=frozenset({"slack"}), requires_channel_context=True)
async def slack_pin_message(message_ts: str) -> str:
    channel_uuid = current_channel_id.get()
    if channel_uuid is None:
        return json.dumps({"error": "no channel in current context"})
    try:
        slack_channel = await resolve_slack_channel_id(channel_uuid)
    except SlackApiError as exc:
        return json.dumps({"error": str(exc)})

    body = {"channel": slack_channel, "timestamp": message_ts}
    try:
        await slack_call("pins.add", body=body)
    except SlackApiError as exc:
        return json.dumps({"error": str(exc)})

    return json.dumps({"ok": True, "pinned_ts": message_ts, "channel": slack_channel})
