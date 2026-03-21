"""Per-session active-request lock for serializing concurrent agent runs.

Because FastAPI runs in a single asyncio event loop, plain set operations are
atomic between await points — no threading or asyncio.Lock needed.
"""
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

_active: set[str] = set()


def is_active(session_id: UUID | str) -> bool:
    return str(session_id) in _active


def acquire(session_id: UUID | str) -> bool:
    """Try to mark session as active. Returns True if acquired, False if already locked."""
    key = str(session_id)
    if key in _active:
        return False
    _active.add(key)
    return True


def release(session_id: UUID | str) -> None:
    """Release the session lock."""
    _active.discard(str(session_id))
