"""In-memory session-scoped tool allows.

When a user clicks "Approve" on a tool approval, the tool is allowed for
the remainder of that conversation (keyed by correlation_id).  This avoids
repeated approval prompts for the same tool within a single agent run —
the most common frustration with the approval system.

Entries are lightweight (just a set of tuples) and naturally expire when
the correlation_id is no longer referenced.
"""

import logging
import time

logger = logging.getLogger(__name__)

# (correlation_id_str, tool_name) → timestamp when allow was granted
_allows: dict[tuple[str, str], float] = {}

# Auto-cleanup: remove entries older than this (covers abandoned sessions)
_MAX_AGE = 3600 * 4  # 4 hours


def add_session_allow(correlation_id: str, tool_name: str) -> None:
    """Allow a tool for the remainder of a conversation."""
    key = (correlation_id, tool_name)
    _allows[key] = time.monotonic()
    logger.debug(
        "Session allow: %s for correlation %s (%d active)",
        tool_name, correlation_id[:8], len(_allows),
    )


def is_session_allowed(correlation_id: str | None, tool_name: str) -> bool:
    """Check if a tool is session-allowed for this conversation."""
    if not correlation_id:
        return False
    return (correlation_id, tool_name) in _allows


def clear_session(correlation_id: str) -> int:
    """Remove all session allows for a conversation. Returns count removed."""
    to_remove = [k for k in _allows if k[0] == correlation_id]
    for k in to_remove:
        del _allows[k]
    if to_remove:
        logger.debug("Cleared %d session allows for %s", len(to_remove), correlation_id[:8])
    return len(to_remove)


def cleanup_stale() -> int:
    """Remove entries older than _MAX_AGE. Call periodically."""
    cutoff = time.monotonic() - _MAX_AGE
    stale = [k for k, ts in _allows.items() if ts < cutoff]
    for k in stale:
        del _allows[k]
    return len(stale)


def active_count() -> int:
    return len(_allows)
