"""Tests for the rate-limiting middleware."""

import asyncio
import json
import time

import pytest

from app.services.rate_limiter import RateLimitMiddleware, RateSpec, _Bucket


# ---------------------------------------------------------------------------
# RateSpec.parse
# ---------------------------------------------------------------------------

class TestRateSpecParse:
    def test_per_minute(self):
        spec = RateSpec.parse("100/minute")
        assert spec.count == 100
        assert spec.period_seconds == 60

    def test_per_second(self):
        spec = RateSpec.parse("10/second")
        assert spec.count == 10
        assert spec.period_seconds == 1

    def test_per_hour(self):
        spec = RateSpec.parse("5000/hour")
        assert spec.count == 5000
        assert spec.period_seconds == 3600

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid rate spec"):
            RateSpec.parse("100")

    def test_unknown_period(self):
        with pytest.raises(ValueError, match="Unknown period"):
            RateSpec.parse("100/day")


# ---------------------------------------------------------------------------
# Bucket
# ---------------------------------------------------------------------------

class TestBucket:
    def test_consume_within_limit(self):
        b = _Bucket(tokens=5.0, max_tokens=5, refill_rate=1.0)
        now = time.monotonic()
        for _ in range(5):
            assert b.consume(now) is True

    def test_consume_exceeds_limit(self):
        b = _Bucket(tokens=1.0, max_tokens=1, refill_rate=1.0)
        now = time.monotonic()
        assert b.consume(now) is True
        assert b.consume(now) is False

    def test_refill_over_time(self):
        b = _Bucket(tokens=0.0, max_tokens=5, refill_rate=10.0)
        now = time.monotonic()
        b.last_refill = now
        # Simulate 0.5s later → 5 tokens refilled
        assert b.consume(now + 0.5) is True

    def test_tokens_capped_at_max(self):
        b = _Bucket(tokens=0.0, max_tokens=3, refill_rate=100.0)
        now = time.monotonic()
        b.last_refill = now
        # After long time, tokens should cap at max
        b.consume(now + 100)  # refills to max, consumes 1
        assert b.tokens <= 3.0

    def test_retry_after(self):
        b = _Bucket(tokens=0.0, max_tokens=5, refill_rate=10.0)
        retry = b.retry_after()
        assert retry > 0
        assert retry <= 0.11  # ~0.1s at 10 tokens/s


# ---------------------------------------------------------------------------
# Middleware helpers
# ---------------------------------------------------------------------------

def _make_middleware(
    default: str = "5/second",
    chat: str = "2/second",
) -> RateLimitMiddleware:
    """Create a middleware with a no-op inner app."""
    async def noop_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    return RateLimitMiddleware(
        noop_app,
        default_spec=RateSpec.parse(default),
        chat_spec=RateSpec.parse(chat),
    )


def _http_scope(
    path: str = "/api/v1/bots",
    method: str = "GET",
    headers: list | None = None,
    client: tuple | None = ("127.0.0.1", 12345),
) -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "client": client,
    }


class TestClientKeyExtraction:
    def test_bearer_token(self):
        mw = _make_middleware()
        scope = _http_scope(headers=[[b"authorization", b"Bearer my-secret-key"]])
        assert mw._get_client_key(scope) == "key:my-secret-key"

    def test_query_param(self):
        mw = _make_middleware()
        scope = _http_scope()
        scope["query_string"] = b"api_key=test123&foo=bar"
        assert mw._get_client_key(scope) == "key:test123"

    def test_fallback_ip(self):
        mw = _make_middleware()
        scope = _http_scope()
        assert mw._get_client_key(scope) == "ip:127.0.0.1"

    def test_no_client(self):
        mw = _make_middleware()
        scope = _http_scope(client=None)
        assert mw._get_client_key(scope) == "ip:unknown"


class TestChatPathDetection:
    def test_chat_stream(self):
        mw = _make_middleware()
        assert mw._is_chat_path("POST", "/chat/stream") is True

    def test_chat_blocking(self):
        mw = _make_middleware()
        assert mw._is_chat_path("POST", "/chat") is True

    def test_non_chat(self):
        mw = _make_middleware()
        assert mw._is_chat_path("GET", "/api/v1/bots") is False

    def test_get_chat_not_matched(self):
        mw = _make_middleware()
        assert mw._is_chat_path("GET", "/chat/stream") is False


