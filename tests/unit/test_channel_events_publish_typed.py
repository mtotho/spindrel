"""Tests for typed bus publish/subscribe.

The bus speaks `domain.channel_events.ChannelEvent` natively. There is no
legacy envelope, no `_typed_event` indirection, no untyped publish path.
Subscribers receive typed events directly.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.domain.actor import ActorRef
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message
from app.domain.payloads import (
    MessagePayload,
    ReplayLapsedPayload,
    ShutdownPayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamTokenPayload,
)
from app.services.channel_events import (
    _global_subscribers,
    _next_seq,
    _replay_buffer,
    _subscribers,
    current_seq,
    event_to_sse_dict,
    publish_typed,
    subscribe,
    subscribe_all,
)


@pytest.fixture(autouse=True)
def _clean_state():
    _subscribers.clear()
    _global_subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _subscribers.clear()
    _global_subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()


def _msg() -> Message:
    return Message(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content="hi",
        created_at=datetime.now(timezone.utc),
        actor=ActorRef.bot("e2e", "E2E"),
    )


def _new_message_event(channel_id: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(message=_msg()),
    )


class TestPublishTypedAssignsSeq:
    def test_first_publish_gets_seq_1(self):
        ch = uuid.uuid4()
        publish_typed(ch, _new_message_event(ch))
        assert current_seq(ch) == 1

    def test_seq_increments_per_publish(self):
        ch = uuid.uuid4()
        for _ in range(5):
            publish_typed(ch, _new_message_event(ch))
        assert current_seq(ch) == 5

    def test_seq_per_channel(self):
        a = uuid.uuid4()
        b = uuid.uuid4()
        publish_typed(a, _new_message_event(a))
        publish_typed(a, _new_message_event(a))
        publish_typed(b, _new_message_event(b))
        assert current_seq(a) == 2
        assert current_seq(b) == 1

    def test_replay_buffer_holds_typed_events_with_assigned_seq(self):
        ch = uuid.uuid4()
        publish_typed(ch, _new_message_event(ch))
        publish_typed(ch, _new_message_event(ch))
        buf = list(_replay_buffer[ch])
        assert len(buf) == 2
        assert buf[0].seq == 1
        assert buf[1].seq == 2
        assert buf[0].kind is ChannelEventKind.NEW_MESSAGE
        assert isinstance(buf[0].payload, MessagePayload)


class TestSubscriberReceivesTypedEvents:
    @pytest.mark.asyncio
    async def test_subscriber_sees_typed_event_directly(self):
        ch = uuid.uuid4()
        publish_typed(ch, _new_message_event(ch))

        received: list[ChannelEvent] = []

        async def consume():
            async for ev in subscribe(ch, since=0):
                received.append(ev)
                break

        await asyncio.wait_for(consume(), timeout=2.0)
        assert received[0].kind is ChannelEventKind.NEW_MESSAGE
        assert received[0].seq == 1
        assert isinstance(received[0].payload, MessagePayload)

    @pytest.mark.asyncio
    async def test_typed_event_payload_message_round_trips(self):
        ch = uuid.uuid4()
        original_msg = _msg()
        evt = ChannelEvent(
            channel_id=ch,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=original_msg),
        )
        publish_typed(ch, evt)

        received: list[ChannelEvent] = []

        async def consume():
            async for ev in subscribe(ch, since=0):
                received.append(ev)
                break

        await asyncio.wait_for(consume(), timeout=2.0)
        assert received[0].payload.message.id == original_msg.id
        assert received[0].payload.message.content == original_msg.content


class TestPublishTypedNoSubscribers:
    def test_returns_zero_when_no_subscribers(self):
        ch = uuid.uuid4()
        delivered = publish_typed(
            ch,
            ChannelEvent(
                channel_id=ch,
                kind=ChannelEventKind.SHUTDOWN,
                payload=ShutdownPayload(),
            ),
        )
        assert delivered == 0
        # The event still lands in the replay buffer.
        assert len(_replay_buffer[ch]) == 1
        assert _replay_buffer[ch][0].kind is ChannelEventKind.SHUTDOWN


class TestEventToSseDict:
    """The SSE wire serializer must produce JSON-safe dicts for every kind."""

    def _serialize_and_assert_jsonable(self, event: ChannelEvent) -> dict:
        wire = event_to_sse_dict(event)
        # json.dumps is the actual contract — it must not raise.
        json.dumps(wire)
        # Wire format invariants:
        assert wire["kind"] == event.kind.value
        assert wire["channel_id"] == str(event.channel_id)
        assert wire["seq"] == event.seq
        assert "ts" in wire
        assert "payload" in wire
        return wire

    def test_serializes_new_message(self):
        ch = uuid.uuid4()
        wire = self._serialize_and_assert_jsonable(_new_message_event(ch))
        assert wire["payload"]["message"]["content"] == "hi"

    def test_serializes_turn_started(self):
        ch = uuid.uuid4()
        evt = ChannelEvent(
            channel_id=ch,
            kind=ChannelEventKind.TURN_STARTED,
            payload=TurnStartedPayload(bot_id="b1", turn_id=uuid.uuid4()),
        )
        wire = self._serialize_and_assert_jsonable(evt)
        assert wire["payload"]["bot_id"] == "b1"
        # turn_id is serialized as a UUID string
        uuid.UUID(wire["payload"]["turn_id"])

    def test_serializes_turn_stream_token(self):
        ch = uuid.uuid4()
        evt = ChannelEvent(
            channel_id=ch,
            kind=ChannelEventKind.TURN_STREAM_TOKEN,
            payload=TurnStreamTokenPayload(
                bot_id="b1", turn_id=uuid.uuid4(), delta="hello"
            ),
        )
        wire = self._serialize_and_assert_jsonable(evt)
        assert wire["payload"]["delta"] == "hello"

    def test_serializes_turn_ended_with_error(self):
        ch = uuid.uuid4()
        evt = ChannelEvent(
            channel_id=ch,
            kind=ChannelEventKind.TURN_ENDED,
            payload=TurnEndedPayload(
                bot_id="b1",
                turn_id=uuid.uuid4(),
                result=None,
                error="cancelled",
            ),
        )
        wire = self._serialize_and_assert_jsonable(evt)
        assert wire["payload"]["error"] == "cancelled"
        assert wire["payload"]["result"] is None

    def test_serializes_shutdown(self):
        ch = uuid.uuid4()
        evt = ChannelEvent(
            channel_id=ch,
            kind=ChannelEventKind.SHUTDOWN,
            payload=ShutdownPayload(),
        )
        self._serialize_and_assert_jsonable(evt)

    def test_serializes_replay_lapsed(self):
        ch = uuid.uuid4()
        evt = ChannelEvent(
            channel_id=ch,
            kind=ChannelEventKind.REPLAY_LAPSED,
            payload=ReplayLapsedPayload(
                requested_since=10,
                oldest_available=15,
                reason="client_lag",
            ),
        )
        wire = self._serialize_and_assert_jsonable(evt)
        assert wire["payload"]["reason"] == "client_lag"
