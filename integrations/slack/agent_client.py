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
    msg_metadata: dict | None = None,
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
    if msg_metadata:
        payload["msg_metadata"] = msg_metadata
    r = await http.post(
        f"{AGENT_BASE_URL}/chat",
        json=payload,
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


async def store_passive_message_http(
    session_id: str,
    client_id: str,
    bot_id: str,
    content: str,
    metadata: dict,
) -> None:
    """POST to /chat with passive=True to store a message without running the agent."""
    payload: dict = {
        "message": content,
        "bot_id": bot_id,
        "client_id": client_id,
        "session_id": session_id,
        "passive": True,
        "msg_metadata": metadata,
    }
    async with httpx.AsyncClient(timeout=10.0) as sc:
        r = await sc.post(
            f"{AGENT_BASE_URL}/chat",
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        r.raise_for_status()


async def fetch_session_context(session_id: str) -> dict:
    r = await http.get(
        f"{AGENT_BASE_URL}/sessions/{session_id}/context",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()
    return r.json()


async def fetch_session_plans(session_id: str, status: str = "active") -> list[dict]:
    r = await http.get(
        f"{AGENT_BASE_URL}/sessions/{session_id}/plans",
        params={"status": status},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()
    return r.json()


async def compact_session(session_id: str) -> dict:
    r = await http.post(
        f"{AGENT_BASE_URL}/sessions/{session_id}/summarize",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


async def update_plan_status(session_id: str, plan_id: str, status: str) -> None:
    r = await http.post(
        f"{AGENT_BASE_URL}/sessions/{session_id}/plans/{plan_id}/status",
        json={"status": status},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()


async def update_plan_item_status(
    session_id: str, plan_id: str, item_position: int, status: str
) -> None:
    r = await http.post(
        f"{AGENT_BASE_URL}/sessions/{session_id}/plans/{plan_id}/items/{item_position}/status",
        json={"status": status},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()


async def stream_chat(
    *,
    message: str,
    bot_id: str,
    client_id: str,
    session_id: str,
    attachments: list[dict] | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
    msg_metadata: dict | None = None,
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
                    continue  # skip keepalives and blank lines
                if line.startswith("data: "):
                    line = line[6:]  # strip SSE prefix
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass
