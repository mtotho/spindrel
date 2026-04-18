"""Slack shortcuts — global + message-action entry points.

These register for shortcut callback_ids that the Slack app manifest
declares (configured at api.slack.com/apps for the installed app). Once
the manifest is updated to include them, users can:

  * ``ask_bot_quick`` (global shortcut)  — opens anywhere from the
    shortcuts menu. Sends a templated prompt into the user's DM with
    the bot (or the default channel).

  * ``ask_bot_about_message`` (message action) — right-click any
    message → "Ask bot about this". Sends the message's text as the
    user's prompt into the channel where they clicked.

Both route to the existing /ask dispatcher via ``dispatch``.

App-manifest entries (for reference; the admin adds these in Slack
after deploy):

  shortcuts:
    - name: "Quick ask"
      type: global
      callback_id: ask_bot_quick
      description: "Ask the bot anything"
    - name: "Ask bot about this"
      type: message
      callback_id: ask_bot_about_message
      description: "Run the bot against the selected message"
"""
from __future__ import annotations

import logging

from message_handlers import dispatch
from slack_settings import get_channel_config

logger = logging.getLogger(__name__)


def register_shortcuts(app) -> None:
    """Register Bolt shortcut handlers."""

    @app.shortcut("ask_bot_quick")
    async def on_quick_ask(ack, shortcut, client):
        """Global shortcut — send an empty prompt to the user's DM with the bot."""
        await ack()
        user_id = shortcut.get("user", {}).get("id")
        if not user_id:
            return
        # Open a DM conversation with the user, then dispatch an
        # empty-body turn so the bot greets.
        try:
            dm = await client.conversations_open(users=user_id)
        except Exception:
            logger.debug("conversations.open failed for %s", user_id, exc_info=True)
            return
        if not dm or not dm.get("ok"):
            return
        channel_id = dm.get("channel", {}).get("id")
        if not channel_id:
            return
        await dispatch(
            channel=channel_id,
            user=user_id,
            text="[Quick ask shortcut — awaiting user question]",
            say=None,
            client=client,
            files=None,
            thread_ts=None,
            mentioned=True,
            message_ts=None,
        )

    @app.shortcut("ask_bot_about_message")
    async def on_ask_bot_about_message(ack, shortcut, client):
        """Message action — run the bot against the selected message."""
        await ack()
        user_id = shortcut.get("user", {}).get("id") or "unknown"
        msg = shortcut.get("message") or {}
        channel = (shortcut.get("channel") or {}).get("id")
        message_text = (msg.get("text") or "").strip()
        message_ts = msg.get("ts")
        thread_ts = msg.get("thread_ts") or message_ts

        if not channel or not message_text:
            return

        prompt = (
            "Please respond to the following message in this thread:\n\n"
            f"{message_text}"
        )
        # Reuse dispatch so approval gating, passive rules, etc. all
        # apply uniformly.
        await dispatch(
            channel=channel,
            user=user_id,
            text=prompt,
            say=None,
            client=client,
            files=None,
            thread_ts=thread_ts,
            mentioned=True,
            message_ts=message_ts,
        )

    @app.action("home_quick_ask")
    async def on_home_quick_ask_button(ack, body, client):
        """The App Home 'Quick Ask' button — same flow as the global shortcut."""
        await ack()
        user_id = body.get("user", {}).get("id")
        if not user_id:
            return
        try:
            dm = await client.conversations_open(users=user_id)
        except Exception:
            logger.debug("conversations.open failed for %s", user_id, exc_info=True)
            return
        if not dm or not dm.get("ok"):
            return
        channel_id = dm.get("channel", {}).get("id")
        if not channel_id:
            return
        try:
            await client.chat_postMessage(
                channel=channel_id,
                text=":wave: Ask me anything — just type below.",
            )
        except Exception:
            logger.debug("home quick-ask greeting failed", exc_info=True)


# Silence the unused-import noise — dispatch is used inside the
# registered Bolt handlers above.
_ = dispatch
_ = get_channel_config
