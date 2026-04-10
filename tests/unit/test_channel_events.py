"""Tests for the in-memory channel event bus."""
import asyncio
import uuid
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from app.services.channel_events import (
    ChannelEvent,
    QUEUE_MAX_SIZE,
    REPLAY_BUFFER_SIZE,
    current_seq,
    publish,
    publish_message,
    publish_message_updated,
    reset_channel_state,
    subscribe,
    subscriber_count,
    _next_seq,
    _replay_buffer,
    _subscribers,
)

# Ensure the constant is what we expect (stream relay needs ≥512)
assert QUEUE_MAX_SIZE == 512


@pytest.fixture(autouse=True)
def _clean_subscribers():
    """Ensure global state is clean between tests."""
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()


def _cid() -> uuid.UUID:
    return uuid.uuid4()


# ------------------------------------------------------------------
# Basic publish / subscribe
# ------------------------------------------------------------------

class TestPublishNoSubscribers:
    def test_returns_zero(self):
        assert publish(_cid(), "new_message") == 0


class TestSubscribeAndPublish:
    @pytest.mark.asyncio
    async def test_subscriber_receives_event(self):
        ch = _cid()
        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch):
                received.append(ev)
                break  # exit after first event

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)  # let subscribe register

        assert subscriber_count(ch) == 1
        delivered = publish(ch, "new_message", {"foo": "bar"})
        assert delivered == 1

        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 1
        assert received[0].event_type == "new_message"
        assert received[0].channel_id == ch
        assert received[0].metadata == {"foo": "bar"}


class TestSubscriberCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_after_generator_exit(self):
        ch = _cid()

        async def _consume():
            async for ev in subscribe(ch):
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        assert subscriber_count(ch) == 1

        publish(ch, "new_message")
        await asyncio.wait_for(task, timeout=1.0)
        # Let the event loop process the generator's aclose()
        await asyncio.sleep(0.01)

        # After the generator exits, subscriber should be cleaned up
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
        delivered = publish(ch, "new_message")
        assert delivered == 2

        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

        assert len(results[0]) == 1
        assert len(results[1]) == 1
        assert results[0][0].event_type == "new_message"
        assert results[1][0].event_type == "new_message"


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
            # This subscriber should never receive an event
            try:
                async for ev in subscribe(ch2):
                    received_ch2.append(ev)
                    break
            except asyncio.CancelledError:
                pass

        t1 = asyncio.create_task(_consume_ch1())
        t2 = asyncio.create_task(_consume_ch2())
        await asyncio.sleep(0.01)

        publish(ch1, "new_message")
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
    async def test_full_queue_drops_event_without_blocking(self):
        ch = _cid()

        # Register a subscriber but don't consume — let the queue fill up
        gen = subscribe(ch)
        # Start the generator to register the subscriber
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.01)

        assert subscriber_count(ch) == 1

        # Fill the queue
        for i in range(QUEUE_MAX_SIZE):
            delivered = publish(ch, "new_message", {"i": i})
            assert delivered == 1

        # Next publish should drop (queue full) — must not block
        delivered = publish(ch, "new_message", {"i": "overflow"})
        assert delivered == 0

        # Clean up
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        await gen.aclose()


class TestEventTypes:
    @pytest.mark.asyncio
    async def test_different_event_types(self):
        ch = _cid()
        received: list[ChannelEvent] = []

        async def _consume():
            count = 0
            async for ev in subscribe(ch):
                received.append(ev)
                count += 1
                if count >= 2:
                    break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)

        publish(ch, "new_message")
        publish(ch, "session_reset")

        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 2
        assert received[0].event_type == "new_message"
        assert received[1].event_type == "session_reset"


# ------------------------------------------------------------------
# Sequence numbers, ring buffer, replay
# ------------------------------------------------------------------


class TestSequenceNumbers:
    def test_seq_starts_at_one_and_increments(self):
        ch = _cid()
        assert current_seq(ch) == 0
        publish(ch, "new_message")
        assert current_seq(ch) == 1
        publish(ch, "new_message")
        assert current_seq(ch) == 2

    def test_seq_is_monotonic_per_channel(self):
        ch1 = _cid()
        ch2 = _cid()
        publish(ch1, "new_message")
        publish(ch1, "new_message")
        publish(ch2, "new_message")
        publish(ch1, "new_message")
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
        publish(ch, "new_message")
        publish(ch, "new_message")
        publish(ch, "new_message")
        await asyncio.wait_for(task, timeout=1.0)

        assert [ev.seq for ev in received] == [1, 2, 3]


class TestReplayBuffer:
    def test_buffer_persists_after_subscribers_leave(self):
        """Buffer must outlive subscribers so reconnects can replay."""
        ch = _cid()
        publish(ch, "new_message", {"i": 1})
        publish(ch, "new_message", {"i": 2})
        # No subscribers were ever connected
        assert len(_replay_buffer[ch]) == 2
        assert current_seq(ch) == 2

    def test_buffer_evicts_oldest_at_max_size(self):
        ch = _cid()
        # Publish more than the buffer can hold
        for i in range(REPLAY_BUFFER_SIZE + 50):
            publish(ch, "new_message", {"i": i})
        buf = _replay_buffer[ch]
        assert len(buf) == REPLAY_BUFFER_SIZE
        # Oldest event should be the (50+1)-th publish (seq=51)
        assert buf[0].seq == 51
        assert buf[-1].seq == REPLAY_BUFFER_SIZE + 50


