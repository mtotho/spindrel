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
            if action.get("type") == "upload_image":
                await upload_image(
                    token=token,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    reply_in_thread=reply_in_thread,
                    action=action,
                )

    async def post_message(self, dispatch_config: dict, text: str, *,
                           bot_id: str | None = None, reply_in_thread: bool = True,
                           client_actions: list[dict] | None = None) -> bool:
        """Post a message to Slack via the shared client, optionally with bot attribution."""
        channel_id = dispatch_config.get("channel_id")
        thread_ts = dispatch_config.get("thread_ts")
        token = dispatch_config.get("token")
        if not channel_id or not token:
            logger.warning("SlackDispatcher.post_message: missing channel_id or token")
            return False

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
                if action.get("type") == "upload_image":
                    await upload_image(
                        token=token,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        reply_in_thread=reply_in_thread,
                        action=action,
                    )

        return ok


register("slack", SlackDispatcher())
