"""BlueBubbles transport boundary tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from integrations.bluebubbles import transport
from integrations.bluebubbles.target import BlueBubblesTarget

pytestmark = pytest.mark.asyncio


def _target() -> BlueBubblesTarget:
    return BlueBubblesTarget(
        chat_guid="iMessage;-;+15551234",
        server_url="http://bb.example.com",
        password="hunter2",
        send_method="apple-script",
    )


def test_call_result_ok_receipt_uses_guid() -> None:
    receipt = transport.BlueBubblesCallResult.ok({"guid": "msg-1"}).to_receipt()

    assert receipt.success is True
    assert receipt.external_id == "msg-1"


def test_call_result_failed_receipt_preserves_retryable() -> None:
    receipt = transport.BlueBubblesCallResult.failed(
        "temporarily down",
        retryable=True,
    ).to_receipt()

    assert receipt.success is False
    assert receipt.error == "temporarily down"
    assert receipt.retryable is True


async def test_send_text_maps_api_success() -> None:
    target = _target()

    with patch.object(
        transport.bb_api,
        "send_text",
        new_callable=AsyncMock,
        return_value={"guid": "msg-1"},
    ) as mock_send:
        result = await transport.send_text(target, "hello", temp_guid="tmp-1")

    assert result.success is True
    assert result.data == {"guid": "msg-1"}
    mock_send.assert_awaited_once_with(
        transport._http,
        "http://bb.example.com",
        "hunter2",
        "iMessage;-;+15551234",
        "hello",
        temp_guid="tmp-1",
        method="apple-script",
    )


async def test_send_text_maps_api_failure_to_retryable() -> None:
    with patch.object(
        transport.bb_api,
        "send_text",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await transport.send_text(_target(), "hello", temp_guid="tmp-1")

    assert result.success is False
    assert result.retryable is True
    assert "send_text failed" in (result.error or "")


async def test_set_typing_delegates_to_api() -> None:
    target = _target()

    with patch.object(
        transport.bb_api,
        "set_typing",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_typing:
        result = await transport.set_typing(target)

    assert result is True
    mock_typing.assert_awaited_once_with(
        transport._http,
        "http://bb.example.com",
        "hunter2",
        "iMessage;-;+15551234",
    )
