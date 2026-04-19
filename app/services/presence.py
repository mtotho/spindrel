"""Lightweight in-memory user presence.

Used by the push service to optionally skip a notification when the user
is already actively using the app. Not a full heartbeat-tracked presence
system — just a last-seen timestamp per user, populated by the frontend
pinging `POST /api/v1/presence/heartbeat` on a 60s interval while the tab
is visible.

In-memory only. A restart resets everyone to "not recently seen" — which
means immediately-after-deploy push sends will go through even to active
users for a brief window. Acceptable tradeoff vs. a DB round-trip on
every message.
"""
from __future__ import annotations

import time
import uuid

_last_seen: dict[uuid.UUID, float] = {}

# Window in seconds after which a user is considered "inactive". Must
# comfortably exceed the frontend heartbeat interval (60s) so one skipped
# ping doesn't flip a user into inactive falsely.
INACTIVE_AFTER_SECONDS = 120.0


def mark_active(user_id: uuid.UUID) -> None:
    _last_seen[user_id] = time.monotonic()


def is_active(user_id: uuid.UUID) -> bool:
    ts = _last_seen.get(user_id)
    if ts is None:
        return False
    return (time.monotonic() - ts) < INACTIVE_AFTER_SECONDS


def seconds_since_seen(user_id: uuid.UUID) -> float | None:
    ts = _last_seen.get(user_id)
    if ts is None:
        return None
    return time.monotonic() - ts
