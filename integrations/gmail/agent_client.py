"""HTTP client for calling back to the agent server.

Used by the poller subprocess to deliver feed items to channel workspaces
and log timeline events.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("AGENT_API_KEY", "")

_http = httpx.AsyncClient(timeout=30.0)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"}


async def write_workspace_file(
    channel_id: str,
    path: str,
    content: str,
) -> bool:
    """Write a file to a channel's workspace via MC's PUT endpoint."""
    try:
        r = await _http.put(
            f"{AGENT_BASE_URL}/integrations/mission_control/channels/{channel_id}/workspace/files/content",
            params={"path": path},
            json={"content": content},
            headers=_headers(),
        )
        r.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to write workspace file %s for channel %s", path, channel_id)
        return False


async def append_timeline(channel_id: str, event: str) -> bool:
    """Append a timeline event via a passive chat message.

    Uses a passive message with metadata to trigger timeline logging
    without triggering the agent loop.
    """
    try:
        r = await _http.post(
            f"{AGENT_BASE_URL}/chat",
            json={
                "message": event,
                "bot_id": "",  # resolved from channel
                "client_id": f"gmail:timeline",
                "passive": True,
                "msg_metadata": {"source": "gmail", "type": "timeline"},
            },
            headers=_headers(),
        )
        r.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to append timeline for channel %s", channel_id)
        return False


async def resolve_channels_for_binding(prefix: str = "gmail:") -> list[dict]:
    """Query admin API for channels bound to gmail.

    Returns list of channel dicts with id, name, bot_id, client_id.
    """
    try:
        r = await _http.get(
            f"{AGENT_BASE_URL}/api/v1/admin/channels",
            headers=_headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        channels = r.json()
        if isinstance(channels, dict) and "items" in channels:
            channels = channels["items"]
        return [
            ch for ch in channels
            if isinstance(ch, dict) and str(ch.get("client_id", "")).startswith(prefix)
        ]
    except Exception:
        logger.exception("Failed to resolve gmail channels")
        return []
