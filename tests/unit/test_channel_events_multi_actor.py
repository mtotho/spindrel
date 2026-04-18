"""Phase E.8 — multi-actor seams: channel_events subscribe + replay

Two behavioral contracts not covered by the existing single-actor tests:

1. Overflow isolation: subscriber A stalls and receives ``replay_lapsed``.
   Subscriber B is healthy and must continue receiving live events with no
   sentinel, no duplicates, no lost events. Overflow drain must touch only the
   overflowed subscriber's queue.

2. Concurrent replay: two subscribers reconnecting with different ``since``
   values independently get their own replay windows from the shared buffer,
   with no cross-contamination between queues and no duplication.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import ReplayLapsedPayload, ShutdownPayload, TurnStartedPayload
from app.services.channel_events import (
    QUEUE_MAX_SIZE,
    publish_typed,
    subscribe,
    subscriber_count,
    _next_seq,
    _replay_buffer,
    _subscribers,
)


@pytest.fixture(autouse=True)
def _clean():
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()


def _cid() -> uuid.UUID:
    return uuid.uuid4()


def _evt(ch: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=ch,
        kind=ChannelEventKind.TURN_STARTED,
        payload=TurnStartedPayload(bot_id="b", turn_id=uuid.uuid4()),
    )


def _shutdown(ch: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=ch,
        kind=ChannelEventKind.SHUTDOWN,
        payload=ShutdownPayload(),
    )


class TestOverflowIsolation:
    @pytest.mark.asyncio
    async def test_when_slow_subscriber_overflows_then_fast_subscriber_unaffected(self):
        """Subscriber A stalls → gets replay_lapsed. Subscriber B drains quickly
        and must never see a replay_lapsed sentinel. Flooding uses sleep(0) between
        each publish so B drains its queue between events while A's queue fills."""
        ch = _cid()
        b_received: list[ChannelEvent] = []
        a_lapsed = asyncio.Event()
        b_done = asyncio.Event()

        async def _consume_a():
            async for ev in subscribe(ch):
                if ev.kind is ChannelEventKind.REPLAY_LAPSED:
                    a_lapsed.set()
                    return
                await asyncio.sleep(0.5)  # stall so queue fills while flood runs

        async def _consume_b():
            count = 0
            async for ev in subscribe(ch):
                if ev.kind is ChannelEventKind.REPLAY_LAPSED:
                    break  # B must NOT reach here — counts as failure
                b_received.append(ev)
                count += 1
                if count >= 5:
                    break
            b_done.set()

        task_a = asyncio.create_task(_consume_a())
        task_b = asyncio.create_task(_consume_b())
        await asyncio.sleep(0.02)
        assert subscriber_count(ch) == 2

        # First event — A stalls for 0.5s, B consumes immediately.
        publish_typed(ch, _evt(ch))
        await asyncio.sleep(0)

        # Flood with a yield after each publish: B drains one event per tick,
        # A stays stalled so its queue grows until overflow (after QUEUE_MAX_SIZE events).
        for _ in range(QUEUE_MAX_SIZE + 20):
            publish_typed(ch, _evt(ch))
            await asyncio.sleep(0)

        # A wakes from sleep(0.5), sees replay_lapsed, sets a_lapsed.
        await asyncio.wait_for(a_lapsed.wait(), timeout=2.0)
        await asyncio.wait_for(b_done.wait(), timeout=2.0)

        task_a.cancel()
        task_b.cancel()
        for t in (task_a, task_b):
            try:
                await t
            except asyncio.CancelledError:
                pass

        assert len(b_received) >= 5
        assert all(
            ev.kind is not ChannelEventKind.REPLAY_LAPSED for ev in b_received
        ), "Healthy subscriber must never receive a replay_lapsed sentinel"

    @pytest.mark.asyncio
    async def test_when_lapsed_subscriber_exits_then_count_decrements(self):
        """After the lapsed subscriber A exits, subscriber_count reflects only
        the remaining healthy subscriber B. Uses sleep(0) between publishes so
        B drains its queue while A's stalls and overflows."""
        ch = _cid()
        a_done = asyncio.Event()

        async def _consume_a():
            # A sleeps on every event — queue fills until overflow.
            # subscribe() exits after yielding replay_lapsed, so the async for
            # loop ends regardless of whether A checks the kind.
            async for _ev in subscribe(ch):
                await asyncio.sleep(0.5)
            a_done.set()

        async def _consume_b():
            # B consumes events immediately; no stall, no break.
            async for _ev in subscribe(ch):
                pass

        task_a = asyncio.create_task(_consume_a())
        task_b = asyncio.create_task(_consume_b())
        await asyncio.sleep(0.02)
        assert subscriber_count(ch) == 2

        # First event → A stalls for 0.5s.
        publish_typed(ch, _evt(ch))
        await asyncio.sleep(0)

        # Flood: B drains, A fills → overflow after QUEUE_MAX_SIZE events.
        for _ in range(QUEUE_MAX_SIZE + 20):
            publish_typed(ch, _evt(ch))
            await asyncio.sleep(0)

        # A wakes, gets replay_lapsed, sleeps 0.5s for that iteration, then
        # subscribe() exits → async for ends → a_done. (~1s total wait).
        await asyncio.wait_for(a_done.wait(), timeout=3.0)
        await asyncio.sleep(0.02)

        assert subscriber_count(ch) == 1, "Only B remains; A exited after lapsed sentinel"

        task_a.cancel()
        task_b.cancel()
        for t in (task_a, task_b):
            try:
                await t
            except asyncio.CancelledError:
                pass


