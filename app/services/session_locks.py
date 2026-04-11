"""Per-session active-request lock for serializing concurrent agent runs.

Because FastAPI runs in a single asyncio event loop, plain set operations are
atomic between await points — no threading or asyncio.Lock needed.

Locks carry an acquired-at timestamp so a janitor task can sweep entries that
have been held longer than ``LOCK_TTL_SECONDS``. Without the sweep, a
background task that's cancelled before its ``try`` block runs leaks the
lock until process restart — see the Phase E loose end. The TTL is sized to
the longest realistic agent turn (2 hours) so a healthy long-running run
will never get swept.
"""
import logging
import time
from uuid import UUID

logger = logging.getLogger(__name__)

# Maximum age (seconds) a session lock may be held before the janitor
# sweeps it. The longest realistic primary-bot turn is bounded by the
# agent loop's iteration cap × per-iter LLM timeout, which sits well
# under an hour. 2 hours gives ~3× headroom.
LOCK_TTL_SECONDS = 7200

_active: dict[str, float] = {}
"""session_id (str) → monotonic acquired-at timestamp."""
_cancel_requested: set[str] = set()


def is_active(session_id: UUID | str) -> bool:
    return str(session_id) in _active


def acquire(session_id: UUID | str) -> bool:
    """Try to mark session as active. Returns True if acquired, False if already locked."""
    key = str(session_id)
    if key in _active:
        return False
    _active[key] = time.monotonic()
    # Clear stale cancel flags so a STOP that arrived after the previous loop
    # finished doesn't kill this fresh request.
    _cancel_requested.discard(key)
    return True


def release(session_id: UUID | str) -> None:
    """Release the session lock."""
    key = str(session_id)
    _active.pop(key, None)
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


def sweep_stale(*, ttl_seconds: float = LOCK_TTL_SECONDS) -> int:
    """Drop locks that have been held for longer than ``ttl_seconds``.

    Designed to be called periodically by a background janitor task
    (``app/main.py:_session_lock_janitor_worker``). Returns the count
    of locks released so the caller can log meaningful sweeps.

    Acquired-at is monotonic, so this is robust against wall-clock
    jumps. Cancel-flag entries for swept locks are cleared too — a
    leaked lock with a leaked cancel flag would cause the next acquire
    of the same session id to immediately see ``is_cancel_requested``
    as True.
    """
    now = time.monotonic()
    cutoff = now - ttl_seconds
    stale = [k for k, ts in _active.items() if ts <= cutoff]
    for key in stale:
        _active.pop(key, None)
        _cancel_requested.discard(key)
    if stale:
        logger.warning(
            "session_locks: swept %d stale lock(s) older than %.0fs",
            len(stale), ttl_seconds,
        )
    return len(stale)
