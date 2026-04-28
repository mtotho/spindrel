"""DB-backed webhook delivery service.

Maintains an in-memory cache of active endpoints (loaded from DB at startup,
invalidated on CRUD).  ``emit_webhooks`` is the hot-path function — it reads
from the cache (no DB hit) and spawns fire-and-forget delivery tasks.

Each delivery attempt records a row in ``webhook_deliveries`` so operators can
inspect history via the admin API.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import WebhookDelivery, WebhookEndpoint
from app.services.encryption import decrypt, encrypt
from app.services.url_safety import UnsafePublicURLError, assert_public_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event registry
# ---------------------------------------------------------------------------

EVENT_REGISTRY: dict[str, str] = {
    "before_context_assembly": "Fired before the context assembly pipeline runs",
    "before_llm_call": "Fired before each LLM API call (includes model, message count, tool count)",
    "after_llm_call": "Fired after each LLM API call (includes usage, duration, fallback info)",
    "before_tool_execution": "Fired before a tool is executed (includes tool name, type, args)",
    "after_tool_call": "Fired after a tool completes (includes tool name, result summary)",
    "after_response": "Fired after the final assistant response is sent",
    "before_transcription": "Fired before audio transcription (includes format, size)",
    "after_task_complete": "Fired after a scheduled task completes",
    "after_workflow_step": "Fired after a workflow step completes",
}

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_endpoints_cache: list[dict[str, Any]] = []
_cache_loaded = False

# Persistent HTTP client (module-level, like dispatchers.py)
_http_client: httpx.AsyncClient | None = None

# Retry delays in seconds: attempt 1 = immediate, attempt 2 = 30s, attempt 3 = 120s
_RETRY_DELAYS = [0, 30, 120]
_MAX_ATTEMPTS = 3


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


async def load_webhook_endpoints() -> None:
    """Load active webhook endpoints from DB into the in-memory cache."""
    global _cache_loaded

    async with async_session() as db:
        rows = (await db.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.is_active.is_(True))
        )).scalars().all()

    _endpoints_cache.clear()
    for row in rows:
        _endpoints_cache.append({
            "id": row.id,
            "url": row.url,
            "secret": decrypt(row.secret),
            "events": row.events or [],
        })
    _cache_loaded = True
    logger.info("Loaded %d active webhook endpoint(s) into cache", len(_endpoints_cache))


def invalidate_cache() -> None:
    """Mark the cache as stale so it's reloaded on next emit."""
    global _cache_loaded
    _cache_loaded = False
    _endpoints_cache.clear()


_cache_lock = asyncio.Lock()


async def _ensure_cache() -> None:
    if _cache_loaded:
        return
    async with _cache_lock:
        if not _cache_loaded:  # double-check after acquiring lock
            await load_webhook_endpoints()


# ---------------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------------

def generate_secret() -> str:
    """Generate a random 64-char hex signing secret."""
    return secrets.token_hex(32)


def sign_payload(body: bytes, secret: str, timestamp: str) -> str:
    """Compute replay-resistant HMAC-SHA256 over timestamp + payload."""
    signed = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def verify_signature(
    body: bytes,
    secret: str,
    signature: str,
    timestamp: str | None,
    *,
    tolerance_seconds: int = 300,
) -> bool:
    """Verify timestamp-bound HMAC-SHA256 signature."""
    if not timestamp:
        return False
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - sent_at) > tolerance_seconds:
        return False
    expected = sign_payload(body, secret, str(sent_at))
    received = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

