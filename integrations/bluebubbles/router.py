"""BlueBubbles integration router — config endpoint.

Serves per-chat bot mapping configuration to the bb_client.py process,
and provides a chat listing endpoint for the admin UI.
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import verify_admin_auth

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatBotMapping(BaseModel):
    """Map a BB chat GUID to a specific bot ID."""
    chat_guid: str
    bot_id: str


class ConfigResponse(BaseModel):
    server_url: str
    default_bot: str
    chat_bot_map: dict[str, str]


# In-memory config (could be persisted to IntegrationSetting later)
_chat_bot_map: dict[str, str] = {}


def _get_server_url() -> str:
    return os.environ.get("BLUEBUBBLES_SERVER_URL", "")


def _get_password() -> str:
    return os.environ.get("BLUEBUBBLES_PASSWORD", "")


def _get_default_bot() -> str:
    return os.environ.get("BB_DEFAULT_BOT", "default")


@router.get("/config")
async def get_config(_auth=Depends(verify_admin_auth)) -> ConfigResponse:
    """Return current BB configuration (used by bb_client.py)."""
    return ConfigResponse(
        server_url=_get_server_url(),
        default_bot=_get_default_bot(),
        chat_bot_map=dict(_chat_bot_map),
    )


@router.post("/config/chat-bot-map")
async def set_chat_bot_mapping(mapping: ChatBotMapping, _auth=Depends(verify_admin_auth)) -> dict:
    """Set a per-chat bot mapping."""
    _chat_bot_map[mapping.chat_guid] = mapping.bot_id
    return {"ok": True, "chat_guid": mapping.chat_guid, "bot_id": mapping.bot_id}


@router.delete("/config/chat-bot-map/{chat_guid:path}")
async def delete_chat_bot_mapping(chat_guid: str, _auth=Depends(verify_admin_auth)) -> dict:
    """Remove a per-chat bot mapping (falls back to default)."""
    _chat_bot_map.pop(chat_guid, None)
    return {"ok": True}


@router.get("/chats")
async def list_chats(limit: int = 25, offset: int = 0, _auth=Depends(verify_admin_auth)) -> dict:
    """Proxy chat listing from the BB server (for admin UI)."""
    server_url = _get_server_url()
    password = _get_password()
    if not server_url or not password:
        raise HTTPException(status_code=503, detail="BlueBubbles not configured")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{server_url}/api/v1/chat/query",
                params={"password": password},
                json={"limit": limit, "offset": offset, "sort": "lastmessage", "with": ["lastMessage"]},
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"BlueBubbles server error: {e}")


@router.get("/status")
async def get_status(_auth=Depends(verify_admin_auth)) -> dict:
    """Check BB server connectivity."""
    server_url = _get_server_url()
    password = _get_password()
    if not server_url or not password:
        return {"connected": False, "reason": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{server_url}/api/v1/server/info",
                params={"password": password},
            )
            if r.status_code == 200:
                return {"connected": True, "server_info": r.json()}
            return {"connected": False, "reason": f"status_{r.status_code}"}
    except Exception as e:
        return {"connected": False, "reason": str(e)}
