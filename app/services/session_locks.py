"""Per-session active-request lock for serializing concurrent agent runs.

Because FastAPI runs in a single asyncio event loop, plain set operations are
atomic between await points — no threading or asyncio.Lock needed.
"""
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

_active: set[str] = set()
_cancel_requested: set[str] = set()


def is_active(session_id: UUID | str) -> bool:
    return str(session_id) in _active


def acquire(session_id: UUID | str) -> bool:
    """Try to mark session as active. Returns True if acquired, False if already locked."""
    key = str(session_id)
    if key in _active:
        return False
    _active.add(key)
    # Clear stale cancel flags so a STOP that arrived after the previous loop
    # finished doesn't kill this fresh request.
    _cancel_requested.discard(key)
    return True


def release(session_id: UUID | str) -> None:
    """Release the session lock."""
    key = str(session_id)
    _active.discard(key)
    _cancel_requested.discard(key)


def request_cancel(session_id: UUID | str) -> bool:
    """Request cancellation of an active session. Returns True if session is active."""
    key = str(session_id)
    if key not in _active:
        return False
    _cancel_requested.add(key)
    return True


def is_cancel_requested(session_id: UUID | str) -> bool:
    """Check if cancellation has been requested for a session."""
    return str(session_id) in _cancel_requested


def clear_cancel(session_id: UUID | str) -> None:
    """Clear the cancellation flag for a session."""
    _cancel_requested.discard(str(session_id))
