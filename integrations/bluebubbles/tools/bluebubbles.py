"""BlueBubbles iMessage tools for the agent."""

import json
import logging
import uuid

import httpx

from integrations.bluebubbles.config import settings
from integrations.bluebubbles.echo_tracker import shared_tracker
from integrations.sdk import register_tool as register

logger = logging.getLogger(__name__)


def _credentials() -> tuple[str, str]:
    """Return (server_url, password). Raises ValueError if not configured."""
    url = settings.BLUEBUBBLES_SERVER_URL
    pw = settings.BLUEBUBBLES_PASSWORD
    if not url or not pw:
        raise ValueError("BlueBubbles not configured (missing server URL or password)")
    return url.rstrip("/"), pw


def _error(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


async def _resolve_chat_guid() -> str | None:
    """Auto-resolve the chat_guid from the current channel's BB binding.

    Tools run inside the agent loop which sets ``current_channel_id``.
    The channel's ``ChannelIntegration`` row with a ``bb:`` prefix
    contains the chat_guid.
    """
    try:
        from app.agent.context import current_channel_id
        channel_id = current_channel_id.get()
        if not channel_id:
            return None

        from app.db.models import ChannelIntegration
        from sqlalchemy import select
        from app.db.engine import async_session

        async with async_session() as db:
            result = await db.execute(
                select(ChannelIntegration.client_id).where(
                    ChannelIntegration.channel_id == channel_id,
                    ChannelIntegration.client_id.like("bb:%"),
                )
            )
            row = result.scalar_one_or_none()
            if row and row.startswith("bb:"):
                return row.removeprefix("bb:")
        return None
    except Exception:
        logger.debug("_resolve_chat_guid failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register({
    "type": "function",
    "function": {
        "name": "bb_list_chats",
        "description": (
            "List recent iMessage conversations from BlueBubbles. "
            "Returns chat GUIDs, display names, participants, and last message preview. "
            "Use this to discover chat GUIDs before reading or sending messages."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max chats to return (default 25).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset (default 0).",
                },
            },
        },
    },
})
async def bb_list_chats(limit: int = 25, offset: int = 0) -> str:
    try:
        server_url, password = _credentials()
    except ValueError as e:
        return _error(str(e))
    try:
        from integrations.bluebubbles.bb_api import query_chats
        async with httpx.AsyncClient(timeout=15.0) as client:
            chats = await query_chats(client, server_url, password, limit=limit, offset=offset)
        results = []
        for chat in chats:
            participants = []
            for h in chat.get("participants", []):
                addr = h.get("address", "")
                name = h.get("displayName") or addr
                participants.append(name)
            last_msg = chat.get("lastMessage")
            preview = None
            if last_msg:
                preview = (last_msg.get("text") or "")[:200]
            results.append({
                "guid": chat.get("guid"),
                "display_name": chat.get("displayName") or ", ".join(participants) or chat.get("guid"),
                "participants": participants,
                "last_message": preview,
                "is_group": chat.get("isGroup", False),
            })
        return json.dumps({"chats": results, "count": len(results)}, ensure_ascii=False)
    except Exception as e:
        logger.exception("bb_list_chats failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "bb_get_messages",
        "description": (
            "Get recent messages from a specific iMessage chat. "
            "Returns messages in reverse chronological order (newest first). "
            "If chat_guid is omitted, uses the current channel's iMessage chat. "
            "Use offset for pagination (e.g. offset=25 to get the next page)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chat_guid": {
                    "type": "string",
                    "description": "The chat GUID. Omit to use the current channel's chat.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (default 25).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset (default 0). Use to page through older messages.",
                },
            },
        },
    },
}, requires_channel_context=True)
async def bb_get_messages(chat_guid: str = "", limit: int = 25, offset: int = 0) -> str:
    try:
        server_url, password = _credentials()
    except ValueError as e:
        return _error(str(e))
    if not chat_guid:
        chat_guid = await _resolve_chat_guid()  # type: ignore[assignment]
    if not chat_guid:
        return _error("No chat_guid provided and could not auto-resolve from current channel")
    try:
        from integrations.bluebubbles.bb_api import get_chat_messages
        async with httpx.AsyncClient(timeout=15.0) as client:
            messages = await get_chat_messages(client, server_url, password, chat_guid, limit=limit, offset=offset)
        results = []
        for msg in messages:
            handle = msg.get("handle") or {}
            sender = handle.get("displayName") or handle.get("address") or "unknown"
            is_from_me = msg.get("isFromMe", False)
            results.append({
                "text": msg.get("text") or "",
                "sender": "me" if is_from_me else sender,
                "date": msg.get("dateCreated"),
                "is_from_me": is_from_me,
                "has_attachments": bool(msg.get("attachments")),
            })
        return json.dumps({"messages": results, "count": len(results), "chat_guid": chat_guid}, ensure_ascii=False)
    except Exception as e:
        logger.exception("bb_get_messages failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "bb_send_message",
        "description": (
            "Send an iMessage to a specific chat via BlueBubbles. "
            "If chat_guid is omitted, sends to the current channel's iMessage chat. "
            "Messages are sent through the BlueBubbles server to Apple's iMessage network."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chat_guid": {
                    "type": "string",
                    "description": "The chat GUID to send to. Omit to use the current channel's chat.",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to send.",
                },
            },
            "required": ["message"],
        },
    },
}, requires_channel_context=True)
async def bb_send_message(chat_guid: str = "", message: str = "") -> str:
    try:
        server_url, password = _credentials()
    except ValueError as e:
        return _error(str(e))
    if chat_guid and not chat_guid.startswith(("iMessage;", "SMS;")):
        logger.info("bb_send_message: ignoring invalid chat_guid %r, auto-resolving", chat_guid)
        chat_guid = ""
    if not chat_guid:
        chat_guid = await _resolve_chat_guid()  # type: ignore[assignment]
    if not chat_guid:
        return _error("No chat_guid provided and could not auto-resolve from current channel")
    if not message:
        return _error("No message text provided")
    try:
        from integrations.bluebubbles.bb_api import send_text
        temp_guid = str(uuid.uuid4())
        # Track before sending so echo detection catches the webhook echo
        shared_tracker.track_sent(temp_guid, message, chat_guid=chat_guid)
        await shared_tracker.save_to_db()
        async with httpx.AsyncClient(timeout=90.0) as client:
            result = await send_text(
                client, server_url, password, chat_guid, message,
                temp_guid=temp_guid,
            )
        if result:
            return json.dumps({"ok": True, "chat_guid": chat_guid, "message_sent": message[:100]}, ensure_ascii=False)
        else:
            return _error("BlueBubbles send_text returned None — message may not have been delivered")
    except Exception as e:
        logger.exception("bb_send_message failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "bb_send_reaction",
        "description": (
            "Send a tapback reaction to a specific iMessage message. "
            "Tapbacks are the small icons (heart, thumbs up, etc.) that appear on messages in iMessage. "
            "If chat_guid is omitted, uses the current channel's iMessage chat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message_text": {
                    "type": "string",
                    "description": "The exact text of the message to react to.",
                },
                "reaction": {
                    "type": "string",
                    "enum": ["love", "like", "dislike", "laugh", "emphasize", "question"],
                    "description": "The tapback reaction type.",
                },
                "chat_guid": {
                    "type": "string",
                    "description": "The chat GUID. Omit to use the current channel's chat.",
                },
            },
            "required": ["message_text", "reaction"],
        },
    },
}, requires_channel_context=True)
async def bb_send_reaction(message_text: str, reaction: str, chat_guid: str = "") -> str:
    try:
        server_url, password = _credentials()
    except ValueError as e:
        return _error(str(e))
    # Validate chat_guid — reject obvious nonsense so we fall through to
    # auto-resolve instead of sending garbage to the API.
    if chat_guid and not chat_guid.startswith(("iMessage;", "SMS;")):
        logger.info("bb_send_reaction: ignoring invalid chat_guid %r, auto-resolving", chat_guid)
        chat_guid = ""
    if not chat_guid:
        chat_guid = await _resolve_chat_guid()  # type: ignore[assignment]
    if not chat_guid:
        return _error("No chat_guid provided and could not auto-resolve from current channel")
    try:
        from integrations.bluebubbles.bb_api import send_reaction
        async with httpx.AsyncClient(timeout=10.0) as client:
            result = await send_reaction(
                client, server_url, password, chat_guid, message_text, reaction,
            )
        if result:
            return json.dumps({"ok": True, "reaction": reaction, "chat_guid": chat_guid}, ensure_ascii=False)
        return _error("send_reaction returned None — reaction may not have been delivered")
    except Exception as e:
        logger.exception("bb_send_reaction failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "bb_find_my",
        "description": (
            "Look up the location of Apple devices and people via Find My. "
            "Returns device names, locations (latitude/longitude), battery levels, and last update times. "
            "Refreshes location data from Apple before returning results. "
            "Note: on macOS Sequoia (15+) device locations may be unavailable due to Apple encryption changes."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def bb_find_my() -> str:
    try:
        server_url, password = _credentials()
    except ValueError as e:
        return _error(str(e))
    try:
        from integrations.bluebubbles.bb_api import (
            get_findmy_devices,
            get_findmy_friends,
            refresh_findmy,
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Refresh first to get latest locations
            await refresh_findmy(client, server_url, password)
            # Fetch both devices and friends
            devices = await get_findmy_devices(client, server_url, password)
            friends = await get_findmy_friends(client, server_url, password)

        device_results = []
        for d in devices:
            location = d.get("location") or {}
            device_results.append({
                "name": d.get("name") or d.get("deviceDisplayName") or "Unknown device",
                "model": d.get("deviceModel") or d.get("deviceDisplayName"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "address": d.get("address") or location.get("address"),
                "battery_level": d.get("batteryLevel"),
                "battery_status": d.get("batteryStatus"),
                "last_updated": d.get("lastUpdated") or location.get("timeStamp"),
            })

        friend_results = []
        for f in friends:
            location = f.get("location") or {}
            friend_results.append({
                "name": (
                    f"{f.get('firstName', '')} {f.get('lastName', '')}".strip()
                    or f.get("handle") or "Unknown"
                ),
                "handle": f.get("handle"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "address": f.get("address") or location.get("address"),
                "last_updated": location.get("timestamp"),
            })

        if not device_results and not friend_results:
            return json.dumps({
                "devices": [],
                "friends": [],
                "note": (
                    "No Find My data available. On macOS Sequoia (15+), "
                    "Apple encrypts the Find My cache which prevents access. "
                    "On older macOS versions, ensure Find My is enabled in System Settings."
                ),
            }, ensure_ascii=False)

        return json.dumps({
            "devices": device_results,
            "friends": friend_results,
            "device_count": len(device_results),
            "friend_count": len(friend_results),
        }, ensure_ascii=False)
    except Exception as e:
        logger.exception("bb_find_my failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "bb_server_info",
        "description": (
            "Check BlueBubbles server connectivity and get server info. "
            "Returns server version, macOS version, and connection status. "
            "Use this to verify the iMessage bridge is working."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def bb_server_info() -> str:
    try:
        server_url, password = _credentials()
    except ValueError as e:
        return _error(str(e))
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{server_url}/api/v1/server/info",
                params={"password": password},
            )
            if r.status_code != 200:
                return json.dumps({"connected": False, "error": f"HTTP {r.status_code}"}, ensure_ascii=False)
            info = r.json()
            data = info.get("data", info)
            return json.dumps({
                "connected": True,
                "os_version": data.get("os_version"),
                "server_version": data.get("server_version"),
                "private_api": data.get("private_api", False),
                "helper_connected": data.get("helper_connected", False),
                "proxy_service": data.get("proxy_service"),
            }, ensure_ascii=False)
    except httpx.ConnectError:
        return json.dumps({"connected": False, "error": "Server unreachable"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("bb_server_info failed")
        return _error(str(e))
