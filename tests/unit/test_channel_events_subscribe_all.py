"""Tests for `subscribe_all()` global subscriber API.

`subscribe_all()` is the bus API the `IntegrationDispatcherTask` uses to
receive every typed event published to every channel without having to
know channel→integration bindings up front. The test surface is:

- A global subscriber receives events from every channel.
- Per-channel subscribers and global subscribers coexist.
- Channel-isolated subscribers do NOT see events from other channels,
  but a global subscriber does.
- The global subscriber is properly cleaned up on generator exit.
- Backpressure: queue overflow pushes a `replay_lapsed` sentinel and
  the generator exits cleanly (mirrors `subscribe()` semantics).
"""
from __future__ import annotations

import asyncio
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
)
from app.services.channel_events import (
    QUEUE_MAX_SIZE,
    _global_subscribers,
    _next_seq,
    _replay_buffer,
    _subscribers,
    global_subscriber_count,
    publish_typed,
    subscribe,
    subscribe_all,
    subscriber_count,
)


@pytest.fixture(autouse=True)
def _clean_state():
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    _global_subscribers.clear()
    yield
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    _global_subscribers.clear()


def _cid() -> uuid.UUID:
    return uuid.uuid4()


def _new_message_event(channel_id: uuid.UUID, content: str = "hi") -> ChannelEvent:
    msg = Message(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content=content,
        created_at=datetime.now(timezone.utc),
        actor=ActorRef.bot("e2e", "E2E"),
    )
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(message=msg),
    )


class TestGlobalSubscriberReceivesAllChannels:
    @pytest.mark.asyncio
    async def test_global_sub_sees_events_from_every_channel(self):
        ch1, ch2, ch3 = _cid(), _cid(), _cid()
        received: list[ChannelEvent] = []

        async def _consume():
            count = 0
            async for ev in subscribe_all():
                received.append(ev)
                count += 1
                if count >= 3:
                    break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        assert global_subscriber_count() == 1

        publish_typed(ch1, _new_message_event(ch1, "one"))
        publish_typed(ch2, _new_message_event(ch2, "two"))
        publish_typed(ch3, _new_message_event(ch3, "three"))

        await asyncio.wait_for(task, timeout=1.0)

        assert {ev.channel_id for ev in received} == {ch1, ch2, ch3}
        assert {ev.payload.message.content for ev in received} == {"one", "two", "three"}


class TestGlobalAndPerChannelCoexist:
    @pytest.mark.asyncio
    async def test_both_subscribers_receive_event(self):
        ch = _cid()
        per_ch: list[ChannelEvent] = []
        global_recv: list[ChannelEvent] = []

        async def _per_channel():
            async for ev in subscribe(ch):
                per_ch.append(ev)
                break

        async def _global():
            async for ev in subscribe_all():
                global_recv.append(ev)
                break

        t1 = asyncio.create_task(_per_channel())
        t2 = asyncio.create_task(_global())
        await asyncio.sleep(0.01)

        assert subscriber_count(ch) == 1
        assert global_subscriber_count() == 1

        delivered = publish_typed(ch, _new_message_event(ch, "v42"))
        # Both subscribers received the original event.
        assert delivered == 2

        await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1.0)

        assert len(per_ch) == 1
        assert len(global_recv) == 1
        assert per_ch[0].payload.message.content == "v42"
        assert global_recv[0].payload.message.content == "v42"


class TestGlobalSubscriberCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_after_generator_exit(self):
        async def _consume():
            async for _ev in subscribe_all():
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        assert global_subscriber_count() == 1

        publish_typed(_cid(), _new_message_event(_cid()))
        await asyncio.wait_for(task, timeout=1.0)
        await asyncio.sleep(0.01)

        assert global_subscriber_count() == 0


class TestGlobalReceivesTypedEvents:
    @pytest.mark.asyncio
    async def test_typed_event_round_trip_via_global_subscriber(self):
        ch = _cid()
        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe_all():
                received.append(ev)
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)

        typed = ChannelEvent(
            channel_id=ch,
            kind=ChannelEventKind.SHUTDOWN,
            payload=ShutdownPayload(),
        )
        publish_typed(ch, typed)

        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 1
        ev = received[0]
        assert ev.kind is ChannelEventKind.SHUTDOWN
        assert ev.channel_id == ch
        assert ev.seq >= 1
        assert isinstance(ev.payload, ShutdownPayload)


class TestGlobalSubscriberOverflow:
    @pytest.mark.asyncio
    async def test_overflow_pushes_lapsed_sentinel_and_exits(self):
        ch = _cid()
        received: list[ChannelEvent] = []
        consumer_done = asyncio.Event()
        first_event = asyncio.Event()

        async def _consume():
            try:
                async for ev in subscribe_all():
                    received.append(ev)
                    if not first_event.is_set():
                        first_event.set()
                        # Stall so the publisher can overflow our queue.
                        await asyncio.sleep(0.5)
            finally:
                consumer_done.set()

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        assert global_subscriber_count() == 1

        # First publish wakes the consumer; it then stalls.
        publish_typed(ch, _new_message_event(ch))
        await asyncio.wait_for(first_event.wait(), timeout=1.0)

        # Overflow the queue.
        for _ in range(QUEUE_MAX_SIZE + 50):
            publish_typed(ch, _new_message_event(ch))

        await asyncio.wait_for(consumer_done.wait(), timeout=2.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Subscriber cleaned up on exit.
        assert global_subscriber_count() == 0

        # Last delivered event is the overflow lapsed sentinel.
        assert any(
            ev.kind is ChannelEventKind.REPLAY_LAPSED
            and isinstance(ev.payload, ReplayLapsedPayload)
            and ev.payload.reason == "subscriber_overflow"
            for ev in received
        )
