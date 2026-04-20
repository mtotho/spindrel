"""HTTP client for calling back to the agent server.

Used by the poller subprocess to deliver feed items to channel workspaces
and log timeline events.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)


def _base_url() -> str:
    try:
        from integrations.gmail.config import settings
        return settings.AGENT_BASE_URL
    except Exception:
        return os.environ.get("AGENT_BASE_URL", "http://localhost:8000")


def _headers() -> dict[str, str]:
    try:
        from integrations.gmail.config import settings
        api_key = settings.AGENT_API_KEY
    except Exception:
        api_key = os.environ.get("AGENT_API_KEY", "")
    return {"Authorization": f"Bearer {api_key}"}


async def write_workspace_file(
    channel_id: str,
    path: str,
    content: str,
) -> bool:
    """Write a file to a channel's workspace via the core channel-workspace PUT endpoint."""
    try:
        r = await _http.put(
            f"{_base_url()}/api/v1/channels/{channel_id}/workspace/files/content",
            params={"path": path},
            json={"content": content},
            headers=_headers(),
        )
        r.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to write workspace file %s for channel %s", path, channel_id)
        return False


async def append_timeline(channel_id: str, bot_id: str, event: str) -> bool:
    """Append a timeline event by sending a passive message to the channel.

    The bot_id + client_id route the message to the correct channel.
    """
    try:
        r = await _http.post(
            f"{_base_url()}/chat",
            json={
                "message": event,
                "bot_id": bot_id,
                "client_id": f"gmail:{channel_id}",
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

    Returns list of channel dicts with id, name, bot_id.
    Checks both the channel's own client_id (legacy) and integration bindings (new activation).
    """
    try:
        r = await _http.get(
            f"{_base_url()}/api/v1/admin/channels",
            headers=_headers(),
            params={"page_size": 100},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        # Response is {"channels": [...], "total": N, ...} or a bare list
        if isinstance(data, list):
            channels = data
        else:
            channels = data.get("channels") or data.get("items") or []

        matched = []
        for ch in channels:
            if not isinstance(ch, dict):
                continue
            # Legacy: channel-level client_id
            if str(ch.get("client_id", "")).startswith(prefix):
                matched.append(ch)
                continue
            # New activation: check integration bindings
            for binding in ch.get("integrations", []):
                if str(binding.get("client_id", "")).startswith(prefix):
                    matched.append(ch)
                    break
        return matched
    except Exception:
        logger.exception("Failed to resolve gmail channels")
        return []
