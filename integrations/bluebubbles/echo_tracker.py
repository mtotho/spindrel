"""Bot/user disambiguation for iMessage.

Since both bot-sent and user-sent messages appear as isFromMe=true,
we track every message we send via the API and treat untracked
isFromMe messages as human-originated.

Tracking uses two signals:
  1. tempGuid — the temp GUID we pass when sending via the BB API
  2. text hash — SHA-256 prefix of the message text (fallback)

Entries expire after a configurable TTL (default 30s).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field


def _text_hash(text: str) -> str:
    """Return a short hash of the message text for fuzzy matching."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class _Entry:
    temp_guid: str
    text_hash: str
    timestamp: float


class EchoTracker:
    """Track bot-sent messages to distinguish them from human isFromMe messages."""

    def __init__(self, ttl: float = 30.0) -> None:
        self.ttl = ttl
        self._by_guid: dict[str, _Entry] = {}
        self._by_hash: dict[str, _Entry] = {}

    def track_sent(self, temp_guid: str, text: str) -> None:
        """Record a message we just sent via the BB API."""
        self._evict()
        h = _text_hash(text)
        entry = _Entry(temp_guid=temp_guid, text_hash=h, timestamp=time.monotonic())
        self._by_guid[temp_guid] = entry
        self._by_hash[h] = entry

    def is_echo(self, guid: str, text: str) -> bool:
        """Check if an incoming isFromMe message is one we sent (echo) or human."""
        self._evict()
        # Check GUID match first (normal case)
        if guid in self._by_guid:
            entry = self._by_guid.pop(guid)
            self._by_hash.pop(entry.text_hash, None)
            return True
        # Fallback: text hash match
        h = _text_hash(text)
        if h in self._by_hash:
            entry = self._by_hash.pop(h)
            self._by_guid.pop(entry.temp_guid, None)
            return True
        return False

    def _evict(self) -> None:
        """Remove entries older than TTL."""
        cutoff = time.monotonic() - self.ttl
        expired_guids = [k for k, e in self._by_guid.items() if e.timestamp < cutoff]
        for k in expired_guids:
            entry = self._by_guid.pop(k)
            self._by_hash.pop(entry.text_hash, None)
        # Also evict orphaned hash entries
        expired_hashes = [k for k, e in self._by_hash.items() if e.timestamp < cutoff]
        for k in expired_hashes:
            self._by_hash.pop(k)
