"""BlueBubbles Socket.IO client — bridges iMessage to the agent server.

Runs as a separate process (like slack_bot.py). Connects to the BB server
via Socket.IO, listens for new messages, and routes them to the agent.

Bot/user disambiguation: Since both bot-sent and human-sent messages appear
as isFromMe=true, we use EchoTracker to identify our own echoes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

# Ensure same-dir imports work regardless of how the process is launched.
_BB_DIR = str(Path(__file__).resolve().parent)
if _BB_DIR not in sys.path:
    sys.path.insert(0, _BB_DIR)

import httpx
import socketio

from echo_tracker import EchoTracker
from bb_api import send_text
from agent_client import (
    AGENT_BASE_URL,
    API_KEY,
    bb_client_id,
    ensure_channel,
    stream_chat,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (from environment)
# ---------------------------------------------------------------------------
BB_SERVER_URL = os.environ.get("BLUEBUBBLES_SERVER_URL", "")
BB_PASSWORD = os.environ.get("BLUEBUBBLES_PASSWORD", "")
DEFAULT_BOT = os.environ.get("BB_DEFAULT_BOT", "default")

# Max concurrent agent requests (prevent flooding)
_MAX_CONCURRENT = 5
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

# Chat GUID → bot_id overrides (populated from router config endpoint)
_chat_bot_map: dict[str, str] = {}

# Global echo tracker instance
_echo = EchoTracker()

# Shared HTTP client for BB API calls
_http = httpx.AsyncClient(timeout=30.0)

# Socket.IO client
sio = socketio.AsyncClient(
    reconnection=True,
    reconnection_attempts=0,  # infinite
    reconnection_delay=1,
    reconnection_delay_max=30,
    logger=False,
)


# ---------------------------------------------------------------------------
# Config refresh
# ---------------------------------------------------------------------------
async def _refresh_config() -> None:
    """Pull per-chat bot mapping from the router config endpoint."""
    global _chat_bot_map
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(
                f"{AGENT_BASE_URL}/integrations/bluebubbles/config",
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            if r.status_code == 200:
                data = r.json()
                _chat_bot_map = data.get("chat_bot_map", {})
    except Exception:
        logger.debug("Config refresh failed (server may not be ready yet)")


def _bot_for_chat(chat_guid: str) -> str:
    """Resolve the bot_id for a given chat, falling back to default."""
    return _chat_bot_map.get(chat_guid, DEFAULT_BOT)


# ---------------------------------------------------------------------------
# Message field extraction
# ---------------------------------------------------------------------------
def _extract_text(message: dict) -> str:
    """Extract plain text from a BB message payload."""
    return (message.get("text") or "").strip()


def _extract_chat_guid(message: dict) -> str | None:
    """Extract the chat GUID from a BB message payload."""
    chats = message.get("chats")
    if chats and isinstance(chats, list) and len(chats) > 0:
        return chats[0].get("guid")
    return message.get("chatGuid")


def _extract_sender(message: dict) -> str:
    """Extract sender handle from the message."""
    handle = message.get("handle")
    if handle and isinstance(handle, dict):
        return handle.get("address", "unknown")
    return str(message.get("handleId") or "unknown")


def _is_group_chat(chat_guid: str) -> bool:
    """Check if a chat GUID represents a group chat.

    BB chat GUIDs use:
      iMessage;-;... for 1:1 chats
      iMessage;+;... for group chats
    """
    return ";+;" in chat_guid


# ---------------------------------------------------------------------------
# Message handling
# ---------------------------------------------------------------------------
async def _handle_message(message: dict) -> None:
    """Process an incoming BB message."""
    text = _extract_text(message)
    if not text:
        return  # Skip empty / attachment-only messages for now

    chat_guid = _extract_chat_guid(message)
    if not chat_guid:
        logger.warning("BB message has no chat GUID: %s", message.get("guid"))
        return

    is_from_me = message.get("isFromMe", False)
    msg_guid = message.get("guid", "")

    if is_from_me:
        # Check if this is our own echo
        if _echo.is_echo(msg_guid, text):
            logger.debug("Skipping echo: %s", msg_guid)
            return
        # Not an echo → it's the human user texting from their phone
        logger.info("Human isFromMe message in chat %s", chat_guid)
    else:
        # In group chats, only respond to external messages if they're
        # directed at the bot (not every random group message).
        # For now we store non-addressed group messages passively.
        if _is_group_chat(chat_guid):
            logger.info("External group message from %s in chat %s (passive)", _extract_sender(message), chat_guid)
            await _store_passive(chat_guid, message, text)
            return
        logger.info("External message from %s in chat %s", _extract_sender(message), chat_guid)

    bot_id = _bot_for_chat(chat_guid)
    client_id = bb_client_id(chat_guid)

    # Build dispatch config so deferred tasks know how to reply
    dispatch_config = {
        "chat_guid": chat_guid,
        "server_url": BB_SERVER_URL,
        "password": BB_PASSWORD,
    }

    # Build sender metadata
    sender = _extract_sender(message) if not is_from_me else "me"
    msg_metadata = {
        "sender": sender,
        "sender_display_name": sender,
        "is_from_me": is_from_me,
        "bb_guid": msg_guid,
    }

    async with _semaphore:
        response_text = await _collect_stream_response(
            message=text,
            bot_id=bot_id,
            client_id=client_id,
            dispatch_type="bluebubbles",
            dispatch_config=dispatch_config,
            msg_metadata=msg_metadata,
        )

    if response_text:
        await _send_reply(chat_guid, response_text)


async def _store_passive(chat_guid: str, message: dict, text: str) -> None:
    """Store a group chat message passively (no agent response triggered)."""
    from agent_client import store_passive_message

    bot_id = _bot_for_chat(chat_guid)
    client_id = bb_client_id(chat_guid)
    sender = _extract_sender(message)
    try:
        await store_passive_message(
            client_id=client_id,
            bot_id=bot_id,
            content=f"[{sender}]: {text}",
            metadata={
                "sender": sender,
                "sender_display_name": sender,
                "bb_guid": message.get("guid", ""),
            },
        )
    except Exception:
        logger.debug("Failed to store passive message for %s", chat_guid, exc_info=True)


async def _collect_stream_response(
    *,
    message: str,
    bot_id: str,
    client_id: str,
    dispatch_type: str,
    dispatch_config: dict,
    msg_metadata: dict,
) -> str | None:
    """Call the agent server streaming endpoint and collect the full response."""
    response_parts: list[str] = []
    try:
        async for event in stream_chat(
            message=message,
            bot_id=bot_id,
            client_id=client_id,
            dispatch_type=dispatch_type,
            dispatch_config=dispatch_config,
            msg_metadata=msg_metadata,
        ):
            etype = event.get("type")
            if etype == "text_delta":
                response_parts.append(event.get("delta", ""))
            elif etype == "response":
                # Final response event — use its text directly
                return event.get("text", "".join(response_parts))
    except Exception:
        logger.exception("Agent stream failed for client_id=%s", client_id)
        return None

    return "".join(response_parts) if response_parts else None


async def _send_reply(chat_guid: str, text: str) -> None:
    """Send a reply back via the BB API and track it in the echo tracker."""
    temp_guid = str(uuid.uuid4())
    _echo.track_sent(temp_guid, text)
    result = await send_text(
        _http, BB_SERVER_URL, BB_PASSWORD, chat_guid, text, temp_guid=temp_guid,
    )
    if not result:
        logger.error("Failed to send reply to chat %s", chat_guid)


# ---------------------------------------------------------------------------
# Socket.IO event handlers
# ---------------------------------------------------------------------------
@sio.on("connect")
async def on_connect():
    logger.info("Connected to BlueBubbles server")
    await _refresh_config()


@sio.on("disconnect")
async def on_disconnect():
    logger.warning("Disconnected from BlueBubbles server")


@sio.on("new-message")
async def on_new_message(data):
    """Handle incoming iMessage."""
    try:
        # BB may send data as a dict or wrapped in a list
        if isinstance(data, list) and data:
            message = data[0] if isinstance(data[0], dict) else {}
        elif isinstance(data, dict):
            message = data
        else:
            logger.warning("Unexpected new-message data type: %s", type(data).__name__)
            return
        await _handle_message(message)
    except Exception:
        logger.exception("Error handling BB message")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    if not BB_SERVER_URL or not BB_PASSWORD:
        logger.error("BLUEBUBBLES_SERVER_URL and BLUEBUBBLES_PASSWORD must be set")
        sys.exit(1)

    logger.info("Connecting to BlueBubbles at %s", BB_SERVER_URL)

    # Socket.IO connection with auth
    await sio.connect(
        BB_SERVER_URL,
        auth={"password": BB_PASSWORD},
        transports=["websocket"],
    )
    # Keep running
    await sio.wait()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(main())
