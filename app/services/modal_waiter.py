"""In-memory waiter for ``open_modal`` tool calls.

When an agent tool opens a modal it needs a way to block on user input.
We keep a process-local registry keyed by ``callback_id``; the tool
awaits an ``asyncio.Event`` and a helper reads the payload from the
corresponding slot when it fires.

This is deliberately not durable — modals expire with the turn. A
process restart while a modal is open means the agent's tool call
raises a timeout and the turn ends cleanly; the user sees their submit
go nowhere because the backing tool call is gone. Good enough for
Phase 4; a durable backing (e.g. outbox-backed waiters) is a Phase 6
conversation.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _ModalSlot:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    values: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    submitted_by: str | None = None
    # Optional cancellation message if the user dismissed the modal or
    # it was explicitly aborted. ``None`` means "waiting".
    cancellation: str | None = None


_slots: dict[str, _ModalSlot] = {}


def register(callback_id: str | None = None) -> str:
    """Create a new waiter slot; return its ``callback_id``.

    Pass an explicit ``callback_id`` to adopt a pre-chosen value (tests);
    otherwise a UUID4 is generated. Collisions raise ``ValueError`` so
    the caller notices rather than silently stealing another waiter's
    slot.
    """
    cid = callback_id or str(uuid.uuid4())
    if cid in _slots:
        raise ValueError(f"callback_id already registered: {cid}")
    _slots[cid] = _ModalSlot()
    return cid


def submit(
    callback_id: str,
    *,
    values: dict,
    submitted_by: str,
    metadata: dict | None = None,
) -> bool:
    """Resolve the waiter for ``callback_id``.

    Returns ``True`` if the slot was found and resolved, ``False`` if
    no waiter is registered (modal submitted against a stale / restarted
    server — the Slack-side view handler treats that as a silent no-op).
    """
    slot = _slots.get(callback_id)
    if slot is None:
        logger.debug("modal submit for unknown callback_id=%s", callback_id)
        return False
    slot.values = dict(values)
    slot.submitted_by = submitted_by
    if metadata:
        slot.metadata.update(metadata)
    slot.event.set()
    return True


def cancel(callback_id: str, reason: str) -> None:
    """Mark a waiter as cancelled (user dismissed modal, timeout, etc.)."""
    slot = _slots.get(callback_id)
    if slot is None:
        return
    slot.cancellation = reason
    slot.event.set()


async def wait(callback_id: str, *, timeout: float) -> dict:
    """Block until the modal is submitted (or cancelled / times out).

    Returns a result dict with ``ok`` plus either ``values`` + ``submitted_by``
    on success or ``error`` on failure. The slot is always cleaned up
    before returning so a repeat submission has nothing to resolve.
    """
    slot = _slots.get(callback_id)
    if slot is None:
        return {"ok": False, "error": f"unknown callback_id: {callback_id}"}
    try:
        await asyncio.wait_for(slot.event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        _slots.pop(callback_id, None)
        return {"ok": False, "error": "modal timed out", "callback_id": callback_id}

    slot = _slots.pop(callback_id, None)
    if slot is None:
        return {"ok": False, "error": "slot disappeared during wait"}
    if slot.cancellation:
        return {"ok": False, "error": slot.cancellation, "callback_id": callback_id}
    return {
        "ok": True,
        "values": slot.values or {},
        "submitted_by": slot.submitted_by or "",
        "metadata": slot.metadata,
        "callback_id": callback_id,
    }


def pending_count() -> int:
    """Debug / test helper."""
    return len(_slots)


def reset() -> None:
    """Test helper — drop every pending waiter."""
    _slots.clear()
