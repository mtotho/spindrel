"""Slack task result dispatcher.

Registers itself with the dispatcher registry at import time so that
integrations/__init__.py can auto-discover it alongside router.py.
"""
from __future__ import annotations

import logging

from app.agent.dispatchers import register
from integrations.slack.client import bot_attribution, post_message
from integrations.slack.formatting import split_for_slack

logger = logging.getLogger(__name__)


class SlackDispatcher:
    async def deliver(self, task, result: str, client_actions: list[dict] | None = None) -> None:
        cfg = task.dispatch_config or {}
        channel_id = cfg.get("channel_id")
        thread_ts = cfg.get("thread_ts")
        token = cfg.get("token")
        if not channel_id or not token:
            logger.warning("SlackDispatcher: missing channel_id or token for task %s", task.id)
            return

        reply_in_thread = cfg.get("reply_in_thread", True)
        attrs = bot_attribution(task.bot_id)

        chunks = split_for_slack(result)
        ok = True
        for chunk in chunks:
            ok = await post_message(
                token, channel_id, chunk,
                thread_ts=thread_ts,
                reply_in_thread=reply_in_thread,
                **attrs,
            )
            if not ok:
                break
        if not ok:
            return

        from app.services.sessions import store_dispatch_echo
        await store_dispatch_echo(
            task.session_id, task.client_id, task.bot_id, result,
        )

        # Upload any images generated during the task
        from integrations.slack.uploads import upload_image
        for action in (client_actions or []):
            if action.get("type") in ("upload_image", "upload_file"):
                await upload_image(
                    token=token,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    reply_in_thread=reply_in_thread,
                    action=action,
                    username=attrs.get("username"),
                    icon_emoji=attrs.get("icon_emoji"),
                )

    async def post_message(self, dispatch_config: dict, text: str, *,
                           bot_id: str | None = None, reply_in_thread: bool = True,
                           username: str | None = None, icon_emoji: str | None = None,
                           icon_url: str | None = None,
                           client_actions: list[dict] | None = None) -> bool:
        """Post a message to Slack via the shared client, optionally with bot/user attribution."""
        channel_id = dispatch_config.get("channel_id")
        thread_ts = dispatch_config.get("thread_ts")
        token = dispatch_config.get("token")
        if not channel_id or not token:
            logger.warning("SlackDispatcher.post_message: missing channel_id or token")
            return False

        # If caller provides explicit username/icon (e.g. user mirror), use those.
        # Otherwise fall back to bot attribution.
        if username or icon_emoji or icon_url:
            attrs: dict = {}
            if username:
                attrs["username"] = username
            if icon_emoji:
                attrs["icon_emoji"] = icon_emoji
            elif icon_url:
                attrs["icon_url"] = icon_url
        else:
            attrs = bot_attribution(bot_id) if bot_id else {}

        ok = await post_message(
            token, channel_id, text,
            thread_ts=thread_ts,
            reply_in_thread=reply_in_thread,
            **attrs,
        )

        if ok:
            from integrations.slack.uploads import upload_image
            for action in (client_actions or []):
                if action.get("type") in ("upload_image", "upload_file"):
                    await upload_image(
                        token=token,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        reply_in_thread=reply_in_thread,
                        action=action,
                        username=attrs.get("username"),
                        icon_emoji=attrs.get("icon_emoji"),
                    )

        return ok


    async def request_approval(
        self,
        *,
        dispatch_config: dict,
        approval_id: str,
        bot_id: str,
        tool_name: str,
        arguments: dict,
        reason: str | None,
    ) -> None:
        """Send a Block Kit message with Approve/Deny buttons for a tool approval."""
        import json as _json
        channel_id = dispatch_config.get("channel_id")
        thread_ts = dispatch_config.get("thread_ts")
        token = dispatch_config.get("token")
        if not channel_id or not token:
            logger.warning("SlackDispatcher.request_approval: missing channel_id or token")
            return

        args_preview = _json.dumps(arguments, indent=2)[:500]
        attrs = bot_attribution(bot_id)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":lock: *Tool approval required*\n"
                        f"*Bot:* `{bot_id}` | *Tool:* `{tool_name}`\n"
                        f"*Reason:* {reason or 'Policy requires approval'}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```\n{args_preview}\n```",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve_tool_call",
                        "value": approval_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Deny"},
                        "style": "danger",
                        "action_id": "deny_tool_call",
                        "value": approval_id,
                    },
                ],
            },
        ]

        import httpx
        payload: dict = {
            "channel": channel_id,
            "text": f"Tool approval required: {tool_name} (approval {approval_id})",
            "blocks": blocks,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if attrs.get("username"):
            payload["username"] = attrs["username"]
        if attrs.get("icon_emoji"):
            payload["icon_emoji"] = attrs["icon_emoji"]
        elif attrs.get("icon_url"):
            payload["icon_url"] = attrs["icon_url"]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
                r.raise_for_status()
                data = r.json()
                if not data.get("ok"):
                    logger.error("Slack approval message error: %s", data.get("error"))
        except Exception:
            logger.exception("Failed to send approval message for %s", approval_id)


register("slack", SlackDispatcher())