async def _deliver(endpoint: dict[str, Any], event: str, payload: dict) -> None:
    """POST a signed payload to an endpoint with retries. Records delivery to DB."""
    import json

    body = json.dumps(payload, default=str).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = sign_payload(body, endpoint["secret"], timestamp)
    headers = {
        "Content-Type": "application/json",
        "X-Spindrel-Signature": f"sha256={signature}",
        "X-Spindrel-Timestamp": timestamp,
        "X-Spindrel-Event": event,
    }

    client = _get_http_client()
    last_status = None
    last_error = None
    last_response_body = None
    last_duration_ms = None
    attempts_made = 1

    try:
        await assert_public_url(endpoint["url"])
    except UnsafePublicURLError as exc:
        last_error = str(exc)[:1024]
        last_status = None
        last_response_body = None
        last_duration_ms = 0
        logger.warning("Blocked unsafe webhook delivery URL %s: %s", endpoint["url"], exc)
        attempt = 0
    else:
        attempt = 0

        for attempt in range(_MAX_ATTEMPTS):
            attempts_made = attempt + 1
            if attempt > 0:
                await asyncio.sleep(_RETRY_DELAYS[attempt])

            start = time.monotonic()
            try:
                resp = await client.post(endpoint["url"], content=body, headers=headers)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                last_status = resp.status_code
                last_response_body = resp.text[:1024] if resp.text else None
                last_duration_ms = elapsed_ms
                last_error = None

                if 200 <= resp.status_code < 300:
                    break  # success
                if resp.status_code < 500:
                    break  # client error, don't retry
                # 5xx → retry
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                last_duration_ms = elapsed_ms
                last_error = str(exc)[:1024]
                last_status = None
                last_response_body = None
                logger.debug("Webhook delivery to %s attempt %d failed: %s", endpoint["url"], attempt + 1, exc)

    # Record delivery
    try:
        async with async_session() as db:
            delivery = WebhookDelivery(
                id=uuid.uuid4(),
                endpoint_id=endpoint["id"],
                event=event,
                payload=payload,
                attempt=attempts_made,
                status_code=last_status,
                response_body=last_response_body,
                error=last_error,
                duration_ms=last_duration_ms,
            )
            db.add(delivery)
            await db.commit()
    except Exception:
        logger.warning("Failed to record webhook delivery", exc_info=True)


async def emit_webhooks(event: str, payload: dict) -> None:
    """Emit an event to all matching webhook endpoints (fire-and-forget).

    This is the hot-path function called from hook emission. It reads from the
    in-memory cache (no DB hit) and spawns a delivery task per endpoint.
    """
    await _ensure_cache()

    for ep in _endpoints_cache:
        # Empty events list = subscribe to all events
        if ep["events"] and event not in ep["events"]:
            continue
        asyncio.create_task(_deliver(ep, event, payload))


# ---------------------------------------------------------------------------
# Test endpoint
# ---------------------------------------------------------------------------

async def send_test_event(endpoint_id: uuid.UUID, db: AsyncSession) -> dict:
    """Send a synthetic test event to an endpoint and return the result synchronously."""
    row = await db.get(WebhookEndpoint, endpoint_id)
    if not row:
        raise ValueError("Endpoint not found")

    secret = decrypt(row.secret)
    ep = {
        "id": row.id,
        "url": row.url,
        "secret": secret,
        "events": row.events or [],
    }

    import json

    payload = {
        "event": "test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": {"bot_id": None, "session_id": None, "channel_id": None, "client_id": None, "correlation_id": None},
        "data": {"message": "This is a test event from Spindrel"},
    }
    body = json.dumps(payload, default=str).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = sign_payload(body, secret, timestamp)
    headers = {
        "Content-Type": "application/json",
        "X-Spindrel-Signature": f"sha256={signature}",
        "X-Spindrel-Timestamp": timestamp,
        "X-Spindrel-Event": "test",
    }

    client = _get_http_client()
    start = time.monotonic()
    try:
        await assert_public_url(ep["url"])
        resp = await client.post(ep["url"], content=body, headers=headers)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        result = {
            "success": 200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "duration_ms": elapsed_ms,
            "response_body": resp.text[:1024] if resp.text else None,
        }
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        result = {
            "success": False,
            "status_code": None,
            "duration_ms": elapsed_ms,
            "error": str(exc)[:1024],
        }

    # Record delivery
    try:
        delivery = WebhookDelivery(
            id=uuid.uuid4(),
            endpoint_id=endpoint_id,
            event="test",
            payload=payload,
            attempt=1,
            status_code=result.get("status_code"),
            response_body=result.get("response_body"),
            error=result.get("error"),
            duration_ms=result["duration_ms"],
        )
        db.add(delivery)
        await db.commit()
    except Exception:
        logger.warning("Failed to record test delivery", exc_info=True)

    return result


# ---------------------------------------------------------------------------
# SSRF validation
# ---------------------------------------------------------------------------

async def validate_webhook_url(url: str) -> None:
    """DNS-resolving SSRF validation for user-configured webhook URLs."""
    try:
        await assert_public_url(url)
    except UnsafePublicURLError as exc:
        raise ValueError(str(exc)) from exc
