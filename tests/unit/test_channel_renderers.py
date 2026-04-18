"""Phase B — tests for `app/services/channel_renderers.py`.

`IntegrationDispatcherTask` is one task per registered ChannelRenderer.
It subscribes to the bus via `subscribe_all()`, demuxes events into
per-channel `RenderContext` instances, capability-filters every event,
resolves the dispatch target via an injected callable, and calls
`renderer.render(event, target)`.

Tests use a fake renderer that records every call so we can assert:

- The renderer receives events for every channel that publishes them.
- Per-channel `RenderContext` is isolated (Slack and Discord-style state
  for channel A doesn't bleed into channel B).
- `RenderContext` is torn down on `turn_ended` so the next turn starts
  with a clean state.
- Capability gating drops events whose `kind.required_capabilities()` is
  not a subset of `renderer.capabilities`.
- A `target_resolver` returning None silently skips delivery.
- A `target_resolver` returning a target with the wrong `integration_id`
  is logged and skipped (programmer-error guard).
- A renderer raising an exception does not crash the dispatcher loop.
- `stop()` cancels the task and clears all contexts.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent as DomainChannelEvent, ChannelEventKind
from app.domain.dispatch_target import WebTarget
from integrations.slack.target import SlackTarget
from app.domain.payloads import (
    MessagePayload,
    ShutdownPayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamTokenPayload,
)
from app.domain.message import Message
from app.domain.actor import ActorRef
from app.integrations.renderer import DeliveryReceipt
from app.services import channel_events as ce_module
from app.services.channel_events import publish_typed
from app.services.channel_renderers import (
    IntegrationDispatcherTask,
    RenderContext,
)


@pytest.fixture(autouse=True)
def _clean_bus_state():
    ce_module._subscribers.clear()
    ce_module._next_seq.clear()
    ce_module._replay_buffer.clear()
    ce_module._global_subscribers.clear()
    yield
    ce_module._subscribers.clear()
    ce_module._next_seq.clear()
    ce_module._replay_buffer.clear()
    ce_module._global_subscribers.clear()


def _cid() -> uuid.UUID:
    return uuid.uuid4()


def _make_message(channel_id: uuid.UUID, body: str = "hello") -> Message:
    return Message(
        id=uuid.uuid4(),
        channel_id=channel_id,
        session_id=uuid.uuid4(),
        role="assistant",
        content=body,
        created_at=datetime.now(timezone.utc),
        actor=ActorRef.bot("bot1"),
    )


class FakeRenderer:
    """Renderer that records every call. Configurable capabilities.

    Uses integration_id="slack" so it pairs naturally with SlackTarget
    in the dispatch tests; the renderer-registry tests in
    test_renderer_registry.py exercise duplicate-id rejection separately.
    """

    integration_id = "slack"

    def __init__(self, *, capabilities: frozenset[Capability] | None = None) -> None:
        self.capabilities = capabilities if capabilities is not None else frozenset({
            Capability.TEXT,
            Capability.STREAMING_EDIT,
        })
        self.rendered: list[tuple[DomainChannelEvent, object]] = []
        self.actions: list[object] = []
        self.deletes: list[dict] = []
        self.raise_on_render = False

    async def render(self, event, target):
        self.rendered.append((event, target))
        if self.raise_on_render:
            raise RuntimeError("simulated renderer crash")
        return DeliveryReceipt.ok(external_id=f"ext-{event.seq}")

    async def handle_outbound_action(self, action, target):
        self.actions.append(action)
        return DeliveryReceipt.ok()

    async def delete_attachment(self, attachment_metadata, target):
        self.deletes.append(attachment_metadata)
        return True


def _slack_target() -> SlackTarget:
    return SlackTarget(channel_id="C1", token="xoxb-test")


async def _spin_until(predicate, *, timeout: float = 1.0):
    """Yield to the loop until `predicate()` is true or timeout elapses."""
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("predicate did not become true within timeout")
        await asyncio.sleep(0.01)


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_then_stop_is_clean(self):
        renderer = FakeRenderer()
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        assert task.is_running
        await asyncio.sleep(0.01)  # let subscribe_all() register
        await task.stop()
        assert not task.is_running

    @pytest.mark.asyncio
    async def test_double_start_raises(self):
        renderer = FakeRenderer()
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        try:
            with pytest.raises(RuntimeError, match="already started"):
                task.start()
        finally:
            await task.stop()


def _turn_started_event(channel_id: uuid.UUID) -> DomainChannelEvent:
    """Build a TURN_STARTED event for use as a non-outbox-durable
    sentinel in dispatch tests. ``NEW_MESSAGE`` is short-circuited by
    ``IntegrationDispatcherTask._dispatch`` because it's outbox-durable;
    streaming/lifecycle kinds still flow via the bus and are the right
    test vehicle for verifying the dispatcher's routing behavior."""
    return DomainChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.TURN_STARTED,
        payload=TurnStartedPayload(bot_id="bot1", turn_id=uuid.uuid4()),
    )


