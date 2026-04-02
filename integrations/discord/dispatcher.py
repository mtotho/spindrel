"""Discord task result dispatcher.

Registers itself with the dispatcher registry at import time so that
integrations/__init__.py can auto-discover it alongside router.py.
"""
from __future__ import annotations

import json as _json
import logging

from app.agent.dispatchers import register
from integrations.discord.client import bot_attribution, post_message, edit_message, upload_file
from integrations.discord.formatting import format_response_for_discord, split_for_discord

logger = logging.getLogger(__name__)


class DiscordDispatcher:
    async def notify_start(self, task) -> None:
        """Post a thinking placeholder to Discord when a queued task starts executing.

        Stores the placeholder message_id in dispatch_config so deliver() can
        update it with the final response instead of posting a new message.
        """
        cfg = task.dispatch_config or {}
        channel_id = cfg.get("channel_id")
        token = cfg.get("token")
        if not channel_id or not token:
            return

        data = await post_message(token, channel_id, "\u23f3 *thinking...*")
        if data:
            cfg["_thinking_message_id"] = data.get("id")

        # Remove the hourglass reaction from the user's original message
        user_message_id = cfg.get("user_message_id")
        if user_message_id:
            from integrations.discord.client import remove_reaction
            await remove_reaction(token, channel_id, user_message_id, "\u23f3")

    async def deliver(self, task, result: str, client_actions: list[dict] | None = None,
                      extra_metadata: dict | None = None) -> None:
        cfg = dict(task.dispatch_config or {})
        channel_id = cfg.get("channel_id")
        token = cfg.get("token")
        if not channel_id or not token:
            logger.warning("DiscordDispatcher: missing channel_id or token for task %s", task.id)
            return

        attrs = bot_attribution(task.bot_id)

        # Prepend delegation attribution
        _text = result
        if extra_metadata and extra_metadata.get("delegated_by_display"):
            _text = f"*Delegated by {extra_metadata['delegated_by_display']}*\n{_text}"

        _text = format_response_for_discord(_text)
        chunks = split_for_discord(_text)

        # If we posted a thinking placeholder via notify_start, update it with the
        # first chunk instead of posting a new message.
        _thinking_id = cfg.get("_thinking_message_id")
        ok = True
        if _thinking_id and chunks:
            ok = await edit_message(token, channel_id, _thinking_id, chunks[0])
            chunks = chunks[1:]

        for chunk in chunks:
            data = await post_message(token, channel_id, chunk)
            if not data:
                ok = False
                break
        if not ok:
            logger.error("DiscordDispatcher.deliver: post_message failed for task %s channel %s", task.id, channel_id)
            return

        from app.services.sessions import store_dispatch_echo
        await store_dispatch_echo(
            task.session_id, task.client_id, task.bot_id, result,
            extra_metadata=extra_metadata,
        )

        # Upload any images generated during the task
        import base64
        for action in (client_actions or []):
            if action.get("type") in ("upload_image", "upload_file"):
                raw = action.get("data")
                if not raw:
                    continue
                try:
                    img_bytes = base64.b64decode(raw)
                except Exception:
                    continue
                filename = action.get("filename") or "generated.png"
                caption = action.get("caption")
                await upload_file(
                    token, channel_id, img_bytes, filename,
                    content=caption,
                )

    async def post_message(self, dispatch_config: dict, text: str, *,
                           bot_id: str | None = None, reply_in_thread: bool = True,
                           username: str | None = None, icon_emoji: str | None = None,
                           icon_url: str | None = None,
                           client_actions: list[dict] | None = None,
                           extra_metadata: dict | None = None) -> bool:
        """Post a message to Discord via the shared client."""
        channel_id = dispatch_config.get("channel_id")
        token = dispatch_config.get("token")
        if not channel_id or not token:
            logger.warning("DiscordDispatcher.post_message: missing channel_id or token")
            return False

        formatted = format_response_for_discord(text)
        chunks = split_for_discord(formatted)
        ok = True
        for chunk in chunks:
            data = await post_message(token, channel_id, chunk)
            if not data:
                ok = False
                break

        # Upload any images
        if ok and client_actions:
            import base64
            for action in client_actions:
                if action.get("type") in ("upload_image", "upload_file"):
                    raw = action.get("data")
                    if not raw:
                        continue
                    try:
                        img_bytes = base64.b64decode(raw)
                    except Exception:
                        continue
                    filename = action.get("filename") or "generated.png"
                    caption = action.get("caption")
                    await upload_file(
                        token, channel_id, img_bytes, filename,
                        content=caption,
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
        """Send an embed with approval buttons for a tool approval.

        Discord custom_ids are limited to 100 characters. We use compact
        prefix:approval_id[:index] format and look up bot_id/tool_name/conditions
        from the approval record server-side when the button is clicked.
        """
        channel_id = dispatch_config.get("channel_id")
        token = dispatch_config.get("token")
        if not channel_id or not token:
            logger.warning("DiscordDispatcher.request_approval: missing channel_id or token")
            return

        args_preview = _json.dumps(arguments, indent=2)[:500]

        from app.services.approval_suggestions import build_suggestions
        suggestions = build_suggestions(tool_name, arguments)

        # Build embed (use Unicode emoji — shortcodes don't render in embeds)
        embed = {
            "title": "\U0001f512 Tool approval required",
            "color": 0xFF9900,  # orange
            "fields": [
                {"name": "Bot", "value": f"`{bot_id}`", "inline": True},
                {"name": "Tool", "value": f"`{tool_name}`", "inline": True},
                {"name": "Reason", "value": reason or "Policy requires approval", "inline": False},
                {"name": "Arguments", "value": f"```json\n{args_preview}\n```", "inline": False},
            ],
        }

        # Compact custom_id format (max 100 chars):
        #   "ap:{approval_id}"   — approve this run
        #   "dn:{approval_id}"   — deny
        #   "aa:{approval_id}"   — allow always (bot-scoped, no conditions)
        #   "ar:{approval_id}:N" — allow rule suggestion N (0-indexed)

        # Row 1: Primary actions
        tool_label = tool_name[:30] if len(tool_name) > 30 else tool_name
        row1_buttons = [
            {
                "type": 2,  # Button
                "style": 3,  # Success (green)
                "label": f"Allow {tool_label}",
                "custom_id": f"aa:{approval_id}",
            },
            {
                "type": 2,
                "style": 1,  # Primary (blurple)
                "label": "Approve this run",
                "custom_id": f"ap:{approval_id}",
            },
            {
                "type": 2,
                "style": 4,  # Danger (red)
                "label": "Deny",
                "custom_id": f"dn:{approval_id}",
            },
        ]

        components = [{"type": 1, "components": row1_buttons}]  # type 1 = ActionRow

        # Row 2: Smart suggestions (referenced by index)
        if suggestions:
            suggestion_buttons = []
            # Global rule suggestion
            if suggestions[0].scope == "global":
                suggestion_buttons.append({
                    "type": 2,
                    "style": 2,  # Secondary (grey)
                    "label": suggestions[0].label[:80],
                    "custom_id": f"ar:{approval_id}:0",
                })
            # Narrower suggestions
            narrow_start = next(
                (i for i, s in enumerate(suggestions) if s.conditions),
                len(suggestions),
            )
            for i, sug in enumerate(suggestions[narrow_start:narrow_start + 4]):
                if len(suggestion_buttons) >= 5:  # Discord max per action row
                    break
                suggestion_buttons.append({
                    "type": 2,
                    "style": 2,
                    "label": sug.label[:80],
                    "custom_id": f"ar:{approval_id}:{narrow_start + i}",
                })
            if suggestion_buttons:
                components.append({"type": 1, "components": suggestion_buttons})

        payload = {
            "content": f"Tool approval required: {tool_name} (approval {approval_id})",
            "embeds": [embed],
            "components": components,
        }

        import httpx
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"https://discord.com/api/v10/channels/{channel_id}/messages",
                    json=payload,
                    headers={"Authorization": f"Bot {token}"},
                )
                r.raise_for_status()
        except Exception:
            logger.exception("Failed to send approval message for %s", approval_id)


register("discord", DiscordDispatcher())
