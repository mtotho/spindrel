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

from app.dependencies import get_db, verify_admin_auth, verify_auth_or_user
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


# ---------------------------------------------------------------------------
# Content dedup — catches the iCloud cross-device duplicate
# ---------------------------------------------------------------------------
# BlueBubbles delivers the same iMessage to the webhook twice when iCloud
# mirrors it across the user's devices: once with ``isFromMe=True`` from the
# origin device and once with ``isFromMe=False`` from the contact's number
# (the mirror). The two deliveries carry DIFFERENT message GUIDs, so
# ``_guid_dedup`` doesn't catch them. We need a (chat_guid, text) match
# inside a short window.
#
# Window is short on purpose: long enough for any iMessage device to mirror
# (a few seconds in practice; 30s for headroom), short enough that the user
# can intentionally retype the same word later without it being dropped.
_TEXT_DEDUP_WINDOW = 30.0
_TEXT_DEDUP_MAX = 2000


class _ContentDedup:
    """Track recently-processed (chat_guid, text) pairs.

    In-memory only — the window is short enough that a process restart
    losing the state is harmless. The slower replay-storm case is already
    covered by the persistent ``_guid_dedup``.
    """

    def __init__(
        self,
        max_size: int = _TEXT_DEDUP_MAX,
        window: float = _TEXT_DEDUP_WINDOW,
    ) -> None:
        self._max = max_size
        self._window = window
        self._seen: OrderedDict[tuple[str, str], float] = OrderedDict()

    def _evict(self, now: float) -> None:
        """Drop entries older than the window."""
        while self._seen:
            oldest_key, oldest_ts = next(iter(self._seen.items()))
            if oldest_ts >= now - self._window:
                break
            self._seen.popitem(last=False)

    def check_and_record(self, chat_guid: str, text: str) -> bool:
        """Return True if this (chat_guid, text) was already seen recently."""
        now = time.time()
        self._evict(now)
        key = (chat_guid, text.strip().lower())
        if key in self._seen:
            return True
        self._seen[key] = now
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return False


_content_dedup = _ContentDedup()

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


def _format_handle_name(handle: dict) -> str | None:
    """Build a display name from BB handle firstName/lastName fields."""
    first = (handle.get("firstName") or "").strip()
    last = (handle.get("lastName") or "").strip()
    if first and last:
        return f"{first} {last}"
    return first or last or None


def _normalize_address(addr: str) -> str:
    """Normalize a phone/email address for comparison (strip +, spaces, dashes)."""
    import re
    return re.sub(r"[\s\-\(\)\+]", "", addr).lower()


def _expected_sender_from_guid(chat_guid: str) -> str | None:
    """Extract the expected sender address from a 1:1 chat GUID.

    1:1 format: ``iMessage;-;+15551234567`` → ``15551234567``
    Group format: ``iMessage;+;chat123`` → None (no single expected sender)
    """
    if ";-;" not in chat_guid:
        return None  # Group chat or unknown format
    parts = chat_guid.split(";-;", 1)
    if len(parts) == 2 and parts[1]:
        return _normalize_address(parts[1])
    return None


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
    from app.integrations import renderer_registry

    issues = []
    checks = {}

    # 1. Check BB meta registration (hooks.py imported?)
    meta = get_integration_meta("bluebubbles")
    checks["meta_registered"] = meta is not None
    if meta:
        checks["has_resolve_dispatch_config"] = meta.resolve_dispatch_config is not None
    else:
        issues.append("IntegrationMeta not registered — hooks.py not imported")

    # 2. Check BB renderer registration (renderer.py imported by discovery?)
    renderer = renderer_registry.get("bluebubbles")
    checks["renderer_registered"] = renderer is not None
    if not renderer:
        issues.append("BlueBubblesRenderer not registered — renderer.py not imported")

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


