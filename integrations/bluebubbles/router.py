"""BlueBubbles integration router — config + webhook endpoints.

Serves per-chat bot mapping configuration to the bb_client.py process,
provides a chat listing endpoint for the admin UI, and receives
new-message webhooks from BlueBubbles Server.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import OrderedDict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_admin_auth
from app.services.channels import resolve_all_channels_by_client_id, ensure_active_session
from integrations import utils
from integrations.bluebubbles.echo_tracker import shared_tracker

logger = logging.getLogger(__name__)

# Lazy-load flag for echo tracker DB state
_echo_state_loaded: dict[str, bool] = {}

# Kill switch — when True, webhook rejects ALL messages.
# Set via POST /integrations/bluebubbles/pause
_paused: bool = False


# ---------------------------------------------------------------------------
# Persistent GUID dedup — survives server restarts via DB
# ---------------------------------------------------------------------------
_SEEN_GUIDS_MAX = 5000
_GUID_DB_KEY = "bb_seen_guids"
_INTEGRATION_ID = "bluebubbles"


class _GuidDedup:
    """Track processed message GUIDs with DB persistence.

    Uses an OrderedDict as a bounded LRU — newest entries at the end.
    Persists to IntegrationSetting so state survives server restarts.
    """

    def __init__(self, max_size: int = _SEEN_GUIDS_MAX) -> None:
        self._max = max_size
        self._seen: OrderedDict[str, float] = OrderedDict()

    def check_and_record(self, guid: str) -> bool:
        """Return True if this GUID was already seen. Records it if new."""
        if guid in self._seen:
            return True
        self._seen[guid] = time.time()
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return False

    async def save_to_db(self) -> None:
        """Persist seen GUIDs to the DB."""
        try:
            from app.db.engine import async_session
            from app.db.models import IntegrationSetting
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            recent = dict(list(self._seen.items())[-1000:])
            data = json.dumps(recent)
            async with async_session() as db:
                stmt = pg_insert(IntegrationSetting).values(
                    integration_id=_INTEGRATION_ID,
                    key=_GUID_DB_KEY,
                    value=data,
                    is_secret=False,
                ).on_conflict_do_update(
                    index_elements=["integration_id", "key"],
                    set_={"value": data},
                )
                await db.execute(stmt)
                await db.commit()
        except Exception:
            logger.debug("BB dedup: could not save to DB", exc_info=True)

    async def load_from_db(self) -> None:
        """Load seen GUIDs from the DB."""
        try:
            from app.db.engine import async_session
            from app.db.models import IntegrationSetting
            from sqlalchemy import select

            async with async_session() as db:
                row = (await db.execute(
                    select(IntegrationSetting).where(
                        IntegrationSetting.integration_id == _INTEGRATION_ID,
                        IntegrationSetting.key == _GUID_DB_KEY,
                    )
                )).scalar_one_or_none()

            if row and row.value:
                data = json.loads(row.value)
                for guid, ts in list(data.items())[-self._max:]:
                    self._seen[guid] = ts
                if self._seen:
                    logger.info("BB dedup: loaded %d GUIDs from DB", len(self._seen))
        except Exception:
            logger.debug("BB dedup: could not load from DB", exc_info=True)


_guid_dedup = _GuidDedup()

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
    """Parse comma-separated wake words, falling back to bot name.

    Used by the /config endpoint (bb_client.py backward compat).
    """
    words = [w.strip().lower() for w in raw.split(",") if w.strip()]
    if not words:
        words = [default_bot.lower()]
    return words


def _parse_extra_wake_words(raw: str) -> list[str]:
    """Parse BB_WAKE_WORDS into a list. Returns empty list if unset."""
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def _bot_wake_words(bot_id: str) -> list[str]:
    """Return wake words derived from a bot's id and name."""
    try:
        from app.agent.bots import get_bot
        bot = get_bot(bot_id)
        words = {bot.id.lower()}
        if bot.name:
            words.add(bot.name.lower())
        return list(words)
    except Exception:
        # Bot not loaded yet or unknown — fall back to id
        return [bot_id.lower()]


