"""Tests for the in-memory channel event bus.

The bus speaks `domain.channel_events.ChannelEvent` natively. There is no
legacy envelope, no untyped publish, no `_typed_event` stash.
"""
import asyncio
import uuid
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from app.domain.actor import ActorRef
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message
from app.domain.payloads import (
    MessagePayload,
    ReplayLapsedPayload,
    ShutdownPayload,
    TurnStartedPayload,
)
from app.services.channel_events import (
    QUEUE_MAX_SIZE,
    REPLAY_BUFFER_SIZE,
    current_seq,
    publish_message,
    publish_message_updated,
    publish_typed,
    reset_channel_state,
    subscribe,
    subscriber_count,
    _next_seq,
    _replay_buffer,
    _subscribers,
)

# Stream relay needs ≥512.
assert QUEUE_MAX_SIZE == 512


@pytest.fixture(autouse=True)
def _clean_subscribers():
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()


def _cid() -> uuid.UUID:
    return uuid.uuid4()


def _shutdown_event(channel_id: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.SHUTDOWN,
        payload=ShutdownPayload(),
    )


def _turn_started_event(channel_id: uuid.UUID, bot_id: str = "b1") -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.TURN_STARTED,
        payload=TurnStartedPayload(bot_id=bot_id, turn_id=uuid.uuid4()),
    )


# ------------------------------------------------------------------
# Basic publish / subscribe
# ------------------------------------------------------------------


class TestPublishNoSubscribers:
    def test_returns_zero(self):
        ch = _cid()
        assert publish_typed(ch, _shutdown_event(ch)) == 0


class TestSubscribeAndPublish:
    @pytest.mark.asyncio
    async def test_subscriber_receives_event(self):
        ch = _cid()
        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch):
                received.append(ev)
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)

        assert subscriber_count(ch) == 1
        delivered = publish_typed(ch, _turn_started_event(ch))
        assert delivered == 1

        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 1
        assert received[0].kind is ChannelEventKind.TURN_STARTED
        assert received[0].channel_id == ch
        assert isinstance(received[0].payload, TurnStartedPayload)


class TestSubscriberCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_after_generator_exit(self):
        ch = _cid()

        async def _consume():
            async for _ev in subscribe(ch):
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        assert subscriber_count(ch) == 1

        publish_typed(ch, _shutdown_event(ch))
        await asyncio.wait_for(task, timeout=1.0)
        await asyncio.sleep(0.01)

        assert subscriber_count(ch) == 0
        assert ch not in _subscribers


class TestMultipleSubscribers:
    @pytest.mark.asyncio
    async def test_all_subscribers_receive_event(self):
        ch = _cid()
        results: list[list[ChannelEvent]] = [[], []]

        async def _consume(idx: int):
            async for ev in subscribe(ch):
                results[idx].append(ev)
                break

        tasks = [asyncio.create_task(_consume(i)) for i in range(2)]
        await asyncio.sleep(0.01)

        assert subscriber_count(ch) == 2
        delivered = publish_typed(ch, _shutdown_event(ch))
        assert delivered == 2

        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

        assert len(results[0]) == 1
        assert len(results[1]) == 1
        assert results[0][0].kind is ChannelEventKind.SHUTDOWN
        assert results[1][0].kind is ChannelEventKind.SHUTDOWN


class TestChannelIsolation:
    @pytest.mark.asyncio
    async def test_events_dont_leak_across_channels(self):
        ch1 = _cid()
        ch2 = _cid()
        received_ch1: list[ChannelEvent] = []
        received_ch2: list[ChannelEvent] = []

        async def _consume_ch1():
            async for ev in subscribe(ch1):
                received_ch1.append(ev)
                break

        async def _consume_ch2():
            try:
                async for ev in subscribe(ch2):
                    received_ch2.append(ev)
                    break
            except asyncio.CancelledError:
                pass

        t1 = asyncio.create_task(_consume_ch1())
        t2 = asyncio.create_task(_consume_ch2())
        await asyncio.sleep(0.01)

        publish_typed(ch1, _shutdown_event(ch1))
        await asyncio.wait_for(t1, timeout=1.0)

        assert len(received_ch1) == 1
        assert len(received_ch2) == 0

        t2.cancel()
        try:
            await t2
        except asyncio.CancelledError:
            pass


