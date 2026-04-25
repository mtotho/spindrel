"""BlueBubbles renderer transport.

Renderer delivery wants receipt-shaped results so callers can decide whether
the outbox should retry. The lower-level ``bb_api`` helpers stay reusable for
routers/tools and continue returning BlueBubbles response dictionaries.
"""
from __future__ import annotations

import httpx

from integrations.sdk import DeliveryReceipt
from integrations.bluebubbles import bb_api
from integrations.bluebubbles.target import BlueBubblesTarget

_http = httpx.AsyncClient(timeout=90.0)


class BlueBubblesCallResult:
    """Success/failure carrier for BlueBubbles renderer calls."""

    __slots__ = ("success", "data", "error", "retryable")

    def __init__(
        self,
        success: bool,
        *,
        data: dict | None = None,
        error: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.success = success
        self.data = data
        self.error = error
        self.retryable = retryable

    @classmethod
    def ok(cls, data: dict | None = None) -> "BlueBubblesCallResult":
        return cls(True, data=data or {})

    @classmethod
    def failed(cls, error: str, *, retryable: bool) -> "BlueBubblesCallResult":
        return cls(False, error=error, retryable=retryable)

    def to_receipt(self) -> DeliveryReceipt:
        if self.success:
            external_id = (self.data or {}).get("guid") or (self.data or {}).get("id")
            return DeliveryReceipt.ok(external_id=external_id)
        return DeliveryReceipt.failed(
            self.error or "unknown",
            retryable=self.retryable,
        )


async def send_text(
    target: BlueBubblesTarget,
    text: str,
    *,
    temp_guid: str,
) -> BlueBubblesCallResult:
    result = await bb_api.send_text(
        _http,
        target.server_url,
        target.password,
        target.chat_guid,
        text,
        temp_guid=temp_guid,
        method=target.send_method,
    )
    if result is None:
        return BlueBubblesCallResult.failed(
            f"BB send_text failed for chat {target.chat_guid}",
            retryable=True,
        )
    return BlueBubblesCallResult.ok(result)


async def send_attachment(
    target: BlueBubblesTarget,
    file_path: str,
    filename: str,
) -> BlueBubblesCallResult:
    result = await bb_api.send_attachment(
        _http,
        target.server_url,
        target.password,
        target.chat_guid,
        file_path,
        filename,
    )
    if result is None:
        return BlueBubblesCallResult.failed(
            f"BB send_attachment failed for chat {target.chat_guid}",
            retryable=True,
        )
    return BlueBubblesCallResult.ok(result)


async def set_typing(target: BlueBubblesTarget) -> bool:
    return await bb_api.set_typing(
        _http,
        target.server_url,
        target.password,
        target.chat_guid,
    )


__all__ = [
    "BlueBubblesCallResult",
    "send_attachment",
    "send_text",
    "set_typing",
]
