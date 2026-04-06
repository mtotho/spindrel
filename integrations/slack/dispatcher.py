"""Slack task result dispatcher.

Registers itself with the dispatcher registry at import time so that
integrations/__init__.py can auto-discover it alongside router.py.
"""
from __future__ import annotations

import logging

from app.agent.dispatchers import register
from integrations.slack.client import bot_attribution, post_message, post_message_raw, update_message
from integrations.slack.formatting import markdown_to_slack_mrkdwn, split_for_slack

logger = logging.getLogger(__name__)


class SlackDispatcher:
    async def notify_start(self, task) -> None:
        """Post a thinking placeholder to Slack when a queued task starts executing.

        Stores the placeholder ts in dispatch_config so deliver() can update it
        with the final response instead of posting a new message.
        """
        cfg = task.dispatch_config or {}
        channel_id = cfg.get("channel_id")
        thread_ts = cfg.get("thread_ts")
        token = cfg.get("token")
        if not channel_id or not token:
            return

        attrs = bot_attribution(task.bot_id)
        data = await post_message_raw(
            token, channel_id, "\u23f3 _thinking..._",
            thread_ts=thread_ts,
            reply_in_thread=True,
            **attrs,
        )
        if data:
            # Stash placeholder info so deliver() can update it
            cfg["_thinking_ts"] = data.get("ts")
            cfg["_thinking_channel"] = data.get("channel")

        # Remove the hourglass reaction from the user's original message
        message_ts = cfg.get("message_ts")
        if message_ts:
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=10.0) as _client:
                    await _client.post(
                        "https://slack.com/api/reactions.remove",
                        json={"channel": channel_id, "name": "hourglass_flowing_sand", "timestamp": message_ts},
                        headers={"Authorization": f"Bearer {token}"},
                    )
            except Exception:
                pass

    async def deliver(self, task, result: str, client_actions: list[dict] | None = None,
                      extra_metadata: dict | None = None) -> None:
        cfg = task.dispatch_config or {}
        channel_id = cfg.get("channel_id")
        thread_ts = cfg.get("thread_ts")
        token = cfg.get("token")
        if not channel_id or not token:
            logger.warning("SlackDispatcher: missing channel_id or token for task %s", task.id)
            return

        reply_in_thread = cfg.get("reply_in_thread", True)
        attrs = bot_attribution(task.bot_id)

        # Prepend delegation attribution for Slack
        _slack_text = result
        if extra_metadata and extra_metadata.get("delegated_by_display"):
            _slack_text = f"_Delegated by {extra_metadata['delegated_by_display']}_\n{_slack_text}"

        _slack_text = markdown_to_slack_mrkdwn(_slack_text)
        chunks = split_for_slack(_slack_text)

        # If we posted a thinking placeholder via notify_start, update it with the
        # first chunk instead of posting a new message.
        _thinking_ts = cfg.pop("_thinking_ts", None)
        _thinking_channel = cfg.pop("_thinking_channel", None)
        ok = True
        if _thinking_ts and _thinking_channel and chunks:
            ok = await update_message(
                token, _thinking_channel, _thinking_ts, chunks[0], **attrs,
            )
            chunks = chunks[1:]

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
            logger.error("SlackDispatcher.deliver: post_message failed for task %s channel %s", task.id, channel_id)
            return

        from app.services.sessions import store_dispatch_echo
        await store_dispatch_echo(
            task.session_id, task.client_id, task.bot_id, result,
            extra_metadata=extra_metadata,
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
                           client_actions: list[dict] | None = None,
                           extra_metadata: dict | None = None) -> bool:
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
            token, channel_id, markdown_to_slack_mrkdwn(text),
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
        extra_metadata: dict | None = None,
    ) -> None:
        """Send a Block Kit message with Approve/Deny buttons for a tool approval.

        For capability activations (extra_metadata contains _capability):
          - Shows capability name/description instead of raw tool name
          - "Allow & Pin" button to permanently add to bot's carapaces
          - No args preview, no generic tool-policy suggestions

        For regular tool approvals:
          Row 1: Allow always | Approve this run | Deny
          Row 2: Smart rule suggestions
        """
        import json as _json
        channel_id = dispatch_config.get("channel_id")
        thread_ts = dispatch_config.get("thread_ts")
        token = dispatch_config.get("token")
        if not channel_id or not token:
            logger.warning("SlackDispatcher.request_approval: missing channel_id or token")
            return

        attrs = bot_attribution(bot_id)
        cap = (extra_metadata or {}).get("_capability")

        if cap:
            blocks = self._build_capability_approval_blocks(
                _json, approval_id, bot_id, cap, reason,
            )
            fallback_text = f"Capability activation: {cap.get('name', 'unknown')} (approval {approval_id})"
        else:
            blocks = self._build_tool_approval_blocks(
                _json, approval_id, bot_id, tool_name, arguments, reason,
            )
            fallback_text = f"Tool approval required: {tool_name} (approval {approval_id})"

        import httpx
        payload: dict = {
            "channel": channel_id,
            "text": fallback_text,
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

    @staticmethod
    def _build_capability_approval_blocks(_json, approval_id, bot_id, cap, reason):
        """Block Kit layout for capability activation approvals."""
        cap_name = cap.get("name", "Unknown")
        cap_desc = cap.get("description", "")
        cap_id = cap.get("id", "")
        tools_count = cap.get("tools_count", 0)
        skills_count = cap.get("skills_count", 0)

        header_lines = [f":sparkles: *Capability activation — {cap_name}*"]
        if cap_desc:
            header_lines.append(cap_desc)
        header_lines.append(f"Provides: {tools_count} tool{'s' if tools_count != 1 else ''}, {skills_count} skill{'s' if skills_count != 1 else ''}")
        header_lines.append(f"Bot: `{bot_id}`")

        primary_actions = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Allow"},
                "action_id": "approve_tool_call",
                "value": approval_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Allow & Pin"},
                "style": "primary",
                "action_id": "pin_capability",
                "value": _json.dumps({
                    "approval_id": approval_id,
                    "capability_id": cap_id,
                    "capability_name": cap_name,
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Deny"},
                "style": "danger",
                "action_id": "deny_tool_call",
                "value": approval_id,
            },
        ]

        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(header_lines),
                },
            },
            {"type": "actions", "elements": primary_actions},
        ]

    @staticmethod
    def _build_tool_approval_blocks(_json, approval_id, bot_id, tool_name, arguments, reason):
        """Block Kit layout for regular tool approvals."""
        args_preview = _json.dumps(arguments, indent=2)[:500]

        from app.services.approval_suggestions import build_suggestions
        suggestions = build_suggestions(tool_name, arguments)

        primary_actions = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": f"Allow {tool_name}"},
                "style": "primary",
                "action_id": "allow_rule_always",
                "value": _json.dumps({
                    "approval_id": approval_id,
                    "bot_id": bot_id,
                    "tool_name": tool_name,
                    "conditions": {},
                    "scope": "bot",
                    "label": f"Allow {tool_name} always",
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve this run"},
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
        ]

        suggestion_actions = []
        if suggestions and suggestions[0].scope == "global":
            sug = suggestions[0]
            suggestion_actions.append({
                "type": "button",
                "text": {"type": "plain_text", "text": sug.label[:75]},
                "action_id": "allow_rule_0",
                "value": _json.dumps({
                    "approval_id": approval_id,
                    "bot_id": bot_id,
                    "tool_name": sug.tool_name,
                    "conditions": sug.conditions,
                    "scope": sug.scope,
                    "label": sug.label,
                }),
            })
        narrow_start = next(
            (i for i, s in enumerate(suggestions) if s.conditions),
            len(suggestions),
        )
        for i, sug in enumerate(suggestions[narrow_start:narrow_start + 4]):
            if len(suggestion_actions) >= 5:
                break
            suggestion_actions.append({
                "type": "button",
                "text": {"type": "plain_text", "text": sug.label[:75]},
                "action_id": f"allow_rule_{narrow_start + i}",
                "value": _json.dumps({
                    "approval_id": approval_id,
                    "bot_id": bot_id,
                    "tool_name": sug.tool_name,
                    "conditions": sug.conditions,
                    "scope": getattr(sug, "scope", "bot"),
                    "label": sug.label,
                }),
            })

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
            {"type": "actions", "elements": primary_actions},
        ]
        if suggestion_actions:
            blocks.append({"type": "actions", "elements": suggestion_actions})
        return blocks


register("slack", SlackDispatcher())
