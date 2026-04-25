"""Reusable ChannelRenderer contract assertions for integration tests."""
from __future__ import annotations

import uuid
from collections.abc import Iterable

from integrations.sdk import ChannelEvent, ChannelEventKind, DeliveryReceipt
from app.domain.payloads import HeartbeatTickPayload


def assert_renderer_capabilities_match_manifest(
    *,
    integration_id: str,
    renderer,
    manifest: dict,
) -> None:
    """Assert renderer runtime capabilities match manifest truth."""
    manifest_caps = frozenset(manifest["capabilities"])
    renderer_caps = frozenset(cap.value for cap in renderer.capabilities)

    assert renderer.integration_id == integration_id
    assert renderer_caps == manifest_caps


def assert_renderer_supports_capabilities(
    *,
    manifest: dict,
    expected: Iterable[str],
) -> None:
    """Assert the manifest advertises required public capabilities."""
    manifest_caps = frozenset(manifest["capabilities"])
    for capability in expected:
        assert capability in manifest_caps


def unsupported_heartbeat_event() -> ChannelEvent:
    """Return an event most chat renderers should skip, not fail."""
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.HEARTBEAT_TICK,
        payload=HeartbeatTickPayload(bot_id="contract-test-bot"),
    )


async def assert_renderer_skips_unsupported_event(
    renderer,
    target,
    *,
    event: ChannelEvent | None = None,
) -> DeliveryReceipt:
    """Assert unsupported events are delivered as skips, not failures."""
    receipt = await renderer.render(event or unsupported_heartbeat_event(), target)

    assert receipt.success is True
    assert receipt.skip_reason
    return receipt


async def assert_renderer_delete_attachment_empty_metadata_false(
    renderer,
    target,
) -> None:
    """Assert direct attachment delete has a safe false default."""
    assert await renderer.delete_attachment({}, target) is False


__all__ = [
    "assert_renderer_capabilities_match_manifest",
    "assert_renderer_delete_attachment_empty_metadata_false",
    "assert_renderer_skips_unsupported_event",
    "assert_renderer_supports_capabilities",
    "unsupported_heartbeat_event",
]