@router.get("/echo-state")
async def echo_state(_auth=Depends(verify_admin_auth)) -> dict:
    """Return the current echo detection state for all tracked chats.

    Shows per-chat cooldowns, circuit breaker status, sent content hashes,
    and echo suppress window state. Useful for debugging why the bot isn't
    responding or why it's looping.
    """
    from integrations.bluebubbles.echo_tracker import (
        _REPLY_COOLDOWN, _CIRCUIT_BREAKER_MAX, _CIRCUIT_BREAKER_WINDOW,
        _ECHO_SUPPRESS_WINDOW,
    )

    now = time.time()
    chats: dict[str, dict] = {}

    # Collect all chat GUIDs from both data structures
    all_guids = set(shared_tracker._chat_replies.keys()) | set(shared_tracker._sent_content.keys())

    for chat_guid in sorted(all_guids):
        replies = shared_tracker._chat_replies.get(chat_guid, [])
        content = shared_tracker._sent_content.get(chat_guid, {})

        recent_replies = [ts for ts in replies if now - ts < _CIRCUIT_BREAKER_WINDOW]
        cooldown_remaining = max(0, max((ts + _REPLY_COOLDOWN - now for ts in replies), default=0))
        suppress_remaining = max(0, max((ts + _ECHO_SUPPRESS_WINDOW - now for ts in replies), default=0))

        chats[chat_guid] = {
            "reply_count_in_window": len(recent_replies),
            "circuit_breaker_max": _CIRCUIT_BREAKER_MAX,
            "circuit_breaker_open": len(recent_replies) >= _CIRCUIT_BREAKER_MAX,
            "reply_cooldown_active": cooldown_remaining > 0,
            "reply_cooldown_remaining_s": round(cooldown_remaining, 1),
            "echo_suppress_active": suppress_remaining > 0,
            "echo_suppress_remaining_s": round(suppress_remaining, 1),
            "sent_content_hashes": len(content),
            "last_reply_age_s": round(now - max(replies), 1) if replies else None,
        }

    return {
        "tracked_chats": len(chats),
        "global_echo_suppress_window_s": _ECHO_SUPPRESS_WINDOW,
        "reply_cooldown_s": _REPLY_COOLDOWN,
        "circuit_breaker_window_s": _CIRCUIT_BREAKER_WINDOW,
        "circuit_breaker_max": _CIRCUIT_BREAKER_MAX,
        "paused": _paused,
        "chats": chats,
    }


@router.get("/hud/status")
async def hud_status(_auth=Depends(verify_auth_or_user)) -> dict:
    """Return HudData for the chat status strip — connection + pause state."""
    server_url = _get_server_url()
    password = _get_password()

    items: list[dict] = []

    # Connection status badge
    if not server_url or not password:
        items.append({
            "type": "badge",
            "label": "Server",
            "value": "Not Configured",
            "icon": "AlertTriangle",
            "variant": "warning",
            "on_click": {"type": "link", "href": "/admin/integrations"},
        })
    else:
        connected = False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{server_url}/api/v1/server/info",
                    params={"password": password},
                )
                connected = r.status_code == 200
        except Exception:
            pass

        if connected:
            items.append({
                "type": "badge",
                "label": "iMessage",
                "value": "Connected",
                "icon": "MessageCircle",
                "variant": "success",
            })
        else:
            items.append({
                "type": "badge",
                "label": "iMessage",
                "value": "Disconnected",
                "icon": "MessageCircle",
                "variant": "danger",
            })

    # Pause state + toggle action
    if _paused:
        items.append({
            "type": "action",
            "label": "Resume",
            "icon": "Play",
            "variant": "success",
            "on_click": {
                "type": "action",
                "endpoint": "/integrations/bluebubbles/resume",
                "method": "POST",
            },
        })
    else:
        items.append({
            "type": "action",
            "label": "Pause",
            "icon": "Pause",
            "variant": "warning",
            "on_click": {
                "type": "action",
                "endpoint": "/integrations/bluebubbles/pause",
                "method": "POST",
                "confirm": "Pause all incoming BlueBubbles messages?",
            },
        })

    return {"visible": True, "items": items}


