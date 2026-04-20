"""Per-script tool-call budget for ``run_script``.

``run_script`` counts as one iteration in the agent loop's
``max_iterations`` fence but its inner Python script can dispatch
arbitrary many tool calls via ``/api/v1/internal/tools/exec``. Without
a cap a prompt-injected script could burn provider credits and
hammer MCP backends around the fence.

Contract
--------
* :func:`open_budget` is called by ``run_script`` before exec, keyed
  by the parent correlation id (injected into the script's env as
  ``SPINDREL_PARENT_CORRELATION_ID``).
* :func:`spend` is called by ``/internal/tools/exec`` on every
  dispatch. If the correlation id has no open budget the call is
  allowed (it came from a non-script path — the channel policy gate
  is still the primary defender there). If a budget exists, it is
  decremented; when it hits zero the function returns ``allowed=False``
  and the endpoint should return HTTP 429.
* :func:`close_budget` is called by ``run_script`` in ``finally`` so
  the in-memory state doesn't leak between invocations.

State is per-process in-memory. Multi-worker deployments would need a
shared store (Redis, DB row) — out of scope; Spindrel runs one
uvicorn worker today.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = [
    "BudgetExhausted",
    "close_budget",
    "open_budget",
    "peek",
    "spend",
]


@dataclass(slots=True)
class _Entry:
    limit: int
    remaining: int


_entries: dict[str, _Entry] = {}
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


class BudgetExhausted(Exception):
    """Raised by :func:`spend` callers that prefer exceptions over tuples."""


async def open_budget(correlation_id: str, limit: int) -> None:
    """Register a new budget. Idempotent: a second open with the same id
    resets the remaining count to ``limit`` (a retried script gets a
    fresh allowance). ``limit`` below 1 disables the budget entirely for
    this correlation id."""
    if not correlation_id or limit <= 0:
        return
    async with _get_lock():
        _entries[correlation_id] = _Entry(limit=limit, remaining=limit)


async def spend(correlation_id: str | None) -> tuple[bool, int, int]:
    """Decrement the budget for ``correlation_id``.

    Returns ``(allowed, remaining, limit)``.

    * ``correlation_id`` empty or not registered → ``(True, -1, -1)``
      (untracked — caller should allow). ``-1`` is the sentinel for
      "no budget applies here".
    * Registered, remaining > 0 → decrement, return ``(True, new_remaining, limit)``.
    * Registered, remaining == 0 → return ``(False, 0, limit)``.
    """
    if not correlation_id:
        return True, -1, -1
    async with _get_lock():
        entry = _entries.get(correlation_id)
        if entry is None:
            return True, -1, -1
        if entry.remaining <= 0:
            return False, 0, entry.limit
        entry.remaining -= 1
        return True, entry.remaining, entry.limit


async def peek(correlation_id: str | None) -> tuple[int, int]:
    """Return ``(remaining, limit)`` without decrementing. ``(-1, -1)``
    if there is no budget for this id."""
    if not correlation_id:
        return -1, -1
    async with _get_lock():
        entry = _entries.get(correlation_id)
        if entry is None:
            return -1, -1
        return entry.remaining, entry.limit


async def close_budget(correlation_id: str | None) -> tuple[int, int] | None:
    """Drop the budget. Returns the final ``(spent, limit)`` if it
    existed, ``None`` otherwise."""
    if not correlation_id:
        return None
    async with _get_lock():
        entry = _entries.pop(correlation_id, None)
        if entry is None:
            return None
        return entry.limit - entry.remaining, entry.limit
