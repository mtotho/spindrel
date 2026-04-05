"""In-memory session-scoped capability (carapace) activation store.

When a bot activates a capability via the activate_capability tool, the
activation is recorded here keyed by session_id (correlation_id).  On
subsequent turns in the same conversation, context assembly merges these
session-activated carapaces into the bot's carapace list so they feed
through the standard resolution pipeline.

Follows the same pattern as app/agent/session_allows.py.
"""

import logging
import time

logger = logging.getLogger(__name__)

# session_id (str) → {carapace_id: activation_timestamp}
_sessions: dict[str, dict[str, float]] = {}

# Auto-cleanup: evict sessions older than this
_MAX_AGE = 3600 * 4  # 4 hours


def activate(session_id: str, carapace_id: str) -> None:
    """Record a capability activation for this session."""
    if session_id not in _sessions:
        _sessions[session_id] = {}
    _sessions[session_id][carapace_id] = time.monotonic()
    logger.debug(
        "Capability activated: %s for session %s (%d active in session)",
        carapace_id, session_id[:8], len(_sessions[session_id]),
    )


def get_activated(session_id: str | None) -> set[str]:
    """Return all activated capability IDs for this session."""
    if not session_id:
        return set()
    return set(_sessions.get(session_id, {}).keys())


def is_activated(session_id: str | None, carapace_id: str) -> bool:
    """Check if a capability is activated in this session."""
    if not session_id:
        return False
    return carapace_id in _sessions.get(session_id, {})


def clear_session(session_id: str) -> int:
    """Remove all activations for a session. Returns count removed."""
    entry = _sessions.pop(session_id, None)
    count = len(entry) if entry else 0
    if count:
        logger.debug("Cleared %d capability activations for session %s", count, session_id[:8])
    return count


def cleanup_stale() -> int:
    """Remove sessions with no activations newer than _MAX_AGE. Call periodically."""
    cutoff = time.monotonic() - _MAX_AGE
    stale_sessions = []
    for sid, caps in _sessions.items():
        if all(ts < cutoff for ts in caps.values()):
            stale_sessions.append(sid)
    for sid in stale_sessions:
        del _sessions[sid]
    return len(stale_sessions)


def active_count() -> int:
    """Total number of sessions with active capabilities."""
    return len(_sessions)


def total_activations() -> int:
    """Total number of activated capabilities across all sessions."""
    return sum(len(caps) for caps in _sessions.values())
