"""BlueBubbles integration router — config endpoint.

Serves per-chat bot mapping configuration to the bb_client.py process,
and provides a chat listing endpoint for the admin UI.
"""
from __future__ import annotations

import logging
import os
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
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


def _get_bb_credentials() -> tuple[str, str]:
    """Get BB server_url and password from DB cache or env."""
    from app.services.integration_settings import get_value
    server_url = get_value("bluebubbles", "BLUEBUBBLES_SERVER_URL")
    password = get_value("bluebubbles", "BLUEBUBBLES_PASSWORD")
    return server_url, password


@router.get("/diagnose")
async def diagnose_mirror(_auth=Depends(verify_admin_auth)) -> dict:
    """Diagnose the mirror-to-iMessage path. Shows exactly what would happen."""
    from app.agent.hooks import get_integration_meta
    from app.agent import dispatchers as disp_mod

    issues = []
    checks = {}

    # 1. Check BB meta registration (hooks.py imported?)
    meta = get_integration_meta("bluebubbles")
    checks["meta_registered"] = meta is not None
    if meta:
        checks["has_resolve_dispatch_config"] = meta.resolve_dispatch_config is not None
    else:
        issues.append("IntegrationMeta not registered — hooks.py not imported")

    # 2. Check BB dispatcher registration
    dispatcher = disp_mod._registry.get("bluebubbles")
    checks["dispatcher_registered"] = dispatcher is not None
    if not dispatcher:
        issues.append("BlueBubblesDispatcher not registered — dispatcher.py not imported")

    # 3. Check BB credentials accessible
    server_url, password = _get_bb_credentials()
    checks["server_url_available"] = bool(server_url)
    checks["password_available"] = bool(password)
    if server_url:
        checks["server_url"] = server_url
    if not server_url:
        issues.append("BLUEBUBBLES_SERVER_URL not found in DB cache or env")
    if not password:
        issues.append("BLUEBUBBLES_PASSWORD not found in DB cache or env")

    # 4. Check resolve_dispatch_config works
    test_client_id = "bb:test-chat-guid"
    if meta and meta.resolve_dispatch_config:
        resolved = meta.resolve_dispatch_config(test_client_id)
        checks["resolve_dispatch_config_result"] = resolved is not None
        if not resolved:
            issues.append("resolve_dispatch_config returned None (credentials not found)")
    else:
        checks["resolve_dispatch_config_result"] = False

    # 5. Check channel bindings
    try:
        from app.db.engine import async_session
        from app.db.models import ChannelIntegration
        from sqlalchemy import select

        async with async_session() as db:
            result = await db.execute(
                select(ChannelIntegration)
                .where(ChannelIntegration.integration_type == "bluebubbles")
            )
            bindings = result.scalars().all()
            checks["bb_bindings"] = [
                {
                    "client_id": b.client_id,
                    "channel_id": str(b.channel_id),
                    "has_dispatch_config": b.dispatch_config is not None,
                    "display_name": b.display_name,
                }
                for b in bindings
            ]
            if not bindings:
                issues.append("No ChannelIntegration rows with integration_type='bluebubbles'")
    except Exception as e:
        checks["bb_bindings"] = f"error: {e}"
        issues.append(f"Failed to query bindings: {e}")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "checks": checks,
    }


@router.post("/test-send")
async def test_send(
    chat_guid: str = Query(..., description="BB chat GUID to send to"),
    text: str = Query("Test message from agent server", description="Message text"),
    _auth=Depends(verify_admin_auth),
) -> dict:
    """Send a test message to an iMessage chat via BB API. Verifies the full send path."""
    server_url, password = _get_bb_credentials()
    if not server_url or not password:
        raise HTTPException(503, "BB credentials not available (check DB settings or env)")

    from integrations.bluebubbles.bb_api import send_text

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            result = await send_text(
                client, server_url, password, chat_guid, text,
                temp_guid=str(uuid.uuid4()),
            )
        if result:
            return {"ok": True, "message": f"Sent to {chat_guid}", "bb_response": result}
        else:
            return {"ok": False, "message": "send_text returned None (BB API error)"}
    except Exception as e:
        raise HTTPException(502, f"Send failed: {e}")
