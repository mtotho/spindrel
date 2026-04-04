"""Tests for the in-memory channel event bus."""
import asyncio
import uuid

import pytest

from app.services.channel_events import (
    ChannelEvent,
    QUEUE_MAX_SIZE,
    publish,
    subscribe,
    subscriber_count,
    _subscribers,
)


@pytest.fixture(autouse=True)
def _clean_subscribers():
    """Ensure global subscriber state is clean between tests."""
    _subscribers.clear()
    yield
    _subscribers.clear()


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
