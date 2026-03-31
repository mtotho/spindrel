"""HTTP calls to the agent server (chat, channels).

Used by bb_client.py (runs in a separate process).
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("AGENT_API_KEY", "")

_http = httpx.AsyncClient(timeout=30.0)


def bb_client_id(chat_guid: str) -> str:
    """Build a client_id from a BB chat GUID."""
    return f"bb:{chat_guid}"


async def ensure_channel(client_id: str, bot_id: str) -> dict | None:
    """Create or get a channel for this client_id + bot_id."""
    try:
        r = await _http.post(
            f"{AGENT_BASE_URL}/api/v1/channels",
            json={"client_id": client_id, "bot_id": bot_id},
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        logger.exception("ensure_channel failed for %s", client_id)
        return None


async def stream_chat(
    *,
    message: str,
    bot_id: str,
    client_id: str,
    session_id: str | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
    msg_metadata: dict | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream a chat response from the agent server."""
    payload: dict = {
        "message": message,
        "bot_id": bot_id,
        "client_id": client_id,
    }
    if session_id:
        payload["session_id"] = session_id
    if dispatch_type:
        payload["dispatch_type"] = dispatch_type
    if dispatch_config:
        payload["dispatch_config"] = dispatch_config
    if msg_metadata:
        payload["msg_metadata"] = msg_metadata
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as sc:
        async with sc.stream(
            "POST",
            f"{AGENT_BASE_URL}/chat/stream",
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}"},
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                line = line.strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass


async def store_passive_message(
    client_id: str,
    bot_id: str,
    content: str,
    metadata: dict,
    session_id: str | None = None,
) -> None:
    """Store a passive (non-triggering) message in the agent session."""
    payload: dict = {
        "message": content,
        "bot_id": bot_id,
        "client_id": client_id,
        "passive": True,
        "msg_metadata": metadata,
    }
    if session_id:
        payload["session_id"] = session_id
    async with httpx.AsyncClient(timeout=10.0) as sc:
        r = await sc.post(
            f"{AGENT_BASE_URL}/chat",
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        r.raise_for_status()