@router.get("/config")
async def get_config(_auth=Depends(verify_admin_auth)) -> ConfigResponse:
    """Return current BB configuration (used by bb_client.py)."""
    from integrations.bluebubbles.config import settings
    from app.db.engine import async_session
    from app.db.models import Channel, ChannelIntegration
    from sqlalchemy import select

    default_bot = _get_default_bot()

    # Parse wake words from settings
    wake_words = _parse_wake_words(settings.BB_WAKE_WORDS, default_bot)

    # Query channel settings for all BB-bound channels.
    # Check BOTH Channel.client_id (legacy) and ChannelIntegration.client_id (modern bindings).
    channels: dict[str, dict] = {}
    try:
        async with async_session() as db:
            # Legacy path: Channel.client_id starts with "bb:"
            rows = (await db.execute(
                select(Channel).where(Channel.client_id.like("bb:%"))
            )).scalars().all()
            for row in rows:
                if not row.client_id:
                    continue
                chat_guid = row.client_id.removeprefix("bb:")
                channels[chat_guid] = {
                    "bot_id": row.bot_id,
                    "require_mention": row.require_mention,
                    "passive_memory": row.passive_memory,
                }

            # Modern path: ChannelIntegration bindings with integration_type='bluebubbles'
            binding_rows = (await db.execute(
                select(Channel, ChannelIntegration)
                .join(ChannelIntegration, ChannelIntegration.channel_id == Channel.id)
                .where(ChannelIntegration.integration_type == "bluebubbles")
            )).tuples().all()
            for channel, binding in binding_rows:
                chat_guid = binding.client_id.removeprefix("bb:")
                if chat_guid not in channels:  # Don't overwrite legacy entries
                    channels[chat_guid] = {
                        "bot_id": channel.bot_id,
                        "require_mention": channel.require_mention,
                        "passive_memory": channel.passive_memory,
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


# ---------------------------------------------------------------------------
# Binding suggestions — cached, configurable
# ---------------------------------------------------------------------------

_suggestions_cache: dict[str, object] = {"data": [], "ts": 0.0}
_SUGGESTIONS_CACHE_TTL = 300  # 5 minutes


@router.get("/binding-suggestions")
async def binding_suggestions(_auth=Depends(verify_admin_auth)) -> list[dict]:
    """Return the most recent BB chats as binding suggestions for the admin UI.

    Controlled by three settings:
    - ``BB_SUGGEST_CHATS`` — enable/disable (default true)
    - ``BB_SUGGEST_COUNT`` — how many to return (default 10, max 50)
    - ``BB_SUGGEST_PREVIEW`` — include last message text (default true)

    Results are cached server-side for 5 minutes to avoid hammering BB.
    """
    from integrations.bluebubbles.config import settings as bb_settings

    if not bb_settings.BB_SUGGEST_CHATS:
        return []

    count = bb_settings.BB_SUGGEST_COUNT
    show_preview = bb_settings.BB_SUGGEST_PREVIEW

    # Return cached results if fresh
    now = time.monotonic()
    if _suggestions_cache["data"] and (now - _suggestions_cache["ts"]) < _SUGGESTIONS_CACHE_TTL:
        cached = _suggestions_cache["data"]
        result = cached[:count]
        if not show_preview:
            return [{k: v for k, v in s.items() if k != "description"} for s in result]
        return result

    server_url = _get_server_url()
    password = _get_password()
    if not server_url or not password:
        raise HTTPException(status_code=503, detail="BlueBubbles not configured")

    # BB applies limit at the DB level BEFORE its last-message sort, so a
    # small limit just returns the N oldest-created chats.  Fetch a large
    # batch so our client-side sort actually sees all recent conversations.
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{server_url}/api/v1/chat/query",
                params={"password": password},
                json={
                    "limit": 200,
                    "offset": 0,
                    "with": ["lastMessage", "participants"],
                },
            )
            r.raise_for_status()
            chats = r.json().get("data", [])
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"BlueBubbles server error: {e}")

    # Re-sort client-side by lastMessage date descending
    def _last_msg_ts(c: dict) -> int:
        lm = c.get("lastMessage") or {}
        return lm.get("dateCreated") or lm.get("dateDelivered") or 0

    chats.sort(key=_last_msg_ts, reverse=True)

    # Build full suggestions list (cache with previews; strip on output if disabled)
    all_suggestions: list[dict] = []
    for chat in chats[:50]:
        guid = chat.get("guid", "")
        if not guid:
            continue

        display_name = chat.get("displayName") or ""
        if not display_name:
            participants = chat.get("participants") or []
            addrs = [p.get("address", "") for p in participants if p.get("address")]
            display_name = ", ".join(addrs) if addrs else guid

        description = ""
        last_msg = chat.get("lastMessage")
        if last_msg:
            text = (last_msg.get("text") or "")[:80]
            if text:
                description = text

        all_suggestions.append({
            "client_id": f"bb:{guid}",
            "display_name": display_name,
            "description": description,
        })

    _suggestions_cache["data"] = all_suggestions
    _suggestions_cache["ts"] = now

    result = all_suggestions[:count]
    if not show_preview:
        return [{k: v for k, v in s.items() if k != "description"} for s in result]
    return result


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


