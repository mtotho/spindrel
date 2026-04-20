"""send_push_notification — deliver a Web Push notification to a user.

Model: this tool is Spindrel's equivalent of Home Assistant's
`homeassistant.notify` service. Bots (and pipelines / tasks) call it to
wake a user's phone/desktop when something important happens. The user
must have previously opted in and subscribed from an installed PWA
(iOS 16.4+ standalone, or desktop/Android Chrome).

Identify the recipient by `user_email` (preferred — stable and readable
in bot configs) or `user_id` (UUID). If neither match, the tool returns
a clear error.

Gating:
  - Callable only if assigned to the bot in its local_tools list.
  - No additional runtime scope check — assigning the tool IS the grant
    (mirrors `send_file`, `send_slack_message`, etc.).
  - VAPID must be configured on the server; otherwise returns the
    "not configured" error with instructions.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import User
from app.services.push import PushDisabledError, send_push
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "send_push_notification",
        "description": (
            "Send a Web Push notification to a user's subscribed devices "
            "(phone, desktop, installed PWA). Use for time-sensitive alerts "
            "— pipeline completions, approval requests, or anything the user "
            "has asked to be buzzed about. By default skips the send when "
            "the user is currently active in the app; set `only_if_inactive` "
            "to false to always send."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_email": {
                    "type": "string",
                    "description": "Email of the target user. Preferred over user_id.",
                },
                "user_id": {
                    "type": "string",
                    "description": "UUID of the target user. Use instead of user_email when you already have the id.",
                },
                "title": {
                    "type": "string",
                    "description": "Short headline shown as the notification title. Keep under ~60 chars.",
                },
                "body": {
                    "type": "string",
                    "description": "Body text shown under the title. Visible on the lock screen — keep under ~180 chars.",
                },
                "url": {
                    "type": "string",
                    "description": "Optional URL to open when the user taps the notification. Relative paths supported (e.g. /channels/abc).",
                },
                "tag": {
                    "type": "string",
                    "description": "Optional tag. Repeat-sends with the same tag replace the prior notification instead of stacking.",
                },
                "only_if_inactive": {
                    "type": "boolean",
                    "description": "When true (default), skip the send if the user has been active in the app within the last ~2 minutes.",
                },
            },
            "required": ["title", "body"],
        },
    },
}, safety_tier="mutating", returns={
    "type": "object",
    "properties": {
        "sent": {"type": "integer"},
        "pruned": {"type": "integer"},
        "failed": {"type": "integer"},
        "skipped_active": {"type": "integer"},
        "error": {"type": "string"},
    },
})
async def send_push_notification(
    title: str,
    body: str,
    user_email: str = "",
    user_id: str = "",
    url: str = "",
    tag: str = "",
    only_if_inactive: bool = True,
) -> str:
    if not title or not body:
        return json.dumps({"error": "title and body are required."}, ensure_ascii=False)
    if not user_email and not user_id:
        return json.dumps({"error": "Provide user_email or user_id."}, ensure_ascii=False)

    async with async_session() as db:
        target_uuid: uuid.UUID
        if user_id:
            try:
                target_uuid = uuid.UUID(user_id)
            except ValueError:
                return json.dumps({"error": "Invalid user_id — must be a UUID."}, ensure_ascii=False)
            exists = (await db.execute(
                select(User.id).where(User.id == target_uuid)
            )).scalar_one_or_none()
            if exists is None:
                return json.dumps({"error": f"User {user_id} not found."}, ensure_ascii=False)
        else:
            u = (await db.execute(
                select(User).where(User.email == user_email)
            )).scalar_one_or_none()
            if u is None:
                return json.dumps({"error": f"User {user_email!r} not found."}, ensure_ascii=False)
            target_uuid = u.id

        try:
            result = await send_push(
                db, target_uuid,
                title, body,
                url=url or None,
                tag=tag or None,
                only_if_inactive=only_if_inactive,
            )
        except PushDisabledError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    return json.dumps({
        "sent": result.sent,
        "pruned": result.pruned,
        "failed": result.failed,
        "skipped_active": result.skipped_active,
    }, ensure_ascii=False)
