"""Live attachment vision routing checks.

These tests use a real vision-capable provider. They prove that current-turn
image uploads are read from inline model input without an attachment-analysis
tool call, while previous-image reanalysis can deliberately load the old
attachment back into model context.
"""

from __future__ import annotations

import base64
import os
import struct
import zlib

import pytest

from ..harness.client import E2EClient


VISION_PROVIDER_ID = os.environ.get("E2E_VISION_PROVIDER_ID", "chatgpt-subscription")
VISION_MODEL = os.environ.get("E2E_VISION_MODEL", "gpt-5.4-mini")


def _solid_png_base64(rgb: tuple[int, int, int], *, size: int = 16) -> str:
    """Return a base64 PNG for a simple solid RGB square."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw_rows = b"".join(
        b"\x00" + bytes(rgb) * size
        for _ in range(size)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw_rows))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode("ascii")


def _trace_events(trace: dict, *, kind: str | None = None, event_type: str | None = None) -> list[dict]:
    events = list(trace.get("events") or [])
    if kind is not None:
        events = [event for event in events if event.get("kind") == kind]
    if event_type is not None:
        events = [event for event in events if event.get("event_type") == event_type]
    return events


def _tool_names(trace: dict) -> list[str]:
    return [
        event.get("tool_name") or ""
        for event in _trace_events(trace, kind="tool_call")
        if event.get("tool_name")
    ]


def _routing_events(trace: dict) -> list[dict]:
    return [
        event.get("data") or {}
        for event in _trace_events(trace, kind="trace_event", event_type="attachment_vision_routing")
    ]


@pytest.fixture
async def vision_bot(client: E2EClient) -> str:
    provider_resp = await client.get(f"/api/v1/admin/providers/{VISION_PROVIDER_ID}")
    if provider_resp.status_code == 404:
        pytest.skip(f"Provider {VISION_PROVIDER_ID!r} is not configured")
    provider_resp.raise_for_status()

    oauth_resp = await client.get(f"/api/v1/admin/providers/openai-oauth/status/{VISION_PROVIDER_ID}")
    if oauth_resp.status_code == 200 and not oauth_resp.json().get("connected"):
        pytest.skip(
            f"Provider {VISION_PROVIDER_ID!r} is configured but has no connected OAuth token"
        )

    models_resp = await client.get(f"/api/v1/admin/providers/{VISION_PROVIDER_ID}/models")
    models_resp.raise_for_status()
    models = models_resp.json()
    model_row = next((row for row in models if row.get("model_id") == VISION_MODEL), None)
    if model_row and model_row.get("supports_vision") is False:
        pytest.fail(f"{VISION_MODEL!r} is configured with supports_vision=false")

    bot_id = await client.create_temp_bot(
        model=VISION_MODEL,
        provider_id=VISION_PROVIDER_ID,
        tools=["view_attachment", "describe_attachment", "list_attachments"],
        system_prompt=(
            "You are a vision routing test bot. For an image attached to the current "
            "user message, inspect the inline image directly and do not call attachment "
            "tools. For a previous image, use view_attachment to load the old pixels "
            "into your current context before answering. Reply tersely."
        ),
    )
    yield bot_id
    await client.delete_bot(bot_id)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_current_turn_image_is_read_inline_without_attachment_tool(
    client: E2EClient,
    vision_bot: str,
) -> None:
    image_b64 = _solid_png_base64((255, 0, 0))
    channel_id = client.new_channel_id()

    resp = await client.chat(
        "What is the dominant color of the attached image? Answer with exactly one color word. "
        "Do not use any tools.",
        bot_id=vision_bot,
        channel_id=channel_id,
        attachments=[{
            "type": "image",
            "content": image_b64,
            "mime_type": "image/png",
            "name": "red-square.png",
        }],
        timeout=90,
    )

    assert "red" in resp.response.lower(), f"Expected direct vision answer, got: {resp.response!r}"

    trace = await client.get_trace_detail(resp.raw["turn_id"])
    tool_names = _tool_names(trace)
    assert "describe_attachment" not in tool_names
    assert "view_attachment" not in tool_names
    routing = _routing_events(trace)
    assert routing, "Expected attachment_vision_routing trace event"
    assert any(
        event.get("source_image_count") == 1
        and event.get("inline_image_count") == 1
        and event.get("stripped_image_count") == 0
        and event.get("model_supports_vision") is True
        for event in routing
    ), routing


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_previous_attachment_can_be_reanalyzed_by_loading_pixels(
    client: E2EClient,
    vision_bot: str,
) -> None:
    image_b64 = _solid_png_base64((0, 0, 255))
    channel_id = client.new_channel_id()

    first = await client.chat(
        "Store this image for a later question. Reply exactly: stored.",
        bot_id=vision_bot,
        channel_id=channel_id,
        attachments=[{
            "type": "image",
            "content": image_b64,
            "mime_type": "image/png",
            "name": "blue-square.png",
        }],
        timeout=90,
    )
    assert "stored" in first.response.lower()

    second = await client.chat(
        "Look back at the previous image. Use view_attachment to load the previous "
        "attachment into your current context, then answer with exactly one dominant "
        "color word.",
        bot_id=vision_bot,
        channel_id=channel_id,
        timeout=120,
    )

    assert "blue" in second.response.lower(), f"Expected reanalysis answer, got: {second.response!r}"

    trace = await client.get_trace_detail(second.raw["turn_id"])
    tool_names = _tool_names(trace)
    assert "view_attachment" in tool_names, tool_names
    assert "describe_attachment" not in tool_names, tool_names
    routing = _routing_events(trace)
    assert any(
        event.get("source_image_count") == 1
        and event.get("inline_image_count") == 1
        and event.get("stripped_image_count") == 0
        for event in routing
    ), routing