class TestBackpressure:
    @pytest.mark.asyncio
    async def test_publish_returns_without_blocking_on_overflow(self):
        """publish_typed must never block or raise even when a subscriber
        is too slow. The dropped events get replaced with a single
        replay_lapsed sentinel — see test_subscribe_yields_lapsed_sentinel."""
        ch = _cid()

        async def _stalled():
            async for _ev in subscribe(ch):
                await asyncio.sleep(60)

        task = asyncio.create_task(_stalled())
        await asyncio.sleep(0.01)
        assert subscriber_count(ch) == 1

        for _ in range(QUEUE_MAX_SIZE * 2):
            publish_typed(ch, _shutdown_event(ch))

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_subscribe_yields_lapsed_sentinel_then_exits(self):
        ch = _cid()
        received: list[ChannelEvent] = []
        consumer_done = asyncio.Event()
        first_seen = asyncio.Event()

        async def _consume():
            try:
                async for ev in subscribe(ch):
                    received.append(ev)
                    if not first_seen.is_set():
                        first_seen.set()
                        # Stall so the publisher can overflow our queue.
                        await asyncio.sleep(0.5)
            finally:
                consumer_done.set()

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        assert subscriber_count(ch) == 1

        publish_typed(ch, _shutdown_event(ch))
        await asyncio.wait_for(first_seen.wait(), timeout=1.0)

        for _ in range(QUEUE_MAX_SIZE + 50):
            publish_typed(ch, _shutdown_event(ch))

        await asyncio.wait_for(consumer_done.wait(), timeout=2.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert subscriber_count(ch) == 0
        assert any(
            ev.kind is ChannelEventKind.REPLAY_LAPSED
            and isinstance(ev.payload, ReplayLapsedPayload)
            and ev.payload.reason == "subscriber_overflow"
            for ev in received
        )


# ------------------------------------------------------------------
# Sequence numbers, ring buffer, replay
# ------------------------------------------------------------------


class TestSequenceNumbers:
    def test_seq_starts_at_one_and_increments(self):
        ch = _cid()
        assert current_seq(ch) == 0
        publish_typed(ch, _shutdown_event(ch))
        assert current_seq(ch) == 1
        publish_typed(ch, _shutdown_event(ch))
        assert current_seq(ch) == 2

    def test_seq_is_monotonic_per_channel(self):
        ch1 = _cid()
        ch2 = _cid()
        publish_typed(ch1, _shutdown_event(ch1))
        publish_typed(ch1, _shutdown_event(ch1))
        publish_typed(ch2, _shutdown_event(ch2))
        publish_typed(ch1, _shutdown_event(ch1))
        assert current_seq(ch1) == 3
        assert current_seq(ch2) == 1

    @pytest.mark.asyncio
    async def test_subscriber_receives_seq_in_event(self):
        ch = _cid()
        received: list[ChannelEvent] = []

        async def _consume():
            count = 0
            async for ev in subscribe(ch):
                received.append(ev)
                count += 1
                if count >= 3:
                    break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        publish_typed(ch, _shutdown_event(ch))
        publish_typed(ch, _shutdown_event(ch))
        publish_typed(ch, _shutdown_event(ch))
        await asyncio.wait_for(task, timeout=1.0)

        assert [ev.seq for ev in received] == [1, 2, 3]


class TestReplayBuffer:
    def test_buffer_persists_after_subscribers_leave(self):
        ch = _cid()
        publish_typed(ch, _shutdown_event(ch))
        publish_typed(ch, _shutdown_event(ch))
        assert len(_replay_buffer[ch]) == 2
        assert current_seq(ch) == 2

    def test_buffer_evicts_oldest_at_max_size(self):
        ch = _cid()
        for _ in range(REPLAY_BUFFER_SIZE + 50):
            publish_typed(ch, _shutdown_event(ch))
        buf = _replay_buffer[ch]
        assert len(buf) == REPLAY_BUFFER_SIZE
        assert buf[0].seq == 51
        assert buf[-1].seq == REPLAY_BUFFER_SIZE + 50


class TestReplayOnReconnect:
    @pytest.mark.asyncio
    async def test_replays_buffered_events_with_seq_greater_than_since(self):
        ch = _cid()
        for _ in range(5):
            publish_typed(ch, _shutdown_event(ch))

        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch, since=2):
                received.append(ev)
                if len(received) >= 3:
                    break

        await asyncio.wait_for(_consume(), timeout=1.0)

        assert [ev.seq for ev in received] == [3, 4, 5]

    @pytest.mark.asyncio
    async def test_replay_then_tail_live(self):
        ch = _cid()
        publish_typed(ch, _shutdown_event(ch))
        publish_typed(ch, _shutdown_event(ch))

        received: list[ChannelEvent] = []
        ready = asyncio.Event()

        async def _consume():
            async for ev in subscribe(ch, since=0):
                received.append(ev)
                if len(received) == 2:
                    ready.set()
                if len(received) >= 4:
                    break

        task = asyncio.create_task(_consume())
        await asyncio.wait_for(ready.wait(), timeout=1.0)
        publish_typed(ch, _shutdown_event(ch))
        publish_typed(ch, _shutdown_event(ch))
        await asyncio.wait_for(task, timeout=1.0)

        assert [ev.seq for ev in received] == [1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_replay_lapsed_sentinel_when_buffer_too_old(self):
        ch = _cid()
        for _ in range(REPLAY_BUFFER_SIZE + 20):
            publish_typed(ch, _shutdown_event(ch))
        assert _replay_buffer[ch][0].seq == 21

        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch, since=5):
                received.append(ev)
                if len(received) >= 1:
                    break

        await asyncio.wait_for(_consume(), timeout=1.0)
        first = received[0]
        assert first.kind is ChannelEventKind.REPLAY_LAPSED
        assert isinstance(first.payload, ReplayLapsedPayload)
        assert first.payload.requested_since == 5
        assert first.payload.oldest_available == 21
        assert first.payload.reason == "client_lag"

    @pytest.mark.asyncio
    async def test_replay_no_events_when_since_is_current_seq(self):
        ch = _cid()
        publish_typed(ch, _shutdown_event(ch))
        publish_typed(ch, _shutdown_event(ch))

        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch, since=2):
                received.append(ev)
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        assert received == []
        publish_typed(ch, _shutdown_event(ch))
        await asyncio.wait_for(task, timeout=1.0)
        assert len(received) == 1
        assert received[0].seq == 3

    @pytest.mark.asyncio
    async def test_replay_dedupes_against_live_events(self):
        ch = _cid()
        publish_typed(ch, _shutdown_event(ch))

        received: list[ChannelEvent] = []

        async def _consume():
            count = 0
            async for ev in subscribe(ch, since=0):
                received.append(ev)
                count += 1
                if count >= 3:
                    break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        publish_typed(ch, _shutdown_event(ch))
        publish_typed(ch, _shutdown_event(ch))
        await asyncio.wait_for(task, timeout=1.0)

        seqs = [ev.seq for ev in received]
        assert seqs == [1, 2, 3]
        assert len(seqs) == len(set(seqs))


