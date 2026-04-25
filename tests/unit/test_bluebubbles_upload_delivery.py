"""BlueBubbles upload delivery boundary tests."""
from __future__ import annotations

import base64

import pytest

from integrations.bluebubbles.target import BlueBubblesTarget
from integrations.bluebubbles.transport import BlueBubblesCallResult
from integrations.bluebubbles.upload_delivery import BlueBubblesUploadDelivery
from integrations.sdk import DeliveryReceipt, UploadFile, UploadImage

pytestmark = pytest.mark.asyncio


def _target() -> BlueBubblesTarget:
    return BlueBubblesTarget(
        chat_guid="iMessage;-;+15551234",
        server_url="http://bb.example.com",
        password="hunter2",
    )


async def test_upload_image_sends_attachment() -> None:
    calls: list[tuple[str, str]] = []

    async def send_attachment(target, file_path, filename):
        calls.append((file_path, filename))
        return BlueBubblesCallResult.ok({"guid": "att-1"})

    async def send_text(*args, **kwargs):
        raise AssertionError("description was not expected")

    delivery = BlueBubblesUploadDelivery(
        send_attachment=send_attachment,
        send_text=send_text,
    )

    receipt = await delivery.render(
        UploadImage(
            image_data_b64=base64.b64encode(b"png").decode("ascii"),
            filename="image.png",
        ),
        _target(),
    )

    assert receipt.success is True
    assert calls[0][1] == "image.png"


async def test_upload_description_is_best_effort() -> None:
    text_calls: list[str] = []

    async def send_attachment(target, file_path, filename):
        return BlueBubblesCallResult.ok({"guid": "att-1"})

    async def send_text(target, text, **kwargs):
        text_calls.append(text)
        return DeliveryReceipt.failed("description failed", retryable=True)

    delivery = BlueBubblesUploadDelivery(
        send_attachment=send_attachment,
        send_text=send_text,
    )

    receipt = await delivery.render(
        UploadFile(
            file_data_b64=base64.b64encode(b"hello").decode("ascii"),
            filename="notes.txt",
            description="see attached",
        ),
        _target(),
    )

    assert receipt.success is True
    assert text_calls == ["see attached"]


async def test_upload_invalid_base64_fails_permanently() -> None:
    async def send_attachment(*args, **kwargs):
        raise AssertionError("invalid data should not be sent")

    async def send_text(*args, **kwargs):
        raise AssertionError("invalid data should not send a description")

    delivery = BlueBubblesUploadDelivery(
        send_attachment=send_attachment,
        send_text=send_text,
    )

    receipt = await delivery.render(
        UploadFile(file_data_b64="not-base64!", filename="bad.bin"),
        _target(),
    )

    assert receipt.success is False
    assert receipt.retryable is False
    assert "invalid base64" in (receipt.error or "")


async def test_upload_without_data_is_skipped() -> None:
    async def send_attachment(*args, **kwargs):
        raise AssertionError("empty data should not be sent")

    async def send_text(*args, **kwargs):
        raise AssertionError("empty data should not send a description")

    delivery = BlueBubblesUploadDelivery(
        send_attachment=send_attachment,
        send_text=send_text,
    )

    receipt = await delivery.render(UploadImage(image_data_b64=""), _target())

    assert receipt.success is True
    assert "no data" in (receipt.skip_reason or "")


async def test_upload_attachment_failure_is_retryable() -> None:
    async def send_attachment(target, file_path, filename):
        return BlueBubblesCallResult.failed("upload failed", retryable=True)

    async def send_text(*args, **kwargs):
        raise AssertionError("failed upload should not send a description")

    delivery = BlueBubblesUploadDelivery(
        send_attachment=send_attachment,
        send_text=send_text,
    )

    receipt = await delivery.render(
        UploadImage(
            image_data_b64=base64.b64encode(b"png").decode("ascii"),
            filename="image.png",
        ),
        _target(),
    )

    assert receipt.success is False
    assert receipt.retryable is True
    assert receipt.error == "upload failed"
