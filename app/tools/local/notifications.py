"""Bot-callable tools for admin-granted notification targets."""
from __future__ import annotations

import json
import uuid

from app.agent.context import current_bot_id
from app.db.engine import async_session
from app.services.notifications import (
    NotificationPayload,
    list_targets,
    send_notification as send_notification_service,
    serialize_target,
)
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "list_notification_targets",
        "description": "List notification targets this bot is allowed to send to.",
        "parameters": {"type": "object", "properties": {}},
    },
}, safety_tier="readonly", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "targets": {"type": "array", "items": {"type": "object"}},
        "error": {"type": "string"},
    },
})
async def list_notification_targets() -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)
    async with async_session() as db:
        rows = await list_targets(db, bot_id=bot_id)
    return json.dumps({"targets": [serialize_target(row) for row in rows]}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "send_notification",
        "description": (
            "Send a short human-facing notification to an admin-configured target. "
            "Call list_notification_targets first and use one of the returned ids."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "Notification target UUID from list_notification_targets."},
                "title": {"type": "string", "description": "Short notification title."},
                "body": {"type": "string", "description": "Notification body text."},
                "url": {"type": "string", "description": "Optional URL to open from push notifications."},
                "severity": {"type": "string", "enum": ["info", "success", "warning", "critical"]},
                "tag": {"type": "string", "description": "Optional collapse/grouping tag."},
            },
            "required": ["target_id", "title", "body"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "attempts": {"type": "integer"},
        "succeeded": {"type": "integer"},
        "details": {"type": "array", "items": {"type": "object"}},
        "error": {"type": "string"},
    },
})
async def send_notification(
    target_id: str,
    title: str,
    body: str,
    url: str = "",
    severity: str = "info",
    tag: str = "",
) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)
    try:
        target_uuid = uuid.UUID(target_id)
    except ValueError:
        return json.dumps({"error": "target_id must be a UUID."}, ensure_ascii=False)
    try:
        result = await send_notification_service(
            target_uuid,
            NotificationPayload(
                title=title,
                body=body,
                url=url or None,
                severity=severity,
                tag=tag or None,
            ),
            sender_type="bot_tool",
            sender_id=bot_id,
            bot_id=bot_id,
            enforce_bot_grant=True,
            actor_label=bot_id,
        )
    except PermissionError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return json.dumps({
        "attempts": result["attempts"],
        "succeeded": result["succeeded"],
        "details": result["details"],
    }, ensure_ascii=False)