# ------------------------------------------------------------------
# publish_message helpers
# ------------------------------------------------------------------


def _make_msg_row():
    """Build a fake Message-like ORM row that domain.Message.from_orm can read."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="user",
        content="hello world",
        tool_calls=None,
        tool_call_id=None,
        correlation_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        metadata_={"foo": "bar"},
        attachments=[],
    )


class TestPublishMessage:
    @pytest.mark.asyncio
    async def test_publish_message_ships_typed_message_payload(self):
        ch = _cid()
        msg = _make_msg_row()
        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch):
                received.append(ev)
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        publish_message(ch, msg)
        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 1
        ev = received[0]
        assert ev.kind is ChannelEventKind.NEW_MESSAGE
        assert isinstance(ev.payload, MessagePayload)
        assert isinstance(ev.payload.message, Message)
        assert ev.payload.message.id == msg.id
        assert ev.payload.message.role == "user"
        assert ev.payload.message.content == "hello world"
        assert ev.payload.message.metadata == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_publish_message_updated_uses_message_updated_kind(self):
        ch = _cid()
        msg = _make_msg_row()
        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch):
                received.append(ev)
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        publish_message_updated(ch, msg)
        await asyncio.wait_for(task, timeout=1.0)

        assert received[0].kind is ChannelEventKind.MESSAGE_UPDATED
        assert received[0].payload.message.id == msg.id


class TestResetChannelState:
    def test_reset_clears_seq_buffer_and_subscribers(self):
        ch = _cid()
        publish_typed(ch, _shutdown_event(ch))
        publish_typed(ch, _shutdown_event(ch))
        assert current_seq(ch) == 2
        assert len(_replay_buffer[ch]) == 2

        reset_channel_state(ch)
        assert current_seq(ch) == 0
        assert ch not in _replay_buffer
        assert ch not in _subscribers
