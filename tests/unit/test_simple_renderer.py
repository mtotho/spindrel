"""SimpleRenderer — contract tests.

Verifies the delivery contract encoded in the base class:

- ``TURN_ENDED`` is always skipped (non-streaming: no placeholder).
- ``NEW_MESSAGE`` is the sole text delivery path.
- Echo prevention: own-origin user messages skipped automatically.
- Internal roles (``tool``, ``system``) skipped automatically.
- Cross-origin user messages delivered normally.
- ``send_text`` return value maps to ``DeliveryReceipt`` correctly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import ClassVar

import pytest

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.dispatch_target import NoneTarget, _BaseTarget as BaseTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    MessagePayload,
    TurnEndedPayload,
)
from app.integrations.renderer import DeliveryReceipt, SimpleRenderer

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------


class _FakeTarget(BaseTarget):
    integration_id: ClassVar[str] = "fake"


class FakeRenderer(SimpleRenderer):
    integration_id: ClassVar[str] = "fake"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({Capability.TEXT})

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.errors: list[str] = []
        self._next_result: bool = True

    async def send_text(self, target, text: str) -> bool:
        self.sent.append(text)
        return self._next_result

    async def send_error(self, target, error: str) -> bool:
        self.errors.append(error)
        return self._next_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _turn_ended(result: str | None = "done", error: str | None = None) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_ENDED,
        payload=TurnEndedPayload(
            bot_id="b", turn_id=uuid.uuid4(),
            result=result, error=error, client_actions=[],
        ),
    )


def _new_msg(role: str = "assistant", content: str = "hello",
             source: str | None = None) -> ChannelEvent:
    cid = uuid.uuid4()
    meta = {"source": source} if source else {}
    return ChannelEvent(
        channel_id=cid,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(
            message=DomainMessage(
                id=uuid.uuid4(), session_id=uuid.uuid4(),
                role=role, content=content,
                created_at=datetime.now(timezone.utc),
                actor=ActorRef.bot("b") if role != "user" else ActorRef.user("u"),
                metadata=meta, channel_id=cid,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# TURN_ENDED — must be a no-op
# ---------------------------------------------------------------------------


class TestTurnEnded:
    async def test_skipped_with_result(self):
        r = FakeRenderer()
        receipt = await r.render(_turn_ended(result="hello"), _FakeTarget())
        assert receipt.success is True
        assert "NEW_MESSAGE" in (receipt.skip_reason or "")
        assert r.sent == []

    async def test_skipped_with_error(self):
        r = FakeRenderer()
        receipt = await r.render(_turn_ended(result=None, error="boom"), _FakeTarget())
        assert receipt.success is True
        assert r.sent == []


# ---------------------------------------------------------------------------
# NEW_MESSAGE — sole delivery path
# ---------------------------------------------------------------------------


class TestNewMessage:
    async def test_assistant_message_delivered(self):
        r = FakeRenderer()
        receipt = await r.render(_new_msg("assistant", "hi"), _FakeTarget())
        assert receipt.success is True
        assert r.sent == ["hi"]

    async def test_tool_role_skipped(self):
        r = FakeRenderer()
        receipt = await r.render(_new_msg("tool", '{"ok":true}'), _FakeTarget())
        assert receipt.success is True
        assert "internal role" in (receipt.skip_reason or "")
        assert r.sent == []

    async def test_system_role_skipped(self):
        r = FakeRenderer()
        receipt = await r.render(_new_msg("system", "context"), _FakeTarget())
        assert receipt.success is True
        assert "internal role" in (receipt.skip_reason or "")

    async def test_own_origin_user_skipped(self):
        r = FakeRenderer()
        receipt = await r.render(_new_msg("user", "hi", source="fake"), _FakeTarget())
        assert receipt.success is True
        assert "echo prevention" in (receipt.skip_reason or "")
        assert r.sent == []

    async def test_cross_origin_user_delivered(self):
        r = FakeRenderer()
        receipt = await r.render(_new_msg("user", "hello", source="web"), _FakeTarget())
        assert receipt.success is True
        assert r.sent == ["hello"]

    async def test_empty_content_skipped(self):
        r = FakeRenderer()
        receipt = await r.render(_new_msg("assistant", ""), _FakeTarget())
        assert receipt.success is True
        assert "empty" in (receipt.skip_reason or "")

    async def test_send_failure_retryable(self):
        r = FakeRenderer()
        r._next_result = False
        receipt = await r.render(_new_msg("assistant", "hi"), _FakeTarget())
        assert receipt.success is False
        assert receipt.retryable is True

    async def test_no_message_payload_skipped(self):
        r = FakeRenderer()
        event = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=None),
        )
        receipt = await r.render(event, _FakeTarget())
        assert receipt.success is True
        assert "without message" in (receipt.skip_reason or "")


# ---------------------------------------------------------------------------
# Default handle_outbound_action and delete_attachment
# ---------------------------------------------------------------------------


class TestDefaults:
    async def test_outbound_action_skipped(self):
        r = FakeRenderer()
        receipt = await r.handle_outbound_action(object(), _FakeTarget())
        assert receipt.success is True
        assert receipt.skip_reason is not None

    async def test_delete_attachment_false(self):
        r = FakeRenderer()
        assert await r.delete_attachment({}, _FakeTarget()) is False
