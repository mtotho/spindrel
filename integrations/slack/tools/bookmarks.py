"""Tool: slack_add_bookmark — add a link bookmark to the current channel."""
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
        "name": "slack_add_bookmark",
        "description": (
            "Add a link bookmark to the current Slack channel. Bookmarks appear "
            "in the channel header and persist across sessions. Use this to "
            "surface important resources the channel members should be able to "
            "reach with one click (runbooks, dashboards, docs). ONLY works "
            "from Slack-backed channels."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Human-readable bookmark label.",
                },
                "link": {
                    "type": "string",
                    "description": "The URL the bookmark points to.",
                },
                "emoji": {
                    "type": "string",
                    "description": "Optional emoji shortcode (e.g. ':book:').",
                },
            },
            "required": ["title", "link"],
        },
    },
}, required_integrations=frozenset({"slack"}))
async def slack_add_bookmark(
    title: str,
    link: str,
    emoji: str | None = None,
) -> str:
    channel_uuid = current_channel_id.get()
    if channel_uuid is None:
        return json.dumps({"error": "no channel in current context"})
    try:
        slack_channel = await resolve_slack_channel_id(channel_uuid)
    except SlackApiError as exc:
        return json.dumps({"error": str(exc)})

    body: dict = {
        "channel_id": slack_channel,
        "title": title,
        "type": "link",
        "link": link,
    }
    if emoji:
        body["emoji"] = emoji

    try:
        data = await slack_call("bookmarks.add", body=body)
    except SlackApiError as exc:
        return json.dumps({"error": str(exc)})

    bookmark = data.get("bookmark") or {}
    return json.dumps({
        "ok": True,
        "bookmark_id": bookmark.get("id"),
        "title": bookmark.get("title"),
        "link": bookmark.get("link"),
        "channel": slack_channel,
    })