# ---------------------------------------------------------------------------
# Pause/resume + startup cleanup
# ---------------------------------------------------------------------------

@router.post("/pause")
async def pause_webhook(_auth=Depends(verify_admin_auth)) -> dict:
    """Emergency kill switch — immediately stop processing ALL BB webhooks."""
    global _paused
    _paused = True
    logger.warning("BB webhook PAUSED — all incoming messages will be rejected")
    return {"ok": True, "paused": True}


@router.post("/resume")
async def resume_webhook(_auth=Depends(verify_admin_auth)) -> dict:
    """Resume processing BB webhooks after a pause."""
    global _paused
    _paused = False
    logger.info("BB webhook RESUMED")
    return {"ok": True, "paused": False}


@router.post("/cancel-pending-tasks")
async def cancel_pending_tasks(_auth=Depends(verify_admin_auth)) -> dict:
    """Cancel all pending BlueBubbles tasks. Use after a spam incident."""
    from app.db.engine import async_session
    from app.db.models import Task
    from sqlalchemy import update

    async with async_session() as db:
        result = await db.execute(
            update(Task)
            .where(Task.status == "pending", Task.dispatch_type == "bluebubbles")
            .values(status="cancelled")
        )
        count = result.rowcount
        await db.commit()

    logger.warning("BB cancel-pending-tasks: cancelled %d pending tasks", count)
    return {"ok": True, "cancelled": count}


