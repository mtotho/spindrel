"""Opt-in rate limiting for the Spindrel API (ASGI middleware, token-bucket per client).

This limits how fast clients can call the Spindrel server itself — it does NOT
affect outbound calls to LLM providers (those have their own retry/backoff in llm.py).

Follows the same raw-ASGI pattern as ``ConfigExportMiddleware`` in ``app/main.py``
to avoid buffering streaming responses.

Two independent limits:
  - **default** — applies to all Spindrel API endpoints
  - **chat** — stricter limit for ``/chat*`` endpoints (POST only)

Limits are expressed as ``"<count>/<period>"`` where *period* is one of
``second``, ``minute``, ``hour``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate spec parsing
# ---------------------------------------------------------------------------

_PERIOD_MAP = {"second": 1, "minute": 60, "hour": 3600}


@dataclass
class RateSpec:
    count: int
    period_seconds: float

    @classmethod
    def parse(cls, spec: str) -> "RateSpec":
        """Parse ``"100/minute"`` into a RateSpec."""
        parts = spec.strip().split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid rate spec '{spec}' — expected '<count>/<period>'")
        count = int(parts[0])
        period = parts[1].strip().lower()
        if period not in _PERIOD_MAP:
            raise ValueError(
                f"Unknown period '{period}' in rate spec '{spec}' — "
                f"expected one of {list(_PERIOD_MAP.keys())}"
            )
        return cls(count=count, period_seconds=_PERIOD_MAP[period])


# ---------------------------------------------------------------------------
# Token bucket
# ---------------------------------------------------------------------------

@dataclass
class _Bucket:
    tokens: float
    max_tokens: int
    refill_rate: float  # tokens per second
    last_refill: float = field(default_factory=time.monotonic)

    def consume(self, now: float | None = None) -> bool:
        """Try to consume one token.  Returns True if allowed."""
        now = now if now is not None else time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def retry_after(self) -> float:
        """Seconds until the next token is available."""
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.refill_rate


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

# Stale-entry cleanup interval (seconds)
_CLEANUP_INTERVAL = 300
_STALE_THRESHOLD = 600  # remove entries idle for 10 min


class RateLimitMiddleware:
    """ASGI middleware — token-bucket rate limiting per API key or client IP."""

    def __init__(
        self,
        app,
        *,
        default_spec: RateSpec,
        chat_spec: RateSpec,
    ):
        self.app = app
        self.default_spec = default_spec
        self.chat_spec = chat_spec
        self._buckets: dict[str, _Bucket] = {}  # key -> bucket (default)
        self._chat_buckets: dict[str, _Bucket] = {}  # key -> bucket (chat)
        self._last_cleanup = time.monotonic()

    # -- public helpers (for testing) --

    def _get_client_key(self, scope: dict) -> str:
        """Extract a rate-limit key from the ASGI scope.

        Priority: Authorization header bearer token → first query-param api_key → client IP.
        """
        headers: dict[bytes, bytes] = {}
        for k, v in scope.get("headers", []):
            headers[k] = v

        # Bearer token
        auth = headers.get(b"authorization", b"").decode(errors="replace")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                return f"key:{token[:32]}"

        # Query-string api_key
        qs = scope.get("query_string", b"").decode(errors="replace")
        for part in qs.split("&"):
            if part.startswith("api_key="):
                return f"key:{part[8:][:32]}"

        # Fallback: client IP
        client = scope.get("client")
        if client:
            return f"ip:{client[0]}"
        return "ip:unknown"

    def _is_chat_path(self, method: str, path: str) -> bool:
        return method == "POST" and path.startswith("/chat")

    def _make_bucket(self, spec: RateSpec) -> _Bucket:
        return _Bucket(
            tokens=float(spec.count),
            max_tokens=spec.count,
            refill_rate=spec.count / spec.period_seconds,
        )

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup < _CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        threshold = now - _STALE_THRESHOLD
        for store in (self._buckets, self._chat_buckets):
            stale = [k for k, b in store.items() if b.last_refill < threshold]
            for k in stale:
                del store[k]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        client_key = self._get_client_key(scope)

        now = time.monotonic()
        self._maybe_cleanup(now)

        # Check chat-specific limit first (stricter)
        if self._is_chat_path(method, path):
            bucket = self._chat_buckets.get(client_key)
            if bucket is None:
                bucket = self._make_bucket(self.chat_spec)
                self._chat_buckets[client_key] = bucket
            if not bucket.consume(now):
                retry_after = bucket.retry_after()
                await self._send_429(send, retry_after)
                return

        # Default limit
        bucket = self._buckets.get(client_key)
        if bucket is None:
            bucket = self._make_bucket(self.default_spec)
            self._buckets[client_key] = bucket
        if not bucket.consume(now):
            retry_after = bucket.retry_after()
            await self._send_429(send, retry_after)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_429(send, retry_after: float) -> None:
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                [b"content-type", b"application/json"],
                [b"retry-after", str(int(retry_after) + 1).encode()],
            ],
        })
        import json
        body = json.dumps({"detail": "Too many requests"}).encode()
        await send({"type": "http.response.body", "body": body})
