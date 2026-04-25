"""BlueBubbles outbound file/image upload delivery."""
from __future__ import annotations

import base64
import os
import tempfile
from collections.abc import Awaitable, Callable

from integrations.sdk import DeliveryReceipt, UploadFile, UploadImage
from integrations.bluebubbles import transport
from integrations.bluebubbles.target import BlueBubblesTarget

SendAttachment = Callable[[BlueBubblesTarget, str, str], Awaitable]
SendText = Callable[..., Awaitable[DeliveryReceipt]]


class BlueBubblesUploadDelivery:
    """Deliver ``UploadImage`` and ``UploadFile`` actions."""

    def __init__(
        self,
        *,
        send_attachment: SendAttachment | None = None,
        send_text: SendText,
    ) -> None:
        self._send_attachment = send_attachment or transport.send_attachment
        self._send_text = send_text

    async def render(
        self,
        action: UploadImage | UploadFile,
        target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        data_b64 = (
            getattr(action, "image_data_b64", None)
            or getattr(action, "file_data_b64", "")
        )
        if not data_b64:
            return DeliveryReceipt.skipped("upload action with no data")

        filename = action.filename
        try:
            raw = base64.b64decode(data_b64)
        except Exception:
            return DeliveryReceipt.failed("invalid base64 data", retryable=False)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp:
                tmp.write(raw)
                tmp_path = tmp.name

            result = await self._send_attachment(target, tmp_path, filename)
            if result.success:
                desc = getattr(action, "description", None)
                if desc:
                    await self._send_text(target, desc)
                return DeliveryReceipt.ok()
            return result.to_receipt()
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)


__all__ = ["BlueBubblesUploadDelivery"]
