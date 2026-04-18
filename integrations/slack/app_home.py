"""App Home tab — the persistent per-user dashboard inside Slack.

When a user clicks on the bot's name in their sidebar, Slack fires
``app_home_opened``. We respond with ``views.publish`` to render a
dashboard-style block layout that gives the user:

  * A summary of what the bot can do
  * The list of Slack channels currently bound to a server-side channel
    (configured via ``SLACK_CHANNELS`` / YAML / admin UI — i.e. known
    bot homes)
  * A "Quick Ask" button that opens a text-entry shortcut

This is the ambient affordance — no slash command needed, users land
here the first time they click the bot's name. The view is a full
redraw each open (Slack recommends this pattern); we don't maintain
per-user state.
"""
from __future__ import annotations

import logging
from typing import Any

from slack_settings import get_slack_config

logger = logging.getLogger(__name__)

_MAX_CHANNEL_ROWS = 15


async def on_app_home_opened_for_tests(event: dict, client) -> None:
    """The app_home_opened handler body — exposed for direct testing."""
    user_id = event.get("user")
    if not user_id:
        return
    # Slack fires both "home" (what we care about) and "messages" (the DM tab).
    if event.get("tab") and event["tab"] != "home":
        return

    view = _build_home_view()
    try:
        await client.views_publish(user_id=user_id, view=view)
    except Exception:
        logger.debug("views.publish failed for user=%s", user_id, exc_info=True)


def register_app_home(app) -> None:
    @app.event("app_home_opened")
    async def on_app_home_opened(event, client):
        await on_app_home_opened_for_tests(event, client)


def _build_home_view() -> dict:
    cfg = get_slack_config()
    channels = cfg.get("channels", {}) or {}
    bots = cfg.get("bots", {}) or {}

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Welcome", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Ask me anything — I have memory, skills, and tool access "
                    "across your bound Slack channels. Use `/ask` in any "
                    "channel, or click below for a quick prompt."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Quick Ask", "emoji": True},
                    "style": "primary",
                    "action_id": "home_quick_ask",
                },
            ],
        },
        {"type": "divider"},
    ]

    if channels:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "Bound channels", "emoji": True},
        })
        rows = list(channels.items())[:_MAX_CHANNEL_ROWS]
        for slack_channel_id, binding in rows:
            if isinstance(binding, dict):
                bot_id = binding.get("bot_id", "?")
            else:
                bot_id = str(binding)
            bot_name = (bots.get(bot_id) or {}).get("display_name") or bot_id
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<#{slack_channel_id}> → *{bot_name}* `{bot_id}`",
                },
            })
        if len(channels) > _MAX_CHANNEL_ROWS:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"_…and {len(channels) - _MAX_CHANNEL_ROWS} more_",
                }],
            })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "_No Slack channels are bound yet. Invite the bot to a "
                    "channel and @-mention it to get started._"
                ),
            },
        })

    return {"type": "home", "blocks": blocks}