class TestEventDispatch:
    @pytest.mark.asyncio
    async def test_renderer_receives_published_event(self):
        renderer = FakeRenderer()
        target = _slack_target()
        task = IntegrationDispatcherTask(renderer, lambda _ch: target)
        task.start()
        await asyncio.sleep(0.01)

        try:
            ch = _cid()
            evt = _turn_started_event(ch)
            publish_typed(ch, evt)

            await _spin_until(lambda: len(renderer.rendered) == 1)

            (received_event, received_target) = renderer.rendered[0]
            assert received_event.kind == ChannelEventKind.TURN_STARTED
            assert received_event.channel_id == ch
            assert received_target is target
        finally:
            await task.stop()

    @pytest.mark.asyncio
    async def test_events_for_multiple_channels_demuxed(self):
        renderer = FakeRenderer()
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        await asyncio.sleep(0.01)

        try:
            ch1, ch2 = _cid(), _cid()
            for ch in (ch1, ch2):
                publish_typed(ch, _turn_started_event(ch))

            await _spin_until(lambda: len(renderer.rendered) == 2)
            channel_ids = {ev.channel_id for ev, _ in renderer.rendered}
            assert channel_ids == {ch1, ch2}
            # Per-channel contexts created.
            assert task.get_context(ch1) is not None
            assert task.get_context(ch2) is not None
            # Different objects.
            assert task.get_context(ch1) is not task.get_context(ch2)
        finally:
            await task.stop()

    @pytest.mark.asyncio
    async def test_outbox_durable_kinds_skip_bus_dispatch(self):
        """Regression: NEW_MESSAGE is outbox-durable. The dispatcher
        must short-circuit it before capability gating + target
        resolution so the renderer never sees the same msg.id twice
        (once via the outbox drainer, once via subscribe_all). The
        outbox drainer is the sole renderer-delivery path for these
        kinds."""
        renderer = FakeRenderer()
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        await asyncio.sleep(0.01)

        try:
            ch = _cid()
            # Publish a NEW_MESSAGE — should NOT reach the renderer
            # because is_outbox_durable returns True.
            publish_typed(ch, DomainChannelEvent(
                channel_id=ch,
                kind=ChannelEventKind.NEW_MESSAGE,
                payload=MessagePayload(message=_make_message(ch)),
            ))
            # And a TURN_STARTED — should reach the renderer (not outbox-durable).
            publish_typed(ch, _turn_started_event(ch))

            await _spin_until(lambda: len(renderer.rendered) == 1)
            await asyncio.sleep(0.05)
            assert len(renderer.rendered) == 1
            assert renderer.rendered[0][0].kind == ChannelEventKind.TURN_STARTED
        finally:
            await task.stop()


