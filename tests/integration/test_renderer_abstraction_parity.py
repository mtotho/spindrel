"""Phase H — renderer abstraction parity tests.

These tests prove the integration delivery refactor's invariants hold:

1. Capability gating actually filters at the dispatcher boundary, not
   inside individual renderers — a TEXT-only renderer never sees a
   STREAMING_EDIT-required event.
2. Multiple renderers bound to the same channel each receive the
   events independently. One integration's rate limiter / errors do
   not block the other.
3. NEW_MESSAGE events reach a renderer ONLY via the outbox drainer,
   never via the in-memory bus path. This is the core "mirror-removal"
   regression — the fix for the dual-delivery foot-gun that the
   per-renderer dedup LRU used to mask.

The canonical "BB port from scratch" case (Track item #1) is out of
scope per session-14 user direction — BlueBubbles is being handled
separately. The remaining 4 cases of the original 8-case Phase H plan
are covered elsewhere:

- ``test_renderer_abstraction_parity.py`` (this file): cases 2, 6, 7
- ``tests/unit/test_outbox_drainer.py::TestClaimBatch``: case 5
  (outbox crash recovery via ``reset_stale_in_flight``)
- ``tests/unit/test_channel_renderers.py``: case 3 (capability gating
  on the IntegrationDispatcherTask path) and case 4 (target-type
  coverage via the per-target-type round-trip suite in
  ``test_domain_dispatch_target.py``)
- ``tests/integration/test_slack_end_to_end.py``: case 8 (Slack
  duplicate-edit / coalesce / safety pass — the original
  user-reported bug fix)
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import ClassVar

import pytest

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import (
    ChannelEvent,
    ChannelEventKind,
)
from app.domain.dispatch_target import _BaseTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    MessagePayload,
    TurnStartedPayload,
    TurnStreamTokenPayload,
)
from app.integrations.renderer import DeliveryReceipt
from app.services.channel_events import (
    _global_subscribers,
    _next_seq,
    _replay_buffer,
    _subscribers,
    publish_typed,
)
from app.services.channel_renderers import IntegrationDispatcherTask


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_bus_state():
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    _global_subscribers.clear()
    yield
    _subscribers.clear()
    _next_seq.clear()
    _replay_buffer.clear()
    _global_subscribers.clear()


class _ParityFakeTarget(_BaseTarget):
    """Lightweight target that tests can hand to any FakeRenderer.

    Uses a dynamic ``integration_id`` so each renderer instance can pin
    its own. Frozen dataclass semantics aren't required for this stub.
    """

    def __init__(self, integration_id: str):
        object.__setattr__(self, "type", integration_id)
        object.__setattr__(self, "integration_id", integration_id)


class _RecordingRenderer:
    """Records every (event, target) pair it receives.

    Configurable capability set so a single test class can drive both
    "TEXT only" and "STREAMING_EDIT" renderers. The dispatcher's
    capability gate is what should filter — the renderer just records.
    """

    def __init__(
        self,
        integration_id: str,
        capabilities: frozenset[Capability],
    ) -> None:
        self.integration_id = integration_id
        self.capabilities = capabilities
        self.received: list[tuple[ChannelEvent, _BaseTarget]] = []

    async def render(self, event, target):
        self.received.append((event, target))
        return DeliveryReceipt.ok()

    async def handle_outbound_action(self, action, target):
        return DeliveryReceipt.ok()

    async def delete_attachment(self, _meta, _target):
        return False


def _new_message_event(channel_id: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(
            message=DomainMessage(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                role="user",
                content="hi from web",
                created_at=datetime.now(timezone.utc),
                actor=ActorRef.user("web-user"),
                channel_id=channel_id,
            ),
        ),
    )


def _turn_started(channel_id: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.TURN_STARTED,
        payload=TurnStartedPayload(bot_id="bot1", turn_id=uuid.uuid4()),
    )


def _turn_token(channel_id: uuid.UUID, delta: str = "x") -> ChannelEvent:
    return ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.TURN_STREAM_TOKEN,
        payload=TurnStreamTokenPayload(
            bot_id="bot1",
            turn_id=uuid.uuid4(),
            delta=delta,
        ),
    )


async def _spin_until(predicate, *, timeout: float = 1.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("predicate did not become true within timeout")
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Case 2 — hypothetical text-only integration
# ---------------------------------------------------------------------------


class TestHypotheticalTextOnlyIntegration:
    """A new integration declares only ``Capability.TEXT``. The
    dispatcher must drop every event whose ``required_capabilities()``
    is not a subset of TEXT — specifically the streaming kinds — without
    the renderer ever having to filter them itself.

    This is the "did we get the abstraction right" canary: building a
    new TEXT-only integration should require zero awareness of which
    kinds exist.
    """

    async def test_text_only_renderer_skips_streaming_kinds(self):
        text_only = _RecordingRenderer(
            integration_id="text_only",
            capabilities=frozenset({Capability.TEXT}),
        )
        target = _ParityFakeTarget("text_only")
        task = IntegrationDispatcherTask(text_only, lambda _ch: target)
        task.start()
        await asyncio.sleep(0.01)

        try:
            ch = uuid.uuid4()
            # TURN_STARTED requires TEXT — should be delivered.
            publish_typed(ch, _turn_started(ch))
            # TURN_STREAM_TOKEN requires STREAMING_EDIT — should NOT be delivered.
            publish_typed(ch, _turn_token(ch, "hello"))
            # And another TURN_STARTED to confirm subsequent TEXT events still flow.
            publish_typed(ch, _turn_started(ch))

            await _spin_until(lambda: len(text_only.received) == 2)
            await asyncio.sleep(0.05)

            kinds = {ev.kind for ev, _ in text_only.received}
            assert kinds == {ChannelEventKind.TURN_STARTED}
            # The streaming token never reached the renderer.
            assert ChannelEventKind.TURN_STREAM_TOKEN not in kinds
        finally:
            await task.stop()


# ---------------------------------------------------------------------------
# Case 6 — two integrations bound to the same channel
# ---------------------------------------------------------------------------


class TestTwoIntegrationsSameChannel:
    """Each integration runs as its own ``IntegrationDispatcherTask``.
    A single channel bound to two integrations must deliver each event
    to both. One integration's failure / rate limit / capability set
    must not block the other."""

    async def test_both_integrations_receive_independently(self):
        a = _RecordingRenderer(
            integration_id="integration_a",
            capabilities=frozenset({Capability.TEXT, Capability.STREAMING_EDIT}),
        )
        b = _RecordingRenderer(
            integration_id="integration_b",
            capabilities=frozenset({Capability.TEXT, Capability.STREAMING_EDIT}),
        )
        target_a = _ParityFakeTarget("integration_a")
        target_b = _ParityFakeTarget("integration_b")

        task_a = IntegrationDispatcherTask(a, lambda _ch: target_a)
        task_b = IntegrationDispatcherTask(b, lambda _ch: target_b)
        task_a.start()
        task_b.start()
        await asyncio.sleep(0.01)

        try:
            ch = uuid.uuid4()
            publish_typed(ch, _turn_started(ch))
            publish_typed(ch, _turn_token(ch, "hi"))

            await _spin_until(
                lambda: len(a.received) == 2 and len(b.received) == 2
            )

            assert {ev.kind for ev, _ in a.received} == {
                ChannelEventKind.TURN_STARTED,
                ChannelEventKind.TURN_STREAM_TOKEN,
            }
            assert {ev.kind for ev, _ in b.received} == {
                ChannelEventKind.TURN_STARTED,
                ChannelEventKind.TURN_STREAM_TOKEN,
            }
            # Each integration sees its own typed target back.
            assert all(t is target_a for _, t in a.received)
            assert all(t is target_b for _, t in b.received)
        finally:
            await task_a.stop()
            await task_b.stop()

    async def test_one_integration_capability_set_does_not_block_other(self):
        """Integration A is TEXT-only. Integration B has STREAMING_EDIT.
        A streaming token should reach B but not A."""
        a = _RecordingRenderer(
            integration_id="integration_a",
            capabilities=frozenset({Capability.TEXT}),
        )
        b = _RecordingRenderer(
            integration_id="integration_b",
            capabilities=frozenset({Capability.TEXT, Capability.STREAMING_EDIT}),
        )
        target_a = _ParityFakeTarget("integration_a")
        target_b = _ParityFakeTarget("integration_b")

        task_a = IntegrationDispatcherTask(a, lambda _ch: target_a)
        task_b = IntegrationDispatcherTask(b, lambda _ch: target_b)
        task_a.start()
        task_b.start()
        await asyncio.sleep(0.01)

        try:
            ch = uuid.uuid4()
            publish_typed(ch, _turn_token(ch, "stream chunk"))
            publish_typed(ch, _turn_started(ch))

            await _spin_until(
                lambda: len(a.received) >= 1 and len(b.received) >= 2
            )
            await asyncio.sleep(0.05)

            assert {ev.kind for ev, _ in a.received} == {
                ChannelEventKind.TURN_STARTED
            }
            assert {ev.kind for ev, _ in b.received} == {
                ChannelEventKind.TURN_STARTED,
                ChannelEventKind.TURN_STREAM_TOKEN,
            }
        finally:
            await task_a.stop()
            await task_b.stop()


# ---------------------------------------------------------------------------
# Case 7 — mirror-removal regression (NEW_MESSAGE single-path delivery)
# ---------------------------------------------------------------------------


class TestNewMessageSinglePathDelivery:
    """The session-14 NEW_MESSAGE single-path migration made the outbox
    drainer the SOLE renderer-delivery path for ``NEW_MESSAGE``.
    ``IntegrationDispatcherTask._dispatch`` short-circuits any kind for
    which ``ChannelEventKind.is_outbox_durable`` is True. Without this,
    a ``publish_typed(NEW_MESSAGE, ...)`` from a non-outbox publisher
    (heartbeat, _fanout, delegation, …) would reach the renderer twice
    once that publisher was migrated — the per-renderer LRU used to
    mask this. The fix removes the LRU; this test pins the contract."""

    async def test_new_message_does_not_reach_renderer_via_bus_path(self):
        """A ``publish_typed(NEW_MESSAGE)`` MUST NOT reach the renderer
        via the bus path. The outbox drainer is the only delivery path
        for outbox-durable kinds."""
        renderer = _RecordingRenderer(
            integration_id="slack",
            capabilities=frozenset({
                Capability.TEXT,
                Capability.STREAMING_EDIT,
            }),
        )
        target = _ParityFakeTarget("slack")
        task = IntegrationDispatcherTask(renderer, lambda _ch: target)
        task.start()
        await asyncio.sleep(0.01)

        try:
            ch = uuid.uuid4()
            # Publish NEW_MESSAGE — this is the path that USED to reach
            # the renderer twice (once via this in-memory bus, once via
            # the outbox drainer). After the fix, it should not reach
            # the bus-side dispatcher at all.
            publish_typed(ch, _new_message_event(ch))
            # And a TURN_STARTED to prove the dispatcher loop IS alive
            # — it's just NEW_MESSAGE that's filtered.
            publish_typed(ch, _turn_started(ch))

            await _spin_until(lambda: len(renderer.received) == 1)
            await asyncio.sleep(0.05)

            assert len(renderer.received) == 1
            assert renderer.received[0][0].kind == ChannelEventKind.TURN_STARTED
        finally:
            await task.stop()

    async def test_outbox_durable_property_is_set_for_new_message(self):
        """Pin the contract at the type level: NEW_MESSAGE is the
        only outbox-durable kind today. Adding a new kind to the
        durable set is a deliberate, reviewable change."""
        durable = {
            k for k in ChannelEventKind if k.is_outbox_durable
        }
        assert durable == {ChannelEventKind.NEW_MESSAGE}
