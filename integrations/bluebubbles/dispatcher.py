"""BlueBubbles task result dispatcher.

Sends agent responses back to iMessage chats via the BB REST API.
Registers with the dispatcher registry at import time.
"""
from __future__ import annotations

import logging
import uuid

import httpx

from app.agent.dispatchers import register
from integrations.bluebubbles.bb_api import send_text
from integrations.bluebubbles.echo_tracker import shared_tracker

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)

# Max iMessage text length (Apple doesn't hard-enforce, but very long
# messages get split by the client; 20k is a safe single-bubble limit).
_MAX_MSG_LEN = 20000


def _split_text(text: str, max_len: int = _MAX_MSG_LEN) -> list[str]:
    """Split text into chunks that fit in a single iMessage bubble."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def _bb_send(
    server_url: str, password: str, chat_guid: str, text: str,
    *, method: str | None = None,
) -> bool:
    """Send a text message via BB API. Returns True on success."""
    temp_guid = str(uuid.uuid4())
    shared_tracker.track_sent(temp_guid, text, chat_guid=chat_guid)
    # Persist reply state to DB so circuit breaker survives restarts
    await shared_tracker.save_to_db()
    result = await send_text(
        _http, server_url, password, chat_guid, text,
        temp_guid=temp_guid,
        method=method,
    )
    return result is not None


class BlueBubblesDispatcher:
    async def notify_start(self, task) -> None:
        """No-op for iMessage — there's no typing indicator API and sending
        a real text message creates echo noise + wastes a circuit breaker slot."""
        pass

    async def deliver(
        self, task, result: str,
        client_actions: list[dict] | None = None,
        extra_metadata: dict | None = None,
    ) -> None:
        cfg = task.dispatch_config or {}
        server_url = cfg.get("server_url")
        password = cfg.get("password")
        chat_guid = cfg.get("chat_guid")
        send_method = cfg.get("send_method") or None

        if not all((server_url, password, chat_guid)):
            logger.warning(
                "BlueBubblesDispatcher: missing config for task %s (need server_url, password, chat_guid)",
                task.id,
            )
            return

        text = result
        if extra_metadata and extra_metadata.get("delegated_by_display"):
            text = f"[Delegated by {extra_metadata['delegated_by_display']}]\n{text}"

        footer = cfg.get("text_footer")
        if footer:
            text = f"{text}\n{footer}"

        chunks = _split_text(text)
        for chunk in chunks:
            if not await _bb_send(server_url, password, chat_guid, chunk, method=send_method):
                logger.error("BlueBubblesDispatcher.deliver failed for task %s chat %s", task.id, chat_guid)
                return

        from app.services.sessions import store_dispatch_echo
        await store_dispatch_echo(
            task.session_id, task.client_id, task.bot_id, result,
            extra_metadata=extra_metadata,
        )

    async def post_message(
        self, dispatch_config: dict, text: str, *,
        bot_id: str | None = None, reply_in_thread: bool = True,
        username: str | None = None, icon_emoji: str | None = None,
        icon_url: str | None = None,
        client_actions: list[dict] | None = None,
        extra_metadata: dict | None = None,
    ) -> bool:
        server_url = dispatch_config.get("server_url")
        password = dispatch_config.get("password")
        chat_guid = dispatch_config.get("chat_guid")
        send_method = dispatch_config.get("send_method") or None

        if not all((server_url, password, chat_guid)):
            logger.warning("BlueBubblesDispatcher.post_message: missing config")
            return False

        footer = dispatch_config.get("text_footer")
        if footer:
            text = f"{text}\n{footer}"

        chunks = _split_text(text)
        for chunk in chunks:
            if not await _bb_send(server_url, password, chat_guid, chunk, method=send_method):
                return False
        return True

    async def request_approval(
        self, *, dispatch_config: dict, approval_id: str,
        bot_id: str, tool_name: str, arguments: dict,
        reason: str | None,
    ) -> None:
        """Send a text-based tool approval request via iMessage.

        iMessage doesn't support interactive buttons, so we send a plain
        text message describing the pending approval. The user must approve
        via the web UI or API.
        """
        import json as _json

        server_url = dispatch_config.get("server_url")
        password = dispatch_config.get("password")
        chat_guid = dispatch_config.get("chat_guid")
        send_method = dispatch_config.get("send_method") or None
        if not all((server_url, password, chat_guid)):
            return

        args_preview = _json.dumps(arguments, indent=2)[:500]
        text = (
            f"Tool approval required\n"
            f"Bot: {bot_id} | Tool: {tool_name}\n"
            f"Reason: {reason or 'Policy requires approval'}\n"
            f"Args: {args_preview}\n\n"
            f"Approve via the web UI (approval ID: {approval_id})"
        )
        await _bb_send(server_url, password, chat_guid, text, method=send_method)


register("bluebubbles", BlueBubblesDispatcher())
