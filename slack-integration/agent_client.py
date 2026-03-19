"""HTTP calls to the agent server (chat, bots, sessions)."""
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
) -> dict:
    payload: dict = {
        "message": message,
        "bot_id": bot_id,
        "client_id": client_id,
        "session_id": session_id,
    }
    if attachments:
        payload["attachments"] = attachments
    r = await http.post(
        f"{AGENT_BASE_URL}/chat",
        json=payload,
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()
