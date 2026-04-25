"""BlueBubbles REST API helpers.

Thin async wrapper around the BB server HTTP API.
All functions take explicit server_url and password parameters
so they work from renderer delivery, routers, and tools.
"""
from __future__ import annotations

import logging
import uuid

import httpx

from integrations.bluebubbles.config import settings

logger = logging.getLogger(__name__)


async def ping(client: httpx.AsyncClient, server_url: str, password: str) -> bool:
    """Check if the BB server is reachable."""
    try:
        r = await client.get(
            f"{server_url}/api/v1/server/info",
            params={"password": password},
        )
        return r.status_code == 200
    except Exception:
        logger.debug("BB ping failed", exc_info=True)
        return False


async def send_text(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
    chat_guid: str,
    text: str,
    *,
    temp_guid: str | None = None,
    method: str | None = None,
) -> dict | None:
    """Send a text message to a BB chat. Returns the API response dict or None on failure.

    Uses a 90s timeout since iMessage relay through BB can be slow.
    If *method* is given, uses it; otherwise falls back to BB_SEND_METHOD
    global setting; otherwise lets the BB server use its own default.
    """
    if temp_guid is None:
        temp_guid = str(uuid.uuid4())

    body: dict = {
        "chatGuid": chat_guid,
        "message": text,
        "tempGuid": temp_guid,
    }
    effective_method = method or settings.BB_SEND_METHOD
    if effective_method:
        body["method"] = effective_method

    try:
        r = await client.post(
            f"{server_url}/api/v1/message/text",
            params={"password": password},
            json=body,
            timeout=90.0,
        )
        if r.status_code >= 400:
            resp_body = r.text[:500] if r.text else "(empty)"
            logger.error("BB send_text returned %s: %s", r.status_code, resp_body)
        r.raise_for_status()
        return r.json()
    except Exception:
        logger.exception("BB send_text failed for chat %s", chat_guid)
        return None


async def send_attachment(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
    chat_guid: str,
    file_path: str,
    file_name: str,
    *,
    temp_guid: str | None = None,
) -> dict | None:
    """Send an attachment to a BB chat."""
    if temp_guid is None:
        temp_guid = str(uuid.uuid4())
    try:
        with open(file_path, "rb") as f:
            r = await client.post(
                f"{server_url}/api/v1/message/attachment",
                params={"password": password},
                data={"chatGuid": chat_guid, "tempGuid": temp_guid, "name": file_name},
                files={"attachment": (file_name, f)},
            )
        r.raise_for_status()
        return r.json()
    except Exception:
        logger.exception("BB send_attachment failed for chat %s", chat_guid)
        return None


async def query_chats(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
    *,
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    """List chats from the BB server."""
    try:
        r = await client.post(
            f"{server_url}/api/v1/chat/query",
            params={"password": password},
            json={"limit": limit, "offset": offset, "sort": "lastmessage", "with": ["lastMessage"]},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data") or []
    except Exception:
        logger.exception("BB query_chats failed")
        return []


async def mark_chat_unread(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
    chat_guid: str,
) -> bool:
    """Tell the BB server's Mac to mark a chat as unread.

    Background: BlueBubbles Server runs on the user's Mac. When BB sees an
    incoming iMessage and pushes it to our webhook, the Mac side ends up
    treating the chat as "read by the user" — iCloud syncs that state to
    every Apple device including the user's iPhone, suppressing the push
    notification banner. Calling this endpoint right after the webhook
    fires re-flips the chat to unread, restoring the iPhone notification
    in the (common) case where iCloud sync hasn't propagated yet.

    This is a best-effort experiment — silently returns False if the BB
    server doesn't support the endpoint, since success/failure of the
    "fix the notifications" workaround should never affect message
    processing.
    """
    try:
        r = await client.post(
            f"{server_url}/api/v1/chat/{chat_guid}/markUnread",
            params={"password": password},
            timeout=5.0,
        )
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            # BB server doesn't expose this endpoint — caller should
            # consider another approach (push notifications, etc.).
            logger.debug("BB markUnread endpoint not supported by server")
            return False
        logger.warning(
            "BB markUnread returned %s for chat %s: %s",
            r.status_code, chat_guid, r.text[:200],
        )
        return False
    except Exception:
        logger.debug("BB markUnread failed for chat %s", chat_guid, exc_info=True)
        return False


async def set_typing(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
    chat_guid: str,
) -> bool:
    """Send a typing indicator to a BB chat.

    iMessage typing indicators auto-expire after ~10s, so there's no
    explicit "stop typing" call needed — the message send clears it.
    Fire-and-forget; failures are silently swallowed.
    """
    try:
        r = await client.post(
            f"{server_url}/api/v1/chat/{chat_guid}/typing",
            params={"password": password},
            json={"chatGuid": chat_guid},
            timeout=5.0,
        )
        return r.status_code in (200, 204)
    except Exception:
        logger.debug("BB set_typing failed for chat %s", chat_guid, exc_info=True)
        return False


async def send_reaction(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
    chat_guid: str,
    message_text: str,
    reaction: str,
    *,
    selected_message_guid: str | None = None,
) -> dict | None:
    """Send a tapback reaction on a message in a BB chat.

    *reaction* must be one of: love, like, dislike, laugh, emphasize, question.
    *selected_message_guid* is the GUID of the specific message part to react to.
    Returns the API response dict or None on failure.
    """
    body: dict = {
        "chatGuid": chat_guid,
        "selectedMessageGuid": selected_message_guid or "",
        "selectedMessageText": message_text,
        "reaction": reaction,
    }
    try:
        r = await client.post(
            f"{server_url}/api/v1/message/react",
            params={"password": password},
            json=body,
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        logger.warning(
            "BB send_reaction HTTP %s for chat %s: %s",
            e.response.status_code, chat_guid, e.response.text[:200],
        )
        return None
    except Exception:
        logger.exception("BB send_reaction failed for chat %s", chat_guid)
        return None


async def get_findmy_devices(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
) -> list[dict]:
    """Get cached Find My device locations.

    On macOS Sequoia (15+) Apple encrypts the Find My cache, so this
    may return an empty list or null locations. Callers should handle
    gracefully.
    """
    try:
        r = await client.get(
            f"{server_url}/api/v1/icloud/findmy/devices",
            params={"password": password},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data") or []
    except Exception:
        logger.exception("BB get_findmy_devices failed")
        return []


async def get_findmy_friends(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
) -> list[dict]:
    """Get cached Find My friends/people locations."""
    try:
        r = await client.get(
            f"{server_url}/api/v1/icloud/findmy/friends",
            params={"password": password},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data") or []
    except Exception:
        logger.exception("BB get_findmy_friends failed")
        return []


async def refresh_findmy(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
) -> bool:
    """Force a refresh of Find My device locations from Apple.

    Returns True if the server accepted the refresh request.
    """
    try:
        r = await client.post(
            f"{server_url}/api/v1/icloud/findmy/devices/refresh",
            params={"password": password},
            timeout=10.0,
        )
        return r.status_code in (200, 204)
    except Exception:
        logger.debug("BB refresh_findmy failed", exc_info=True)
        return False


async def get_chat_messages(
    client: httpx.AsyncClient,
    server_url: str,
    password: str,
    chat_guid: str,
    *,
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    """Get messages from a specific chat."""
    try:
        r = await client.get(
            f"{server_url}/api/v1/chat/{chat_guid}/message",
            params={"password": password, "limit": limit, "offset": offset, "sort": "DESC"},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data") or []
    except Exception:
        logger.exception("BB get_chat_messages failed for %s", chat_guid)
        return []
