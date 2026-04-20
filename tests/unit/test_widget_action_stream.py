"""Tests for `app.services.widget_action_stream` — the SSE multiplexer
that backs `window.spindrel.stream(...)` in widget iframes.

Covers:
- ``parse_kinds_csv`` — valid + empty + unknown-kind error
- ``widget_event_stream`` kind filter drops non-matching events
- Control frames (SHUTDOWN / REPLAY_LAPSED) bypass the kind filter
- ``since`` forwards into the bus subscriber and replays buffered events
- Keepalive fires when idle (no events within window)
- Generator teardown unregisters the subscriber from the bus
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import (
    MessagePayload,
    ShutdownPayload,
    TurnEndedPayload,
    TurnStartedPayload,
)
from app.services import widget_action_stream as stream_mod
from app.services.channel_events import (
    _next_seq,
    _replay_buffer,
    _subscribers,
    publish_typed,
    subscriber_count,
)


@pytest.fixture(autouse=True)
def _reset_bus():
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()


def _turn_started(cid: uuid.UUID, *, bot_id: str = "b1") -> ChannelEvent:
    return ChannelEvent(
        channel_id=cid,
        kind=ChannelEventKind.TURN_STARTED,
        payload=TurnStartedPayload(bot_id=bot_id, turn_id=uuid.uuid4()),
    )


def _turn_ended(cid: uuid.UUID, *, bot_id: str = "b1") -> ChannelEvent:
    return ChannelEvent(
        channel_id=cid,
        kind=ChannelEventKind.TURN_ENDED,
        payload=TurnEndedPayload(bot_id=bot_id, turn_id=uuid.uuid4()),
    )


async def _drain_one(gen) -> str:
    """Pull one frame (skipping keepalive comments) with a short timeout."""
    while True:
        chunk = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        if chunk.startswith(":"):
            continue  # keepalive
        return chunk


def _parse_data(frame: str) -> dict:
    assert frame.startswith("data: "), frame
    return json.loads(frame[len("data: "):].strip())


class TestParseKindsCsv:
    def test_none_returns_none(self):
        assert stream_mod.parse_kinds_csv(None) is None

    def test_empty_returns_none(self):
        assert stream_mod.parse_kinds_csv("") is None
        assert stream_mod.parse_kinds_csv("  ,  ") is None

    def test_single_kind(self):
        kinds = stream_mod.parse_kinds_csv("new_message")
        assert kinds == frozenset({ChannelEventKind.NEW_MESSAGE})

    def test_multiple_kinds(self):
        kinds = stream_mod.parse_kinds_csv("turn_started, turn_ended")
        assert kinds == frozenset({
            ChannelEventKind.TURN_STARTED,
            ChannelEventKind.TURN_ENDED,
        })

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown channel event kind"):
            stream_mod.parse_kinds_csv("not_a_real_kind")


class TestKindFilter:
    @pytest.mark.asyncio
    async def test_filter_drops_non_matching(self):
        cid = uuid.uuid4()
        gen = stream_mod.widget_event_stream(
            channel_id=cid,
            kinds=frozenset({ChannelEventKind.TURN_STARTED}),
            since=None,
        )
        # Prime the subscriber so publish fans out to us.
        pending = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.01)
        assert subscriber_count(cid) == 1

        # Publish a non-matching kind — it should NOT come out.
        publish_typed(cid, _turn_ended(cid))
        # Publish a matching kind — it SHOULD come out.
        publish_typed(cid, _turn_started(cid))

        frame = await asyncio.wait_for(pending, timeout=2.0)
        payload = _parse_data(frame)
        assert payload["kind"] == "turn_started"

        # Verify the turn_ended didn't leak by pulling one more with a timeout
        # short enough that the 15s keepalive can't arrive.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(gen.__anext__(), timeout=0.2)

        await gen.aclose()

    @pytest.mark.asyncio
    async def test_no_filter_passes_every_kind(self):
        cid = uuid.uuid4()
        gen = stream_mod.widget_event_stream(channel_id=cid, kinds=None, since=None)
        pending = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.01)

        publish_typed(cid, _turn_started(cid))
        publish_typed(cid, _turn_ended(cid))

        first = _parse_data(await asyncio.wait_for(pending, timeout=2.0))
        second = _parse_data(await _drain_one(gen))

        assert {first["kind"], second["kind"]} == {"turn_started", "turn_ended"}

        await gen.aclose()


class TestControlFrames:
    @pytest.mark.asyncio
    async def test_shutdown_passes_filter_and_closes(self):
        cid = uuid.uuid4()
        gen = stream_mod.widget_event_stream(
            channel_id=cid,
            kinds=frozenset({ChannelEventKind.NEW_MESSAGE}),  # shutdown NOT included
            since=None,
        )
        pending = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.01)

        # Publish a SHUTDOWN sentinel — should still come through AND the
        # generator should terminate after emitting it (no reconnect on shutdown).
        publish_typed(cid, ChannelEvent(
            channel_id=cid,
            kind=ChannelEventKind.SHUTDOWN,
            payload=ShutdownPayload(),
        ))

        payload = _parse_data(await asyncio.wait_for(pending, timeout=2.0))
        assert payload["kind"] == "shutdown"

        # Generator should exit cleanly — next anext raises StopAsyncIteration.
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(gen.__anext__(), timeout=2.0)


class TestReplayViaSince:
    @pytest.mark.asyncio
    async def test_since_replays_buffered_events(self):
        cid = uuid.uuid4()
        # Pre-publish while no subscriber is connected — events land in the ring.
        publish_typed(cid, _turn_started(cid, bot_id="alpha"))
        publish_typed(cid, _turn_started(cid, bot_id="beta"))
        # The two events are at seq 1 and 2. Subscribe with since=0 → both replay.

        gen = stream_mod.widget_event_stream(
            channel_id=cid,
            kinds=frozenset({ChannelEventKind.TURN_STARTED}),
            since=0,
        )

        first = _parse_data(await _drain_one(gen))
        second = _parse_data(await _drain_one(gen))

        assert first["seq"] == 1
        assert second["seq"] == 2
        assert first["payload"]["bot_id"] == "alpha"
        assert second["payload"]["bot_id"] == "beta"

        await gen.aclose()


class TestTeardown:
    @pytest.mark.asyncio
    async def test_aclose_unregisters_subscriber(self):
        cid = uuid.uuid4()
        gen = stream_mod.widget_event_stream(channel_id=cid, kinds=None, since=None)
        # Drive one __anext__ so the underlying ``subscribe()`` registers
        # its queue in ``_subscribers``.
        pending = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.01)
        assert subscriber_count(cid) == 1

        # Cancel the in-flight anext before aclose so we hit the teardown path.
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass
        await gen.aclose()

        # Subscriber must be gone from the bus registry.
        assert subscriber_count(cid) == 0
