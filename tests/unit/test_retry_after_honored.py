"""Unit tests for `Retry-After` header honoring in `_classify_error`.

When a 429 response carries a ``Retry-After`` header (RFC 7231: either
``delta-seconds`` or ``HTTP-date``), the retry loop should respect it instead
of using the existing exp-jitter, so we don't wake up before the upstream
provider lifts the ban and burn a retry attempt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import openai
import pytest


def _rate_limit_error(retry_after: str | None) -> openai.RateLimitError:
    """Construct a real openai.RateLimitError with a fake httpx.Response that
    carries (or omits) the Retry-After header."""
    headers = {}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(429, headers=headers, request=request)
    return openai.RateLimitError(
        message="rate limited",
        response=response,
        body=None,
    )


def test_retry_after_seconds_int_parsed():
    from app.agent.llm import _parse_retry_after

    exc = _rate_limit_error("30")
    assert _parse_retry_after(exc) == 30.0


def test_retry_after_seconds_float_parsed():
    from app.agent.llm import _parse_retry_after

    exc = _rate_limit_error("12.5")
    assert _parse_retry_after(exc) == 12.5


def test_retry_after_http_date_parsed_to_positive_delta():
    from app.agent.llm import _parse_retry_after

    future = datetime.now(timezone.utc) + timedelta(seconds=45)
    exc = _rate_limit_error(format_datetime(future, usegmt=True))

    parsed = _parse_retry_after(exc)
    assert parsed is not None
    # Allow a small drift (network/clock parse latency).
    assert 30 < parsed < 60


def test_retry_after_http_date_in_past_returns_none():
    from app.agent.llm import _parse_retry_after

    past = datetime.now(timezone.utc) - timedelta(seconds=300)
    exc = _rate_limit_error(format_datetime(past, usegmt=True))
    assert _parse_retry_after(exc) is None


def test_retry_after_missing_returns_none():
    from app.agent.llm import _parse_retry_after

    exc = _rate_limit_error(retry_after=None)
    assert _parse_retry_after(exc) is None


def test_retry_after_unparseable_returns_none():
    from app.agent.llm import _parse_retry_after

    exc = _rate_limit_error("not-a-number-not-a-date")
    assert _parse_retry_after(exc) is None


def test_classify_error_propagates_retry_after_to_classification():
    """Smoking gun: `_classify_error` must populate retry_after_seconds so the
    sleep computation can branch on it."""
    from app.agent.llm import _classify_error

    exc = _rate_limit_error("17")
    cl = _classify_error(exc, has_tools=False)

    assert cl.retryable is True
    assert cl.retry_after_seconds == 17.0


def test_classify_error_falls_through_when_no_header():
    from app.agent.llm import _classify_error

    exc = _rate_limit_error(retry_after=None)
    cl = _classify_error(exc, has_tools=False)

    assert cl.retryable is True
    assert cl.retry_after_seconds is None
