"""SSE multiplexer for interactive HTML widgets.

Bridges the in-memory channel-events bus (`app.services.channel_events`) to
an SSE response body consumable by `window.spindrel.stream(...)` inside a
widget iframe. A thin wrapper around `subscribe()` that adds:

- kind filtering (widgets usually care about one or two of 25 event kinds)
- keepalive comments every 15 s
- clean teardown on consumer disconnect

Control frames (`SHUTDOWN`, `REPLAY_LAPSED`) are always forwarded — a widget
needs them to know when to reconnect or refetch baseline state, regardless
of its declared kind filter.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from app.domain.channel_events import ChannelEventKind
from app.services.channel_events import (
    event_to_sse_dict,
    get_shutdown_event,
    subscribe,
)

logger = logging.getLogger(__name__)

_KEEPALIVE_SECONDS = 15.0
_CONTROL_KINDS = frozenset({
    ChannelEventKind.SHUTDOWN,
    ChannelEventKind.REPLAY_LAPSED,
})


async def widget_event_stream(
    *,
    channel_id: uuid.UUID,
    kinds: frozenset[ChannelEventKind] | None,
    since: int | None,
) -> AsyncIterator[str]:
    """Yield pre-formatted SSE `data: ...\\n\\n` lines for a widget subscriber.

    ``kinds`` — if ``None``, forwards every event. Otherwise, forwards only
    events whose ``kind`` is in the set, plus control frames (SHUTDOWN,
    REPLAY_LAPSED) which always pass.

    ``since`` — forwarded to ``subscribe()`` for replay-on-reconnect.

    Keepalives (``: keepalive\\n\\n``) fire every 15 s of silence so the
    browser and any intermediate proxy keep the connection open.

    Teardown semantics are copied verbatim from
    ``api_v1_channels.channel_events`` — cancel the pending ``__anext__``
    future, await its completion, then ``aclose()`` the generator to avoid
    "asynchronous generator is already running" on closure.
    """
    shutdown = get_shutdown_event()
    async_gen = subscribe(channel_id, since=since)
    pending = asyncio.ensure_future(async_gen.__anext__())
    try:
        while not shutdown.is_set():
            try:
                event = await asyncio.wait_for(
                    asyncio.shield(pending), timeout=_KEEPALIVE_SECONDS,
                )
                if event.kind is ChannelEventKind.SHUTDOWN:
                    # Forward the sentinel so the widget sees a clean close,
                    # then exit — no reconnect expected on process shutdown.
                    yield f"data: {json.dumps(event_to_sse_dict(event))}\n\n"
                    break
                if kinds is None or event.kind in kinds or event.kind in _CONTROL_KINDS:
                    yield f"data: {json.dumps(event_to_sse_dict(event))}\n\n"
                pending = asyncio.ensure_future(async_gen.__anext__())
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
            except StopAsyncIteration:
                break
    finally:
        pending.cancel()
        try:
            await pending
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        except Exception:  # noqa: BLE001 — best effort on shutdown
            pass
        try:
            await async_gen.aclose()
        except (RuntimeError, StopAsyncIteration):
            pass


def parse_kinds_csv(raw: str | None) -> frozenset[ChannelEventKind] | None:
    """Parse a CSV of ``ChannelEventKind`` values from a query string.

    Returns ``None`` when ``raw`` is empty (no filter). Raises
    ``ValueError`` on unknown kinds — the caller should map that to 400.
    """
    if not raw:
        return None
    values: set[ChannelEventKind] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            values.add(ChannelEventKind(token))
        except ValueError as exc:
            raise ValueError(f"Unknown channel event kind: {token!r}") from exc
    return frozenset(values) if values else None
