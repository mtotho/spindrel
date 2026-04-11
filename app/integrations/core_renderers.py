"""Core renderers — the four integration-agnostic `ChannelRenderer`s.

These are the typed-bus replacements for `_NoneDispatcher`, `_WebhookDispatcher`,
and `_InternalDispatcher` from `app/agent/dispatchers.py`, plus a new
`WebRenderer` that makes "web UI origin" first-class instead of "the absence
of a dispatch_config". They register themselves at module import time so the
renderer registry is populated before `IntegrationDispatcherTask` instances
spin up in `app/main.py` lifespan.

The four renderers:

- `NoneRenderer` — null delivery. Capability set is empty, so capability
  gating skips every kind. Replaces `_NoneDispatcher`.

- `WebRenderer` — the web UI consumes the bus directly via SSE; renderer
  exists purely so the registry has a routing entry for `WebTarget` and so
  the web UI's capability set is declared in code.

- `WebhookRenderer` — POSTs JSON `{"task_id": ..., "result": ...}` to a
  `WebhookTarget.url`. Mirrors `_WebhookDispatcher.deliver` line-for-line
  including SSRF DNS pinning.

- `InternalRenderer` — persists a user `Message` row into the parent
  session DB and republishes it. Mirrors `_InternalDispatcher.deliver`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import ClassVar

import httpx

from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.dispatch_target import (
    DispatchTarget,
    InternalTarget,
    NoneTarget,
    WebhookTarget,
    WebTarget,
)
from app.domain.outbound_action import OutboundAction
from app.integrations.renderer import DeliveryReceipt

logger = logging.getLogger(__name__)


# Shared HTTP client for the WebhookRenderer. Mirrors the module-level
# `_http` in `app/agent/dispatchers.py:18` so the connection pool behavior
# is preserved during the migration.
_http = httpx.AsyncClient(timeout=30.0)


class NoneRenderer:
    """Null renderer — accepts every event but delivers nothing.

    Replacement for `app/agent/dispatchers.py:_NoneDispatcher`. Capability
    set is empty, so capability gating in `IntegrationDispatcherTask`
    skips every event before reaching `render()`. Method bodies are still
    implemented for the rare case where a caller invokes them directly.
    """

    integration_id: ClassVar[str] = "none"
    capabilities: ClassVar[frozenset[Capability]] = frozenset()

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.skipped("none target")

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.skipped("none target")

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        return False


class WebRenderer:
    """Web UI renderer — no-op acknowledgment.

    The web UI subscribes to the channel-events bus directly via SSE; it
    does not need a renderer pushing to it. The renderer exists so that
    `WebTarget` has a routing entry in the registry and so that the web
    UI's capability set is declared in code (a future capability-aware
    publisher can short-circuit unsupported events without speculating).

    All `render()` calls return `DeliveryReceipt.ok()` because the
    publish-typed event was already delivered to bus subscribers by the
    time `IntegrationDispatcherTask` invoked us; nothing more is needed.
    """

    integration_id: ClassVar[str] = "web"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.TEXT,
        Capability.RICH_TEXT,
        Capability.STREAMING_EDIT,
        Capability.ATTACHMENTS,
        Capability.IMAGE_UPLOAD,
        Capability.FILE_UPLOAD,
        Capability.FILE_DELETE,
        Capability.APPROVAL_BUTTONS,
        Capability.MENTIONS,
        Capability.INLINE_BUTTONS,
        Capability.REACTIONS,
        Capability.TYPING_INDICATOR,
        Capability.DISPLAY_NAMES,
        Capability.CANCELLATION,
    })

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        # Web UI consumes the bus directly — nothing to do here. Return ok
        # so the outbox drainer (Phase D) marks the row delivered.
        return DeliveryReceipt.ok()

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.ok()

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        # Web UI deletion happens through the regular HTTP DELETE flow,
        # not through the renderer. Return False to mirror the legacy
        # _NoneDispatcher / _WebhookDispatcher behavior.
        return False


class WebhookRenderer:
    """Outbound HTTP webhook renderer.

    Renders `TURN_ENDED` events as a JSON POST to `WebhookTarget.url`.
    Other event kinds are skipped. Mirrors
    `app/agent/dispatchers.py:_WebhookDispatcher.deliver` (lines 70-95)
    line-for-line, including SSRF DNS pinning via
    `app/utils/url_validation.resolve_and_pin` + `pin_url` and the
    audit log via `app/security/audit.log_outbound_request`.
    """

    integration_id: ClassVar[str] = "webhook"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({Capability.TEXT})

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if event.kind != ChannelEventKind.TURN_ENDED:
            return DeliveryReceipt.skipped(
                f"webhook only handles turn_ended, got {event.kind.value}"
            )
        if not isinstance(target, WebhookTarget):
            return DeliveryReceipt.failed(
                f"WebhookRenderer received non-webhook target: {type(target).__name__}",
                retryable=False,
            )

        url = target.url
        if not url:
            return DeliveryReceipt.failed("WebhookTarget.url is empty", retryable=False)

        payload = event.payload  # TurnEndedPayload
        task_id = getattr(payload, "task_id", None) or ""
        result_text = getattr(payload, "result", None) or ""

        # SSRF protection with DNS pinning: resolve once, connect to pinned IP.
        try:
            from app.utils.url_validation import pin_url, resolve_and_pin
            _orig, pinned_ip = resolve_and_pin(url)
        except ValueError as exc:
            logger.warning("WebhookRenderer: SSRF blocked for task %s: %s", task_id, exc)
            return DeliveryReceipt.failed(f"SSRF blocked: {exc}", retryable=False)

        from app.security.audit import log_outbound_request
        log_outbound_request(
            url=url,
            method="POST",
            tool_name="webhook_dispatch",
            bot_id=getattr(payload, "bot_id", None),
        )
        try:
            pinned, extra_headers = pin_url(url, pinned_ip)
            merged_headers = {**target.headers, **extra_headers}
            response = await _http.post(
                pinned,
                json={"task_id": str(task_id), "result": result_text},
                headers=merged_headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status >= 500 or status == 429
            logger.warning(
                "WebhookRenderer.render HTTP %s for task %s",
                status,
                task_id,
            )
            return DeliveryReceipt.failed(f"HTTP {status}", retryable=retryable)
        except Exception as exc:  # noqa: BLE001
            logger.exception("WebhookRenderer.render failed for task %s", task_id)
            return DeliveryReceipt.failed(str(exc), retryable=True)

        return DeliveryReceipt.ok()

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.skipped("webhook does not support outbound actions")

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        return False


class InternalRenderer:
    """Cross-bot delegation renderer.

    Renders `TURN_ENDED` events by inserting a user `Message` into the
    parent session DB so the parent bot's next turn can read the
    delegated child's result. Mirrors
    `app/agent/dispatchers.py:_InternalDispatcher.deliver` (lines 110-143).
    """

    integration_id: ClassVar[str] = "internal"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({Capability.TEXT})

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if event.kind != ChannelEventKind.TURN_ENDED:
            return DeliveryReceipt.skipped(
                f"internal only handles turn_ended, got {event.kind.value}"
            )
        if not isinstance(target, InternalTarget):
            return DeliveryReceipt.failed(
                f"InternalRenderer received non-internal target: {type(target).__name__}",
                retryable=False,
            )

        payload = event.payload  # TurnEndedPayload
        result_text = getattr(payload, "result", None) or ""
        task_id = getattr(payload, "task_id", None) or ""

        try:
            session_id = uuid.UUID(target.parent_session_id)
        except (TypeError, ValueError) as exc:
            return DeliveryReceipt.failed(
                f"InternalTarget.parent_session_id is not a valid UUID: {exc}",
                retryable=False,
            )

        try:
            from app.db.engine import async_session
            from app.db.models import Message as ORMMessage
            from app.db.models import Session

            async with async_session() as db:
                session = await db.get(Session, session_id)
                if not session:
                    msg = (
                        f"InternalRenderer: parent session {session_id} not "
                        f"found for task {task_id}"
                    )
                    logger.error(msg)
                    return DeliveryReceipt.failed(msg, retryable=False)

                record = ORMMessage(
                    session_id=session_id,
                    role="user",
                    content=f"[Task {task_id} completed]\n\n{result_text}",
                    created_at=datetime.now(timezone.utc),
                )
                db.add(record)
                await db.commit()
                await db.refresh(record)

                if session.channel_id:
                    from app.services.channel_events import publish_message
                    publish_message(session.channel_id, record)
        except Exception as exc:  # noqa: BLE001
            logger.exception("InternalRenderer.render failed for task %s", task_id)
            return DeliveryReceipt.failed(str(exc), retryable=True)

        return DeliveryReceipt.ok()

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.skipped("internal does not support outbound actions")

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        return False


# Self-register at module import. `app/main.py` imports this module from
# lifespan startup before the dispatcher loop spins up; tests using
# `renderer_registry.clear()` should also re-import or re-call register().
def _register_core_renderers() -> None:
    # Tolerate re-import / re-execution: skip if already registered. Tests
    # that call `renderer_registry.clear()` re-invoke this helper.
    from app.integrations import renderer_registry

    for renderer_cls in (NoneRenderer, WebRenderer, WebhookRenderer, InternalRenderer):
        if renderer_registry.get(renderer_cls.integration_id) is None:
            renderer_registry.register(renderer_cls())


_register_core_renderers()
