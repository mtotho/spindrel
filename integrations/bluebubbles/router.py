"""BlueBubbles integration router — config + webhook endpoints.

Serves per-chat bot mapping configuration to the bb_client.py process,
provides a chat listing endpoint for the admin UI, and receives
new-message webhooks from BlueBubbles Server.
"""
from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_admin_auth
from app.services.channels import resolve_all_channels_by_client_id, ensure_active_session
from integrations import utils
from integrations.bluebubbles.echo_tracker import shared_tracker

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
    wake_words: list[str]
    channels: dict[str, dict]


# In-memory config (could be persisted to IntegrationSetting later)
_chat_bot_map: dict[str, str] = {}


def _get_server_url() -> str:
    from integrations.bluebubbles.config import settings
    return settings.BLUEBUBBLES_SERVER_URL


def _get_password() -> str:
    from integrations.bluebubbles.config import settings
    return settings.BLUEBUBBLES_PASSWORD


def _get_default_bot() -> str:
    from integrations.bluebubbles.config import settings
    return settings.BB_DEFAULT_BOT


def _parse_wake_words(raw: str, default_bot: str) -> list[str]:
    """Parse comma-separated wake words, falling back to bot name."""
    words = [w.strip().lower() for w in raw.split(",") if w.strip()]
    if not words:
        words = [default_bot.lower()]
    return words


@router.get("/config")
async def get_config(_auth=Depends(verify_admin_auth)) -> ConfigResponse:
    """Return current BB configuration (used by bb_client.py)."""
    from integrations.bluebubbles.config import settings
    from app.db.engine import async_session
    from app.db.models import Channel
    from sqlalchemy import select

    default_bot = _get_default_bot()

    # Parse wake words from settings
    wake_words = _parse_wake_words(settings.BB_WAKE_WORDS, default_bot)

    # Query channel settings for all BB-bound channels
    channels: dict[str, dict] = {}
    try:
        async with async_session() as db:
            rows = (await db.execute(
                select(Channel).where(Channel.client_id.like("bb:%"))
            )).scalars().all()
        for row in rows:
            if not row.client_id:
                continue
            chat_guid = row.client_id.removeprefix("bb:")
            channels[chat_guid] = {
                "require_mention": row.require_mention,
                "passive_memory": row.passive_memory,
            }
    except Exception:
        logger.debug("Failed to query BB channel settings", exc_info=True)

    return ConfigResponse(
        server_url=_get_server_url(),
        default_bot=default_bot,
        chat_bot_map=dict(_chat_bot_map),
        wake_words=wake_words,
        channels=channels,
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
    return _get_server_url(), _get_password()


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


@router.post("/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Receive new-message webhooks from BlueBubbles Server.

    BB POSTs ``{"type": "new-message", "data": {...}}`` for each incoming
    iMessage.  This replaces Socket.IO for message delivery.

    Authenticated via ``?token=<BB_WEBHOOK_TOKEN>`` query param.
    If ``BB_WEBHOOK_TOKEN`` is not configured, the endpoint is open
    (for local/trusted networks).
    """
    from integrations.bluebubbles.config import settings as bb_settings
    expected = bb_settings.BB_WEBHOOK_TOKEN
    if expected:
        token = request.query_params.get("token", "")
        if not token or token != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing token")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = payload.get("type")
    if event_type != "new-message":
        logger.debug("BB webhook: ignoring event type %s", event_type)
        return {"status": "ignored", "event": event_type}

    data = payload.get("data") or {}
    text = (data.get("text") or "").strip()
    if not text:
        return {"status": "ignored", "reason": "empty_text"}

    is_from_me = bool(data.get("isFromMe"))
    msg_guid = data.get("guid", "")

    # Extract chat GUID (BB puts chats in a list)
    chats = data.get("chats") or []
    chat_guid = chats[0]["guid"] if chats else data.get("chatGuid", "")
    if not chat_guid:
        logger.warning("BB webhook: new-message without chat GUID, guid=%s", msg_guid)
        return {"status": "ignored", "reason": "no_chat_guid"}

    # Echo check — is this our own reply bouncing back?
    if is_from_me and shared_tracker.is_echo(msg_guid, text):
        logger.debug("BB webhook: echo detected, guid=%s", msg_guid)
        return {"status": "ignored", "reason": "echo"}

    # Resolve channels bound to this chat
    client_id = f"bb:{chat_guid}"
    pairs = await resolve_all_channels_by_client_id(db, client_id)
    if not pairs:
        logger.debug("BB webhook: no channels bound to %s", client_id)
        return {"status": "ignored", "reason": "unbound"}

    # Extract sender info
    handle = data.get("handle") or {}
    sender = handle.get("address", "unknown") if not is_from_me else "me"

    # Read BB credentials + wake words
    from integrations.bluebubbles.config import settings as bb_settings
    server_url = bb_settings.BLUEBUBBLES_SERVER_URL
    password = bb_settings.BLUEBUBBLES_PASSWORD
    default_bot = bb_settings.BB_DEFAULT_BOT
    wake_words = _parse_wake_words(bb_settings.BB_WAKE_WORDS, default_bot)

    dispatch_config = {
        "type": "bluebubbles",
        "chat_guid": chat_guid,
        "server_url": server_url,
        "password": password,
    }

    results = []
    for channel, binding in pairs:
        session_id = await ensure_active_session(db, channel)

        if is_from_me:
            # Human texting from their own phone — always active
            run_agent = True
            content = text
        elif not channel.require_mention:
            # Channel doesn't require mention — always active
            run_agent = True
            content = text
        else:
            # Check wake word
            text_lower = text.lower()
            mentioned = any(w in text_lower for w in wake_words) if wake_words else False
            if mentioned:
                run_agent = True
                content = text
            else:
                # Passive — store with sender prefix, no agent run
                run_agent = False
                content = f"[{sender}]: {text}"

        result = await utils.inject_message(
            session_id, content, source="bluebubbles",
            run_agent=run_agent, notify=False,
            dispatch_config=dispatch_config,
            db=db,
        )
        results.append(result)

    logger.info("BB webhook: processed %s from %s → %d channel(s), run_agent=%s",
                chat_guid, sender, len(results), any(r.get("task_id") for r in results))

    return {
        "status": "processed",
        "channels": len(results),
        "results": results,
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
        async with httpx.AsyncClient(timeout=90.0) as client:
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