async def cancel_stale_pending_tasks() -> None:
    """Cancel BB tasks that were pending before this server started.

    Called during integration startup to prevent replay storms from
    tasks that accumulated during a previous crash/spam incident.
    """
    from app.db.engine import async_session
    from app.db.models import Task
    from sqlalchemy import update
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    try:
        async with async_session() as db:
            result = await db.execute(
                update(Task)
                .where(
                    Task.status == "pending",
                    Task.dispatch_type == "bluebubbles",
                    Task.created_at < cutoff,
                )
                .values(status="cancelled")
            )
            count = result.rowcount
            await db.commit()
        if count:
            logger.warning("BB startup: cancelled %d stale pending tasks (older than 5min)", count)
    except Exception:
        logger.debug("BB startup: could not cancel stale tasks", exc_info=True)


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

    # Kill switch — reject everything when paused
    if _paused:
        return {"status": "ignored", "reason": "paused"}

    logger.info("BB webhook: received request from %s", request.client.host if request.client else "unknown")

    expected = bb_settings.BB_WEBHOOK_TOKEN
    if expected:
        token = request.query_params.get("token", "")
        if not token or token != expected:
            logger.warning("BB webhook: auth failed (token mismatch, expected_len=%d got_len=%d)",
                           len(expected), len(token))
            raise HTTPException(status_code=401, detail="Invalid or missing token")

    # Load persisted state from DB on first webhook call.
    # This ensures circuit breaker / cooldown / GUID dedup survive server restarts.
    # Also cancels stale pending tasks to prevent replay storms.
    if not _echo_state_loaded.get("done"):
        await shared_tracker.load_from_db()
        await _guid_dedup.load_from_db()
        await cancel_stale_pending_tasks()
        _echo_state_loaded["done"] = True

    try:
        payload = await request.json()
    except Exception:
        logger.warning("BB webhook: invalid JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = payload.get("type")
    logger.info("BB webhook: event_type=%s", event_type)
    if event_type != "new-message":
        return {"status": "ignored", "event": event_type}

    data = payload.get("data") or {}

    # Staleness check — ignore messages older than 5 minutes to prevent
    # replay storms when BB retries a backlog of failed webhook deliveries.
    _STALE_THRESHOLD = 300  # seconds
    date_created = data.get("dateCreated")
    if date_created:
        try:
            msg_age = time.time() * 1000 - float(date_created)
            if msg_age > _STALE_THRESHOLD * 1000:
                logger.info("BB webhook: ignoring stale message (age=%.0fs, threshold=%ds)",
                            msg_age / 1000, _STALE_THRESHOLD)
                return {"status": "ignored", "reason": "stale"}
        except (ValueError, TypeError):
            pass  # Non-numeric dateCreated — skip check

    text = (data.get("text") or "").strip()
    if not text:
        logger.info("BB webhook: ignoring new-message with empty text")
        return {"status": "ignored", "reason": "empty_text"}

    is_from_me = bool(data.get("isFromMe"))
    msg_guid = data.get("guid", "")

    # GUID dedup — reject any message we've already processed.
    # This is persisted to disk so it survives server restarts,
    # preventing replay storms when BB retries old webhooks.
    if msg_guid and _guid_dedup.check_and_record(msg_guid):
        logger.info("BB webhook: duplicate GUID %s, ignoring", msg_guid)
        return {"status": "ignored", "reason": "duplicate"}

    # Extract chat GUID (BB puts chats in a list)
    chats = data.get("chats") or []
    chat_guid = (chats[0].get("guid", "") if chats else "") or data.get("chatGuid", "")
    if not chat_guid:
        logger.warning("BB webhook: new-message without chat GUID, guid=%s", msg_guid)
        return {"status": "ignored", "reason": "no_chat_guid"}

    logger.info("BB webhook: new-message chat_guid=%s is_from_me=%s text=%r",
                chat_guid, is_from_me, text[:80])

    # Echo check — is this our own reply bouncing back?
    if is_from_me and shared_tracker.is_echo(msg_guid, text):
        logger.info("BB webhook: echo detected (guid match), guid=%s", msg_guid)
        return {"status": "ignored", "reason": "echo"}

    # Reply cooldown: if we sent a reply to this chat recently, treat isFromMe as echo.
    # This catches cases where the LLM takes longer than the echo TTL.
    if is_from_me and shared_tracker.in_reply_cooldown(chat_guid):
        logger.info("BB webhook: echo detected (reply cooldown), chat_guid=%s", chat_guid)
        return {"status": "ignored", "reason": "echo_cooldown"}

    # Circuit breaker: if we've replied too many times to this chat recently, stop.
    if shared_tracker.is_circuit_open(chat_guid):
        logger.warning("BB webhook: circuit breaker open for chat_guid=%s — too many replies, "
                        "stopping to prevent loop", chat_guid)
        return {"status": "ignored", "reason": "circuit_breaker"}

    # Resolve channels bound to this chat
    client_id = f"bb:{chat_guid}"
    pairs = await resolve_all_channels_by_client_id(db, client_id)
    if not pairs:
        logger.warning("BB webhook: no channels bound to client_id=%s (chat_guid=%s). "
                        "Create a binding via Admin > Channels > Integrations tab.", client_id, chat_guid)
        return {"status": "ignored", "reason": "unbound", "client_id": client_id}

    # Extract sender info
    handle = data.get("handle") or {}
    sender = handle.get("address", "unknown") if not is_from_me else "me"

    # Read BB credentials
    from integrations.bluebubbles.config import settings as bb_settings
    server_url = bb_settings.BLUEBUBBLES_SERVER_URL
    password = bb_settings.BLUEBUBBLES_PASSWORD

    # Extra custom wake words (additive, on top of per-channel bot name/id)
    extra_wake_words = _parse_extra_wake_words(bb_settings.BB_WAKE_WORDS)

    dispatch_config = {
        "type": "bluebubbles",
        "chat_guid": chat_guid,
        "server_url": server_url,
        "password": password,
    }

    results = []
    for channel, binding in pairs:
        session_id = await ensure_active_session(db, channel)

        # Per-binding config from dispatch_config
        dc = binding.dispatch_config or {}
        use_bot_wake = dc.get("use_bot_wake_word", True)
        per_binding_words = _parse_extra_wake_words(dc.get("extra_wake_words", ""))

        if is_from_me:
            # Human texting from their own phone — always active
            run_agent = True
            content = text
        elif not channel.require_mention:
            # Channel doesn't require mention — always active
            run_agent = True
            content = text
        else:
            # Build per-channel wake words: binding-specific + global extras
            wake_words = per_binding_words + extra_wake_words
            if use_bot_wake:
                wake_words = _bot_wake_words(channel.bot_id) + wake_words
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

    # Persist GUID dedup state to DB (batched — only on successful processing)
    await _guid_dedup.save_to_db()

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


@router.post("/simulate-webhook")
async def simulate_webhook(
    chat_guid: str = Query(..., description="BB chat GUID (without bb: prefix)"),
    text: str = Query("Hello, this is a test message", description="Simulated message text"),
    dry_run: bool = Query(True, description="If true, only show what would happen (no agent run)"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_admin_auth),
) -> dict:
    """Simulate an inbound BB webhook to diagnose routing.

    Shows exactly which channels would be matched, what wake word evaluation
    would produce, and whether the agent would run. With dry_run=false,
    actually injects the message and triggers the agent.
    """
    from integrations.bluebubbles.config import settings as bb_settings

    client_id = f"bb:{chat_guid}"
    pairs = await resolve_all_channels_by_client_id(db, client_id)

    extra_wake_words = _parse_extra_wake_words(bb_settings.BB_WAKE_WORDS)
    text_lower = text.lower()

    channel_results = []
    for channel, binding in pairs:
        dc = binding.dispatch_config or {}
        use_bot_wake = dc.get("use_bot_wake_word", True)
        per_binding_words = _parse_extra_wake_words(dc.get("extra_wake_words", ""))

        wake_words = per_binding_words + extra_wake_words
        if use_bot_wake:
            wake_words = _bot_wake_words(channel.bot_id) + wake_words

        mentioned = any(w in text_lower for w in wake_words) if wake_words else False

        would_run = not channel.require_mention or mentioned

        entry = {
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "bot_id": channel.bot_id,
            "require_mention": channel.require_mention,
            "wake_words_evaluated": wake_words,
            "wake_word_matched": mentioned,
            "would_run_agent": would_run,
            "binding_client_id": binding.client_id,
            "binding_display_name": binding.display_name,
        }
        channel_results.append(entry)

    result: dict = {
        "client_id_searched": client_id,
        "channels_found": len(pairs),
        "channels": channel_results,
        "dry_run": dry_run,
    }

    if not pairs:
        result["hint"] = (
            f"No channels bound to client_id '{client_id}'. "
            "Check that a ChannelIntegration binding exists with this exact client_id."
        )
        return result

    if not dry_run:
        server_url = bb_settings.BLUEBUBBLES_SERVER_URL
        password = bb_settings.BLUEBUBBLES_PASSWORD
        dispatch_config = {
            "type": "bluebubbles",
            "chat_guid": chat_guid,
            "server_url": server_url,
            "password": password,
        }
        inject_results = []
        for channel, _binding in pairs:
            session_id = await ensure_active_session(db, channel)
            r = await utils.inject_message(
                session_id, text, source="bluebubbles",
                run_agent=True, notify=False,
                dispatch_config=dispatch_config,
                db=db,
            )
            inject_results.append(r)
        result["inject_results"] = inject_results

    return result
