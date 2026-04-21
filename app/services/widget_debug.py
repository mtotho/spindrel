"""In-memory event ring for pinned-widget debug traces.

Widgets post structured events (tool calls, attachment loads, JS errors,
unhandled rejections, console output, author logs) to this store while
they run in the user's browser. Two readers consume it:

- The ``WidgetInspector`` UI panel on each pinned widget (queries the
  GET endpoint, polls while open).
- The ``inspect_widget_pin`` bot tool, so the authoring bot can iterate
  against the real envelope shape instead of guessing.

State is a per-pin bounded deque, held in the API process's memory.
Wiped on restart. No database, no disk — this is debug telemetry with a
short useful life, not a system of record.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any
from uuid import UUID

# Cap per pin. Large enough to catch a handful of render cycles and the
# error trail they produce; small enough that a noisy widget can't blow
# memory for an idle server.
MAX_EVENTS_PER_PIN = 50

_events: dict[UUID, deque[dict[str, Any]]] = defaultdict(
    lambda: deque(maxlen=MAX_EVENTS_PER_PIN)
)
_lock = Lock()


def record_event(pin_id: UUID, event: dict[str, Any]) -> dict[str, Any]:
    """Append a single event for a pin. Adds a server-side ``ts_server``.

    Returns the stored event (with ``ts_server`` injected) so the caller
    has a stable reference if it wants to echo back.
    """
    stored = dict(event)
    stored.setdefault("ts_server", time.time())
    with _lock:
        _events[pin_id].append(stored)
    return stored


def get_events(pin_id: UUID, limit: int = MAX_EVENTS_PER_PIN) -> list[dict[str, Any]]:
    """Return up to ``limit`` events for a pin, newest-first."""
    if limit <= 0:
        return []
    with _lock:
        buf = _events.get(pin_id)
        if not buf:
            return []
        snapshot = list(buf)
    snapshot.reverse()
    return snapshot[:limit]


def clear_events(pin_id: UUID) -> int:
    """Drop all events for a pin. Returns the number removed.

    Used by the Inspector's "Clear" button and by tests.
    """
    with _lock:
        buf = _events.pop(pin_id, None)
    return len(buf) if buf else 0


def reset_all() -> None:
    """Test helper — drop every buffer."""
    with _lock:
        _events.clear()