class TestReplayOnReconnect:
    @pytest.mark.asyncio
    async def test_replays_buffered_events_with_seq_greater_than_since(self):
        ch = _cid()
        # Publish 5 events before any subscriber exists
        for i in range(5):
            publish(ch, "new_message", {"i": i})

        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch, since=2):
                received.append(ev)
                if len(received) >= 3:
                    break

        await asyncio.wait_for(_consume(), timeout=1.0)

        # Should replay seq 3, 4, 5 (since=2 means "give me everything > 2")
        assert [ev.seq for ev in received] == [3, 4, 5]

    @pytest.mark.asyncio
    async def test_replay_then_tail_live(self):
        ch = _cid()
        # 2 events before subscriber
        publish(ch, "new_message", {"i": 1})
        publish(ch, "new_message", {"i": 2})

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
        # Wait for replay to complete
        await asyncio.wait_for(ready.wait(), timeout=1.0)
        # Now publish 2 more live
        publish(ch, "new_message", {"i": 3})
        publish(ch, "new_message", {"i": 4})
        await asyncio.wait_for(task, timeout=1.0)

        assert [ev.seq for ev in received] == [1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_replay_lapsed_sentinel_when_buffer_too_old(self):
        ch = _cid()
        # Fill buffer well past `since=5`
        for i in range(REPLAY_BUFFER_SIZE + 20):
            publish(ch, "new_message", {"i": i})
        # Buffer's oldest seq is now 21, requested since is 5 → lapsed
        assert _replay_buffer[ch][0].seq == 21

        received: list[ChannelEvent] = []

        async def _consume():
            async for ev in subscribe(ch, since=5):
                received.append(ev)
                if len(received) >= 1:
                    break

        await asyncio.wait_for(_consume(), timeout=1.0)
        # First event delivered should be the replay_lapsed sentinel
        assert received[0].event_type == "replay_lapsed"
        assert received[0].metadata["requested_since"] == 5
        assert received[0].metadata["oldest_available"] == 21

    @pytest.mark.asyncio
    async def test_replay_no_events_when_since_is_current_seq(self):
        ch = _cid()
        publish(ch, "new_message", {"i": 1})
        publish(ch, "new_message", {"i": 2})

        # since=2 means "up to date already" — no replay events expected
        received: list[ChannelEvent] = []
        live_ready = asyncio.Event()

        async def _consume():
            async for ev in subscribe(ch, since=2):
                received.append(ev)
                live_ready.set()
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        # Nothing replayed; live publish wakes the consumer
        assert received == []
        publish(ch, "new_message", {"i": 3})
        await asyncio.wait_for(task, timeout=1.0)
        assert len(received) == 1
        assert received[0].seq == 3

    @pytest.mark.asyncio
    async def test_replay_dedupes_against_live_events(self):
        """An event published between buffer-snapshot and live-tail
        registration would be in BOTH the replay buffer and the live queue.
        The subscribe() implementation must dedupe by seq."""
        ch = _cid()
        publish(ch, "new_message", {"i": 1})

        received: list[ChannelEvent] = []

        async def _consume():
            # Use since=0 so all events get replayed
            count = 0
            async for ev in subscribe(ch, since=0):
                received.append(ev)
                count += 1
                if count >= 3:
                    break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        # Now publish more events that go through the live queue
        publish(ch, "new_message", {"i": 2})
        publish(ch, "new_message", {"i": 3})
        await asyncio.wait_for(task, timeout=1.0)

        # No duplicates by seq
        seqs = [ev.seq for ev in received]
        assert seqs == [1, 2, 3]
        assert len(seqs) == len(set(seqs))


# ------------------------------------------------------------------
# publish_message helpers
# ------------------------------------------------------------------


def _make_msg_row():
    """Build a fake Message-like object that MessageOut.from_orm can serialize."""
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
    async def test_publish_message_ships_serialized_row(self):
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
        assert ev.event_type == "new_message"
        assert "message" in ev.metadata
        body = ev.metadata["message"]
        assert body["id"] == str(msg.id)
        assert body["role"] == "user"
        assert body["content"] == "hello world"
        assert body["metadata"] == {"foo": "bar"}
        assert body["attachments"] == []

    @pytest.mark.asyncio
    async def test_publish_message_updated_uses_message_updated_event_type(self):
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

        assert received[0].event_type == "message_updated"
        assert received[0].metadata["message"]["id"] == str(msg.id)


class TestResetChannelState:
    def test_reset_clears_seq_buffer_and_subscribers(self):
        ch = _cid()
        publish(ch, "new_message")
        publish(ch, "new_message")
        assert current_seq(ch) == 2
        assert len(_replay_buffer[ch]) == 2

        reset_channel_state(ch)
        assert current_seq(ch) == 0
        assert ch not in _replay_buffer
        assert ch not in _subscribers
