"""Slack task result dispatcher.

Registers itself with the dispatcher registry at import time so that
integrations/__init__.py can auto-discover it alongside router.py.
"""
from __future__ import annotations

import logging

import httpx

from app.agent.bots import get_bot
from app.agent.dispatchers import register

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)


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
        payload: dict = {
            "channel": channel_id,
            "text": result,
        }
        if thread_ts and reply_in_thread:
            payload["thread_ts"] = thread_ts

        # Display name / icon overrides (requires chat:write.customize scope)
        try:
            bot_config = get_bot(task.bot_id)
            username = bot_config.display_name or bot_config.name or None
            if username:
                payload["username"] = username
            slack_cfg = bot_config.integration_config.get("slack", {})
            if slack_cfg.get("icon_emoji"):
                payload["icon_emoji"] = slack_cfg["icon_emoji"]
            elif bot_config.avatar_url:
                payload["icon_url"] = bot_config.avatar_url
        except Exception:
            pass  # bot not found or no display config — use Slack app defaults

        try:
            r = await _http.post(
                "https://slack.com/api/chat.postMessage",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                logger.error("Slack API error for task %s: %s", task.id, data.get("error"))
                return
            from app.services.sessions import store_slack_echo_as_passive
            await store_slack_echo_as_passive(
                task.session_id, task.client_id, task.bot_id, result,
            )
        except Exception:
            logger.exception("SlackDispatcher.deliver failed for task %s", task.id)
            return

        # Upload any images generated during the task
        from app.services.slack_uploads import upload_image
        for action in (client_actions or []):
            if action.get("type") == "upload_image":
                await upload_image(
                    token=token,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    reply_in_thread=reply_in_thread,
                    action=action,
                )


register("slack", SlackDispatcher())
