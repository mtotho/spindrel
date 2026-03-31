"""Discord file upload helpers for the task dispatcher (non-bot code paths).

Discord's file upload is simpler than Slack's — just POST multipart to
the channel messages endpoint. This module wraps that for use by the
dispatcher and other server-side code.
"""
from __future__ import annotations

import base64
import logging

import httpx

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)

DISCORD_API = "https://discord.com/api/v10"


async def upload_image(
    *,
    token: str,
    channel_id: str,
    action: dict,
) -> None:
    """Upload an upload_image client_action to a Discord channel.

    Args:
        token: Discord bot token.
        channel_id: Target channel ID.
        action: client_action dict with keys: data (base64), filename, caption.
    """
    raw = action.get("data")
    if not raw:
        return
    try:
        img_bytes = base64.b64decode(raw)
    except Exception:
        logger.warning("discord_uploads: could not base64-decode image data")
        return

    filename = action.get("filename") or "generated.png"
    caption = action.get("caption") or None

    try:
        files = {"file": (filename, img_bytes)}
        data: dict = {}
        if caption:
            data["content"] = caption
        r = await _http.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            data=data,
            files=files,
            headers={"Authorization": f"Bot {token}"},
        )
        r.raise_for_status()
    except Exception:
        logger.exception("discord_uploads: failed to upload file to channel %s", channel_id)
