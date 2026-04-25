"""BlueBubbles durable ``NEW_MESSAGE`` delivery."""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from integrations.sdk import ChannelEvent, DeliveryReceipt
from integrations.bluebubbles import transport
from integrations.bluebubbles.echo_tracker import shared_tracker
from integrations.bluebubbles.target import BlueBubblesTarget

_MAX_MSG_LEN = 20000

SendText = Callable[..., Awaitable[Any]]


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


def _apply_footer(text: str, target: BlueBubblesTarget) -> str:
    """Append the per-target text footer if configured."""
    if target.text_footer:
        return f"{text}\n{target.text_footer}"
    return text


class BlueBubblesMessageDelivery:
    """Deliver durable BlueBubbles ``NEW_MESSAGE`` events."""

    def __init__(
        self,
        *,
        send_text=None,
        tracker=None,
    ) -> None:
        self._send_text = send_text or transport.send_text
        self._tracker = tracker or shared_tracker

    async def render(
        self,
        event: ChannelEvent,
        target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        payload = event.payload
        msg = getattr(payload, "message", None)
        if msg is None:
            return DeliveryReceipt.skipped("new_message without message payload")

        role = getattr(msg, "role", "") or ""
        if role in ("tool", "system"):
            return DeliveryReceipt.skipped(f"bb skips internal role={role}")

        if role == "user":
            msg_metadata = getattr(msg, "metadata", None) or {}
            if msg_metadata.get("source") == "bluebubbles":
                return DeliveryReceipt.skipped(
                    "bb skips own-origin user message (echo prevention)"
                )

        text = (getattr(msg, "content", "") or "").strip()
        if not text:
            return DeliveryReceipt.skipped("new_message with empty content")

        return await self.send_text(target, text)

    async def send_text(
        self,
        target: BlueBubblesTarget,
        text: str,
        *,
        failure_message: str | None = None,
    ) -> DeliveryReceipt:
        """Send text with footer/chunking and echo tracking."""
        text = _apply_footer(text, target)
        for chunk in _split_text(text):
            result = await self._send_chunk(target, chunk)
            if not result.success:
                return DeliveryReceipt.failed(
                    failure_message or f"BB send_text failed for chat {target.chat_guid}",
                    retryable=result.retryable,
                )
        return DeliveryReceipt.ok()

    async def _send_chunk(
        self,
        target: BlueBubblesTarget,
        text: str,
    ):
        temp_guid = str(uuid.uuid4())
        self._tracker.track_sent(temp_guid, text, chat_guid=target.chat_guid)
        await self._tracker.save_to_db()

        return await self._send_text(target, text, temp_guid=temp_guid)


__all__ = [
    "BlueBubblesMessageDelivery",
    "_apply_footer",
    "_split_text",
]