class TestCapabilityGating:
    @pytest.mark.asyncio
    async def test_event_requiring_missing_capability_is_skipped(self):
        # Renderer only declares TEXT (no STREAMING_EDIT).
        renderer = FakeRenderer(capabilities=frozenset({Capability.TEXT}))
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch = _cid()
            _tid = uuid.uuid4()
            # turn_stream_token requires STREAMING_EDIT.
            publish_typed(ch, DomainChannelEvent(
                channel_id=ch,
                kind=ChannelEventKind.TURN_STREAM_TOKEN,
                payload=TurnStreamTokenPayload(bot_id="bot1", turn_id=_tid, delta="hi"),
            ))
            # And a TEXT-only event that should pass through.
            publish_typed(ch, DomainChannelEvent(
                channel_id=ch,
                kind=ChannelEventKind.TURN_STARTED,
                payload=TurnStartedPayload(bot_id="bot1", turn_id=_tid),
            ))
            await _spin_until(lambda: len(renderer.rendered) >= 1)
            await asyncio.sleep(0.05)
            assert len(renderer.rendered) == 1
            assert renderer.rendered[0][0].kind == ChannelEventKind.TURN_STARTED
        finally:
            await task.stop()

    @pytest.mark.asyncio
    async def test_event_requiring_no_capabilities_is_always_delivered(self):
        renderer = FakeRenderer(capabilities=frozenset())
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch = _cid()
            # SHUTDOWN requires no capabilities.
            publish_typed(ch, DomainChannelEvent(
                channel_id=ch,
                kind=ChannelEventKind.SHUTDOWN,
                payload=ShutdownPayload(),
            ))
            await _spin_until(lambda: len(renderer.rendered) == 1)
        finally:
            await task.stop()


class TestTargetResolution:
    @pytest.mark.asyncio
    async def test_resolver_none_skips_delivery(self):
        renderer = FakeRenderer()
        task = IntegrationDispatcherTask(renderer, lambda _ch: None)
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch = _cid()
            publish_typed(ch, _turn_started_event(ch))
            await asyncio.sleep(0.05)
            assert renderer.rendered == []
        finally:
            await task.stop()

    @pytest.mark.asyncio
    async def test_async_resolver_supported(self):
        renderer = FakeRenderer()
        target = _slack_target()

        async def _async_resolver(_channel_id):
            await asyncio.sleep(0)
            return target

        task = IntegrationDispatcherTask(renderer, _async_resolver)
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch = _cid()
            publish_typed(ch, _turn_started_event(ch))
            await _spin_until(lambda: len(renderer.rendered) == 1)
            assert renderer.rendered[0][1] is target
        finally:
            await task.stop()

    @pytest.mark.asyncio
    async def test_resolver_returning_wrong_integration_target_skips(self):
        """A misconfigured resolver that returns a target whose
        integration_id doesn't match the renderer is a programmer error.
        The dispatcher logs and skips."""
        renderer = FakeRenderer()
        # WebTarget has integration_id="web", renderer is "fake".
        task = IntegrationDispatcherTask(renderer, lambda _ch: WebTarget())
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch = _cid()
            publish_typed(ch, _turn_started_event(ch))
            await asyncio.sleep(0.05)
            assert renderer.rendered == []
        finally:
            await task.stop()


class TestPerBindingTargetFilter:
    """``target_integration_id`` on a payload scopes an event to one
    bound integration. Dispatchers for every other integration must
    silently drop — otherwise a multi-bound channel fans private
    content out to every surface (the Phase 3 ephemeral bug)."""

    @pytest.mark.asyncio
    async def test_mismatched_target_integration_id_is_skipped(self):
        from app.domain.payloads import EphemeralMessagePayload

        renderer = FakeRenderer(capabilities=frozenset({
            Capability.TEXT, Capability.EPHEMERAL,
        }))
        # renderer.integration_id == "slack" (class attribute).
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch = _cid()
            msg = _make_message(ch, "private")
            # Event targeted at "web" — our slack dispatcher must ignore it.
            publish_typed(ch, DomainChannelEvent(
                channel_id=ch,
                kind=ChannelEventKind.EPHEMERAL_MESSAGE,
                payload=EphemeralMessagePayload(
                    message=msg,
                    recipient_user_id="UALICE",
                    target_integration_id="web",
                ),
            ))
            await asyncio.sleep(0.05)
            assert renderer.rendered == []
        finally:
            await task.stop()

    @pytest.mark.asyncio
    async def test_matching_target_integration_id_delivered(self):
        from app.domain.payloads import EphemeralMessagePayload

        renderer = FakeRenderer(capabilities=frozenset({
            Capability.TEXT, Capability.EPHEMERAL,
        }))
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch = _cid()
            msg = _make_message(ch, "private")
            publish_typed(ch, DomainChannelEvent(
                channel_id=ch,
                kind=ChannelEventKind.EPHEMERAL_MESSAGE,
                payload=EphemeralMessagePayload(
                    message=msg,
                    recipient_user_id="UALICE",
                    target_integration_id="slack",
                ),
            ))
            await _spin_until(lambda: len(renderer.rendered) == 1)
        finally:
            await task.stop()