class TestConcurrentReplay:
    @pytest.mark.asyncio
    async def test_two_subscribers_with_different_since_get_independent_windows(self):
        """Subscriber A reconnects with since=2, subscriber B with since=4.
        Each reads only its own slice of the shared replay buffer — no
        cross-contamination, no missing events."""
        ch = _cid()
        for _ in range(6):
            publish_typed(ch, _evt(ch))
        # Buffer now has seq 1..6.

        a_received: list[int] = []
        b_received: list[int] = []

        async def _consume_a():
            async for ev in subscribe(ch, since=2):
                a_received.append(ev.seq)
                if ev.seq >= 6:
                    break

        async def _consume_b():
            async for ev in subscribe(ch, since=4):
                b_received.append(ev.seq)
                if ev.seq >= 6:
                    break

        await asyncio.gather(
            asyncio.wait_for(_consume_a(), timeout=2.0),
            asyncio.wait_for(_consume_b(), timeout=2.0),
        )

        assert a_received == [3, 4, 5, 6]
        assert b_received == [5, 6]

    @pytest.mark.asyncio
    async def test_replay_subscriber_does_not_inject_into_live_subscriber_queue(self):
        """When A reconnects with since=N and replays buffered events, those
        replayed events must not appear in B's queue. B is a live subscriber
        that joined after the original publish."""
        ch = _cid()
        publish_typed(ch, _evt(ch))  # seq=1 — in buffer only

        b_received: list[ChannelEvent] = []
        b_ready = asyncio.Event()
        b_done = asyncio.Event()

        async def _consume_b():
            b_ready.set()
            async for ev in subscribe(ch):
                b_received.append(ev)
                if len(b_received) >= 2:
                    break
            b_done.set()

        task_b = asyncio.create_task(_consume_b())
        await asyncio.wait_for(b_ready.wait(), timeout=1.0)
        await asyncio.sleep(0.02)

        a_received: list[ChannelEvent] = []

        async def _consume_a():
            async for ev in subscribe(ch, since=0):
                a_received.append(ev)
                if len(a_received) >= 3:
                    break

        task_a = asyncio.create_task(_consume_a())
        await asyncio.sleep(0.02)

        # Two live events: both A and B should receive them.
        publish_typed(ch, _evt(ch))   # seq=2
        publish_typed(ch, _evt(ch))   # seq=3

        await asyncio.wait_for(task_a, timeout=2.0)
        await asyncio.wait_for(b_done.wait(), timeout=2.0)
        task_b.cancel()
        try:
            await task_b
        except asyncio.CancelledError:
            pass

        b_seqs = [ev.seq for ev in b_received]
        a_seqs = [ev.seq for ev in a_received]

        # A must have received the replayed seq=1 plus live events.
        assert 1 in a_seqs
        # A must not receive duplicate seqs.
        assert a_seqs == sorted(set(a_seqs))
        # B was not subscribed when seq=1 was published and must not receive it
        # via A's replay (replay is per-subscriber, not broadcast).
        assert 1 not in b_seqs

    @pytest.mark.asyncio
    async def test_both_subscribers_independently_deduplicate_replay_vs_live(self):
        """Each subscriber's seq deduplication is independent: events that
        arrive during replay are queued for the subscriber that replays, not
        duplicated in its own stream, and not visible in the other's stream."""
        ch = _cid()
        for _ in range(3):
            publish_typed(ch, _evt(ch))  # seq 1..3

        a_seqs: list[int] = []
        b_seqs: list[int] = []

        async def _consume_a():
            async for ev in subscribe(ch, since=1):
                a_seqs.append(ev.seq)
                if len(a_seqs) >= 3:
                    break

        async def _consume_b():
            async for ev in subscribe(ch, since=2):
                b_seqs.append(ev.seq)
                if len(b_seqs) >= 2:
                    break

        tasks = [
            asyncio.create_task(_consume_a()),
            asyncio.create_task(_consume_b()),
        ]
        # Publish two more events after both subscribers start replaying.
        await asyncio.sleep(0.02)
        publish_typed(ch, _evt(ch))  # seq=4
        publish_typed(ch, _evt(ch))  # seq=5

        for t in tasks:
            await asyncio.wait_for(t, timeout=2.0)

        assert a_seqs == sorted(set(a_seqs)), "A must not see duplicate seqs"
        assert b_seqs == sorted(set(b_seqs)), "B must not see duplicate seqs"
        # A started after seq=1 so gets 2..
        assert all(s > 1 for s in a_seqs)
        # B started after seq=2 so gets 3..
        assert all(s > 2 for s in b_seqs)
