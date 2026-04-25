"""Bot/user disambiguation for iMessage.

Since both bot-sent and user-sent messages appear as isFromMe=true,
we track every message we send via the API and treat untracked
isFromMe messages as human-originated.

Tracking uses four layers:
  1. content match — per-chat text hash of every message we sent;
     checked BEFORE is_from_me, catches echoes regardless of flag
  2. tempGuid / text hash — the temp GUID or SHA-256 prefix of the
     message text (legacy, popped on match, is_from_me only)
  3. per-chat reply cooldown — if we replied to a chat recently,
     treat any isFromMe as an echo (prevents loops when LLM is slow)
  4. circuit breaker — if we've replied to the same chat N times
     in a short window, stop responding entirely

The reply cooldown, circuit breaker, and sent-content state are
**persisted to the DB** (via IntegrationSetting) so they survive
server restarts — this is critical to prevent loops when BB replays
queued webhooks after a restart.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _text_hash(text: str) -> str:
    """Return a short hash of the normalized message text.

    Strips leading/trailing whitespace before hashing so that LLM
    responses with trailing newlines match the webhook's .strip()ed text.
    """
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


@dataclass
class _Entry:
    temp_guid: str
    text_hash: str
    timestamp: float  # monotonic


# Default: 5 minutes — long enough for slow LLM responses
_DEFAULT_TTL = 300.0

# Per-chat reply cooldown: if we sent a reply within this window,
# treat any isFromMe message as an echo (not human).
_REPLY_COOLDOWN = 120.0  # 2 minutes

# Echo suppress: short window to catch echoed bot replies that contain
# wake words.  Content-based matching is the primary defense, but when
# iMessage modifies the text (smart quotes, encoding) the hash won't
# match and the wake word in the bot's own echoed reply re-triggers it.
# 15 seconds is long enough to catch any echo, short enough for a human
# to re-trigger the bot intentionally.
_ECHO_SUPPRESS_WINDOW = 15.0

# Circuit breaker: max bot replies per chat in a time window.
# If exceeded, refuse to respond until the window passes.
_CIRCUIT_BREAKER_MAX = 5
_CIRCUIT_BREAKER_WINDOW = 300.0  # 5 minutes

_DB_KEY = "bb_reply_state"
_DB_KEY_CONTENT = "bb_sent_content"
_INTEGRATION_ID = "bluebubbles"


class EchoTracker:
    """Track bot-sent messages to distinguish them from human isFromMe messages."""

    def __init__(self, ttl: float = _DEFAULT_TTL) -> None:
        self.ttl = ttl
        self._by_guid: dict[str, _Entry] = {}
        self._by_hash: dict[str, _Entry] = {}
        # Per-chat: list of wall-clock timestamps when we sent replies.
        # Uses time.time() (not monotonic) so it can be persisted.
        self._chat_replies: dict[str, list[float]] = defaultdict(list)
        # Per-chat sent content: {chat_guid: {text_hash: wall-clock timestamp}}.
        # NOT popped on match — entries only expire by TTL.  Used for
        # content-based echo detection regardless of is_from_me flag.
        self._sent_content: dict[str, dict[str, float]] = defaultdict(dict)

    def track_sent(self, temp_guid: str, text: str, *, chat_guid: str = "") -> None:
        """Record a message we just sent via the BB API."""
        self._evict()
        h = _text_hash(text)
        entry = _Entry(temp_guid=temp_guid, text_hash=h, timestamp=time.monotonic())
        self._by_guid[temp_guid] = entry
        self._by_hash[h] = entry
        if chat_guid:
            self._chat_replies[chat_guid].append(time.time())
            self._sent_content[chat_guid][h] = time.time()

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
        now = time.time()
        replies = self._chat_replies.get(chat_guid, [])
        return any(now - ts < _REPLY_COOLDOWN for ts in replies)

    def in_echo_suppress(self, chat_guid: str, window: float | None = None) -> bool:
        """Return True if we replied to this chat very recently (echo suppress window).

        Shorter than in_reply_cooldown — designed to catch echoed bot messages
        that contain wake words and would otherwise re-trigger the bot.
        Used for is_from_me=False paths (wake word + no-mention).

        Args:
            chat_guid: The chat to check.
            window: Override the default suppress window (seconds).
                    If None, uses _ECHO_SUPPRESS_WINDOW (15s).
        """
        if not chat_guid:
            return False
        w = window if window is not None else _ECHO_SUPPRESS_WINDOW
        now = time.time()
        replies = self._chat_replies.get(chat_guid, [])
        return any(now - ts < w for ts in replies)

    def is_circuit_open(self, chat_guid: str) -> bool:
        """Return True if the circuit breaker has tripped for this chat.

        If True, the bot should NOT respond — too many replies in the window.
        """
        if not chat_guid:
            return False
        now = time.time()
        replies = self._chat_replies.get(chat_guid, [])
        recent = [ts for ts in replies if now - ts < _CIRCUIT_BREAKER_WINDOW]
        return len(recent) >= _CIRCUIT_BREAKER_MAX

    def is_own_content(self, chat_guid: str, text: str) -> bool:
        """Check if we recently sent this exact text to this chat.

        Unlike is_echo(), this is NOT gated on is_from_me and does NOT
        pop entries.  It catches echoes regardless of how BB reports the
        is_from_me flag — the primary defense against echo loops.
        """
        if not chat_guid:
            return False
        self._evict()
        h = _text_hash(text)
        ts = self._sent_content.get(chat_guid, {}).get(h)
        if ts is None:
            return False
        return time.time() - ts < self.ttl

    def _evict(self) -> None:
        """Remove entries older than TTL."""
        cutoff = time.monotonic() - self.ttl
        expired_guids = [k for k, e in self._by_guid.items() if e.timestamp < cutoff]
        for k in expired_guids:
            entry = self._by_guid.pop(k)
            self._by_hash.pop(entry.text_hash, None)
        expired_hashes = [k for k, e in self._by_hash.items() if e.timestamp < cutoff]
        for k in expired_hashes:
            self._by_hash.pop(k)
        # Evict old chat reply timestamps (wall clock)
        breaker_cutoff = time.time() - _CIRCUIT_BREAKER_WINDOW
        for chat_guid in list(self._chat_replies):
            self._chat_replies[chat_guid] = [
                ts for ts in self._chat_replies[chat_guid] if ts > breaker_cutoff
            ]
            if not self._chat_replies[chat_guid]:
                del self._chat_replies[chat_guid]
        # Evict old sent content entries (wall clock, same TTL as main entries)
        content_cutoff = time.time() - self.ttl
        for chat_guid in list(self._sent_content):
            self._sent_content[chat_guid] = {
                h: ts for h, ts in self._sent_content[chat_guid].items()
                if ts > content_cutoff
            }
            if not self._sent_content[chat_guid]:
                del self._sent_content[chat_guid]

    # -- DB persistence (IntegrationSetting) --

    async def save_to_db(self) -> None:
        """Persist reply timestamps and sent content hashes to the DB."""
        try:
            from integrations.sdk import IntegrationSetting, async_session
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            replies_data = json.dumps(dict(self._chat_replies))
            content_data = json.dumps(dict(self._sent_content))
            async with async_session() as db:
                for key, data in ((_DB_KEY, replies_data), (_DB_KEY_CONTENT, content_data)):
                    stmt = pg_insert(IntegrationSetting).values(
                        integration_id=_INTEGRATION_ID,
                        key=key,
                        value=data,
                        is_secret=False,
                    ).on_conflict_do_update(
                        index_elements=["integration_id", "key"],
                        set_={"value": data},
                    )
                    await db.execute(stmt)
                await db.commit()
        except Exception:
            logger.debug("BB echo tracker: could not save reply state to DB", exc_info=True)

    async def load_from_db(self) -> None:
        """Load reply timestamps and sent content hashes from the DB."""
        try:
            from integrations.sdk import IntegrationSetting, async_session
            from sqlalchemy import select

            async with async_session() as db:
                rows = (await db.execute(
                    select(IntegrationSetting).where(
                        IntegrationSetting.integration_id == _INTEGRATION_ID,
                        IntegrationSetting.key.in_((_DB_KEY, _DB_KEY_CONTENT)),
                    )
                )).scalars().all()

            now = time.time()
            for row in rows:
                if not row.value:
                    continue
                data = json.loads(row.value)

                if row.key == _DB_KEY:
                    loaded = 0
                    for chat_guid, timestamps in data.items():
                        recent = [ts for ts in timestamps if now - ts < _CIRCUIT_BREAKER_WINDOW]
                        if recent:
                            self._chat_replies[chat_guid] = recent
                            loaded += len(recent)
                    if loaded:
                        logger.info("BB echo tracker: loaded %d reply timestamps for %d chats from DB",
                                    loaded, len(self._chat_replies))

                elif row.key == _DB_KEY_CONTENT:
                    loaded = 0
                    for chat_guid, hashes in data.items():
                        recent = {h: ts for h, ts in hashes.items() if now - ts < self.ttl}
                        if recent:
                            self._sent_content[chat_guid] = recent
                            loaded += len(recent)
                    if loaded:
                        logger.info("BB echo tracker: loaded %d sent content hashes for %d chats from DB",
                                    loaded, len(self._sent_content))
        except Exception:
            logger.debug("BB echo tracker: could not load reply state from DB", exc_info=True)


# Shared singleton — used by both webhook handler and renderer delivery.
# (both run in the same FastAPI process).
shared_tracker = EchoTracker()
