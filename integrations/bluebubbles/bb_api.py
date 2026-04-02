"""BlueBubbles REST API helpers.

Thin async wrapper around the BB server HTTP API.
All functions take explicit server_url and password parameters
so they work from both the Socket.IO client process and the dispatcher.
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
) -> dict | None:
    """Send a text message to a BB chat. Returns the API response dict or None on failure.

    Uses a 90s timeout since iMessage relay through BB can be slow.
    If BB_SEND_METHOD is set, includes it in the request; otherwise lets
    the BB server use its own configured default.
    """
    if temp_guid is None:
        temp_guid = str(uuid.uuid4())

    body: dict = {
        "chatGuid": chat_guid,
        "message": text,
        "tempGuid": temp_guid,
    }
    method = settings.BB_SEND_METHOD
    if method:
        body["method"] = method

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
        return data.get("data", [])
    except Exception:
        logger.exception("BB query_chats failed")
        return []


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
        return data.get("data", [])
    except Exception:
        logger.exception("BB get_chat_messages failed for %s", chat_guid)
        return []