# ---------------------------------------------------------------------------
# Full middleware integration
# ---------------------------------------------------------------------------

async def _call_middleware(mw, scope):
    """Call the middleware and capture the response status + body."""
    status = None
    headers = {}
    body_parts = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
            for k, v in message.get("headers", []):
                headers[k if isinstance(k, str) else k.decode()] = (
                    v if isinstance(v, str) else v.decode()
                )
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    await mw(scope, receive, send)
    return status, headers, b"".join(body_parts)


@pytest.mark.asyncio
async def test_allows_within_limit():
    mw = _make_middleware(default="5/second")
    scope = _http_scope()
    for _ in range(5):
        status, _, _ = await _call_middleware(mw, scope)
        assert status == 200


@pytest.mark.asyncio
async def test_denies_over_limit():
    mw = _make_middleware(default="2/second")
    scope = _http_scope()
    await _call_middleware(mw, scope)  # 1
    await _call_middleware(mw, scope)  # 2
    status, headers, body = await _call_middleware(mw, scope)  # 3 → denied
    assert status == 429
    assert "retry-after" in headers
    data = json.loads(body)
    assert data["detail"] == "Too many requests"


@pytest.mark.asyncio
async def test_chat_stricter_limit():
    mw = _make_middleware(default="10/second", chat="2/second")
    scope = _http_scope(path="/chat/stream", method="POST")
    await _call_middleware(mw, scope)  # 1
    await _call_middleware(mw, scope)  # 2
    status, _, _ = await _call_middleware(mw, scope)  # 3 → chat limit hit
    assert status == 429


@pytest.mark.asyncio
async def test_chat_and_default_both_checked():
    """Chat requests consume both the chat bucket and the default bucket."""
    mw = _make_middleware(default="3/second", chat="10/second")
    scope = _http_scope(path="/chat", method="POST")
    # 3 requests exhaust the default bucket (chat has 10)
    for _ in range(3):
        status, _, _ = await _call_middleware(mw, scope)
        assert status == 200
    # 4th fails on default limit even though chat has room
    status, _, _ = await _call_middleware(mw, scope)
    assert status == 429


@pytest.mark.asyncio
async def test_different_keys_independent():
    """Each API key gets its own bucket — exhausting one doesn't block the other."""
    mw = _make_middleware(default="2/second")
    scope_a = _http_scope(headers=[[b"authorization", b"Bearer key-a"]])
    scope_b = _http_scope(headers=[[b"authorization", b"Bearer key-b"]])
    # Exhaust key-a's bucket
    await _call_middleware(mw, scope_a)
    await _call_middleware(mw, scope_a)
    s_a_blocked, _, _ = await _call_middleware(mw, scope_a)
    assert s_a_blocked == 429
    # key-b should still work — separate bucket
    s_b, _, _ = await _call_middleware(mw, scope_b)
    assert s_b == 200


@pytest.mark.asyncio
async def test_non_http_passthrough():
    """Non-HTTP scopes (e.g. websocket) are passed through."""
    called = False

    async def inner(scope, receive, send):
        nonlocal called
        called = True

    mw = RateLimitMiddleware(
        inner,
        default_spec=RateSpec.parse("1/second"),
        chat_spec=RateSpec.parse("1/second"),
    )
    await mw({"type": "websocket"}, None, None)
    assert called is True


@pytest.mark.asyncio
async def test_stale_cleanup():
    """Stale buckets are cleaned up after the threshold."""
    mw = _make_middleware(default="100/second")
    scope = _http_scope()
    await _call_middleware(mw, scope)
    assert len(mw._buckets) == 1

    # Simulate time passing beyond cleanup threshold
    now = time.monotonic()
    mw._last_cleanup = now - 400  # force cleanup trigger
    for b in mw._buckets.values():
        b.last_refill = now - 700  # make it stale

    # Next call triggers cleanup
    scope2 = _http_scope(headers=[[b"authorization", b"Bearer other-key"]])
    await _call_middleware(mw, scope2)
    # The stale ip:127.0.0.1 bucket should be gone, only the new key remains
    assert "ip:127.0.0.1" not in mw._buckets
