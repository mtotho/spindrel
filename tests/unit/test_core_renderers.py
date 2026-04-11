"""Phase C1 — tests for the four core renderers in `app/integrations/core_renderers.py`.

These tests verify capability declarations, success / skip / failure paths
for each renderer, and that the four core renderers self-register on
import. They do NOT exercise the bus or `IntegrationDispatcherTask` (those
are covered by `test_channel_renderers.py`); these are unit tests of the
renderer classes themselves.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.dispatch_target import (
    InternalTarget,
    NoneTarget,
    WebhookTarget,
    WebTarget,
)
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    MessagePayload,
    TurnEndedPayload,
    TurnStartedPayload,
)
from app.integrations import core_renderers, renderer_registry
from app.integrations.core_renderers import (
    InternalRenderer,
    NoneRenderer,
    WebhookRenderer,
    WebRenderer,
)
from app.integrations.renderer import DeliveryReceipt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_turn_ended_event(
    *,
    channel_id: uuid.UUID | None = None,
    bot_id: str = "bot1",
    result: str | None = "hello",
    task_id: str | None = "t1",
) -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id or uuid.uuid4(),
        kind=ChannelEventKind.TURN_ENDED,
        payload=TurnEndedPayload(
            bot_id=bot_id,
            turn_id=uuid.uuid4(),
            result=result,
            task_id=task_id,
        ),
    )


def _make_new_message_event(channel_id: uuid.UUID | None = None) -> ChannelEvent:
    cid = channel_id or uuid.uuid4()
    return ChannelEvent(
        channel_id=cid,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(
            message=DomainMessage(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                role="assistant",
                content="hi",
                created_at=datetime.now(timezone.utc),
                actor=ActorRef.bot("bot1"),
                channel_id=cid,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------


class TestSelfRegistration:
    def test_all_four_core_renderers_registered_on_import(self):
        # Re-run the registration helper in case a previous test cleared it.
        core_renderers._register_core_renderers()
        for integration_id in ("none", "web", "webhook", "internal"):
            renderer = renderer_registry.get(integration_id)
            assert renderer is not None, (
                f"core renderer {integration_id!r} should be registered after import"
            )

    def test_self_registration_is_idempotent(self):
        # Running it twice must not raise (the helper checks for existing).
        core_renderers._register_core_renderers()
        core_renderers._register_core_renderers()
        assert renderer_registry.get("none") is not None


# ---------------------------------------------------------------------------
# NoneRenderer
# ---------------------------------------------------------------------------


class TestNoneRenderer:
    def test_capabilities_are_empty(self):
        assert NoneRenderer.capabilities == frozenset()

    def test_integration_id(self):
        assert NoneRenderer.integration_id == "none"

    @pytest.mark.asyncio
    async def test_render_skips_every_event(self):
        renderer = NoneRenderer()
        receipt = await renderer.render(_make_turn_ended_event(), NoneTarget())
        assert isinstance(receipt, DeliveryReceipt)
        assert receipt.success is True
        assert receipt.skip_reason == "none target"

    @pytest.mark.asyncio
    async def test_delete_attachment_returns_false(self):
        renderer = NoneRenderer()
        result = await renderer.delete_attachment({}, NoneTarget())
        assert result is False


# ---------------------------------------------------------------------------
# WebRenderer
# ---------------------------------------------------------------------------


class TestWebRenderer:
    def test_capabilities_include_text_and_streaming(self):
        caps = WebRenderer.capabilities
        assert Capability.TEXT in caps
        assert Capability.STREAMING_EDIT in caps
        assert Capability.APPROVAL_BUTTONS in caps
        assert isinstance(caps, frozenset)

    def test_integration_id(self):
        assert WebRenderer.integration_id == "web"

    @pytest.mark.asyncio
    async def test_render_returns_ok_for_any_event(self):
        renderer = WebRenderer()
        target = WebTarget()
        for event in (_make_turn_ended_event(), _make_new_message_event()):
            receipt = await renderer.render(event, target)
            assert receipt.success is True
            assert receipt.skip_reason is None

    @pytest.mark.asyncio
    async def test_delete_attachment_returns_false(self):
        renderer = WebRenderer()
        result = await renderer.delete_attachment({}, WebTarget())
        assert result is False


# ---------------------------------------------------------------------------
# WebhookRenderer
# ---------------------------------------------------------------------------


class TestWebhookRenderer:
    def test_capabilities_text_only(self):
        assert WebhookRenderer.capabilities == frozenset({Capability.TEXT})

    def test_integration_id(self):
        assert WebhookRenderer.integration_id == "webhook"

    @pytest.mark.asyncio
    async def test_render_skips_non_turn_ended_events(self):
        renderer = WebhookRenderer()
        target = WebhookTarget(url="https://example.com/hook")
        receipt = await renderer.render(_make_new_message_event(), target)
        assert receipt.success is True
        assert receipt.skip_reason and "turn_ended" in receipt.skip_reason

    @pytest.mark.asyncio
    async def test_render_fails_on_wrong_target_type(self):
        renderer = WebhookRenderer()
        receipt = await renderer.render(_make_turn_ended_event(), NoneTarget())
        assert receipt.success is False
        assert receipt.error and "non-webhook target" in receipt.error
        assert receipt.retryable is False

    @pytest.mark.asyncio
    async def test_render_fails_on_empty_url(self):
        renderer = WebhookRenderer()
        target = WebhookTarget(url="")
        receipt = await renderer.render(_make_turn_ended_event(), target)
        assert receipt.success is False
        assert "url is empty" in (receipt.error or "")
        assert receipt.retryable is False

    @pytest.mark.asyncio
    async def test_render_ssrf_blocked_returns_failed_non_retryable(self):
        renderer = WebhookRenderer()
        target = WebhookTarget(url="http://10.0.0.1/hook")
        with patch(
            "app.utils.url_validation.resolve_and_pin",
            side_effect=ValueError("blocked private network"),
        ):
            receipt = await renderer.render(_make_turn_ended_event(), target)
        assert receipt.success is False
        assert receipt.retryable is False
        assert "SSRF" in (receipt.error or "")

    @pytest.mark.asyncio
    async def test_render_success_posts_payload(self):
        renderer = WebhookRenderer()
        target = WebhookTarget(url="https://example.com/hook", headers={"X-Secret": "v"})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch(
            "app.utils.url_validation.resolve_and_pin",
            return_value=("https://example.com/hook", "1.2.3.4"),
        ), patch(
            "app.utils.url_validation.pin_url",
            return_value=("https://1.2.3.4/hook", {"Host": "example.com"}),
        ), patch(
            "app.security.audit.log_outbound_request"
        ), patch.object(
            core_renderers._http,
            "post",
            new=AsyncMock(return_value=mock_response),
        ) as mock_post:
            receipt = await renderer.render(_make_turn_ended_event(), target)

        assert receipt.success is True
        assert mock_post.called
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"] == {"task_id": "t1", "result": "hello"}
        # Caller's headers + extra pin headers should both be present
        assert call_kwargs["headers"]["X-Secret"] == "v"
        assert call_kwargs["headers"]["Host"] == "example.com"

    @pytest.mark.asyncio
    async def test_render_http_5xx_is_retryable(self):
        renderer = WebhookRenderer()
        target = WebhookTarget(url="https://example.com/hook")
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "boom", request=MagicMock(), response=mock_response
            )
        )

        with patch(
            "app.utils.url_validation.resolve_and_pin",
            return_value=("https://example.com/hook", "1.2.3.4"),
        ), patch(
            "app.utils.url_validation.pin_url",
            return_value=("https://1.2.3.4/hook", {}),
        ), patch(
            "app.security.audit.log_outbound_request"
        ), patch.object(
            core_renderers._http,
            "post",
            new=AsyncMock(return_value=mock_response),
        ):
            receipt = await renderer.render(_make_turn_ended_event(), target)

        assert receipt.success is False
        assert receipt.retryable is True
        assert "503" in (receipt.error or "")

    @pytest.mark.asyncio
    async def test_render_http_4xx_is_not_retryable(self):
        renderer = WebhookRenderer()
        target = WebhookTarget(url="https://example.com/hook")
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "bad", request=MagicMock(), response=mock_response
            )
        )

        with patch(
            "app.utils.url_validation.resolve_and_pin",
            return_value=("https://example.com/hook", "1.2.3.4"),
        ), patch(
            "app.utils.url_validation.pin_url",
            return_value=("https://1.2.3.4/hook", {}),
        ), patch(
            "app.security.audit.log_outbound_request"
        ), patch.object(
            core_renderers._http,
            "post",
            new=AsyncMock(return_value=mock_response),
        ):
            receipt = await renderer.render(_make_turn_ended_event(), target)

        assert receipt.success is False
        assert receipt.retryable is False

    @pytest.mark.asyncio
    async def test_delete_attachment_returns_false(self):
        renderer = WebhookRenderer()
        result = await renderer.delete_attachment({}, WebhookTarget(url="x"))
        assert result is False


# ---------------------------------------------------------------------------
# InternalRenderer
# ---------------------------------------------------------------------------


class TestInternalRenderer:
    def test_capabilities_text_only(self):
        assert InternalRenderer.capabilities == frozenset({Capability.TEXT})

    def test_integration_id(self):
        assert InternalRenderer.integration_id == "internal"

    @pytest.mark.asyncio
    async def test_render_skips_non_turn_ended(self):
        renderer = InternalRenderer()
        target = InternalTarget(parent_session_id=str(uuid.uuid4()))
        receipt = await renderer.render(_make_new_message_event(), target)
        assert receipt.success is True
        assert receipt.skip_reason and "turn_ended" in receipt.skip_reason

    @pytest.mark.asyncio
    async def test_render_fails_on_wrong_target(self):
        renderer = InternalRenderer()
        receipt = await renderer.render(_make_turn_ended_event(), NoneTarget())
        assert receipt.success is False
        assert receipt.retryable is False
        assert "non-internal target" in (receipt.error or "")

    @pytest.mark.asyncio
    async def test_render_fails_on_invalid_session_uuid(self):
        renderer = InternalRenderer()
        target = InternalTarget(parent_session_id="not-a-uuid")
        receipt = await renderer.render(_make_turn_ended_event(), target)
        assert receipt.success is False
        assert receipt.retryable is False
        assert "UUID" in (receipt.error or "")

    @pytest.mark.asyncio
    async def test_delete_attachment_returns_false(self):
        renderer = InternalRenderer()
        result = await renderer.delete_attachment(
            {}, InternalTarget(parent_session_id=str(uuid.uuid4()))
        )
        assert result is False
