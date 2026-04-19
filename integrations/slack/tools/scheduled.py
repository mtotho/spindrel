"""Tool: slack_schedule_message — post a message to Slack at a future time."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from integrations.sdk import current_channel_id, register_tool as register

from integrations.slack.web_api import (
    SlackApiError,
    resolve_slack_channel_id,
    slack_call,
)

logger = logging.getLogger(__name__)


def _parse_post_at(value: str) -> int:
    """Accept ISO 8601 or epoch seconds; return epoch-seconds int.

    Agents love to emit ISO strings; Slack wants epoch seconds. Normalize
    here so the tool signature stays human-friendly.
    """
    if not value:
        raise ValueError("post_at is required")
    if value.isdigit():
        return int(value)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


@register({
    "type": "function",
    "function": {
        "name": "slack_schedule_message",
        "description": (
            "Schedule a Slack message to be posted to the current Slack channel at "
            "a future time. The message must be in the future (up to 120 days out). "
            "Returns the scheduled_message_id which can be used to cancel before it "
            "fires. ONLY works from Slack-backed channels."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Message body (Slack mrkdwn supported).",
                },
                "post_at": {
                    "type": "string",
                    "description": (
                        "When to post. ISO 8601 timestamp ('2026-05-01T09:00:00Z') "
                        "or epoch seconds as a string ('1746086400')."
                    ),
                },
                "thread_ts": {
                    "type": "string",
                    "description": (
                        "Optional: post into this thread's parent ts (format "
                        "'1700000000.123456')."
                    ),
                },
            },
            "required": ["text", "post_at"],
        },
    },
}, required_integrations=frozenset({"slack"}), requires_channel_context=True)
async def slack_schedule_message(
    text: str,
    post_at: str,
    thread_ts: str | None = None,
) -> str:
    channel_uuid = current_channel_id.get()
    if channel_uuid is None:
        return json.dumps({"error": "no channel in current context"})
    try:
        slack_channel = await resolve_slack_channel_id(channel_uuid)
    except SlackApiError as exc:
        return json.dumps({"error": str(exc)})

    try:
        post_at_epoch = _parse_post_at(post_at)
    except ValueError as exc:
        return json.dumps({"error": f"invalid post_at: {exc}"})

    body: dict = {
        "channel": slack_channel,
        "text": text,
        "post_at": post_at_epoch,
    }
    if thread_ts:
        body["thread_ts"] = thread_ts

    try:
        data = await slack_call("chat.scheduleMessage", body=body)
    except SlackApiError as exc:
        return json.dumps({"error": str(exc)})

    return json.dumps({
        "ok": True,
        "scheduled_message_id": data.get("scheduled_message_id"),
        "post_at": data.get("post_at"),
        "channel": data.get("channel"),
    })
