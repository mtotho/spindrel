"""HTTP calls to the agent server (chat, bots, sessions)."""
import json
from collections.abc import AsyncGenerator

import httpx

from slack_settings import AGENT_BASE_URL, API_KEY
from session_helpers import slack_client_id

http = httpx.AsyncClient()


async def fetch_sessions(channel_id: str) -> list[dict]:
    client_id = slack_client_id(channel_id)
    r = await http.get(
        f"{AGENT_BASE_URL}/sessions",
        params={"client_id": client_id},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()
    return r.json()


async def list_bots() -> list[dict]:
    r = await http.get(
        f"{AGENT_BASE_URL}/bots",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()
    return r.json()


async def post_chat(
    *,
    message: str,
    bot_id: str,
    client_id: str,
    session_id: str,
    attachments: list[dict] | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
) -> dict:
    payload: dict = {
        "message": message,
        "bot_id": bot_id,
        "client_id": client_id,
        "session_id": session_id,
    }
    if attachments:
        payload["attachments"] = attachments
    if dispatch_type:
        payload["dispatch_type"] = dispatch_type
    if dispatch_config:
        payload["dispatch_config"] = dispatch_config
    r = await http.post(
        f"{AGENT_BASE_URL}/chat",
        json=payload,
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


async def stream_chat(
    *,
    message: str,
    bot_id: str,
    client_id: str,
    session_id: str,
    attachments: list[dict] | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream events from POST /chat/stream as an async generator of parsed dicts."""
    payload: dict = {
        "message": message,
        "bot_id": bot_id,
        "client_id": client_id,
        "session_id": session_id,
    }
    if attachments:
        payload["attachments"] = attachments
    if dispatch_type:
        payload["dispatch_type"] = dispatch_type
    if dispatch_config:
        payload["dispatch_config"] = dispatch_config
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
                    continue  # skip keepalives and blank lines
                if line.startswith("data: "):
                    line = line[6:]  # strip SSE prefix
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass
