"""Phase F — SlackRateLimiter unit tests.

The limiter is a per-method async token bucket. These tests verify the
core invariants:

- Two calls to the same method are spaced by at least ``min_interval``.
- A 429 response with a ``Retry-After`` header pushes the next allowed
  call out by that many seconds.
- Different methods have independent buckets.
- ``reset()`` wipes all state.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from integrations.slack.rate_limit import SlackRateLimiter

pytestmark = pytest.mark.asyncio


class TestSlackRateLimiter:
    async def test_first_call_returns_immediately(self):
        limiter = SlackRateLimiter(default_min_interval=0.05)
        before = time.monotonic()
        await limiter.acquire("chat.postMessage")
        elapsed = time.monotonic() - before
        assert elapsed < 0.05

    async def test_second_call_blocks_until_min_interval(self):
        limiter = SlackRateLimiter(default_min_interval=0.05)
        await limiter.acquire("chat.postMessage")
        before = time.monotonic()
        await limiter.acquire("chat.postMessage")
        elapsed = time.monotonic() - before
        assert elapsed >= 0.04  # allow tiny scheduler slop

    async def test_independent_buckets_per_method(self):
        limiter = SlackRateLimiter(default_min_interval=0.5)
        await limiter.acquire("chat.postMessage")
        # A different method's bucket should be untouched and return
        # immediately.
        before = time.monotonic()
        await limiter.acquire("chat.update")
        elapsed = time.monotonic() - before
        assert elapsed < 0.05

    async def test_record_429_pushes_next_allowed_forward(self):
        limiter = SlackRateLimiter(default_min_interval=0.01)
        await limiter.acquire("chat.update")
        limiter.record_429("chat.update", retry_after=0.1)
        before = time.monotonic()
        await limiter.acquire("chat.update")
        elapsed = time.monotonic() - before
        assert elapsed >= 0.09

    async def test_record_429_does_not_shrink_existing_window(self):
        # If a much longer Retry-After is already in effect, a smaller
        # one should NOT bring the next-allowed time back.
        limiter = SlackRateLimiter(default_min_interval=0.01)
        await limiter.acquire("chat.update")
        limiter.record_429("chat.update", retry_after=10.0)
        bucket = limiter._get("chat.update")
        long_window = bucket.next_allowed_at
        limiter.record_429("chat.update", retry_after=0.001)
        assert bucket.next_allowed_at == long_window

    async def test_reset_wipes_buckets(self):
        limiter = SlackRateLimiter(default_min_interval=10.0)
        await limiter.acquire("chat.postMessage")
        limiter.reset()
        before = time.monotonic()
        await limiter.acquire("chat.postMessage")
        elapsed = time.monotonic() - before
        assert elapsed < 0.05

    async def test_concurrent_acquires_serialize(self):
        limiter = SlackRateLimiter(default_min_interval=0.05)
        results: list[float] = []

        async def _one():
            await limiter.acquire("chat.update")
            results.append(time.monotonic())

        before = time.monotonic()
        await asyncio.gather(_one(), _one(), _one())

        # Three serialized calls with min_interval=0.05 means the
        # third should land at >= 0.10 after start. Allow generous
        # slack so CI scheduling jitter doesn't flake.
        assert results[-1] - before >= 0.08
