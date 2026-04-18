"""IntegrationDispatcherTask — bus-side multiplexer for `ChannelRenderer`s.

One long-lived asyncio task per registered renderer:

1. Subscribes via `channel_events.subscribe_all()`.
2. Demultiplexes events by `channel_id` into per-channel `RenderContext`
   instances (created lazily on first event, torn down on `turn_ended`).
3. Capability-checks every event before invoking the renderer — events
   whose `kind.required_capabilities()` is not a subset of the renderer's
   declared capabilities are silently skipped.
4. Resolves the typed `DispatchTarget` for the channel via an injected
   `target_resolver` callable. Phase B accepts whatever the caller passes;
   Phase D wires this to the outbox-row target column once that exists.
   Phase F passes a real channel→target resolver.
5. Calls `renderer.render(typed_event, target)` and logs the receipt.

Phase B is inert: no renderers register with `renderer_registry`, so the
lifespan loop iterates an empty dict and starts zero tasks. The wiring
exists so Phase F can register `SlackRenderer` and have a working
delivery loop with no further plumbing.

Justification for "one task per integration, demuxed by channel" rather
than "one task per channel":

- Slack/Discord/BB all have process-wide rate limits. A single rate
  limiter per task is easier to reason about than N×channels limiters.
- Per-channel `RenderContext` (e.g., Slack's `thinking_ts`,
  `current_stream_buffer`) is per-turn ephemeral state, kept in a
  `dict[channel_id, RenderContext]` inside the task and instantiated on
  first use, torn down on `turn_ended`.
- Subscriber-queue overflow is per-subscriber: N integrations vs
  N×channels paths is the difference.
- Channels don't have an "active vs idle" lifecycle in the bus today;
  per-channel tasks would need new lifecycle hooks.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from app.services.channel_events import subscribe_all

if TYPE_CHECKING:
    from app.domain.channel_events import ChannelEvent as DomainChannelEvent
    from app.domain.dispatch_target import DispatchTarget
    from app.integrations.renderer import ChannelRenderer

logger = logging.getLogger(__name__)


# Type alias for the target-resolver callback. Returns None when the channel
# is not bound to this integration (so the dispatcher should skip it).
# May be sync or async — the dispatcher awaits both.
TargetResolver = Callable[
    [uuid.UUID],
    "DispatchTarget | None | Awaitable[DispatchTarget | None]",
]


@dataclass
class RenderContext:
    """Per-channel ephemeral state held by an integration's renderer task.

    Created lazily on the first event for a channel, torn down on
    `turn_ended`. Renderers stash transient delivery state here
    (Slack: `thinking_ts`, current `SlackStreamBuffer`, last update time;
    Discord: similar; BB: idempotency keys for duplicate webhook delivery).

    The `state` dict is intentionally untyped so each renderer can use
    its own keys without forcing a shared schema. The dispatcher does
    not read it — only the renderer does.

    Note: this dataclass is NOT frozen because renderers mutate `state`.
    `DispatchTarget` IS frozen because targets must round-trip through
    the outbox column unchanged.
    """

    channel_id: uuid.UUID
    state: dict[str, Any] = field(default_factory=dict)


class IntegrationDispatcherTask:
    """One long-lived task per registered `ChannelRenderer`.

    Subscribes to `subscribe_all()`, demuxes events to per-channel
    `RenderContext`, and calls `renderer.render(event, target)` for
    every event the renderer can handle.

    Lifecycle:

    - `start()` schedules `_run()` on the running event loop and returns
      immediately.
    - `_run()` opens a `subscribe_all()` generator and loops until
      cancelled or until the bus pushes a `replay_lapsed` sentinel
      (subscriber overflow). On overflow, the loop reopens a fresh
      subscription and continues — the outbox (Phase D) is the
      durability story for any events that fall in the gap.
    - `stop()` cancels the task and awaits its termination.

    Tests inject a fake `target_resolver`. Phase D and Phase F wire real
    resolvers (channel binding lookups, possibly outbox-row metadata).
    """

    def __init__(
        self,
        renderer: "ChannelRenderer",
        target_resolver: TargetResolver,
    ) -> None:
        self.renderer = renderer
        self._target_resolver = target_resolver
        self._contexts: dict[uuid.UUID, RenderContext] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    @property
    def integration_id(self) -> str:
        return self.renderer.integration_id

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Schedule the dispatcher loop on the running event loop."""
        if self._task is not None:
            raise RuntimeError(
                f"IntegrationDispatcherTask({self.integration_id}) already started"
            )
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(
            self._run(),
            name=f"renderer:{self.integration_id}",
        )

    async def stop(self) -> None:
        """Cancel the dispatcher loop and await termination."""
        self._stopped.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(
                "IntegrationDispatcherTask(%s) raised during shutdown",
                self.integration_id,
            )
        finally:
            self._task = None
            self._contexts.clear()

    def get_context(self, channel_id: uuid.UUID) -> RenderContext | None:
        """Test/debug helper — return the live RenderContext for a channel."""
        return self._contexts.get(channel_id)

    async def _run(self) -> None:
        """Main subscriber loop. Restarts on overflow.

        Outer `while not stopped` reopens the subscription if the bus
        pushes a `replay_lapsed` sentinel (subscriber overflow). The
        outbox covers anything missed in the gap.
        """
        while not self._stopped.is_set():
            try:
                async for event in subscribe_all():
                    if self._stopped.is_set():
                        return
                    await self._dispatch(event)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception(
                    "IntegrationDispatcherTask(%s) crashed; restarting subscription",
                    self.integration_id,
                )
                # Brief backoff so a tight crash loop doesn't peg the CPU.
                try:
                    await asyncio.sleep(0.5)
                except asyncio.CancelledError:
                    return

    async def _dispatch(self, event: "DomainChannelEvent") -> None:
        """Capability-check + target-resolve + render a single event."""
        # Outbox-durable kinds (NEW_MESSAGE today) are delivered to
        # renderers exclusively via the outbox drainer. Skipping them
        # here avoids the dual-path delivery foot-gun: the same event
        # reaching ``renderer.render()`` once via the outbox drainer and
        # again via this in-memory bus path. Publishers of these kinds
        # must enqueue an outbox row in addition to (or instead of)
        # calling ``publish_typed`` — see ``outbox_publish.enqueue_new_
        # message_for_channel`` and the ``ChannelEventKind.is_outbox_
        # durable`` docstring.
        if event.kind.is_outbox_durable:
            return

        # Capability gate. Renderers that don't declare the required
        # capabilities for a kind never see those events.
        required = event.kind.required_capabilities()
        if not required.issubset(self.renderer.capabilities):
            return

        # Per-binding target filter. Some payloads (EphemeralMessagePayload,
        # ModalButtonPayload) scope themselves to exactly one integration
        # so a multi-bound channel does not fan private content out to
        # every surface. If the payload carries a ``target_integration_id``
        # that isn't us, silently skip — the authoritative renderer will
        # pick it up on its own dispatcher task.
        target_iid = getattr(event.payload, "target_integration_id", None)
        if target_iid is not None and target_iid != self.integration_id:
            return

        # Resolve the target. None means "this channel is not bound to
        # this integration" — silently skip.
        target_or_aw = self._target_resolver(event.channel_id)
        if asyncio.iscoroutine(target_or_aw):
            target = await target_or_aw
        else:
            target = target_or_aw  # type: ignore[assignment]
        if target is None:
            return

        # Optional sanity: the target should belong to this renderer's
        # integration. A misconfigured resolver returning the wrong
        # target type is a programmer error worth logging.
        target_integration = getattr(target, "integration_id", None)
        if target_integration and target_integration != self.integration_id:
            logger.warning(
                "IntegrationDispatcherTask(%s) got a %s target for channel %s; "
                "skipping — resolver bug",
                self.integration_id,
                target_integration,
                event.channel_id,
            )
            return

        # Get-or-create per-channel RenderContext.
        ctx = self._contexts.get(event.channel_id)
        if ctx is None:
            ctx = RenderContext(channel_id=event.channel_id)
            self._contexts[event.channel_id] = ctx

        # Hand the event to the renderer. Receipts are logged but not
        # persisted in Phase B — the outbox in Phase D is what records
        # delivery state durably.
        try:
            receipt = await self.renderer.render(event, target)
        except Exception:
            logger.exception(
                "renderer(%s).render() crashed for channel %s kind=%s seq=%d",
                self.integration_id,
                event.channel_id,
                event.kind.value,
                event.seq,
            )
        else:
            if not receipt.success:
                logger.warning(
                    "renderer(%s) failed channel=%s kind=%s seq=%d retryable=%s: %s",
                    self.integration_id,
                    event.channel_id,
                    event.kind.value,
                    event.seq,
                    receipt.retryable,
                    receipt.error,
                )

        # turn_ended is the natural moment to drop per-turn ephemeral state.
        # Renderers can rely on this for cleanup; the next turn rebuilds
        # the context fresh.
        from app.domain.channel_events import ChannelEventKind  # local import to avoid cycles
        if event.kind == ChannelEventKind.TURN_ENDED:
            self._contexts.pop(event.channel_id, None)
