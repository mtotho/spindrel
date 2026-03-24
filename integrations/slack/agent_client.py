"""HTTP calls to the agent server (chat, bots, sessions)."""
import json
import logging
from collections.abc import AsyncGenerator

import httpx

from slack_settings import AGENT_BASE_URL, API_KEY
from session_helpers import slack_client_id

logger = logging.getLogger(__name__)

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
    session_id: str | None = None,
    attachments: list[dict] | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
    msg_metadata: dict | None = None,
) -> dict:
    payload: dict = {
        "message": message,
        "bot_id": bot_id,
        "client_id": client_id,
    }
    if session_id:
        payload["session_id"] = session_id
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


async def ensure_channel(client_id: str, bot_id: str) -> dict | None:
    """Ensure a Channel row exists on the agent server for this client_id.

    Calls POST /api/v1/channels which is idempotent (get-or-create).
    Returns the channel dict (including active_session_id) or None on failure.
    """
    payload = {"client_id": client_id, "bot_id": bot_id}
    try:
        r = await http.post(
            f"{AGENT_BASE_URL}/api/v1/channels",
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


async def get_channel_session_id(channel_id: str, bot_id: str) -> str | None:
    """Get the active session_id for a Slack channel from the server.

    Returns the session_id string or None if the channel has no active session.
    """
    client_id = slack_client_id(channel_id)
    data = await ensure_channel(client_id, bot_id)
    if data and data.get("active_session_id"):
        return data["active_session_id"]
    return None


async def store_passive_message_http(
    client_id: str,
    bot_id: str,
    content: str,
    metadata: dict,
    session_id: str | None = None,
) -> None:
    """POST to /chat with passive=True to store a message without running the agent."""
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


async def fetch_todos(bot_id: str, channel_id: str, status: str = "pending") -> list[dict]:
    """Fetch todos from the agent server API."""
    r = await http.get(
        f"{AGENT_BASE_URL}/api/v1/todos",
        params={"bot_id": bot_id, "channel_id": channel_id, "status": status},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()
    return r.json()


async def fetch_session_context(session_id: str) -> dict:
    r = await http.get(
        f"{AGENT_BASE_URL}/sessions/{session_id}/context",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()
    return r.json()


async def fetch_session_context_compressed(session_id: str) -> dict:
    r = await http.get(
        f"{AGENT_BASE_URL}/sessions/{session_id}/context/compressed",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


async def fetch_session_context_contents(session_id: str, compress: bool = True) -> dict:
    r = await http.get(
        f"{AGENT_BASE_URL}/sessions/{session_id}/context/contents",
        params={"compress": str(compress).lower()},
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=30.0,
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
    session_id: str | None = None,
    attachments: list[dict] | None = None,
    file_metadata: list[dict] | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
    msg_metadata: dict | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream events from POST /chat/stream as an async generator of parsed dicts."""
    payload: dict = {
        "message": message,
        "bot_id": bot_id,
        "client_id": client_id,
    }
    if session_id:
        payload["session_id"] = session_id
    if attachments:
        payload["attachments"] = attachments
    if file_metadata:
        payload["file_metadata"] = file_metadata
    if dispatch_type:
        payload["dispatch_type"] = dispatch_type
    if dispatch_config:
        payload["dispatch_config"] = dispatch_config
    if msg_metadata:
        payload["msg_metadata"] = msg_metadata
    logger.info("stream_chat payload keys=%s file_metadata_count=%d", list(payload.keys()), len(payload.get("file_metadata", [])))
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