@router.get("/hud/echo-diagnostics")
async def hud_echo_diagnostics(_auth=Depends(verify_auth_or_user)) -> dict:
    """Return HudData for the echo diagnostics side panel.

    Shows summary badges, per-chat breakdown with cooldown/suppress timers,
    and footer actions. Reads from in-memory echo tracker state — no external calls.
    """
    from integrations.bluebubbles.echo_tracker import (
        _REPLY_COOLDOWN, _CIRCUIT_BREAKER_MAX, _CIRCUIT_BREAKER_WINDOW,
        _ECHO_SUPPRESS_WINDOW,
    )

    # Evict expired entries before reading state — without this,
    # phantom chats and stale hash counts would appear in diagnostics.
    shared_tracker._evict()

    now = time.time()
    items: list[dict] = []

    # Collect all chat GUIDs from both data structures
    all_guids = set(shared_tracker._chat_replies.keys()) | set(shared_tracker._sent_content.keys())

    # Compute summary stats
    circuit_open_count = 0
    suppress_active_count = 0
    for chat_guid in all_guids:
        replies = shared_tracker._chat_replies.get(chat_guid, [])
        recent = [ts for ts in replies if now - ts < _CIRCUIT_BREAKER_WINDOW]
        if len(recent) >= _CIRCUIT_BREAKER_MAX:
            circuit_open_count += 1
        if any(now - ts < _ECHO_SUPPRESS_WINDOW for ts in replies):
            suppress_active_count += 1

    # Summary badges
    items.append({
        "type": "badge",
        "label": "Webhooks",
        "value": "Paused" if _paused else "Active",
        "icon": "Pause" if _paused else "Activity",
        "variant": "warning" if _paused else "success",
    })
    items.append({
        "type": "badge",
        "label": "Tracked Chats",
        "value": str(len(all_guids)),
        "icon": "MessageSquare",
        "variant": "muted" if len(all_guids) == 0 else "accent",
    })
    if circuit_open_count > 0:
        items.append({
            "type": "badge",
            "label": "Circuit Breakers",
            "value": f"{circuit_open_count} open",
            "icon": "AlertOctagon",
            "variant": "danger",
        })
    if suppress_active_count > 0:
        items.append({
            "type": "badge",
            "label": "Suppress Windows",
            "value": f"{suppress_active_count} active",
            "icon": "ShieldAlert",
            "variant": "warning",
        })

    # Divider or empty state
    if all_guids:
        items.append({"type": "divider"})
    else:
        items.append({
            "type": "text",
            "value": "No active echo tracking — all quiet",
            "variant": "muted",
        })

    # Per-chat breakdown (sorted by most recent activity)
    def _last_activity(guid: str) -> float:
        replies = shared_tracker._chat_replies.get(guid, [])
        return max(replies) if replies else 0.0

    for chat_guid in sorted(all_guids, key=_last_activity, reverse=True):
        replies = shared_tracker._chat_replies.get(chat_guid, [])
        content = shared_tracker._sent_content.get(chat_guid, {})
        recent = [ts for ts in replies if now - ts < _CIRCUIT_BREAKER_WINDOW]
        cooldown_remaining = max(0, max((ts + _REPLY_COOLDOWN - now for ts in replies), default=0))
        suppress_remaining = max(0, max((ts + _ECHO_SUPPRESS_WINDOW - now for ts in replies), default=0))
        breaker_open = len(recent) >= _CIRCUIT_BREAKER_MAX

        # Short label — last segment of GUID for readability
        short_label = chat_guid.split(";")[-1] if ";" in chat_guid else chat_guid[-12:]

        chat_parts: list[dict] = []
        chat_parts.append({
            "type": "badge",
            "label": "Replies",
            "value": f"{len(recent)}/{_CIRCUIT_BREAKER_MAX}",
            "variant": "danger" if breaker_open else ("warning" if len(recent) > 0 else "muted"),
        })
        if cooldown_remaining > 0:
            chat_parts.append({
                "type": "badge",
                "label": "Cooldown",
                "value": f"{cooldown_remaining:.0f}s",
                "icon": "Clock",
                "variant": "warning",
            })
        if suppress_remaining > 0:
            chat_parts.append({
                "type": "badge",
                "label": "Suppress",
                "value": f"{suppress_remaining:.0f}s",
                "icon": "ShieldAlert",
                "variant": "warning",
            })
        if content:
            chat_parts.append({
                "type": "badge",
                "label": "Hashes",
                "value": str(len(content)),
                "variant": "muted",
            })

        items.append({
            "type": "group",
            "label": short_label,
            "items": chat_parts,
        })

    # Divider + footer
    items.append({"type": "divider"})
    items.append({
        "type": "action",
        "label": "Admin Integrations",
        "icon": "Settings",
        "variant": "muted",
        "on_click": {"type": "link", "href": "/admin/integrations"},
    })
    if _paused:
        items.append({
            "type": "action",
            "label": "Resume Webhooks",
            "icon": "Play",
            "variant": "success",
            "on_click": {
                "type": "action",
                "endpoint": "/integrations/bluebubbles/resume",
                "method": "POST",
            },
        })
    else:
        items.append({
            "type": "action",
            "label": "Pause Webhooks",
            "icon": "Pause",
            "variant": "warning",
            "on_click": {
                "type": "action",
                "endpoint": "/integrations/bluebubbles/pause",
                "method": "POST",
                "confirm": "Pause all incoming BlueBubbles messages?",
            },
        })

    return {"visible": True, "items": items}


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

    from app.security.prompt_sanitize import sanitize_unicode
    text = sanitize_unicode((data.get("text") or "").strip())
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

    # Cross-device duplicate dedup — iCloud delivers the same iMessage twice
    # to the BB webhook (once is_from_me=True, once is_from_me=False from the
    # contact's number) with DIFFERENT message GUIDs, so the GUID dedup misses
    # them. Match by (chat_guid, text) inside a short window.
    if _content_dedup.check_and_record(chat_guid, text):
        logger.info(
            "BB webhook: duplicate content for chat %s (is_from_me=%s), ignoring",
            chat_guid, is_from_me,
        )
        return {"status": "ignored", "reason": "duplicate_content"}

    # Content-based echo detection — catches our own messages regardless of
    # is_from_me flag.  This is the primary echo defense; it compares incoming
    # text against all text we recently sent to this chat (normalized, not popped).
    if shared_tracker.is_own_content(chat_guid, text):
        logger.info("BB webhook: echo detected (content match), chat_guid=%s is_from_me=%s",
                    chat_guid, is_from_me)
        return {"status": "ignored", "reason": "echo_content"}

    # Legacy echo check — GUID or text hash (popped on match, is_from_me only)
    if is_from_me and shared_tracker.is_echo(msg_guid, text):
        logger.info("BB webhook: echo detected (guid/hash match), guid=%s", msg_guid)
        return {"status": "ignored", "reason": "echo"}

    # NOTE: Reply cooldown (in_reply_cooldown) removed.  It blocked ALL
    # is_from_me messages for 2 minutes after every bot reply, preventing
    # the user from using wake words.  Content-based echo detection
    # (is_own_content above) + GUID-based detection (is_echo) are the real
    # defenses.  The circuit breaker below is the safety net against loops.

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
    # Sender display name is resolved per-binding below (needs binding.display_name)

    # Read BB credentials
    from integrations.bluebubbles.config import settings as bb_settings
    server_url = bb_settings.BLUEBUBBLES_SERVER_URL
    password = bb_settings.BLUEBUBBLES_PASSWORD

    # Extra custom wake words (additive, on top of per-channel bot name/id)
    extra_wake_words = _parse_extra_wake_words(bb_settings.BB_WAKE_WORDS)
    echo_suppress_window = bb_settings.BB_ECHO_SUPPRESS_WINDOW

    results = []
    for channel, binding in pairs:
        session_id = await ensure_active_session(db, channel)

        # Per-binding config from dispatch_config
        dc = binding.dispatch_config or {}
        use_bot_wake = dc.get("use_bot_wake_word", True)
        per_binding_words = _parse_extra_wake_words(dc.get("extra_wake_words", ""))
        # Per-binding echo suppress window override (empty string = use global)
        binding_echo_window = dc.get("echo_suppress_window", "")
        effective_echo_window = float(binding_echo_window) if binding_echo_window not in ("", None) else echo_suppress_window
        # Per-binding send method override (empty = use global default)
        binding_send_method = dc.get("send_method", "") or None

        binding_text_footer = dc.get("text_footer", "") or ""
        binding_typing = dc.get("typing_indicator", True)
        dispatch_config = {
            "type": "bluebubbles",
            "chat_guid": chat_guid,
            "server_url": server_url,
            "password": password,
            "typing_indicator": binding_typing,
        }
        if binding_send_method:
            dispatch_config["send_method"] = binding_send_method
        if binding_text_footer:
            dispatch_config["text_footer"] = binding_text_footer

        # Resolve sender display name early so it's available for content prefixes.
        # Group chats (chat_guid without ";-;") have multiple participants, so
        # ``binding.display_name`` (which labels the WHOLE chat) must NOT be used
        # as a per-message sender — it would collapse every speaker into the
        # same name and the agent could not tell people apart. For 1:1 chats
        # ``binding.display_name`` remains a useful fallback when the BB handle
        # has no contact info.
        _is_group_chat = ";-;" not in chat_guid
        _handle_address = (handle.get("address") or "").strip()
        if _is_group_chat:
            sender_display = (
                handle.get("displayName")
                or _format_handle_name(handle)
                or (_handle_address if not is_from_me else None)
            )
        else:
            sender_display = (
                handle.get("displayName")
                or _format_handle_name(handle)
                or binding.display_name
                or (_handle_address if not is_from_me else None)
            )
        # Label used in message content so the LLM can distinguish speakers.
        # is_from_me → "Me", otherwise → contact's display name or raw address.
        # In group chats, append the address as a stable disambiguator when the
        # display name doesn't already contain it — so two participants who
        # share a first name don't blur into one identity in the agent's view.
        if is_from_me:
            _sender_label = "Me"
        else:
            _sender_label = sender_display or sender
            if (
                _is_group_chat
                and _handle_address
                and _sender_label
                and _handle_address not in _sender_label
            ):
                _sender_label = f"{_sender_label} ({_handle_address})"

        # Sender filtering: for 1:1 chats, only the bound contact's messages
        # should trigger the bot.  Messages from other phone numbers (e.g. the
        # user texting from a secondary device) are stored passively.
        _unexpected_sender = False
        if not is_from_me:
            _expected = _expected_sender_from_guid(chat_guid)
            if _expected:
                sender_addr = (handle.get("address") or "").strip()
                if sender_addr and _normalize_address(sender_addr) != _expected:
                    _unexpected_sender = True
                    logger.info(
                        "BB webhook: unexpected sender %s (expected %s), storing passively",
                        sender_addr, _expected,
                    )

        if _unexpected_sender:
            # Not from the expected contact — store passively regardless of settings
            run_agent = False
            content = f"[{_sender_label}]: {text}"
        elif not channel.require_mention:
            # No mention required
            if is_from_me:
                # Human texting from their own phone — always active
                run_agent = True
                content = f"[Me]: {text}"
            elif shared_tracker.in_echo_suppress(chat_guid, window=effective_echo_window):
                # Suppress if we just replied (catches echoed bot messages
                # that iMessage modified, breaking content hash)
                logger.info("BB webhook: echo suppress (no-mention path), chat_guid=%s", chat_guid)
                run_agent = False
                content = f"[{_sender_label}]: {text}"
            else:
                run_agent = True
                content = f"[{_sender_label}]: {text}"
        else:
            # require_mention is True — check wake words for ALL messages
            # (including is_from_me so the user can text in monitored chats
            # without accidentally triggering the bot)
            wake_words = per_binding_words + extra_wake_words
            if use_bot_wake:
                wake_words = _bot_wake_words(channel.bot_id) + wake_words
            text_lower = text.lower()
            mentioned = any(w in text_lower for w in wake_words) if wake_words else False
            if mentioned:
                # Wake word matched — skip echo suppress for is_from_me
                # (user deliberately typed the wake word)
                if not is_from_me and shared_tracker.in_echo_suppress(chat_guid, window=effective_echo_window):
                    logger.info("BB webhook: echo suppress (wake word path), chat_guid=%s", chat_guid)
                    run_agent = False
                    content = f"[{_sender_label}]: {text}"
                else:
                    run_agent = True
                    content = f"[{_sender_label}]: {text}"
            else:
                # Passive — store with sender prefix, no agent run
                run_agent = False
                content = f"[{_sender_label}]: {text}"

        # Sender metadata — matches the Slack/Discord pattern so the
        # agent context builder can attribute messages properly in group
        # chats. ``message_guid`` is included so tools (e.g. reactions)
        # can reference the specific inbound message.
        extra_metadata: dict = {
            "sender_id": f"bb:{handle.get('address', 'unknown')}",
            "sender_type": "human",
            "is_from_me": is_from_me,
            "message_guid": data.get("guid", ""),
        }
        if sender_display:
            extra_metadata["sender_display_name"] = sender_display
        if binding.display_name:
            extra_metadata["binding_display_name"] = binding.display_name

        result = await utils.inject_message(
            session_id, content, source="bluebubbles",
            run_agent=run_agent, notify=False,
            dispatch_config=dispatch_config,
            extra_metadata=extra_metadata,
            db=db,
        )
        results.append(result)

    logger.info("BB webhook: processed %s from %s → %d channel(s), run_agent=%s",
                chat_guid, sender, len(results), any(r.get("task_id") for r in results))

    # Persist GUID dedup state to DB (batched — only on successful processing)
    await _guid_dedup.save_to_db()

    # Best-effort: re-mark the chat as unread on the Mac so iCloud syncs
    # the unread state to the iPhone, restoring the push notification.
    # Skip for is_from_me messages — we never need to notify the user about
    # their own outgoing text. See bb_api.mark_chat_unread for full context.
    if not is_from_me and server_url and password:
        try:
            from integrations.bluebubbles.bb_api import mark_chat_unread
            async with httpx.AsyncClient(timeout=5.0) as _bb:
                await mark_chat_unread(_bb, server_url, password, chat_guid)
        except Exception:
            # Notification restoration is non-essential — never let it
            # break webhook processing.
            logger.debug("BB markUnread post-processing failed", exc_info=True)

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
