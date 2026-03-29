"""In-memory progress tracker for long-running background operations."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_CLEANUP_DELAY = 30  # seconds after complete/fail before auto-removal


@dataclass
class Operation:
    id: str
    type: str           # e.g. "reindex", "fs_index"
    label: str          # human-readable description
    current: int = 0
    total: int = 0
    status: str = "running"  # running | completed | failed
    started_at: float = field(default_factory=time.monotonic)
    message: str = ""   # current status message (e.g. file being processed)


_operations: dict[str, Operation] = {}


def start(
    op_type: str,
    label: str,
    total: int = 0,
    *,
    op_id: str | None = None,
) -> str:
    """Start tracking a new operation. Returns the operation ID."""
    oid = op_id or uuid.uuid4().hex[:12]
    _operations[oid] = Operation(
        id=oid,
        type=op_type,
        label=label,
        total=total,
    )
    logger.debug("Progress: started %s (%s) total=%d", oid, label, total)
    return oid


def update(op_id: str, *, current: int | None = None, message: str | None = None, total: int | None = None) -> None:
    """Update progress on a running operation."""
    op = _operations.get(op_id)
    if not op:
        return
    if current is not None:
        op.current = current
    if message is not None:
        op.message = message
    if total is not None:
        op.total = total


def complete(op_id: str, *, message: str = "") -> None:
    """Mark an operation as completed and schedule cleanup."""
    op = _operations.get(op_id)
    if not op:
        return
    op.status = "completed"
    op.message = message
    _schedule_removal(op_id)


def fail(op_id: str, *, message: str = "") -> None:
    """Mark an operation as failed and schedule cleanup."""
    op = _operations.get(op_id)
    if not op:
        return
    op.status = "failed"
    op.message = message
    _schedule_removal(op_id)


def remove(op_id: str) -> None:
    """Immediately remove an operation."""
    _operations.pop(op_id, None)


def list_operations() -> list[dict]:
    """Return all tracked operations as dicts (for API serialization)."""
    now = time.monotonic()
    return [
        {
            "id": op.id,
            "type": op.type,
            "label": op.label,
            "current": op.current,
            "total": op.total,
            "status": op.status,
            "elapsed": round(now - op.started_at, 1),
            "message": op.message,
        }
        for op in _operations.values()
    ]


def _schedule_removal(op_id: str) -> None:
    """Schedule auto-removal after CLEANUP_DELAY seconds."""
    try:
        loop = asyncio.get_running_loop()
        loop.call_later(_CLEANUP_DELAY, lambda: _operations.pop(op_id, None))
    except RuntimeError:
        # No running event loop — just remove immediately
        _operations.pop(op_id, None)