class TestRenderContextLifecycle:
    @pytest.mark.asyncio
    async def test_context_torn_down_on_turn_ended(self):
        renderer = FakeRenderer()
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch = _cid()
            _tid = uuid.uuid4()
            publish_typed(ch, DomainChannelEvent(
                channel_id=ch,
                kind=ChannelEventKind.TURN_STARTED,
                payload=TurnStartedPayload(bot_id="bot1", turn_id=_tid),
            ))
            await _spin_until(lambda: task.get_context(ch) is not None)
            # Stash some state in the context.
            task.get_context(ch).state["thinking_ts"] = "1234.5678"

            # Now end the turn.
            publish_typed(ch, DomainChannelEvent(
                channel_id=ch,
                kind=ChannelEventKind.TURN_ENDED,
                payload=TurnEndedPayload(bot_id="bot1", turn_id=_tid, result="done"),
            ))
            await _spin_until(lambda: task.get_context(ch) is None)
        finally:
            await task.stop()

    @pytest.mark.asyncio
    async def test_render_context_isolated_per_channel(self):
        renderer = FakeRenderer()
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch1, ch2 = _cid(), _cid()
            _tid = uuid.uuid4()
            for ch in (ch1, ch2):
                publish_typed(ch, DomainChannelEvent(
                    channel_id=ch,
                    kind=ChannelEventKind.TURN_STARTED,
                    payload=TurnStartedPayload(bot_id="bot1", turn_id=_tid),
                ))
            await _spin_until(lambda: task.get_context(ch1) is not None and task.get_context(ch2) is not None)

            task.get_context(ch1).state["k"] = "v1"
            task.get_context(ch2).state["k"] = "v2"
            assert task.get_context(ch1).state == {"k": "v1"}
            assert task.get_context(ch2).state == {"k": "v2"}

            # Ending one channel's turn doesn't affect the other.
            publish_typed(ch1, DomainChannelEvent(
                channel_id=ch1,
                kind=ChannelEventKind.TURN_ENDED,
                payload=TurnEndedPayload(bot_id="bot1", turn_id=_tid, result="done"),
            ))
            await _spin_until(lambda: task.get_context(ch1) is None)
            assert task.get_context(ch2) is not None
            assert task.get_context(ch2).state == {"k": "v2"}
        finally:
            await task.stop()


class TestRendererCrashIsolation:
    @pytest.mark.asyncio
    async def test_render_exception_does_not_kill_loop(self):
        renderer = FakeRenderer()
        renderer.raise_on_render = True
        task = IntegrationDispatcherTask(renderer, lambda _ch: _slack_target())
        task.start()
        await asyncio.sleep(0.01)
        try:
            ch = _cid()
            publish_typed(ch, _turn_started_event(ch))
            await _spin_until(lambda: len(renderer.rendered) == 1)

            # Now stop raising and verify the loop still processes.
            renderer.raise_on_render = False
            publish_typed(ch, _turn_started_event(ch))
            await _spin_until(lambda: len(renderer.rendered) == 2)
            assert task.is_running
        finally:
            await task.stop()


class TestRenderContextDataclass:
    def test_default_state_is_empty_dict(self):
        ctx = RenderContext(channel_id=_cid())
        assert ctx.state == {}
        ctx.state["foo"] = "bar"
        assert ctx.state == {"foo": "bar"}

    def test_separate_instances_have_isolated_state(self):
        a = RenderContext(channel_id=_cid())
        b = RenderContext(channel_id=_cid())
        a.state["k"] = "a"
        b.state["k"] = "b"
        assert a.state["k"] == "a"
        assert b.state["k"] == "b"
