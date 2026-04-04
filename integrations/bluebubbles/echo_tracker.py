"""Bot/user disambiguation for iMessage.

Since both bot-sent and user-sent messages appear as isFromMe=true,
we track every message we send via the API and treat untracked
isFromMe messages as human-originated.

Tracking uses three layers:
  1. tempGuid — the temp GUID we pass when sending via the BB API
  2. text hash — SHA-256 prefix of the message text (fallback)
  3. per-chat reply cooldown — if we replied to a chat recently,
     treat any isFromMe as an echo (prevents loops when LLM is slow)

Plus a circuit breaker: if we've replied to the same chat N times
in a short window, stop responding entirely.
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass


def _text_hash(text: str) -> str:
    """Return a short hash of the message text for fuzzy matching."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class _Entry:
    temp_guid: str
    text_hash: str
    timestamp: float


# Default: 5 minutes — long enough for slow LLM responses
_DEFAULT_TTL = 300.0

# Per-chat reply cooldown: if we sent a reply within this window,
# treat any isFromMe message as an echo (not human).
_REPLY_COOLDOWN = 120.0  # 2 minutes

# Circuit breaker: max bot replies per chat in a time window.
# If exceeded, refuse to respond until the window passes.
_CIRCUIT_BREAKER_MAX = 5
_CIRCUIT_BREAKER_WINDOW = 300.0  # 5 minutes


class EchoTracker:
    """Track bot-sent messages to distinguish them from human isFromMe messages."""

    def __init__(self, ttl: float = _DEFAULT_TTL) -> None:
        self.ttl = ttl
        self._by_guid: dict[str, _Entry] = {}
        self._by_hash: dict[str, _Entry] = {}
        # Per-chat: list of timestamps when we sent replies
        self._chat_replies: dict[str, list[float]] = defaultdict(list)

    def track_sent(self, temp_guid: str, text: str, *, chat_guid: str = "") -> None:
        """Record a message we just sent via the BB API."""
        self._evict()
        h = _text_hash(text)
        entry = _Entry(temp_guid=temp_guid, text_hash=h, timestamp=time.monotonic())
        self._by_guid[temp_guid] = entry
        self._by_hash[h] = entry
        if chat_guid:
            self._chat_replies[chat_guid].append(time.monotonic())

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

    def in_reply_cooldown(self, chat_guid: str) -> bool:
        """Return True if we recently sent a reply to this chat.

        If True, any isFromMe message should be treated as an echo, not human input.
        """
        if not chat_guid:
            return False
        now = time.monotonic()
        replies = self._chat_replies.get(chat_guid, [])
        return any(now - ts < _REPLY_COOLDOWN for ts in replies)

    def is_circuit_open(self, chat_guid: str) -> bool:
        """Return True if the circuit breaker has tripped for this chat.

        If True, the bot should NOT respond — too many replies in the window.
        """
        if not chat_guid:
            return False
        now = time.monotonic()
        replies = self._chat_replies.get(chat_guid, [])
        recent = [ts for ts in replies if now - ts < _CIRCUIT_BREAKER_WINDOW]
        return len(recent) >= _CIRCUIT_BREAKER_MAX

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
        # Evict old chat reply timestamps
        breaker_cutoff = time.monotonic() - _CIRCUIT_BREAKER_WINDOW
        for chat_guid in list(self._chat_replies):
            self._chat_replies[chat_guid] = [
                ts for ts in self._chat_replies[chat_guid] if ts > breaker_cutoff
            ]
            if not self._chat_replies[chat_guid]:
                del self._chat_replies[chat_guid]


# Shared singleton — used by both webhook handler and dispatcher
# (both run in the same FastAPI process).
shared_tracker = EchoTracker()
