"""Polling helpers for waiting on async conditions."""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class WaitTimeout(Exception):
    """Raised when a wait_for_condition call exceeds its timeout."""


async def wait_for_condition(
    check_fn: Callable[[], Awaitable[T]],
    timeout: float,
    interval: float = 1.0,
    description: str = "condition",
) -> T:
    """Poll *check_fn* until it returns a truthy value or *timeout* expires.

    Args:
        check_fn: Async callable that returns a truthy value on success.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.
        description: Human-readable label for error messages.

    Returns:
        The truthy return value from *check_fn*.

    Raises:
        WaitTimeout: If *timeout* expires before *check_fn* succeeds.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            result = await check_fn()
            if result:
                return result
        except Exception as exc:
            last_error = exc

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(interval, remaining))

    msg = f"Timed out waiting for {description} after {timeout}s"
    if last_error:
        msg += f" (last error: {last_error})"
    raise WaitTimeout(msg)
