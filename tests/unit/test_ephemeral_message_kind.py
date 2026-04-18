"""Tests for the new EPHEMERAL_MESSAGE event kind + payload."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message
from app.domain.payloads import EphemeralMessagePayload, MessagePayload


def _msg(content: str = "hi") -> Message:
    return Message(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content=content,
        created_at=datetime.now(timezone.utc),
        actor=ActorRef.bot("bot1"),
    )


class TestKindRegistration:
    def test_kind_enum_value(self):
        assert ChannelEventKind.EPHEMERAL_MESSAGE.value == "ephemeral_message"

    def test_requires_ephemeral_capability(self):
        required = ChannelEventKind.EPHEMERAL_MESSAGE.required_capabilities()
        assert required == frozenset({Capability.EPHEMERAL})

    def test_not_outbox_durable(self):
        # Ephemerals are transient; durable delivery would broadcast a
        # message that was meant for one recipient. Keep strict.
        assert ChannelEventKind.EPHEMERAL_MESSAGE.is_outbox_durable is False


class TestPayloadPairing:
    def test_accepts_ephemeral_payload(self):
        ev = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.EPHEMERAL_MESSAGE,
            payload=EphemeralMessagePayload(
                message=_msg(),
                recipient_user_id="U01ALICE",
            ),
        )
        assert ev.payload.recipient_user_id == "U01ALICE"

    def test_rejects_message_payload_mispairing(self):
        with pytest.raises(TypeError):
            ChannelEvent(
                channel_id=uuid.uuid4(),
                kind=ChannelEventKind.EPHEMERAL_MESSAGE,
                payload=MessagePayload(message=_msg()),
            )

    def test_ephemeral_payload_not_accepted_by_new_message_kind(self):
        with pytest.raises(TypeError):
            ChannelEvent(
                channel_id=uuid.uuid4(),
                kind=ChannelEventKind.NEW_MESSAGE,
                payload=EphemeralMessagePayload(
                    message=_msg(),
                    recipient_user_id="U01",
                ),
            )
