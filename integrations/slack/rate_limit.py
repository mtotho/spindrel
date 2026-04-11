"""Slack rate limiter — single token bucket per Slack API method.

Slack's tier-1 web-API limits are roughly 1 req/sec for ``chat.postMessage``
and ``chat.update`` (the two methods that produce the user-reported
"mobile sometimes never refreshes" symptom when over-driven). The legacy
in-subprocess code path debounced ``chat.update`` to 0.8s but had no
process-wide rate limit and no awareness of Slack's 429 ``Retry-After``
header — multiple parallel turns or fast tool-result loops could still
storm the API.

The renderer in ``integrations/slack/renderer.py`` calls
``acquire(method)`` before every API call. ``acquire`` blocks until the
bucket has a token; on a 429 response from Slack the renderer calls
``record_429(method, retry_after)`` and the limiter pushes the next
allowed time forward by ``retry_after`` seconds, throttling all
in-process callers of the same method.

Single global instance — ``slack_rate_limiter`` — keeps the state shared
across all per-channel ``RenderContext``s.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Per-method minimum interval between requests (seconds). Slack's tier-1
# limits are documented as "1+ per second" — leave a bit of headroom so
# we don't get 429s in steady state.
_DEFAULT_MIN_INTERVAL = 1.05


@dataclass
class _MethodBucket:
    """State for a single Slack API method.

    ``next_allowed_at`` is a monotonic clock timestamp; ``acquire`` sleeps
    until ``time.monotonic() >= next_allowed_at`` and then advances it by
    ``min_interval``.
    """

    min_interval: float = _DEFAULT_MIN_INTERVAL
    next_allowed_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SlackRateLimiter:
    """Per-method async token bucket for the Slack web API."""

    def __init__(self, default_min_interval: float = _DEFAULT_MIN_INTERVAL) -> None:
        self._default = default_min_interval
        self._buckets: dict[str, _MethodBucket] = {}

    def _get(self, method: str) -> _MethodBucket:
        bucket = self._buckets.get(method)
        if bucket is None:
            bucket = _MethodBucket(min_interval=self._default)
            self._buckets[method] = bucket
        return bucket

    async def acquire(self, method: str) -> None:
        """Block until the limiter allows the next call to ``method``.

        The lock around the bucket serializes concurrent ``acquire`` calls
        for the same method so they queue rather than racing.
        """
        bucket = self._get(method)
        async with bucket.lock:
            now = time.monotonic()
            wait = bucket.next_allowed_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            bucket.next_allowed_at = now + bucket.min_interval

    def record_429(self, method: str, retry_after: float) -> None:
        """Push ``next_allowed_at`` for ``method`` forward by ``retry_after`` seconds.

        Called when Slack returns ``429`` with a ``Retry-After`` header.
        """
        bucket = self._get(method)
        new_next = time.monotonic() + max(retry_after, 0.0)
        if new_next > bucket.next_allowed_at:
            bucket.next_allowed_at = new_next
        logger.warning(
            "SlackRateLimiter: 429 on %s, deferring next call by %.1fs",
            method, retry_after,
        )

    def reset(self) -> None:
        """Wipe all bucket state. Test helper."""
        self._buckets.clear()


# Single shared instance — used by SlackRenderer and any other Slack-side
# code that hits the web API on the renderer's behalf.
slack_rate_limiter = SlackRateLimiter()
