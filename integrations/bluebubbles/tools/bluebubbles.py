"""BlueBubbles iMessage tools for the agent."""

import json
import logging
import uuid

import httpx

from integrations.bluebubbles.config import settings
from integrations.bluebubbles.echo_tracker import shared_tracker
from integrations._register import register

logger = logging.getLogger(__name__)


def _credentials() -> tuple[str, str]:
    """Return (server_url, password). Raises ValueError if not configured."""
    url = settings.BLUEBUBBLES_SERVER_URL
    pw = settings.BLUEBUBBLES_PASSWORD
    if not url or not pw:
        raise ValueError("BlueBubbles not configured (missing server URL or password)")
    return url.rstrip("/"), pw


def _error(msg: str) -> str:
    return json.dumps({"error": msg})


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
        return json.dumps({"chats": results, "count": len(results)})
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
            "Use bb_list_chats first to find the chat GUID. "
            "Use offset for pagination (e.g. offset=25 to get the next page)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chat_guid": {
                    "type": "string",
                    "description": "The chat GUID (e.g. 'iMessage;-;+15551234567' or 'iMessage;+;chat123456').",
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
            "required": ["chat_guid"],
        },
    },
})
async def bb_get_messages(chat_guid: str, limit: int = 25, offset: int = 0) -> str:
    try:
        server_url, password = _credentials()
    except ValueError as e:
        return _error(str(e))
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
        return json.dumps({"messages": results, "count": len(results), "chat_guid": chat_guid})
    except Exception as e:
        logger.exception("bb_get_messages failed")
        return _error(str(e))


@register({
    "type": "function",
    "function": {
        "name": "bb_send_message",
        "description": (
            "Send an iMessage to a specific chat via BlueBubbles. "
            "Use bb_list_chats first to find the chat GUID. "
            "Messages are sent through the BlueBubbles server to Apple's iMessage network."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chat_guid": {
                    "type": "string",
                    "description": "The chat GUID to send to.",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to send.",
                },
            },
            "required": ["chat_guid", "message"],
        },
    },
})
async def bb_send_message(chat_guid: str, message: str) -> str:
    try:
        server_url, password = _credentials()
    except ValueError as e:
        return _error(str(e))
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
            return json.dumps({"ok": True, "chat_guid": chat_guid, "message_sent": message[:100]})
        else:
            return _error("BlueBubbles send_text returned None — message may not have been delivered")
    except Exception as e:
        logger.exception("bb_send_message failed")
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
                return json.dumps({"connected": False, "error": f"HTTP {r.status_code}"})
            info = r.json()
            data = info.get("data", info)
            return json.dumps({
                "connected": True,
                "os_version": data.get("os_version"),
                "server_version": data.get("server_version"),
                "private_api": data.get("private_api", False),
                "helper_connected": data.get("helper_connected", False),
                "proxy_service": data.get("proxy_service"),
            })
    except httpx.ConnectError:
        return json.dumps({"connected": False, "error": "Server unreachable"})
    except Exception as e:
        logger.exception("bb_server_info failed")
        return _error(str(e))
